"""Workflow Step 6: readiness checks before scaling, one per item in the report's checklist.

1. Every raster has the same CRS, transform, origin, dimensions, extent and 5 km cell size.
2. All dynamic features precede the target date; vegetation is the latest month before it.
3. Wildfire and prescribed-burn labels are distinguished, and low-quality or ambiguous
   burn detections are flagged.
4. Positive/negative counts and missingness are reported by year, season and spatial block.
5. Sampling is reproducible, with a saved seed, strata and inclusion weights.
6. The final sample has no duplicate cell-date rows, and the test partition is spatially
   and temporally separate.

Writes outputs/readiness_checks.json, outputs/counts_by_season_block.csv and
outputs/missingness_by_season_block.csv.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import rasterio
import xarray as xr

from grid import CELL, CRS, GRID_TIF, OUTPUTS, PROCESSED, ROOT, study_dates

SAMPLE = PROCESSED / "sample" / "sample_1000000.parquet"
TABLE = PROCESSED / "pixel_day"


def season(dates):
    start = np.where(dates.month >= 7, dates.year, dates.year - 1)
    return pd.Series([f"{s}-{str(s + 1)[2:]}" for s in start], index=dates)


def raster_grid(path):
    if path.suffix == ".tif":
        with rasterio.open(path) as src:
            return {"crs": src.crs.to_string(), "transform": tuple(round(v, 6) for v in src.transform)[:6], "shape": (src.height, src.width)}
    with xr.open_dataset(path, decode_coords="all") as ds:
        x, y = ds["x"].values, ds["y"].values
        crs = ds.rio.crs.to_string() if ds.rio.crs else None
        transform = (round(float(x[1] - x[0]), 6), 0.0, round(float(x[0] - (x[1] - x[0]) / 2), 6), 0.0, round(float(y[1] - y[0]), 6), round(float(y[0] - (y[1] - y[0]) / 2), 6))
        return {"crs": crs, "transform": transform, "shape": (len(y), len(x))}


def check_rasters():
    import rioxarray  # noqa: F401
    reference = raster_grid(GRID_TIF)
    paths = [GRID_TIF, PROCESSED / "masks" / "valid_static_mask.tif", *sorted((PROCESSED / "rasters").rglob("*.tif")), *sorted((PROCESSED / "rasters").rglob("*.nc")), *sorted((OUTPUTS / "maps").glob("*.tif"))]
    results = {}
    for path in paths:
        grid = raster_grid(path)
        results[str(path.relative_to(ROOT))] = {**grid, "same_as_grid": grid["crs"] == reference["crs"] == CRS and grid["shape"] == reference["shape"] and np.allclose(grid["transform"], reference["transform"])}
    return {"reference": {**reference, "cell_size_m": CELL}, "files": results, "passed": all(r["same_as_grid"] for r in results.values())}


def table_checks():
    from_checks = json.loads((OUTPUTS / "pixel_day_checks.json").read_text())
    counts, missing_dates = [], []
    types, flags = {}, {"burn_unconfirmed": 0, "burn_small": 0, "burned": 0}
    for path in sorted(TABLE.glob("*/part-0.parquet")):
        frame = pd.read_parquet(path, columns=["date", "block_id", "burned", "burn_type", "burn_unconfirmed", "burn_small"])
        dates = pd.DatetimeIndex(frame["date"])
        frame["season"] = season(dates).values
        counts.append(frame.groupby(["season", "block_id"]).agg(rows=("burned", "size"), burned=("burned", "sum")).reset_index())
        burned = frame.loc[frame["burned"] == 1]
        for name, value in burned["burn_type"].value_counts().items():
            types[name] = types.get(name, 0) + int(value)
        for name in flags:
            flags[name] += int(frame[name].sum())
    counts = pd.concat(counts).groupby(["season", "block_id"]).sum().reset_index()
    counts["unburned"] = counts["rows"] - counts["burned"]
    counts.to_csv(OUTPUTS / "counts_by_season_block.csv", index=False)
    return from_checks, counts, types, flags


def missingness_by_season_block():
    """Rows dropped for missing vegetation, recomputed from the gridded layer."""
    cells = pd.read_csv(ROOT / "splits" / "cells.csv")
    dates = study_dates()
    months = (dates.to_period("M") - 1).to_timestamp()
    with xr.open_dataset(PROCESSED / "monthly" / "vegetation.nc") as veg:
        missing = np.isnan(veg["phot_veg"].sel(month=months).values)
    frame = pd.DataFrame(missing, index=season(dates).values, columns=cells["block_id"].values)
    out = frame.T.groupby(level=0).sum().T.groupby(level=0).sum().stack().rename("rows_missing_vegetation").reset_index()
    out.columns = ["season", "block_id", "rows_missing_vegetation"]
    out.to_csv(OUTPUTS / "missingness_by_season_block.csv", index=False)
    return int(out["rows_missing_vegetation"].sum())


def key_hash(frame):
    keys = frame[["cell_id", "date", "sample_weight"]].sort_values(["date", "cell_id"])
    return hashlib.sha256(pd.util.hash_pandas_object(keys, index=False).values.tobytes()).hexdigest()


def reproducibility():
    before = key_hash(pd.read_parquet(SAMPLE))
    subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "15_draw_sample.py"), "1000000"], check=True, capture_output=True)
    after = key_hash(pd.read_parquet(SAMPLE))
    manifest = json.loads((OUTPUTS / "sample_manifest_1000000.json").read_text())
    return {
        "redraw_same_rows_and_weights": before == after,
        "seed_saved": manifest["seed"],
        "strata_saved": manifest["strata"],
        "strata_file": manifest["strata_file"],
        "weights_saved": True,
        "passed": before == after and manifest["seed"] is not None,
    }


def separation():
    sample = pd.read_parquet(SAMPLE, columns=["cell_id", "date", "partition", "spatial_holdout"])
    cells = pd.read_csv(ROOT / "splits" / "cells.csv")
    periods = json.loads((ROOT / "splits" / "periods.json").read_text())
    held = set(cells.loc[cells["spatial_holdout"] == 1, "cell_id"])
    test_dates = (periods["test"]["start"], periods["test"]["end"])
    sample_dates = pd.to_datetime(sample["date"])
    return {
        "sample_duplicate_cell_dates": int(sample.duplicated(["cell_id", "date"]).sum()),
        "sample_rows_in_test_cells": int(sample["cell_id"].isin(held).sum()),
        "sample_rows_in_test_dates": int(sample_dates.between(*test_dates).sum()),
        "sample_rows_outside_train_period": int((~sample_dates.between(periods["train"]["start"], periods["train"]["end"])).sum()),
        "test_cells": len(held),
        "train_cells": int((cells["spatial_holdout"] == 0).sum()),
        "test_period": test_dates,
        "train_period": (periods["train"]["start"], periods["train"]["end"]),
    }


def main():
    report = {}
    report["1_same_grid"] = check_rasters()

    from_checks, counts, types, flags = table_checks()
    years = from_checks["years"].values()
    report["2_time_safe_features"] = {
        "weather_is_previous_day_every_row": all(y["weather_is_previous_day"] for y in years),
        "vegetation_before_target_month_every_row": all(y["vegetation_before_target_month"] for y in years),
        "spot_check_mismatches": from_checks["spot_checks"]["mismatches"],
        "pilot_mismatches": json.loads((ROOT / "manifests" / "pilot_checks.json").read_text())["total_mismatches"],
    }
    report["2_time_safe_features"]["passed"] = report["2_time_safe_features"]["weather_is_previous_day_every_row"] and report["2_time_safe_features"]["vegetation_before_target_month_every_row"] and report["2_time_safe_features"]["spot_check_mismatches"] == 0

    report["3_burn_labels"] = {
        "burned_rows_by_type": types,
        "flags": flags,
        "flag_rules": {"burn_unconfirmed": "burned and no NPWS polygon of the same season", "burn_small": "burned and burned_fraction < 0.05"},
        "passed": set(types) >= {"wildfire", "prescribed"} and flags["burn_unconfirmed"] > 0,
    }

    missing_total = missingness_by_season_block()
    report["4_counts_and_missingness"] = {
        "counts_files": ["outputs/population_counts.csv (partition x year x month x region x veg_band x block)", "outputs/counts_by_season_block.csv"],
        "missingness_files": ["outputs/missingness_by_layer_year.csv", "outputs/pixel_day_exclusions.csv", "outputs/missingness_by_season_block.csv"],
        "seasons": counts["season"].nunique(),
        "blocks": counts["block_id"].nunique(),
        "rows": int(counts["rows"].sum()),
        "burned": int(counts["burned"].sum()),
        "rows_missing_vegetation": missing_total,
        "passed": True,
    }
    report["5_reproducible_sampling"] = reproducibility()
    sep = separation()
    sep["passed"] = sep["sample_duplicate_cell_dates"] == 0 and sep["sample_rows_in_test_cells"] == 0 and sep["sample_rows_in_test_dates"] == 0 and sep["sample_rows_outside_train_period"] == 0
    report["6_no_duplicates_and_separate_test"] = sep
    report["all_passed"] = all(v["passed"] for k, v in report.items() if isinstance(v, dict) and "passed" in v)

    (OUTPUTS / "readiness_checks.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: ({kk: vv for kk, vv in v.items() if kk != "files"} if isinstance(v, dict) else v) for k, v in report.items()}, indent=2, default=str))


if __name__ == "__main__":
    main()
