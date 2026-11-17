"""Workflow Step 4: build the pixel-day table.

One row per NSW cell per study day, stored as Parquet files partitioned by year.
Every dynamic feature comes from before the target day t:
- weather and wind from day t-1, plus rainfall totals and dry-day counts ending at t-1;
- vegetation from the last full month before t's month;
- terrain is static.
Rows missing a required predictor are dropped, and the counts are recorded by reason.

Writes data/processed/pixel_day/YYYY/part-0.parquet and
outputs/pixel_day_exclusions.csv, outputs/pixel_day_summary.csv.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import xarray as xr

from grid import LOOKBACK_DAYS, OUTPUTS, PROCESSED, STUDY_BLOCKS, cell_centres, load_grid

OUT = PROCESSED / "pixel_day"
DRY_DAY_MM = 2.0
BLOCK_CELLS = 20  # 100 km spatial blocks for splitting and stratification
VEG_PARTIAL = 0.5
SMALL_BURN = 0.05

WEATHER = ["max_temp", "min_temp", "daily_rain", "vp", "wind_10m"]
VEGETATION = {"phot_veg": "pv", "nphot_veg": "npv", "bare_soil": "bare_soil", "tot_cov": "total_cover"}
TERRAIN = ["elevation_mean", "slope_mean", "slope_p90", "aspect_sin", "aspect_cos", "flat_cell"]
REQUIRED = [
    "max_temp_prev", "min_temp_prev", "rain_prev", "rain_7d", "rain_30d", "dry_days",
    "vp_prev", "vpd_prev", "wind_prev", "pv", "npv", "bare_soil", "total_cover",
    "elevation", "slope_mean", "slope_p90", "aspect_sin", "aspect_cos",
]
BURN_TYPES = ["none", "unknown", "wildfire", "prescribed"]


def saturation_vp(temp_c):
    """Saturation vapour pressure (hPa), Tetens formula."""
    return 6.1078 * np.exp(17.27 * temp_c / (temp_c + 237.3))


def block_weather(start, end):
    """Weather features for each study day in one block, shape (days, cells)."""
    first = pd.Timestamp(start) - pd.Timedelta(days=LOOKBACK_DAYS)
    days = pd.date_range(first, end, freq="D")
    raw = {}
    for name in WEATHER:
        with xr.open_dataset(PROCESSED / "daily" / f"{name}.nc") as ds:
            raw[name] = ds[name].sel(date=slice(first, end)).load().values
        if raw[name].shape[0] != len(days):
            raise ValueError(f"{name}: expected {len(days)} days from {first.date()}, found {raw[name].shape[0]}")

    rain = raw["daily_rain"].astype("float64")
    cumulative = np.vstack([np.zeros((1, rain.shape[1])), np.cumsum(rain, axis=0)])
    dry = np.zeros_like(rain, dtype="float32")  # dry[i]: dry days ending at day i
    run = np.zeros(rain.shape[1], dtype="float32")
    for i in range(len(days)):
        run = np.where(rain[i] < DRY_DAY_MM, np.minimum(run + 1, LOOKBACK_DAYS), 0)
        dry[i] = run

    t = np.arange(LOOKBACK_DAYS, len(days))  # study-day indices; t-1 is the previous day
    features = {
        "max_temp_prev": raw["max_temp"][t - 1],
        "min_temp_prev": raw["min_temp"][t - 1],
        "rain_prev": raw["daily_rain"][t - 1],
        "rain_7d": (cumulative[t] - cumulative[t - 7]).astype("float32"),
        "rain_30d": (cumulative[t] - cumulative[t - 30]).astype("float32"),
        "dry_days": dry[t - 1],
        "vp_prev": raw["vp"][t - 1],
        "wind_prev": raw["wind_10m"][t - 1],
    }
    features["vpd_prev"] = np.maximum(saturation_vp(features["max_temp_prev"]) - features["vp_prev"], 0).astype("float32")
    return days[t], features


def label_arrays(labels, dates, n_cells):
    index = pd.Series(np.arange(len(dates)), index=dates)
    rows = labels.loc[labels["date"].isin(dates)]
    i, j = index[rows["date"]].values, rows["cell"].values
    shape = (len(dates), n_cells)
    out = {
        "burned": np.zeros(shape, dtype="int8"),
        "burned_fraction": np.zeros(shape, dtype="float32"),
        "burned_pixels": np.zeros(shape, dtype="int32"),
        "burn_type": np.zeros(shape, dtype="int8"),
        "share_wildfire": np.zeros(shape, dtype="float32"),
        "share_prescribed": np.zeros(shape, dtype="float32"),
    }
    out["burned"][i, j] = rows["burned"].values
    out["burned_fraction"][i, j] = rows["burned_fraction"].values
    out["burned_pixels"][i, j] = rows["burned_pixels"].values
    out["burn_type"][i, j] = rows["burn_type"].map({name: k for k, name in enumerate(BURN_TYPES)}).values
    out["share_wildfire"][i, j] = rows["share_wildfire"].values
    out["share_prescribed"][i, j] = rows["share_prescribed"].values
    return out


def main():
    spec, cell_id, _ = load_grid()
    n_cells = spec["nsw_cells"]
    x, y, _, _ = cell_centres(spec)
    inside = cell_id >= 0
    order = np.argsort(cell_id[inside])
    rows_idx, cols_idx = np.nonzero(inside)
    rows_idx, cols_idx = rows_idx[order], cols_idx[order]
    blocks_per_row = int(np.ceil(spec["width"] / BLOCK_CELLS))
    static = {
        "x": x[inside][order].astype("float32"),
        "y": y[inside][order].astype("float32"),
        "block_id": ((rows_idx // BLOCK_CELLS) * blocks_per_row + cols_idx // BLOCK_CELLS).astype("int16"),
    }
    with xr.open_dataset(PROCESSED / "static" / "terrain.nc") as terrain:
        for name in TERRAIN:
            static["elevation" if name == "elevation_mean" else name] = terrain[name].values.astype("float32")
    vegetation = xr.open_dataset(PROCESSED / "monthly" / "vegetation.nc").load()
    labels = pd.read_parquet(PROCESSED / "labels" / "burn_cell_days.parquet")
    labels = labels.loc[labels["in_study_period"]]

    if OUT.exists():
        shutil.rmtree(OUT)
    exclusions, summary = [], []
    for start, end in STUDY_BLOCKS:
        dates, weather = block_weather(start, end)
        for year in sorted(set(dates.year)):
            in_year = dates.year == year
            year_dates = dates[in_year]
            n_days = len(year_dates)
            columns = {name: values[in_year] for name, values in weather.items()}

            # Vegetation: last full month before the target day's month.
            veg_month = (year_dates.to_period("M") - 1).to_timestamp()
            for source, name in VEGETATION.items():
                columns[name] = vegetation[source].sel(month=veg_month).values
            columns["veg_valid_fraction"] = vegetation["valid_fraction"].sel(month=veg_month).values
            columns.update(label_arrays(labels, year_dates, n_cells))

            table = {
                "cell_id": np.tile(np.arange(n_cells, dtype="int32"), n_days),
                "date": np.repeat(year_dates.values.astype("datetime64[D]"), n_cells),
                "year": np.full(n_days * n_cells, year, dtype="int16"),
                "month": np.repeat(year_dates.month.values.astype("int8"), n_cells),
                "weather_date": np.repeat((year_dates - pd.Timedelta(days=1)).values.astype("datetime64[D]"), n_cells),
                "veg_month": np.repeat(veg_month.values.astype("datetime64[D]"), n_cells),
            }
            for name, values in static.items():
                table[name] = np.tile(values, n_days)
            for name, values in columns.items():
                table[name] = values.reshape(-1)
            table["veg_partial"] = (table["veg_valid_fraction"] < VEG_PARTIAL).astype("int8")
            # Burn-quality flags (readiness check): burned cell-days not matched to an NPWS
            # polygon, and burned cell-days covering less than 5% of the cell.
            burned = table["burned"] == 1
            table["burn_unconfirmed"] = (burned & (table["burn_type"] == BURN_TYPES.index("unknown"))).astype("int8")
            table["burn_small"] = (burned & (table["burned_fraction"] < SMALL_BURN)).astype("int8")

            frame = pd.DataFrame(table)
            missing = frame[REQUIRED].isna()
            dropped = missing.any(axis=1)
            for name in REQUIRED:
                if missing[name].any():
                    exclusions.append({"year": year, "reason": f"missing {name}", "rows": int(missing[name].sum())})
            exclusions.append({"year": year, "reason": "any required predictor missing (rows dropped)", "rows": int(dropped.sum())})
            frame = frame.loc[~dropped]
            frame["burn_type"] = pd.Categorical.from_codes(frame["burn_type"], categories=BURN_TYPES)

            path = OUT / str(year) / "part-0.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path, row_group_size=1_000_000, compression="zstd")
            summary.append({
                "year": year, "days": n_days, "rows": len(frame), "rows_dropped": int(dropped.sum()),
                "burned_rows": int(frame["burned"].sum()), "any_burn_rows": int((frame["burned_fraction"] > 0).sum()),
                "first_date": str(year_dates[0].date()), "last_date": str(year_dates[-1].date()),
            })
            print(summary[-1], flush=True)
            del frame, table, columns

    pd.DataFrame(exclusions).to_csv(OUTPUTS / "pixel_day_exclusions.csv", index=False)
    totals = pd.DataFrame(summary)
    totals.to_csv(OUTPUTS / "pixel_day_summary.csv", index=False)
    print(totals.sum(numeric_only=True).to_string())


if __name__ == "__main__":
    main()
