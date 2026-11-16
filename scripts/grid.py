"""Shared definition of the project grid and study period (workflow Step 3.2)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"
GRID_DIR = PROCESSED / "grid"
GRID_SPEC = GRID_DIR / "grid_spec.json"
GRID_TIF = GRID_DIR / "nsw_grid_5km.tif"

CRS = "EPSG:8058"  # GDA2020 / NSW Lambert
CELL = 5000.0

# Burn dates exist for these blocks (Step 1 coverage, corrected by the burn-date check in Step 3).
STUDY_BLOCKS = [("2002-08-01", "2008-11-30"), ("2010-12-01", "2013-11-30"), ("2015-12-01", "2017-01-31")]
# Rolling rainfall needs 30 days before the first study day.
LOOKBACK_DAYS = 30


def study_dates():
    return pd.DatetimeIndex(np.concatenate([pd.date_range(a, b, freq="D").values for a, b in STUDY_BLOCKS]))


def feature_dates():
    """Every date a predictor is needed for: study dates plus each block's lookback."""
    days = [pd.date_range(pd.Timestamp(a) - pd.Timedelta(days=LOOKBACK_DAYS), b, freq="D") for a, b in STUDY_BLOCKS]
    return pd.DatetimeIndex(np.unique(np.concatenate([d.values for d in days])))


def load_grid():
    spec = json.loads(GRID_SPEC.read_text())
    with rasterio.open(GRID_TIF) as src:
        cell_id = src.read(1)
        transform = src.transform
    return spec, cell_id, transform


def cell_centres(spec):
    """Projected and lat/long centres of every grid cell, as 2D arrays (row, col)."""
    xs = spec["x_min"] + CELL * (np.arange(spec["width"]) + 0.5)
    ys = spec["y_max"] - CELL * (np.arange(spec["height"]) + 0.5)
    x, y = np.meshgrid(xs, ys)
    lon, lat = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform(x, y)
    return x, y, lon, lat
