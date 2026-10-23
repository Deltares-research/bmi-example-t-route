# FEWS-BMI smoke test

## 1. What is a smoke test?

A smoke test is a small, quick check that the main parts of a system work
together. Here it checks that a compiled T-Route model can initialize, accept
lateral inflows through BMI, advance in time, and return routed results.

The test is also the **model-side reference run** for the Delft-FEWS
integration. The driver makes the same BMI calls as the **FEWS-BMI adaptor**
(the coupling driver in Delft-FEWS), using the same folder layout, model
configuration, and synthetic inputs. Running the same inputs through the
adaptor and comparing its results with this test's output CSVs shows whether
the adaptor exchanges data with the model correctly.

Reading `run_info.xml`, reading and writing NetCDF, and writing `diag.xml` are
adaptor responsibilities and are not part of this test.

The test checks input validity, clock advancement, segment IDs, finite
results, and some positive discharge. It is not a scientific validation or a
numerical regression test.

## 2. Model contents, inputs, and outputs

### Folder layout

The folder follows the layout of the Delft-FEWS module folder used by the
adaptor:

| Path | Contents | Delft-FEWS / adaptor run |
|---|---|---|
| [input/lateral_inflows.csv](input/lateral_inflows.csv) | Synthetic lateral inflows | The same series, exported by Delft-FEWS as NetCDF |
| [work/fews_bmi_smoke.yaml](work/fews_bmi_smoke.yaml) | T-Route BMI configuration | Model configuration in the ModuleDataSet |
| [work/gauge_01069700.gpkg](work/gauge_01069700.gpkg) | Network geometry and channel attributes | Model geometry; source for location sets and map layers |
| `output/` (generated, ignored by Git) | One result CSV per BMI output variable, plus CI logs | NetCDF results written by the adaptor |
| [run_fews_bmi_smoke.py](run_fews_bmi_smoke.py) | BMI driver and test checks | Replaced by the FEWS-BMI adaptor |

`work/` is the working directory for the model: the driver switches into it
before `initialize`, as the adaptor does, so relative paths in the YAML resolve
from `work/`. In a Delft-FEWS deployment, `geo_file_path` may instead point to
the GeoPackage shared with the FEWS location sets, for example
`../../../Config/MapLayerFiles/gauge_01069700.gpkg`.

### Model geometry and configuration

The [GeoPackage](work/gauge_01069700.gpkg) contains three river flowpaths and
no lakes. It is copied unchanged from the original T-Route
[unit-test hydrofabric](../unit_test_hyfeature/domain/gauge_01069700.gpkg).

```text
flowpath 10245 -> flowpath 10236 -> flowpath 10237 -> terminal nexus 10238
    1.81 km          5.95 km          5.77 km
```

The total channel length is approximately 13.53 km. Channel geometry, slopes,
and Manning roughness come from the GeoPackage.

The [configuration](work/fews_bmi_smoke.yaml) uses:

- One T-Route BMI instance for all three segments, with serial Muskingum-Cunge
  routing (`V02-structured`). Upstream and downstream segments are routed
  internally; there is no flow exchange between separate model instances.
- A 300-second time step (`dt`). Each `update()` advances the model by one
  time step, so lateral inflows must be supplied every 5 minutes.
- Zero initial channel flow and depth (cold start).
- No reservoirs, data assimilation, or hybrid/diffusive routing.

In BMI mode, the run length is set by the number of `update()` calls, not by
`nts` or `start_datetime` in the YAML.

### Time stepping

The model's time step is `dt` in the YAML (300 s); a caller can read it with
`get_time_step()`. The BMI caller controls the run:

- **One input value per `update()`.** Each `update()` runs exactly one `dt`
  with the lateral inflows last set through `set_value`. Inputs must therefore
  be supplied at the model time step: 5-minute values for `dt: 300`. The
  driver stops if the input spacing differs from `dt`.
- **Run length.** The number of `update()` calls sets the run length. `nts`
  and `start_datetime` in the YAML do not. `get_current_time()` returns the
  elapsed model time in seconds since `initialize`, not a calendar date. The
  caller turns it into dates (here: first input time + elapsed time).
- **Coarser inputs.** For hourly inputs, either resample them to 5-minute
  values before the run (as in this test), or set `dt: 3600`. A 1-hour
  Muskingum-Cunge step on these short segments is less accurate: peaks are
  smoothed and delayed. `assume_short_ts: true` is also intended for short
  steps. Compare with a 300 s run before using a longer `dt`.
- **Avoid `update_until()`.** In the current BMI wrapper:
  - its argument is treated as a duration ("run this many more seconds"),
    not an absolute model time as the BMI standard defines;
  - with `qts_subdivisions: 1`, running more than one `dt` in a single call
    fails, because one inflow value cannot cover several internal steps.

  Use repeated `update()` calls instead.

### Synthetic inputs

[input/lateral_inflows.csv](input/lateral_inflows.csv) holds 12 hours of
5-minute lateral inflows (144 values, 2025-01-01 00:00 to 11:55) in m3/s. It
has a `time` column and one column per numeric segment ID:

| Segment | Synthetic lateral inflow |
|---|---|
| `10245` | Constant 1.0 |
| `10236` | 0.0 |
| `10237` | 0.0 |

All inflow enters the most upstream segment, so discharge from a cold start
travels down `10245 -> 10236 -> 10237` and approaches 1.0 m3/s in every
segment. If the coupling mixes up segment IDs, the inflow enters a downstream
segment instead, and the upstream segments stay at zero discharge. This model
routes lateral inflow; it does not calculate rainfall-runoff.

### BMI exchange and segment mapping

The [driver](run_fews_bmi_smoke.py) uses the calls implemented by
[T-Route's BMI wrapper](../../src/bmi_troute.py), which delegates model
execution to [troute_model.py](../../src/troute_model.py).

| Direction | BMI variable | Meaning | Units |
|---|---|---|---|
| Input | `land_surface_water_source__id` | Numeric river-segment IDs corresponding to the inflow array | ID |
| Input | `land_surface_water_source__volume_flow_rate` | Lateral inflow for each matching segment | m3/s |
| Output | `channel_exit_water_x-section__volume_flow_rate` | Discharge leaving the downstream end of each segment | m3/s |
| Output | `channel_water_flow__speed` | Channel flow velocity | m/s |
| Output | `channel_water__mean_depth` | Channel water depth | m |

GeoPackage flowpath names such as `wb-10245` become numeric BMI IDs such as
`10245`. These are **segment IDs**, not nexus IDs:

| GeoPackage flowpath | BMI segment ID | Downstream nexus |
|---|---|---|
| `wb-10245` | `10245` | `nex-10236` |
| `wb-10236` | `10236` | `nex-10237` |
| `wb-10237` | `10237` | `nex-10238` |

The exchange follows this sequence:

```python
os.chdir("work")
model.initialize("fews_bmi_smoke.yaml")
model.set_value("land_surface_water_source__id", segment_ids)
# For each 5-minute input value:
model.set_value("land_surface_water_source__volume_flow_rate", lateral_inflows)
model.update()
discharge = model.get_value("channel_exit_water_x-section__volume_flow_rate")
velocity = model.get_value("channel_water_flow__speed")
depth = model.get_value("channel_water__mean_depth")
# After the last input value:
model.finalize()
```

Outputs are pandas Series indexed by segment ID. Their order need not match
the input order, so identify values by their index (for example
`discharge.loc[10245]`). The driver aligns them to the input order. T-Route
silently ignores inflows for IDs outside its network, so the driver fails if
an input ID is missing from the outputs.

### Output CSVs and time convention

The driver writes one CSV per output variable to `output/`, named after the
BMI variable, for example
`output/channel_exit_water_x-section__volume_flow_rate.csv`. Each file has a
`time` column and one column per segment ID, in the input order.

The inflow at time *t* drives the step from *t* to *t* + 5 minutes, and the
result is stamped at the **end** of the step. The input from 00:00 to 11:55
therefore gives 144 results from 00:05 to 12:00. Channel flow and depth carry
over between updates; the model is not reinitialized.

When comparing with the adaptor, check that it uses the same time convention.
If the adaptor stamps results at the start of the step, the series are
shifted by one step.

### Boundary conditions and warm-state limitations

- **Lateral inflows only:** an inflow into the most upstream segment is still
  lateral inflow, not a separately prescribed external upstream discharge.
- **No external boundaries in this setup:** upstream discharge and downstream/
  coastal water levels are not supplied or tested.
- **Cold start:** nonzero initial state and save/restore across separate model
  instances are not tested.
- **No restart files:** the output CSVs are not saved model state.

These are limits of this setup and test, not all native T-Route capabilities.

## 3. Manually compile and run the model

Use **Ubuntu 22.04 and Python 3.10**, directly or through WSL2. Run the commands
below in Ubuntu, not PowerShell, using a checkout of **this fork**.
For WSL installation, see the
[original NOAA setup instructions](https://github.com/NOAA-OWP/t-route/blob/master/readme.md#usage-and-testing).

Already built this checkout? Activate its environment and go straight to
**Step 4**.

### Step 1: Install system dependencies

Use Ubuntu's NetCDF packages, as in the GitHub workflow:

```bash
sudo apt-get update
sudo apt-get install -y \
  python3.10-venv python3-pip build-essential gfortran \
  libnetcdf-dev libnetcdff-dev
```

### Step 2: Activate a Python environment

Create an environment outside the checkout, if you do not already have one:

```bash
python3.10 -m venv "$HOME/.venvs/troute"
```

Activate it and enter your checkout of this fork. Replace `/path/to/your/checkout`
with its location in Ubuntu (for a Windows folder, use its `/mnt/c/...` path):

```bash
source "$HOME/.venvs/troute/bin/activate"
cd /path/to/your/checkout
```

Recreate the environment and rebuild on each machine; do not copy the virtual
environment between machines or Ubuntu installations.

### Step 3: Install Python dependencies and compile

Install dependencies in the active environment:

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install bmipy fiona
hash -r
python3 -m pip --version
command -v pip
```

Both pip checks must point into the active environment because `compiler.sh`
invokes bare `pip`. Then compile:

```bash
export F90=gfortran
export CC=gcc
export NETCDFALTERNATIVE=/usr/include
bash ./compiler.sh no-e
```

The `no-e` option installs non-editable packages, matching CI.

### Step 4: Run the smoke test

From any folder, in the same activated environment:

```bash
python3 test/fews-bmi-smoke-test/run_fews_bmi_smoke.py
```

Expected success message:

```text
FEWS-BMI smoke test passed: 3 segments, 144 updates, 300 seconds per update, results 2025-01-01 00:05:00 to 2025-01-01 12:00:00.
```

Results are written to `test/fews-bmi-smoke-test/output/`. Use `--input` for
another inflow CSV and `--output-dir` for another output folder.

### Build notes

- **Required BMI routing fix:** this fork updates the `nwm_route` call in
  [src/troute_model.py](../../src/troute_model.py) to pass three required
  arguments: `great_lakes_df`, `great_lakes_param_df`, and
  `great_lakes_climatology_df`. The function requires these arguments even
  when the model has no Great Lakes. Without this fix, the BMI update fails
  with a missing-arguments error.
- **BMI dependency:** `bmipy` is installed separately because it is not in
  `requirements.txt`.
- **NetCDF dependencies:** Step 1 installs the native C/Fortran libraries;
  `requirements.txt` installs the Python `netCDF4` package.
- **Library paths:** `LD_LIBRARY_PATH` is normally unnecessary with Ubuntu's
  packages. Custom library installations must be visible to the system linker
  or included in `LD_LIBRARY_PATH`.
- **Known build message:** the reservoir makefile may report a missing
  `bind_hybrid.a` target. The script continues to explicit level-pool/RFC
  targets; installation and the smoke test must still succeed.

## 4. GitHub build and test

The [FEWS-BMI smoke-test workflow](../../.github/workflows/fews-bmi-smoke-test.yml)
automates the build and test on a fresh Ubuntu 22.04 runner with Python 3.10.
It:

1. Installs native build tools, NetCDF-C, and NetCDF-Fortran.
2. Installs Python requirements, `bmipy`, and `fiona`.
3. Compiles T-Route with `bash ./compiler.sh no-e`.
4. Runs the smoke test without `LD_LIBRARY_PATH`.
5. Uploads build/test logs and the result CSVs as
   `fews-bmi-smoke-test-results`, including available logs if a step fails.

Pushes and pull requests trigger the workflow. Manual execution through
**Actions > FEWS-BMI smoke test > Run workflow** is available once the
workflow is on the default branch. Artifacts are retained for 14 days, and the
job has a 30-minute timeout.

The artifact's CSVs are the reference results to compare with an adaptor run
of the same inputs. A successful run verifies that the tested revision builds
and passes the BMI smoke test in a fresh Ubuntu 22.04 / Python 3.10
environment. It does not guarantee results on other operating systems or
future dependency versions, and it does not run Delft-FEWS or the adaptor.
