"""Workflow Step 3.2: define the 5 km project grid over NSW.

Cells use GDA2020 / NSW Lambert (EPSG:8058), with the origin snapped to multiples of 5 km.
A cell belongs to NSW when its centre falls inside the ABS NSW boundary (mainland only;
Lord Howe Island and the ACT are excluded). Writes the cell ID raster and grid_spec.json.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin

from grid import CELL, CRS, GRID_DIR, GRID_SPEC, GRID_TIF, RAW

STATES = RAW / "abs_boundaries" / "STE_2021_AUST_SHP_GDA2020.zip"


def nsw_mainland():
    states = gpd.read_file(f"zip://{STATES.as_posix()}!STE_2021_AUST_GDA2020.shp")
    nsw = states.loc[states["STE_NAME21"] == "New South Wales"].to_crs(CRS)
    parts = nsw.explode(index_parts=False)
    # Keep the largest polygon, which drops Lord Howe Island and other offshore islands.
    mainland = parts.iloc[[parts.geometry.area.values.argmax()]]
    return mainland, nsw


def main():
    GRID_DIR.mkdir(parents=True, exist_ok=True)
    mainland, nsw = nsw_mainland()
    x0, y0, x1, y1 = mainland.total_bounds
    x_min, y_max = np.floor(x0 / CELL) * CELL, np.ceil(y1 / CELL) * CELL
    x_max, y_min = np.ceil(x1 / CELL) * CELL, np.floor(y0 / CELL) * CELL
    width, height = int(round((x_max - x_min) / CELL)), int(round((y_max - y_min) / CELL))
    transform = from_origin(x_min, y_max, CELL, CELL)

    inside = rasterize(mainland.geometry, out_shape=(height, width), transform=transform, fill=0, default_value=1, all_touched=False, dtype="uint8")
    cell_id = np.full((height, width), -1, dtype="int32")
    cell_id[inside == 1] = np.arange(int(inside.sum()), dtype="int32")

    profile = {"driver": "GTiff", "width": width, "height": height, "count": 1, "dtype": "int32", "crs": CRS, "transform": transform, "nodata": -1, "compress": "deflate"}
    with rasterio.open(GRID_TIF, "w", **profile) as dst:
        dst.write(cell_id, 1)
        dst.set_band_description(1, "cell_id (-1 outside NSW)")

    mainland.to_file(GRID_DIR / "nsw_mainland_boundary.gpkg", driver="GPKG")
    spec = {
        "crs": CRS,
        "cell_size_m": CELL,
        "x_min": x_min,
        "y_max": y_max,
        "width": width,
        "height": height,
        "nsw_cells": int(inside.sum()),
        "rule": "Cell is in NSW when its centre is inside the ABS 2021 NSW mainland polygon",
        "nsw_area_km2_mainland_polygon": round(float(mainland.geometry.area.sum()) / 1e6, 1),
        "nsw_area_km2_all_parts": round(float(nsw.geometry.area.sum()) / 1e6, 1),
    }
    GRID_SPEC.write_text(json.dumps(spec, indent=2))
    print(json.dumps(spec, indent=2))


if __name__ == "__main__":
    main()
