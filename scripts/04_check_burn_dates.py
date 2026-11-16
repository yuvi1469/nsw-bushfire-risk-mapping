"""Workflow Step 3.8: compare each burnt area file's name and time stamp with the burn dates inside it.

Reads only the NSW window of each file. Writes outputs/burn_date_check.csv.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "tern_burnt_area"
OUT = ROOT / "outputs" / "burn_date_check.csv"
EPOCH = pd.Timestamp("1970-01-01")
NSW_WINDOW = {"latitude": slice(-28.0, -37.6), "longitude": slice(140.9, 153.7)}


def main():
    rows = []
    for path in sorted(RAW.glob("dob_*.nc")):
        start, end = (pd.Timestamp(part) for part in path.stem.split("_")[1:3])
        with xr.open_dataset(path, decode_times=False) as ds:
            stamp = EPOCH + pd.Timedelta(days=float(ds["time"].values[0]))
            values = ds["julian_date_of_burn"].isel(time=0).sel(**NSW_WINDOW).values
        burned = values[np.isfinite(values)]
        dates = EPOCH + pd.to_timedelta(np.floor(burned), unit="D") if burned.size else pd.DatetimeIndex([])
        months = pd.Series(dates.to_period("M")).value_counts() if burned.size else pd.Series(dtype=int)
        rows.append({
            "file": path.name,
            "name_month": start.strftime("%Y-%m"),
            "time_stamp": stamp.strftime("%Y-%m-%d"),
            "nsw_burned_pixels": int(burned.size),
            "first_burn_date": dates.min().date() if burned.size else None,
            "last_burn_date": dates.max().date() if burned.size else None,
            "main_burn_month": str(months.idxmax()) if burned.size else None,
            "share_in_name_month": round(float((dates.to_period("M") == start.to_period("M")).mean()), 3) if burned.size else None,
            "share_in_previous_month": round(float((dates.to_period("M") == (start - pd.offsets.MonthBegin(1)).to_period("M")).mean()), 3) if burned.size else None,
        })
        print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(OUT, index=False)


if __name__ == "__main__":
    main()
