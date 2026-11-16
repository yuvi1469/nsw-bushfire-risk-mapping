"""Workflow Steps 3.3-3.4: aggregate monthly MODIS fractional cover to the 5 km grid.

Each 463 m sinusoidal pixel is assigned to the project cell that contains its centre.
Cell values are the mean of valid pixels; valid_fraction records how many of the cell's
pixels had data that month, so cloud or no-data gaps stay visible.

Writes data/processed/monthly/vegetation.nc with dims (month, cell).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import xarray as xr
from pyproj import CRS as ProjCRS
from pyproj import Transformer

from grid import CELL, CRS, PROCESSED, RAW, load_grid

FOLDER = RAW / "tern_fractional_cover"
TILES = ["h29v12", "h30v11", "h30v12", "h31v11", "h31v12"]
YEARS = range(2002, 2018)
VARIABLES = ["phot_veg", "nphot_veg", "bare_soil", "tot_cov"]
OUT = PROCESSED / "monthly" / "vegetation.nc"


def tile_cells(path, spec, cell_id):
    """Cell ID for every pixel in a tile (-1 when outside NSW)."""
    with xr.open_dataset(path) as ds:
        wkt = ds["sinusoidal"].attrs["spatial_ref"]
        x, y = ds["x"].values, ds["y"].values
    xx, yy = np.meshgrid(x, y)
    px, py = Transformer.from_crs(ProjCRS.from_wkt(wkt), CRS, always_xy=True).transform(xx, yy)
    col = np.floor((px - spec["x_min"]) / CELL).astype(int)
    row = np.floor((spec["y_max"] - py) / CELL).astype(int)
    inside = (row >= 0) & (row < spec["height"]) & (col >= 0) & (col < spec["width"])
    cells = np.full(xx.shape, -1, dtype="int64")
    cells[inside] = cell_id[row[inside], col[inside]]
    return cells.ravel()


def main():
    spec, cell_id, _ = load_grid()
    n_cells = spec["nsw_cells"]
    months = pd.period_range(f"{YEARS[0]}-01", f"{YEARS[-1]}-12", freq="M")
    sums = {v: np.zeros((len(months), n_cells)) for v in VARIABLES}
    counts = {v: np.zeros((len(months), n_cells)) for v in VARIABLES}
    pixels = np.zeros(n_cells)

    for tile in TILES:
        cells = tile_cells(FOLDER / f"FC_Monthly_Medoid.v310.MCD43A4.{tile}.{YEARS[0]}.006.nc", spec, cell_id)
        keep = cells >= 0
        if not keep.any():
            print(f"{tile}: no NSW cells", flush=True)
            continue
        pixels += np.bincount(cells[keep], minlength=n_cells)
        for year in YEARS:
            with xr.open_dataset(FOLDER / f"FC_Monthly_Medoid.v310.MCD43A4.{tile}.{year}.006.nc") as ds:
                stamps = pd.DatetimeIndex(ds["time"].values).to_period("M")
                for variable in VARIABLES:
                    cube = ds[variable].values.reshape(len(stamps), -1)[:, keep]
                    for t, month in enumerate(stamps):
                        m = months.get_loc(month)
                        valid = np.isfinite(cube[t])
                        sums[variable][m] += np.bincount(cells[keep][valid], weights=cube[t][valid], minlength=n_cells)
                        counts[variable][m] += np.bincount(cells[keep][valid], minlength=n_cells)
            print(f"{tile} {year} done", flush=True)

    coords = {"month": months.to_timestamp(), "cell": np.arange(n_cells)}
    data = {}
    for variable in VARIABLES:
        with np.errstate(invalid="ignore", divide="ignore"):
            data[variable] = (("month", "cell"), np.where(counts[variable] > 0, sums[variable] / counts[variable], np.nan).astype("float32"))
    with np.errstate(invalid="ignore", divide="ignore"):
        data["valid_fraction"] = (("month", "cell"), np.where(pixels > 0, counts["tot_cov"] / pixels, 0).astype("float32"))
    ds = xr.Dataset(data, coords=coords)
    ds["pixels_per_cell"] = ("cell", pixels.astype("int32"))
    ds.attrs = {"source": "TERN MODIS fractional cover v310 monthly medoid", "method": "mean of valid 463 m pixels whose centre lies in the cell", "units": "%"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(OUT, encoding={v: {"zlib": True, "complevel": 4} for v in ds.data_vars})
    print(f"cells with no pixels: {int((pixels == 0).sum())}; median pixels per cell: {np.median(pixels):.0f}")


if __name__ == "__main__":
    main()
