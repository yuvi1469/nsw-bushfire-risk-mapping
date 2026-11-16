"""Workflow Step 3.8: check missingness and quality of every aligned layer.

- Missing share by layer and year, over NSW cells and the dates each layer is used for.
- Values outside physically plausible ranges (flagged, not changed).
- Edge cells where a cell is only partly covered by the source.
- A static valid-data mask: cells whose terrain predictors all exist.
- One GeoTIFF per layer with the share of missing values in each cell, for mapping.

Writes outputs/missingness_by_layer_year.csv, outputs/quality_checks.json,
outputs/maps/*.tif and data/processed/masks/valid_static_mask.tif.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import rasterio
import xarray as xr

from grid import GRID_TIF, OUTPUTS, PROCESSED, load_grid, study_dates

PLAUSIBLE = {
    "max_temp": (-15, 55),
    "min_temp": (-25, 40),
    "daily_rain": (0, 1000),  # NSW daily record is about 809 mm
    "vp": (0, 50),
    "wind_10m": (0, 30),
    "phot_veg": (0, 100),
    "nphot_veg": (0, 100),
    "bare_soil": (0, 100),
    "tot_cov": (0, 100),
    "elevation_mean": (-10, 2300),
    "slope_mean": (0, 90),
    "slope_p90": (0, 90),
    "aspect_sin": (-1, 1),
    "aspect_cos": (-1, 1),
}


def write_map(name, values, cell_id, profile):
    grid = np.full(cell_id.shape, np.nan, dtype="float32")
    grid[cell_id >= 0] = values[cell_id[cell_id >= 0]]
    path = OUTPUTS / "maps" / f"{name}.tif"
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **{**profile, "dtype": "float32", "nodata": np.nan}) as dst:
        dst.write(grid, 1)


def outside(values, name):
    low, high = PLAUSIBLE[name]
    finite = values[np.isfinite(values)]
    return {"checked": int(finite.size), "below": int((finite < low).sum()), "above": int((finite > high).sum()), "min": float(finite.min()) if finite.size else None, "max": float(finite.max()) if finite.size else None}


def main():
    spec, cell_id, _ = load_grid()
    with rasterio.open(GRID_TIF) as src:
        profile = src.profile
    rows, report = [], {"ranges": {}, "edge_cells": {}}

    study = study_dates()
    for name in ["max_temp", "min_temp", "daily_rain", "vp", "wind_10m"]:
        with xr.open_dataset(PROCESSED / "daily" / f"{name}.nc") as ds:
            data = ds[name].load().sel(date=study)
            values = data.values
        missing = ~np.isfinite(values)
        years = pd.DatetimeIndex(data.date.values).year
        for year in sorted(set(years)):
            rows.append({"layer": name, "year": year, "missing_share": float(missing[years == year].mean())})
        report["ranges"][name] = outside(values, name)
        write_map(f"missing_share_{name}", missing.mean(axis=0), cell_id, profile)

    with xr.open_dataset(PROCESSED / "monthly" / "vegetation.nc") as veg:
        months = pd.DatetimeIndex(veg.month.values)
        used = months[(months >= "2002-07-01") & (months <= "2017-01-01")]
        veg = veg.sel(month=used)
        for name in ["phot_veg", "nphot_veg", "bare_soil", "tot_cov"]:
            values = veg[name].values
            missing = ~np.isfinite(values)
            for year in sorted(set(used.year)):
                rows.append({"layer": name, "year": year, "missing_share": float(missing[used.year == year].mean())})
            report["ranges"][name] = outside(values, name)
            write_map(f"missing_share_{name}", missing.mean(axis=0), cell_id, profile)
        fractions = veg[["phot_veg", "nphot_veg", "bare_soil"]].to_array().sum("variable", skipna=False).values
        report["vegetation_fraction_sum"] = {"median": float(np.nanmedian(fractions)), "share_outside_97_103": float(np.nanmean((fractions < 97) | (fractions > 103)))}
        valid_fraction = veg["valid_fraction"].values
        report["edge_cells"]["vegetation_cells_mean_valid_fraction_below_0.5"] = int((np.nanmean(valid_fraction, axis=0) < 0.5).sum())
        write_map("vegetation_mean_valid_fraction", np.nanmean(valid_fraction, axis=0), cell_id, profile)

    with xr.open_dataset(PROCESSED / "static" / "terrain.nc") as terrain:
        static_valid = np.ones(spec["nsw_cells"], dtype=bool)
        for name in ["elevation_mean", "slope_mean", "slope_p90", "aspect_sin", "aspect_cos"]:
            values = terrain[name].values
            rows.append({"layer": name, "year": "static", "missing_share": float((~np.isfinite(values)).mean())})
            report["ranges"][name] = outside(values, name)
            static_valid &= np.isfinite(values)
        dem_fraction = terrain["dem_valid_fraction"].values
        report["edge_cells"]["dem_cells_partly_covered"] = int(((dem_fraction > 0) & (dem_fraction < 1)).sum())
        write_map("dem_valid_fraction", dem_fraction, cell_id, profile)

    labels = pd.read_parquet(PROCESSED / "labels" / "burn_cell_days.parquet")
    labels = labels.loc[labels["in_study_period"]]
    report["fire_label"] = {
        "cell_days_with_any_burn": int(len(labels)),
        "cell_days_burned_at_threshold": int(labels["burned"].sum()),
        "burned_by_type": labels.loc[labels["burned"], "burn_type"].value_counts().to_dict(),
        "burned_fraction_quantiles": labels["burned_fraction"].quantile([0.1, 0.5, 0.9, 0.99]).round(4).to_dict(),
    }

    mask = np.full(cell_id.shape, 0, dtype="uint8")
    mask[cell_id >= 0] = static_valid[cell_id[cell_id >= 0]]
    path = PROCESSED / "masks" / "valid_static_mask.tif"
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **{**profile, "dtype": "uint8", "nodata": 255}) as dst:
        dst.write(mask, 1)
    report["valid_static_cells"] = int(static_valid.sum())
    report["nsw_cells"] = spec["nsw_cells"]
    report["study_days"] = len(study)
    report["possible_cell_days"] = int(static_valid.sum()) * len(study)

    pd.DataFrame(rows).to_csv(OUTPUTS / "missingness_by_layer_year.csv", index=False)
    (OUTPUTS / "quality_checks.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    table = pd.DataFrame(rows)
    print(table.pivot_table(index="layer", columns="year", values="missing_share").round(4).to_string())


if __name__ == "__main__":
    main()
