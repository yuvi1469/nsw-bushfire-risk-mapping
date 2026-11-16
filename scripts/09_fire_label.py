"""Workflow Step 3.7: build the cell-day fire label and cross-check it against NSW NPWS records.

Burn dates come from the values inside each TERN file (fractional days since 1970-01-01),
not the file name, because every file holds the month before the one it is named for.
Each 250 m burned pixel is assigned to the cell containing its centre and weighted by its
area. A pixel-date seen in two files is counted once.

Partial-cell rule: a cell-day is labelled burned when burned_fraction >= BURN_THRESHOLD.
The fraction is kept so the threshold can be tested later.

Burn type: each burned pixel is matched to NPWS polygons from the same fire season
(1 July - 30 June). The cell-day takes the type covering most of its matched pixels,
or "unknown" when no NPWS polygon matches.

Writes data/processed/labels/burn_cell_days.parquet and outputs/fire_label_checks.csv.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from pyproj import Transformer

from grid import CELL, CRS, OUTPUTS, PROCESSED, RAW, STUDY_BLOCKS, load_grid

BURN_THRESHOLD = 0.01
EPOCH = pd.Timestamp("1970-01-01")
WINDOW = {"latitude": slice(-27.9, -37.7), "longitude": slice(140.8, 153.8)}
NPWS = RAW / "npws_fire_history" / "fire_npwsfirehistory.zip"
OUT = PROCESSED / "labels" / "burn_cell_days.parquet"


def fire_season(date):
    start = date.year if date.month >= 7 else date.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def load_npws():
    fires = gpd.read_file(f"zip://{NPWS.as_posix()}!NPWSFireHistory.shp")
    fires["season"] = fires["Label"].str.extract(r"(\d{4}-\d{2})", expand=False)
    fires = fires.dropna(subset=["season"])
    fires = fires.loc[fires["season"].between("2002-03", "2016-17"), ["season", "FireType", "AreaHa", "geometry"]]
    return fires.to_crs("EPSG:4326")


def npws_types(frame, lat, lon, fires):
    """Match burned pixels to NPWS polygons of the same fire season."""
    seasons = frame["date"].map(fire_season)
    points = gpd.GeoDataFrame({"season": seasons}, geometry=gpd.points_from_xy(lon[frame["col"]], lat[frame["row"]]), crs="EPSG:4326")
    joined = gpd.sjoin(points, fires, predicate="within", how="inner")
    joined = joined.loc[joined["season_left"] == joined["season_right"]]
    # A pixel inside both a wildfire and a prescribed burn polygon counts as wildfire.
    pixel_type = joined.groupby(level=0)["FireType"].min()
    return pixel_type.reindex(frame.index).map({1: "wildfire", 2: "prescribed"}).fillna("unknown").values


def pixel_cells(lat, lon, spec, cell_id):
    lon2, lat2 = np.meshgrid(lon, lat)
    x, y = Transformer.from_crs("EPSG:4326", CRS, always_xy=True).transform(lon2, lat2)
    col = np.floor((x - spec["x_min"]) / CELL).astype(int)
    row = np.floor((spec["y_max"] - y) / CELL).astype(int)
    inside = (row >= 0) & (row < spec["height"]) & (col >= 0) & (col < spec["width"])
    cells = np.full(lon2.shape, -1, dtype="int64")
    cells[inside] = cell_id[row[inside], col[inside]]
    return cells, np.cos(np.radians(lat2))


def main():
    spec, cell_id, _ = load_grid()
    fires = load_npws()
    files = sorted((RAW / "tern_burnt_area").glob("dob_*.nc"))

    with xr.open_dataset(files[0], decode_times=False) as ds:
        lat, lon = ds["latitude"].sel(latitude=WINDOW["latitude"]).values, ds["longitude"].sel(longitude=WINDOW["longitude"]).values
    cells, weight = pixel_cells(lat, lon, spec, cell_id)
    cell_weight = np.bincount(cells[cells >= 0], weights=weight[cells >= 0], minlength=spec["nsw_cells"])

    pixels = []
    for path in files:
        with xr.open_dataset(path, decode_times=False) as ds:
            window = ds["julian_date_of_burn"].isel(time=0).sel(**WINDOW)
            if not (np.array_equal(window.latitude.values, lat) and np.array_equal(window.longitude.values, lon)):
                raise ValueError(f"{path.name} uses a different grid")
            values = window.values
        rows, cols = np.nonzero(np.isfinite(values) & (cells >= 0))
        dates = EPOCH + pd.to_timedelta(np.floor(values[rows, cols]), unit="D")
        frame = pd.DataFrame({"row": rows, "col": cols, "date": dates, "file": path.name})
        frame["npws_type"] = npws_types(frame, lat, lon, fires)
        pixels.append(frame)
        print(f"{path.name}: {len(rows)} burned NSW pixels", flush=True)

    pixels = pd.concat(pixels, ignore_index=True)
    before = len(pixels)
    pixels = pixels.drop_duplicates(["row", "col", "date"]).reset_index(drop=True)
    in_study = np.zeros(len(pixels), dtype=bool)
    for start, end in STUDY_BLOCKS:
        in_study |= pixels["date"].between(start, end).values
    pixels["cell"] = cells[pixels["row"], pixels["col"]]
    pixels["weight"] = weight[pixels["row"], pixels["col"]]
    pixels["season"] = pixels["date"].map(fire_season)

    grouped = pixels.groupby(["cell", "date"])
    cell_days = grouped.agg(burned_pixels=("weight", "size"), burned_weight=("weight", "sum"), first_file=("file", "first")).reset_index()
    cell_days["burned_fraction"] = (cell_days["burned_weight"] / cell_weight[cell_days["cell"]]).astype("float32")
    shares = pixels.pivot_table(index=["cell", "date"], columns="npws_type", values="weight", aggfunc="sum", fill_value=0)
    shares = shares.div(shares.sum(axis=1), axis=0).reindex(columns=["wildfire", "prescribed", "unknown"], fill_value=0)
    cell_days = cell_days.merge(shares.add_prefix("share_").reset_index(), on=["cell", "date"])
    matched = cell_days[["share_wildfire", "share_prescribed"]]
    cell_days["burn_type"] = np.where(matched.sum(axis=1) == 0, "unknown", np.where(matched["share_wildfire"] >= matched["share_prescribed"], "wildfire", "prescribed"))
    cell_days["burned"] = cell_days["burned_fraction"] >= BURN_THRESHOLD
    cell_days["in_study_period"] = False
    for start, end in STUDY_BLOCKS:
        cell_days.loc[cell_days["date"].between(start, end), "in_study_period"] = True
    cell_days = cell_days.drop(columns="burned_weight")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cell_days.to_parquet(OUT, index=False)

    # Season-level comparison with NPWS records.
    pixel_km2 = (lat[1] - lat[0]) * (lon[1] - lon[0])
    pixels["area_km2"] = np.abs(pixel_km2) * (111.32 ** 2) * pixels["weight"]
    tern = pixels.loc[in_study].groupby("season").agg(tern_burned_km2=("area_km2", "sum"))
    tern["tern_share_matched_to_npws"] = pixels.loc[in_study].assign(m=lambda d: d["npws_type"] != "unknown").groupby("season").apply(lambda d: (d["area_km2"] * d["m"]).sum() / d["area_km2"].sum())
    npws = fires.assign(type=fires["FireType"].map({1: "npws_wildfire_km2", 2: "npws_prescribed_km2"})).pivot_table(index="season", columns="type", values="AreaHa", aggfunc="sum", fill_value=0) / 100
    checks = tern.join(npws, how="outer").round(3)
    checks.to_csv(OUTPUTS / "fire_label_checks.csv")

    labelled = cell_days.loc[cell_days["in_study_period"]]
    print(f"pixel-dates: {before}, after removing duplicates: {len(pixels)}")
    print(f"cell-days with any burn in study period: {len(labelled)}; labelled burned (>= {BURN_THRESHOLD}): {int(labelled['burned'].sum())}")
    print(labelled.loc[labelled["burned"], "burn_type"].value_counts().to_string())
    print(checks.to_string())


if __name__ == "__main__":
    main()
