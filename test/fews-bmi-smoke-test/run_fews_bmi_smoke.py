"""Reference BMI run of the three-segment T-Route smoke model.

Folder layout, matching the Delft-FEWS module folder used by the FEWS-BMI adaptor::

    input/lateral_inflows.csv   synthetic lateral inflows (time + one column per segment ID)
    work/                       T-Route BMI configuration and GeoPackage (working directory)
    output/                     one CSV per BMI output variable (generated)

The driver makes the same BMI calls as the adaptor, so its output CSVs can be
compared with the adaptor's results for the same synthetic inputs.
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from bmi_troute import bmi_troute


WORK_DIR = TEST_DIR / "work"
CONFIG_PATH = WORK_DIR / "fews_bmi_smoke.yaml"
DEFAULT_INPUT = TEST_DIR / "input" / "lateral_inflows.csv"
DEFAULT_OUTPUT_DIR = TEST_DIR / "output"
INPUT_ID_VARIABLE = "land_surface_water_source__id"
INPUT_FLOW_VARIABLE = "land_surface_water_source__volume_flow_rate"
OUTPUT_VARIABLES = (
    "channel_exit_water_x-section__volume_flow_rate",
    "channel_water_flow__speed",
    "channel_water__mean_depth",
)
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the T-Route smoke model through BMI with synthetic lateral inflows."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="CSV with a 'time' column and one column per numeric segment ID in m3/s.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Folder for the result CSVs (default: output/).",
    )
    return parser.parse_args()


def load_lateral_inflows(path):
    inflows = pd.read_csv(path, parse_dates=["time"], index_col="time")
    if inflows.empty:
        raise ValueError(f"{path} contains no rows.")
    if not inflows.index.is_monotonic_increasing or not inflows.index.is_unique:
        raise ValueError("Input times must be unique and increasing.")
    segment_ids = np.asarray([int(column) for column in inflows.columns], dtype=np.int64)
    values = inflows.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Lateral inflows must all be finite.")
    if (values < 0).any():
        raise ValueError("Lateral inflows must be non-negative.")
    return inflows.index, segment_ids, values


def check_output(name, values, segment_ids):
    if not isinstance(values, pd.Series):
        raise RuntimeError(f"{name} must return a Series indexed by segment ID.")
    if not values.index.is_unique:
        raise RuntimeError(f"{name} returned duplicate segment IDs.")
    # T-Route silently ignores lateral inflows for IDs outside its network.
    missing = pd.Index(segment_ids).difference(values.index)
    if len(missing):
        raise RuntimeError(f"Input segment IDs not in the T-Route network: {missing.tolist()}")
    aligned = values.reindex(segment_ids).to_numpy(dtype=float)
    if not np.isfinite(aligned).all():
        raise RuntimeError(f"{name} contains non-finite values.")
    return aligned


def main():
    args = parse_args()
    times, segment_ids, values = load_lateral_inflows(args.input.resolve())
    output_dir = args.output_dir.resolve()

    # Relative paths in the configuration resolve from the working directory.
    os.chdir(WORK_DIR)
    model = bmi_troute()
    model.initialize(str(CONFIG_PATH))
    results = {name: [] for name in OUTPUT_VARIABLES}
    try:
        timestep = int(model.get_time_step())
        spacing = np.diff(times.values).astype("timedelta64[s]").astype(np.int64)
        if len(spacing) and not (spacing == timestep).all():
            raise ValueError(
                f"Input must be at the model time step of {timestep} s, one value per update()."
            )

        model.set_value(INPUT_ID_VARIABLE, segment_ids)
        for step, lateral_inflows in enumerate(values, start=1):
            model.set_value(INPUT_FLOW_VARIABLE, lateral_inflows)
            model.update()
            if int(model.get_current_time()) != step * timestep:
                raise RuntimeError(
                    f"BMI time is {model.get_current_time()} s; expected {step * timestep} s."
                )
            for name in OUTPUT_VARIABLES:
                results[name].append(check_output(name, model.get_value(name), segment_ids))
    finally:
        model.finalize()

    # Input at time t drives the step t -> t + dt; results are stamped at the end of the step.
    output_times = (times + pd.Timedelta(seconds=timestep)).strftime(TIME_FORMAT)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in results.items():
        table = pd.DataFrame(rows, index=pd.Index(output_times, name="time"), columns=segment_ids)
        table.to_csv(output_dir / f"{name}.csv")

    discharge = np.asarray(results[OUTPUT_VARIABLES[0]])
    if not (discharge > 0).any():
        raise RuntimeError("T-Route returned no positive discharge for positive lateral inflows.")

    print(
        f"FEWS-BMI smoke test passed: {len(segment_ids)} segments, {len(values)} updates, "
        f"{timestep} seconds per update, results {output_times[0]} to {output_times[-1]}."
    )
    print(f"Wrote {len(OUTPUT_VARIABLES)} result CSVs to {output_dir}")


if __name__ == "__main__":
    main()
