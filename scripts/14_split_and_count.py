"""Workflow Step 5.2 and 5.7: assign the holdouts, then count the eligible population.

Holdouts are fixed before any sampling.
- Time: the three study blocks are the natural split. Earlier years train, middle years
  validate, latest years test:
    train      1 Aug 2002 - 30 Nov 2008
    validation 1 Dec 2010 - 30 Nov 2013
    test       1 Dec 2015 - 31 Jan 2017
- Space: 20% of the 100 km blocks in each longitude region (seeded) are held out.
  Train and validation use only the other blocks; test uses only the held-out blocks.
  Rows in held-out blocks during train/validation years, and in other blocks during the
  test period, are not used. Train and test therefore share no cells and no dates.

Strata substitutes (the report's "fire region" and "vegetation class" are not in the
source list):
- region: four longitude bands of the cell centre (141-144, 144-147, 147-150, 150-154 E);
- veg_band: tertiles of each cell's mean total cover over the training years (2002-2008).

Writes data/processed/splits/cells.csv, outputs/population_counts.csv and
outputs/population_histograms.json (for the coverage audit).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import xarray as xr
from pyproj import Transformer

from grid import OUTPUTS, PROCESSED

SEED = 20261117
HOLDOUT_SHARE = 0.20
PERIODS = {"train": ("2002-08-01", "2008-11-30"), "validation": ("2010-12-01", "2013-11-30"), "test": ("2015-12-01", "2017-01-31")}
REGIONS = [141, 144, 147, 150, 154]
REGION_NAMES = ["far_west", "west", "central", "east"]
SPLITS = PROCESSED / "splits"
HISTOGRAMS = {
    "max_temp_prev": np.arange(-10, 51, 1.0),
    "vpd_prev": np.arange(0, 81, 1.0),
    "wind_prev": np.arange(0, 21, 0.5),
    "dry_days": np.arange(0, 32, 1.0),
    "rain_30d": np.arange(0, 1001, 5.0),
    "npv": np.arange(0, 112, 2.0),
}


def cell_table():
    first = pd.read_parquet(PROCESSED / "pixel_day" / "2003" / "part-0.parquet", columns=["cell_id", "x", "y", "block_id"]).drop_duplicates("cell_id")
    lon, _ = Transformer.from_crs("EPSG:8058", "EPSG:4326", always_xy=True).transform(first["x"].values, first["y"].values)
    cells = first.assign(lon=lon).sort_values("cell_id").reset_index(drop=True)
    cells["region"] = pd.cut(cells["lon"], REGIONS, labels=REGION_NAMES).astype(str)

    with xr.open_dataset(PROCESSED / "monthly" / "vegetation.nc") as veg:
        cover = veg["tot_cov"].sel(month=slice("2002-01-01", "2008-12-01")).mean("month").values
    cells["mean_total_cover_2002_2008"] = cover[cells["cell_id"].values]
    edges = np.nanquantile(cells["mean_total_cover_2002_2008"], [1 / 3, 2 / 3])
    cells["veg_band"] = np.select([cells["mean_total_cover_2002_2008"] < edges[0], cells["mean_total_cover_2002_2008"] < edges[1]], ["low_cover", "mid_cover"], "high_cover")

    # Each block belongs to the region holding most of its cells.
    block_region = cells.groupby("block_id")["region"].agg(lambda r: r.value_counts().idxmax())
    rng = np.random.default_rng(SEED)
    held = []
    for region, blocks in block_region.groupby(block_region):
        ids = np.sort(blocks.index.values)
        n = max(1, int(round(HOLDOUT_SHARE * len(ids))))
        held.extend(rng.choice(ids, size=n, replace=False).tolist())
    cells["spatial_holdout"] = cells["block_id"].isin(held).astype("int8")
    return cells, edges, sorted(int(b) for b in held)


def partition(dates, holdout):
    role = np.full(len(dates), "unused", dtype=object)
    for name, (start, end) in PERIODS.items():
        in_period = (dates >= start) & (dates <= end)
        use = in_period & ((holdout == 1) if name == "test" else (holdout == 0))
        role[use] = name
    return role


def main():
    cells, edges, held = cell_table()
    SPLITS.mkdir(parents=True, exist_ok=True)
    cells.to_csv(SPLITS / "cells.csv", index=False)

    counts, hist = [], {}
    for path in sorted((PROCESSED / "pixel_day").glob("*/part-0.parquet")):
        frame = pd.read_parquet(path, columns=["cell_id", "date", "year", "month", "block_id", "burned", "burn_type", *HISTOGRAMS])
        frame = frame.merge(cells[["cell_id", "region", "veg_band", "spatial_holdout"]], on="cell_id")
        frame["partition"] = partition(pd.to_datetime(frame["date"]), frame["spatial_holdout"].values)
        counts.append(frame.groupby(["partition", "year", "month", "region", "veg_band", "block_id"], observed=True).agg(rows=("burned", "size"), burned=("burned", "sum")).reset_index())
        for (part, burned), group in frame.groupby(["partition", "burned"]):
            for name, bins in HISTOGRAMS.items():
                key = f"{part}|{burned}|{name}"
                values = np.clip(group[name].values, bins[0], bins[-1] - 1e-6)
                hist[key] = (np.array(hist.get(key, np.zeros(len(bins) - 1))) + np.histogram(values, bins)[0]).tolist()
        print(f"{path.parent.name} counted", flush=True)

    counts = pd.concat(counts, ignore_index=True)
    counts.to_csv(OUTPUTS / "population_counts.csv", index=False)
    (OUTPUTS / "population_histograms.json").write_text(json.dumps({"bins": {k: v.tolist() for k, v in HISTOGRAMS.items()}, "counts": hist}))

    summary = counts.groupby("partition").agg(rows=("rows", "sum"), burned=("burned", "sum"))
    summary["prevalence"] = summary["burned"] / summary["rows"]
    blocks = cells.groupby("spatial_holdout")["block_id"].nunique()
    print(summary.to_string())
    print(f"veg_band edges (mean total cover %): {np.round(edges, 1).tolist()}")
    print(f"blocks: {blocks.to_dict()}; held out: {held}")
    print(counts.loc[counts["partition"] == "train"].groupby(["region", "veg_band"]).agg(rows=("rows", "sum"), burned=("burned", "sum")).to_string())


if __name__ == "__main__":
    main()
