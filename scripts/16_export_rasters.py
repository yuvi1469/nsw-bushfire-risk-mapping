"""Workflow Step 7 outputs 2-3: write the aligned layers as georeferenced rasters on the project grid.

The working layers are stored by cell number. This exports them as grids with the
project CRS (EPSG:8058) and 5 km transform, NaN outside NSW:
- daily weather and wind stacks (date, y, x), NetCDF;
- monthly vegetation stack (month, y, x), NetCDF;
- terrain, one GeoTIFF with one band per field;
- burned-area label (date, y, x) for study days, NetCDF: burned_fraction and burned
  (burned_fraction >= 0.01, the partial-cell rule).

Writes data/processed/rasters/.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import rasterio
import rioxarray  # noqa: F401  (adds .rio to xarray)
import xarray as xr

from grid import CELL, CRS, PROCESSED, load_grid, study_dates

OUT = PROCESSED / "rasters"
BURN_THRESHOLD = 0.01


def to_grid(values, cell_id):
    """(..., cell) -> (..., y, x) with NaN outside NSW."""
    inside = cell_id >= 0
    grid = np.full(values.shape[:-1] + cell_id.shape, np.nan, dtype="float32")
    grid[..., inside] = values[..., cell_id[inside]]
    return grid


def georeference(ds, spec):
    x = spec["x_min"] + CELL * (np.arange(spec["width"]) + 0.5)
    y = spec["y_max"] - CELL * (np.arange(spec["height"]) + 0.5)
    ds = ds.assign_coords(x=("x", x), y=("y", y))
    ds["x"].attrs = {"units": "m", "standard_name": "projection_x_coordinate"}
    ds["y"].attrs = {"units": "m", "standard_name": "projection_y_coordinate"}
    ds = ds.rio.write_crs(CRS).rio.write_coordinate_system()
    # Link each variable to the CRS so GIS tools read the projection from the file.
    for name in ds.data_vars:
        ds[name].attrs["grid_mapping"] = "spatial_ref"
    return ds


def write_stack(name, data, time_name, times, spec, cell_id, attrs, path):
    ds = xr.Dataset({name: ((time_name, "y", "x"), to_grid(data, cell_id))}, coords={time_name: times})
    ds[name].attrs = attrs
    ds = georeference(ds, spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(path, encoding={name: {"zlib": True, "complevel": 4, "chunksizes": (1, spec["height"], spec["width"])}})
    print(f"wrote {path.relative_to(PROCESSED)}", flush=True)


def main():
    spec, cell_id, transform = load_grid()

    for name in ["max_temp", "min_temp", "daily_rain", "vp", "wind_10m"]:
        with xr.open_dataset(PROCESSED / "daily" / f"{name}.nc") as ds:
            data = ds[name].load()
        write_stack(name, data.values, "date", data.date.values, spec, cell_id, data.attrs, OUT / "daily" / f"{name}.nc")

    with xr.open_dataset(PROCESSED / "monthly" / "vegetation.nc") as veg:
        veg = veg.load()
    grids = {v: (("month", "y", "x"), to_grid(veg[v].values, cell_id)) for v in ["phot_veg", "nphot_veg", "bare_soil", "tot_cov", "valid_fraction"]}
    ds = georeference(xr.Dataset(grids, coords={"month": veg.month.values}), spec)
    ds.attrs = veg.attrs
    (OUT / "monthly").mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(OUT / "monthly" / "vegetation.nc", encoding={v: {"zlib": True, "complevel": 4} for v in grids})
    print("wrote rasters/monthly/vegetation.nc", flush=True)

    with xr.open_dataset(PROCESSED / "static" / "terrain.nc") as terrain:
        names = [n for n in terrain.data_vars]
        bands = np.stack([to_grid(terrain[n].values, cell_id) for n in names])
    profile = {"driver": "GTiff", "width": spec["width"], "height": spec["height"], "count": len(names), "dtype": "float32", "crs": CRS, "transform": transform, "nodata": np.nan, "compress": "deflate"}
    (OUT / "static").mkdir(parents=True, exist_ok=True)
    with rasterio.open(OUT / "static" / "terrain.tif", "w", **profile) as dst:
        dst.write(bands)
        for i, n in enumerate(names, start=1):
            dst.set_band_description(i, n)
    print("wrote rasters/static/terrain.tif", flush=True)

    dates = study_dates()
    labels = pd.read_parquet(PROCESSED / "labels" / "burn_cell_days.parquet")
    labels = labels.loc[labels["in_study_period"]]
    fraction = np.zeros((len(dates), spec["nsw_cells"]), dtype="float32")
    fraction[pd.Index(dates).get_indexer(labels["date"]), labels["cell"].values] = labels["burned_fraction"].values
    label = xr.Dataset(
        {
            "burned_fraction": (("date", "y", "x"), to_grid(fraction, cell_id)),
            "burned": (("date", "y", "x"), to_grid((fraction >= BURN_THRESHOLD).astype("float32"), cell_id)),
        },
        coords={"date": dates},
    )
    label["burned_fraction"].attrs = {"units": "1", "long_name": "Share of the cell's 250 m pixels with this burn date (TERN MODIS burnt area)"}
    label["burned"].attrs = {"long_name": "1 when burned_fraction >= 0.01 (partial-cell rule), 0 otherwise, NaN outside NSW"}
    label = georeference(label, spec)
    (OUT / "label").mkdir(parents=True, exist_ok=True)
    label.to_netcdf(OUT / "label" / "burned_area_label.nc", encoding={v: {"zlib": True, "complevel": 4, "chunksizes": (1, spec["height"], spec["width"])} for v in ["burned_fraction", "burned"]})
    print("wrote rasters/label/burned_area_label.nc", flush=True)


if __name__ == "__main__":
    main()
