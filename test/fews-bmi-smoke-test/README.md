# FEWS-BMI smoke test

## 1. What is a smoke test?

A smoke test is a small, quick check that the main parts of a system work
together. Here it checks that a compiled T-Route model can initialize, accept
lateral inflows through BMI, advance in time, and return routed results.

The standalone Python driver substitutes for the **FEWS-BMI adaptor**, which
is the coupling driver in Delft-FEWS. It uses the same three-segment model used
in the Delft-FEWS integration, but runs without Delft-FEWS.

The test checks the network size, input validity, clock advancement, output
sizes, finite results, and some positive discharge. It is not a scientific
validation, a numerical regression test, or an end-to-end Delft-FEWS test.

## 2. Model contents, inputs, and outputs

### Model geometry and configuration

The [GeoPackage](gauge_01069700.gpkg) contains three river flowpaths and no
lakes. It is copied unchanged from the original T-Route
[unit-test hydrofabric](../unit_test_hyfeature/domain/gauge_01069700.gpkg).

```text
flowpath 10245 -> flowpath 10236 -> flowpath 10237 -> terminal nexus 10238
    1.81 km          5.95 km          5.77 km
```

The total channel length is approximately 13.53 km. Channel geometry, slopes,
and Manning roughness come from the GeoPackage.

The [configuration](fews_bmi_smoke.yaml) uses:

- One T-Route BMI instance for all three segments, with serial Muskingum-Cunge
  routing (`V02-structured`). Unlike the split upstream/reservoir/downstream
  BMI examples, this test has no separate model components or flow exchange
  between instances; upstream and downstream segments are routed internally.
  The standalone driver substitutes for the FEWS-BMI adaptor to supply lateral
  inflows and read results from this one instance.
- A 300-second timestep and twelve updates: one simulated hour.
- A start time of December 1, 2015 at 00:00, with zero initial channel flow
  and depth.
- No reservoirs, data assimilation, or hybrid/diffusive routing.

This model routes lateral inflow; it does not calculate rainfall-runoff.
The example supplies a synthetic pulse of 0 to 3 m3/s to segment `10245`.
Direct lateral inflows into `10236` and `10237` are zero, but water reaches
these segments through routing.

### BMI exchange and segment mapping

The [local driver](run_fews_bmi_smoke.py) demonstrates the calls implemented by
[T-Route's BMI wrapper](../../src/bmi_troute.py). The wrapper delegates model
execution to [troute_model.py](../../src/troute_model.py).

| Direction | BMI variable | Meaning | Units |
|---|---|---|---|
| Input | `land_surface_water_source__id` | Numeric river-segment IDs corresponding to the inflow array | ID |
| Input | `land_surface_water_source__volume_flow_rate` | Lateral inflow for each matching segment | m3/s |
| Output | `channel_exit_water_x-section__volume_flow_rate` | Discharge leaving the downstream end of each segment | m3/s |
| Output | `channel_water_flow__speed` | Channel flow velocity | m/s |
| Output | `channel_water__mean_depth` | Channel water depth | m |

GeoPackage flowpath names such as `wb-10245` become numeric BMI IDs such as
`10245`. These are **segment IDs**, not nexus IDs. For this network:

| GeoPackage flowpath | BMI segment ID | Downstream nexus |
|---|---|---|
| `wb-10245` | `10245` | `nex-10236` |
| `wb-10236` | `10236` | `nex-10237` |
| `wb-10237` | `10237` | `nex-10238` |

For example, an input ID array `[10245, 10236, 10237]` with an inflow array
`[1.0, 0.0, 0.0]` supplies 1 m3/s to segment `10245`. The ID and value arrays
must use the same order. The local driver reads IDs from the GeoPackage and
aligns its input data to that order.

The exchange follows this sequence:

```python
model.initialize(str(config_path))
model.set_value("land_surface_water_source__id", segment_ids)
# Repeat for each 300-second interval:
model.set_value("land_surface_water_source__volume_flow_rate", lateral_inflows)
model.update()
discharge = model.get_value("channel_exit_water_x-section__volume_flow_rate")
velocity = model.get_value("channel_water_flow__speed")
depth = model.get_value("channel_water__mean_depth")

# Outputs are pandas Series indexed by segment ID, not downstream nexus ID.
# Output order need not match input order; identify values by their own indexes.
output_segment_ids = discharge.index.to_numpy()
q_10245 = discharge.loc[10245]  # Discharge at segment 10245's downstream exit.
v_10245 = velocity.loc[10245]
h_10245 = depth.loc[10245]
# After the final interval:
model.finalize()
```

Results are read at the **end** of each interval: 300, 600, ..., 3600 seconds.
For example, lateral inflows supplied for 0-300 seconds produce results at
300 seconds after the first `update()`. The next update produces results at
600 seconds. Channel flow and depth carry over between updates in the same
instance; the model is not reinitialized each time.

The local driver validates each output's segment index and reorders values to
match the input segment IDs before writing results. Duplicate, missing, or
unexpected IDs cause the test to fail, as do unindexed or non-finite outputs.

### Model files and their role in Delft-FEWS

| File | Local smoke test | Delft-FEWS |
|---|---|---|
| [gauge_01069700.gpkg](gauge_01069700.gpkg) | Network geometry and channel attributes | Model geometry; source for location sets and map layers |
| [fews_bmi_smoke.yaml](fews_bmi_smoke.yaml) | T-Route BMI configuration | Model configuration in the ModuleDataSet |
| [run_fews_bmi_smoke.py](run_fews_bmi_smoke.py) | BMI driver and test checks | Replaced by the FEWS-BMI adaptor |
| [lateral_inflows.csv](lateral_inflows.csv) | Example lateral inflows | Replaced by NetCDF input |
| [README.md](README.md) | Setup and model guide | Reference documentation |
| `output/` (generated, ignored by Git) | Result CSV and CI logs | NetCDF model results written by the FEWS-BMI adaptor |

This folder alone is not a complete Delft-FEWS deployment. The compiled
T-Route environment, BMI source modules, FEWS-BMI adaptor, and FEWS
configuration are also needed.

When preparing the model for Delft-FEWS:

- Use the model's segment IDs in the FEWS location mappings and configure
  location sets and map layers using the GeoPackage geometry.
- Update the YAML paths for the deployed working directory and align the
  simulation start time with the FEWS run. Local paths are relative to the
  repository root.
- Configure NetCDF exchange through the FEWS-BMI adaptor. The standalone
  driver and model YAML do not create NetCDF exchange files.

Comments in the [model configuration](fews_bmi_smoke.yaml) explain the settings,
including the validator-required `qlat_input_folder`; lateral inflows enter
through BMI, not native NEXOUT files.

### Boundary conditions and warm-state limitations

- **Lateral inflows only:** an inflow into the most upstream segment is still
  lateral inflow, not a separately prescribed external upstream discharge.
- **No external boundaries in this setup:** upstream discharge and downstream/
  coastal water levels are not supplied or tested.
- **Cold start:** nonzero initial state and save/restore across separate model
  instances are not tested. State persists during this test's twelve updates,
  but warm-restart equivalence has not been verified.
- **No restart files:** the optional local results CSV is not a saved model
  state.

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

From the repository root, in the same activated environment:

```bash
python3 test/fews-bmi-smoke-test/run_fews_bmi_smoke.py
```

Expected success message:

```text
FEWS-BMI smoke test passed: 3 segments, 12 updates, 300 seconds per update.
```

Optionally save local results:

```bash
python3 test/fews-bmi-smoke-test/run_fews_bmi_smoke.py \
  --output-csv test/fews-bmi-smoke-test/output/fews_bmi_smoke_output.csv
```

The CSV contains 36 rows: three segments at twelve timesteps, with discharge,
velocity, and depth as columns.

### Build notes

- **Required BMI routing fix:** this fork updates the `nwm_route` call in
  [src/troute_model.py](../../src/troute_model.py) to pass three required
  arguments: `great_lakes_df`, `great_lakes_param_df`, and
  `great_lakes_climatology_df`. The function requires these arguments even
  when the model has no Great Lakes. Without this fix, the BMI update fails
  with a missing-arguments error. Include this source change when committing
  or transferring the example; the test folder alone is not sufficient.
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
automates the build and local test on a fresh Ubuntu 22.04 runner with Python
3.10. It:

1. Installs native build tools, NetCDF-C, and NetCDF-Fortran.
2. Installs Python requirements, `bmipy`, and `fiona`.
3. Compiles T-Route with `bash ./compiler.sh no-e`.
4. Runs the smoke test without `LD_LIBRARY_PATH` and saves its results CSV.
5. Uploads build/test logs and the CSV as `fews-bmi-smoke-test-results`,
   including available logs if a step fails.

Commit and push the workflow, this test folder, and the required
[BMI routing code](../../src/troute_model.py) changes. With Actions enabled
in your fork, pushes and pull requests trigger the workflow. Manual execution
through **Actions > FEWS-BMI smoke test > Run workflow** is available once the
workflow is on the default branch.

Open the run to inspect build/test logs and download its artifact, retained
for 14 days. The job has a 30-minute timeout. There is no separate result-
coverage verification step; the driver's own checks determine test success.

A successful run verifies that the tested revision builds and passes the
standalone BMI smoke test in a fresh Ubuntu 22.04 / Python 3.10 environment,
without relying on local packages or uncommitted files. This provides a
reference setup that others should be able to reproduce on a matching system.
Check the workflow result for the revision you use; the workflow's presence
alone does not mean it has passed.

This is not a guarantee for other operating systems or future dependency
versions: WSL is not directly tested, and dependencies are not all pinned to
exact versions. A passing test also does not establish scientific accuracy or
bitwise-identical numerical results.

This workflow does not run Delft-FEWS or its adaptor, validate NetCDF exchange,
or reuse your local compiled environment. The original regional-model workflow
is unchanged.
