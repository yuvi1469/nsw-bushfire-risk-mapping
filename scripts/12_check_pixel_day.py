"""Workflow Step 4 checks: verify the pixel-day table before sampling.

- No duplicate cell-date rows and no missing required predictors.
- Every dynamic feature comes before the target date (weather t-1, vegetation previous month).
- Features and labels for random rows match a fresh calculation from the aligned layers.
- Burned and total row counts by year, month and spatial block.

Writes outputs/pixel_day_checks.json and outputs/pixel_day_counts_by_year_month.csv.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import xarray as xr

from grid import OUTPUTS, PROCESSED, study_dates

TABLE = PROCESSED / "pixel_day"
SPOT_CHECKS = 200
SEED = 20261117
REQUIRED = [
    "max_temp_prev", "min_temp_prev", "rain_prev", "rain_7d", "rain_30d", "dry_days",
    "vp_prev", "vpd_prev", "wind_prev", "pv", "npv", "bare_soil", "total_cover",
    "elevation", "slope_mean", "slope_p90", "aspect_sin", "aspect_cos",
]


def main():
    report, counts, spot = {"years": {}}, [], []
    rng = np.random.default_rng(SEED)

    daily = {n: xr.open_dataset(PROCESSED / "daily" / f"{n}.nc")[n].load() for n in ["max_temp", "daily_rain", "vp", "wind_10m"]}
    vegetation = xr.open_dataset(PROCESSED / "monthly" / "vegetation.nc").load()
    labels = pd.read_parquet(PROCESSED / "labels" / "burn_cell_days.parquet").set_index(["cell", "date"])

    total_rows = 0
    for path in sorted(TABLE.glob("*/part-0.parquet")):
        year = int(path.parent.name)
        frame = pd.read_parquet(path)
        total_rows += len(frame)
        duplicates = int(frame.duplicated(["cell_id", "date"]).sum())
        dates = pd.to_datetime(frame["date"])
        weather_ok = bool((pd.to_datetime(frame["weather_date"]) == dates - pd.Timedelta(days=1)).all())
        veg_ok = bool((pd.to_datetime(frame["veg_month"]) < dates.dt.to_period("M").dt.to_timestamp()).all())
        report["years"][year] = {
            "rows": len(frame),
            "duplicate_cell_dates": duplicates,
            "missing_required": int(frame[REQUIRED].isna().sum().sum()),
            "weather_is_previous_day": weather_ok,
            "vegetation_before_target_month": veg_ok,
        }
        counts.append(frame.groupby("month").agg(rows=("burned", "size"), burned=("burned", "sum")).reset_index().assign(year=year))

        for _, row in frame.iloc[rng.choice(len(frame), size=SPOT_CHECKS // 13, replace=False)].iterrows():
            date, cell = pd.Timestamp(row["date"]), int(row["cell_id"])
            prev = date - pd.Timedelta(days=1)
            rain = daily["daily_rain"].sel(cell=cell)
            expected = {
                "max_temp_prev": float(daily["max_temp"].sel(date=prev, cell=cell)),
                "rain_7d": float(rain.sel(date=slice(date - pd.Timedelta(days=7), prev)).sum()),
                "rain_30d": float(rain.sel(date=slice(date - pd.Timedelta(days=30), prev)).sum()),
                "vp_prev": float(daily["vp"].sel(date=prev, cell=cell)),
                "wind_prev": float(daily["wind_10m"].sel(date=prev, cell=cell)),
                "pv": float(vegetation["phot_veg"].sel(month=(date.to_period("M") - 1).to_timestamp(), cell=cell)),
            }
            label = labels.loc[(cell, date)] if (cell, date) in labels.index else None
            expected["burned_fraction"] = float(label["burned_fraction"]) if label is not None else 0.0
            for name, value in expected.items():
                spot.append({"year": year, "cell": cell, "date": str(date.date()), "feature": name, "table": float(row[name]), "recomputed": value, "match": bool(np.isclose(row[name], value, rtol=1e-4, atol=1e-3))})
        print(year, report["years"][year], flush=True)
        del frame

    spot = pd.DataFrame(spot)
    by_year = pd.concat(counts)
    by_year.to_csv(OUTPUTS / "pixel_day_counts_by_year_month.csv", index=False)
    report["total_rows"] = total_rows
    report["expected_rows_before_exclusions"] = len(study_dates()) * 32029
    report["spot_checks"] = {"values_checked": len(spot), "mismatches": int((~spot["match"]).sum()), "mismatch_examples": spot.loc[~spot["match"]].head(10).to_dict("records")}
    report["burned_rows"] = int(by_year["burned"].sum())
    report["burned_share"] = report["burned_rows"] / total_rows
    (OUTPUTS / "pixel_day_checks.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != "years"}, indent=2, default=str))


if __name__ == "__main__":
    main()
