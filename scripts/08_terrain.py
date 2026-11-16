"""Workflow Steps 3.4-3.5: derive slope and aspect from the DEM and aggregate them to the grid.

Method (documented GIS method):
- The 1 arc-second DEM is warped to the project CRS at 25 m (bilinear), so each 5 km cell
  holds exactly 200 x 200 DEM pixels.
- Slope (degrees) and aspect (compass degrees, clockwise from north, facing downslope)
  use Horn's (1981) 3x3 method, as in ArcGIS and GDAL gdaldem.
- Per cell: mean elevation, mean slope, 90th percentile slope, and aspect as the mean of
  sin(aspect) and cos(aspect) over pixels steeper than 1 degree, so flat ground does not
  add a false direction. Cells with no pixel steeper than 1 degree get 0/0 (no direction)
  and flat_cell = 1.
- Sea pixels in the DEM are about 0 m rather than nodata, so coastal cell means include them.

Writes data/processed/static/terrain.nc with dims (cell).
"""
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import rasterio
import xarray as xr
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window

from grid import CELL, CRS, INTERIM, PROCESSED, load_grid

DEM = INTERIM / "ga_dem_s_1sec" / "srtm-1sec-dems-v1-COG.tif"
OUT = PROCESSED / "static" / "terrain.nc"
PIXEL = 25.0
PER_CELL = int(CELL / PIXEL)
STRIP_ROWS = 4  # grid rows processed at once
FLAT_DEGREES = 1.0


def horn(z, size):
    a, b, c = z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:]
    d, f = z[1:-1, :-2], z[1:-1, 2:]
    g, h, i = z[2:, :-2], z[2:, 1:-1], z[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * size)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * size)
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    angle = np.degrees(np.arctan2(dzdy, -dzdx))
    aspect = np.where(angle < 0, 90.0 - angle, np.where(angle > 90.0, 450.0 - angle, 90.0 - angle))
    return slope, aspect % 360.0


def per_cell(values, n_cols):
    """(rows*200, cols*200) -> (rows, cols, 40000)"""
    rows = values.shape[0] // PER_CELL
    return values.reshape(rows, PER_CELL, n_cols, PER_CELL).transpose(0, 2, 1, 3).reshape(rows, n_cols, -1)


def main():
    spec, cell_id, _ = load_grid()
    width_px, height_px = spec["width"] * PER_CELL, spec["height"] * PER_CELL
    # WarpedVRT cannot read past its edges, so the warped grid has one extra pixel on every side.
    transform = from_origin(spec["x_min"] - PIXEL, spec["y_max"] + PIXEL, PIXEL, PIXEL)
    names = ["elevation_mean", "slope_mean", "slope_p90", "aspect_sin", "aspect_cos", "dem_valid_fraction"]
    result = {n: np.full((spec["height"], spec["width"]), np.nan, dtype="float32") for n in names}

    with rasterio.open(DEM) as src:
        print(f"DEM CRS {src.crs}, nodata {src.nodata}, size {src.width}x{src.height}", flush=True)
        with WarpedVRT(src, crs=CRS, transform=transform, width=width_px + 2, height=height_px + 2, resampling=Resampling.bilinear, src_nodata=src.nodata, nodata=np.nan, dtype="float32") as vrt:
            for top in range(0, spec["height"], STRIP_ROWS):
                rows = min(STRIP_ROWS, spec["height"] - top)
                if not (cell_id[top:top + rows] >= 0).any():
                    continue
                # Read one extra pixel on every side so the 3x3 window works at strip edges.
                window = Window(0, top * PER_CELL, width_px + 2, rows * PER_CELL + 2)
                z = vrt.read(1, window=window).astype("float64")
                slope, aspect = horn(z, PIXEL)
                elevation = z[1:-1, 1:-1]
                steep = slope > FLAT_DEGREES

                blocks = {
                    "elevation": per_cell(elevation, spec["width"]),
                    "slope": per_cell(slope, spec["width"]),
                    "sin": per_cell(np.where(steep, np.sin(np.radians(aspect)), np.nan), spec["width"]),
                    "cos": per_cell(np.where(steep, np.cos(np.radians(aspect)), np.nan), spec["width"]),
                }
                # All-NaN cells (sea) raise "mean of empty slice" warnings and correctly give NaN.
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    result["elevation_mean"][top:top + rows] = np.nanmean(blocks["elevation"], axis=2)
                    result["slope_mean"][top:top + rows] = np.nanmean(blocks["slope"], axis=2)
                    result["slope_p90"][top:top + rows] = np.nanpercentile(blocks["slope"], 90, axis=2)
                    result["aspect_sin"][top:top + rows] = np.nanmean(blocks["sin"], axis=2)
                    result["aspect_cos"][top:top + rows] = np.nanmean(blocks["cos"], axis=2)
                    result["dem_valid_fraction"][top:top + rows] = np.isfinite(blocks["elevation"]).mean(axis=2)
                print(f"grid rows {top}-{top + rows - 1} of {spec['height']} done", flush=True)

    # Cells with no pixel steeper than 1 degree have no meaningful direction: aspect sin/cos = 0.
    flat = np.isnan(result["aspect_sin"]) & np.isfinite(result["slope_mean"])
    result["aspect_sin"][flat] = 0.0
    result["aspect_cos"][flat] = 0.0
    result["flat_cell"] = flat.astype("float32")
    names.append("flat_cell")

    inside = cell_id >= 0
    order = np.argsort(cell_id[inside])
    ds = xr.Dataset({n: ("cell", result[n][inside][order]) for n in names}, coords={"cell": cell_id[inside][order]})
    ds["elevation_mean"].attrs["units"] = "m"
    for n in ("slope_mean", "slope_p90"):
        ds[n].attrs["units"] = "degrees"
    ds.attrs = {"source": "GA SRTM-derived Smoothed 1 Second DEM v1.0", "method": "warped to EPSG:8058 at 25 m (bilinear); Horn slope and aspect; aspect averaged as sin/cos over pixels steeper than 1 degree; cells with no such pixel get 0/0 and flat_cell = 1"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(OUT)
    print(ds.to_dataframe().describe().to_string())


if __name__ == "__main__":
    main()
