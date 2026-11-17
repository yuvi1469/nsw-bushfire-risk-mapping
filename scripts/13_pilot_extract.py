"""Workflow Step 5.1: run a small pilot extract and check it against the aligned layers.

Takes 30,000 rows from two years (2003 and 2012) and two subregions (one inland and one
coastal 100 km block row), then recalculates every weather, vegetation, terrain and label
value for every pilot row from data/processed and compares.

Writes data/processed/sample/pilot_30k.parquet and outputs/pilot_checks.json.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import xarray as xr

from grid import OUTPUTS, PROCESSED

YEARS = [2003, 2012]
PILOT_ROWS = 30_000
SEED = 20261117
OUT = PROCESSED / "sample" / "pilot_30k.parquet"
TOLERANCE = {"rtol": 1e-4, "atol": 1e-3}


def pick_subregions(frame):
    """One inland and one coastal block: the blocks with most cells west of 146 E and east of 151 E."""
    from pyproj import Transformer
    lon, _ = Transformer.from_crs("EPSG:8058", "EPSG:4326", always_xy=True).transform(frame["x"].values, frame["y"].values)
    cells = pd.DataFrame({"block_id": frame["block_id"].values, "lon": lon}).drop_duplicates()
    inland = cells.loc[cells["lon"] < 146].groupby("block_id").size().idxmax()
    coastal = cells.loc[cells["lon"] > 151].groupby("block_id").size().idxmax()
    return [int(inland), int(coastal)]


def main():
    rng = np.random.default_rng(SEED)
    frames = []
    for year in YEARS:
        frames.append(pd.read_parquet(PROCESSED / "pixel_day" / str(year) / "part-0.parquet"))
    population = pd.concat(frames, ignore_index=True)
    blocks = pick_subregions(population.drop_duplicates("cell_id"))
    population = population.loc[population["block_id"].isin(blocks)]
    pilot = population.iloc[rng.choice(len(population), size=PILOT_ROWS, replace=False)].reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pilot.to_parquet(OUT, index=False)

    dates = pd.to_datetime(pilot["date"])
    prev = dates - pd.Timedelta(days=1)
    cells = pilot["cell_id"].values
    expected = {}

    for name, column in [("max_temp", "max_temp_prev"), ("min_temp", "min_temp_prev"), ("daily_rain", "rain_prev"), ("vp", "vp_prev"), ("wind_10m", "wind_prev")]:
        data = xr.open_dataset(PROCESSED / "daily" / f"{name}.nc")[name].load()
        index = pd.Index(pd.DatetimeIndex(data.date.values))
        values = data.values
        expected[column] = values[index.get_indexer(prev), cells]
        if name == "daily_rain":
            for days, column_sum in [(7, "rain_7d"), (30, "rain_30d")]:
                total = np.zeros(len(pilot))
                for k in range(1, days + 1):
                    total += values[index.get_indexer(dates - pd.Timedelta(days=k)), cells]
                expected[column_sum] = total
            dry = np.zeros(len(pilot))
            still_dry = np.ones(len(pilot), dtype=bool)
            for k in range(1, 31):
                still_dry &= values[index.get_indexer(dates - pd.Timedelta(days=k)), cells] < 2.0
                dry += still_dry
            expected["dry_days"] = dry

    vegetation = xr.open_dataset(PROCESSED / "monthly" / "vegetation.nc").load()
    months = pd.Index(pd.DatetimeIndex(vegetation.month.values))
    month_index = months.get_indexer((dates.dt.to_period("M") - 1).dt.to_timestamp())
    for source, column in [("phot_veg", "pv"), ("nphot_veg", "npv"), ("bare_soil", "bare_soil"), ("tot_cov", "total_cover")]:
        expected[column] = vegetation[source].values[month_index, cells]

    terrain = xr.open_dataset(PROCESSED / "static" / "terrain.nc").load()
    for source, column in [("elevation_mean", "elevation"), ("slope_mean", "slope_mean"), ("slope_p90", "slope_p90"), ("aspect_sin", "aspect_sin"), ("aspect_cos", "aspect_cos")]:
        expected[column] = terrain[source].values[cells]

    labels = pd.read_parquet(PROCESSED / "labels" / "burn_cell_days.parquet")
    merged = pilot[["cell_id", "date"]].assign(date=dates).merge(labels.rename(columns={"cell": "cell_id"}), on=["cell_id", "date"], how="left")
    expected["burned_fraction"] = merged["burned_fraction"].fillna(0).values
    expected["burned"] = merged["burned"].fillna(False).astype(int).values

    results = {}
    for column, values in expected.items():
        match = np.isclose(pilot[column].values.astype("float64"), np.asarray(values, dtype="float64"), **TOLERANCE)
        results[column] = {"checked": len(match), "mismatches": int((~match).sum())}
    report = {
        "years": YEARS,
        "blocks": blocks,
        "rows": len(pilot),
        "burned_rows": int(pilot["burned"].sum()),
        "duplicate_cell_dates": int(pilot.duplicated(["cell_id", "date"]).sum()),
        "weather_is_previous_day": bool((pd.to_datetime(pilot["weather_date"]) == prev).all()),
        "units": {"max_temp_prev": "Celsius", "rain": "mm", "vp_prev": "hPa", "wind_prev": "m/s", "vegetation": "%", "elevation": "m"},
        "value_ranges": pilot[list(expected)].describe().loc[["min", "max"]].round(3).to_dict(),
        "feature_checks": results,
        "total_mismatches": sum(r["mismatches"] for r in results.values()),
    }
    (OUTPUTS / "pilot_checks.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != "value_ranges"}, indent=2, default=str))


if __name__ == "__main__":
    main()
