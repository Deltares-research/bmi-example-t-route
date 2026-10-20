"""Run the FEWS-BMI smoke test with segment lateral inflows."""

import argparse
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from bmi_troute import bmi_troute


CONFIG_PATH = Path(__file__).resolve().with_name("fews_bmi_smoke.yaml")
DEFAULT_LATERAL_INFLOW_PATH = Path(__file__).resolve().with_name("lateral_inflows.csv")
NETWORK_PATH = Path(__file__).resolve().with_name("gauge_01069700.gpkg")
OUTPUT_VARIABLES = (
    "channel_exit_water_x-section__volume_flow_rate",
    "channel_water_flow__speed",
    "channel_water__mean_depth",
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the FEWS-BMI smoke test using lateral inflows only."
    )
    parser.add_argument(
        "--lateral-inflow-csv",
        type=Path,
        default=DEFAULT_LATERAL_INFLOW_PATH,
        help=(
            "CSV with time_seconds and one column per numeric segment ID "
            "in m3/s (default: bundled deterministic lateral inflows)."
        ),
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        help="Optional path for writing per-step discharge, velocity, and depth.",
    )
    return parser.parse_args()


def load_lateral_inflows(path, segment_ids, timestep_seconds):
    inflows = pd.read_csv(path)
    required_columns = {"time_seconds", *(str(segment_id) for segment_id in segment_ids)}
    missing = required_columns.difference(inflows.columns)
    if missing:
        raise ValueError(f"Lateral-inflow CSV is missing required columns: {sorted(missing)}")
    if inflows.empty:
        raise ValueError("Lateral-inflow CSV must contain at least one row.")

    times = inflows["time_seconds"].to_numpy(dtype=np.int64)
    expected_times = np.arange(len(inflows), dtype=np.int64) * timestep_seconds
    if not np.array_equal(times, expected_times):
        raise ValueError(
            "time_seconds must start at zero and increase by the configured "
            f"{timestep_seconds}-second timestep."
        )

    values = inflows[[str(segment_id) for segment_id in segment_ids]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Lateral-inflow values must all be finite.")
    if (values < 0).any():
        raise ValueError("This smoke test expects non-negative lateral inflows.")
    return values


def align_output(name, values, segment_ids):
    if not isinstance(values, pd.Series):
        raise RuntimeError(f"{name} must return a Series indexed by segment ID.")
    if not values.index.is_unique:
        raise RuntimeError(f"{name} returned duplicate segment IDs.")

    missing = pd.Index(segment_ids).difference(values.index)
    unexpected = values.index.difference(segment_ids)
    if len(missing) or len(unexpected):
        raise RuntimeError(
            f"{name} returned mismatched segment IDs: "
            f"missing={missing.tolist()}, unexpected={unexpected.tolist()}."
        )

    aligned = values.reindex(segment_ids).to_numpy(dtype=float)
    if not np.isfinite(aligned).all():
        raise RuntimeError(f"{name} contains non-finite values.")
    return aligned


def main():
    args = parse_args()
    os.chdir(REPO_ROOT)

    flowpaths = gpd.read_file(NETWORK_PATH, layer="flowpaths")
    lakes = gpd.read_file(NETWORK_PATH, layer="lake_attributes")
    if len(flowpaths) != 3 or not lakes.empty:
        raise RuntimeError(
            "Expected the bundled toy hydrofabric to contain three flowpaths "
            f"and no lakes; found {len(flowpaths)} flowpaths and {len(lakes)} lakes."
        )

    segment_ids = np.asarray(
        [int(segment_id.rsplit("-", 1)[-1]) for segment_id in flowpaths["id"]],
        dtype=np.int64,
    )
    inflow_values = load_lateral_inflows(args.lateral_inflow_csv, segment_ids, timestep_seconds=300)
    if not np.any(inflow_values > 0):
        raise ValueError("Lateral-inflow CSV must contain at least one positive lateral inflow.")

    model = bmi_troute()
    model.initialize(str(CONFIG_PATH))
    model.set_value("land_surface_water_source__id", segment_ids)

    output_rows = []
    try:
        for step, lateral_inflows in enumerate(inflow_values):
            model.set_value(
                "land_surface_water_source__volume_flow_rate",
                lateral_inflows,
            )
            model.update()

            current_time = int(model.get_current_time())
            if current_time != (step + 1) * 300:
                raise RuntimeError(
                    f"BMI time advanced to {current_time}s; expected {(step + 1) * 300}s."
                )

            outputs = {
                name: align_output(name, model.get_value(name), segment_ids)
                for name in OUTPUT_VARIABLES
            }

            for index, segment_id in enumerate(segment_ids):
                output_rows.append(
                    {
                        "time_seconds": current_time,
                        "segment_id": segment_id,
                        "lateral_inflow_m3_s": lateral_inflows[index],
                        "streamflow_m3_s": outputs[OUTPUT_VARIABLES[0]][index],
                        "velocity_m_s": outputs[OUTPUT_VARIABLES[1]][index],
                        "depth_m": outputs[OUTPUT_VARIABLES[2]][index],
                    }
                )
    finally:
        model.finalize()

    results = pd.DataFrame(output_rows)
    if not np.any(results["streamflow_m3_s"].to_numpy() > 0):
        raise RuntimeError("T-Route returned no positive streamflow for the positive lateral inflows.")
    if args.output_csv:
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        results.to_csv(args.output_csv, index=False)
        print(f"Wrote BMI results to {args.output_csv}")

    print(
        f"FEWS-BMI smoke test passed: {len(segment_ids)} segments, "
        f"{len(inflow_values)} updates, 300 seconds per update."
    )
    print(results.tail(len(segment_ids)).to_string(index=False))


if __name__ == "__main__":
    main()
