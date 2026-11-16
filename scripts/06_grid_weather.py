"""Workflow Steps 3.3-3.4: put daily SILO weather and TERN wind on the 5 km grid.

Both sources share one 0.05 degree lat/long grid, about the same size as the project cells,
so each NSW cell takes a bilinear value from the four source cells around its centre.
Source cells with no data (sea) are left out of the weighting; if all four are missing the
cell stays NaN and is reported in the missingness check rather than filled.

Writes data/processed/daily/<variable>.nc with dims (date, cell).
"""
import gzip
import io
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import xarray as xr

from grid import PROCESSED, RAW, cell_centres, feature_dates, load_grid

SILO_VARIABLES = ["max_temp", "min_temp", "daily_rain", "vp"]
WIND_TAR = RAW / "tern_wind" / "mean_wind_10m.tar"
OUT = PROCESSED / "daily"
BOX = {"lat": slice(-38.5, -27.5), "lon": slice(140.5, 154.0)}


class Bilinear:
    def __init__(self, lats, lons, cell_lat, cell_lon):
        self.lat_step, self.lon_step = lats[1] - lats[0], lons[1] - lons[0]
        fi = (cell_lat - lats[0]) / self.lat_step
        fj = (cell_lon - lons[0]) / self.lon_step
        self.i0, self.j0 = np.floor(fi).astype(int), np.floor(fj).astype(int)
        di, dj = fi - self.i0, fj - self.j0
        self.corners = [(0, 0, (1 - di) * (1 - dj)), (1, 0, di * (1 - dj)), (0, 1, (1 - di) * dj), (1, 1, di * dj)]
        if self.i0.min() < 0 or self.j0.min() < 0 or self.i0.max() + 1 >= len(lats) or self.j0.max() + 1 >= len(lons):
            raise ValueError("Grid cells fall outside the source window")

    def __call__(self, cube):
        """cube: (time, lat, lon) -> (time, cell)"""
        total = np.zeros((cube.shape[0], self.i0.size), dtype="float64")
        weight = np.zeros_like(total)
        for a, b, w in self.corners:
            values = cube[:, self.i0 + a, self.j0 + b]
            valid = np.isfinite(values)
            total += np.where(valid, values, 0.0) * w
            weight += valid * w
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(weight > 0, total / weight, np.nan).astype("float32")


def ascending(ds, lat, lon):
    return ds.sortby(lat).sortby(lon)


def silo_years(variable, years):
    for year in years:
        with xr.open_dataset(RAW / "silo" / variable / f"{year}.{variable}.nc") as ds:
            yield ascending(ds, "lat", "lon").sel(**BOX)[variable].load()


def wind_years(years):
    with tarfile.open(WIND_TAR) as archive:
        members = {int(Path(m.name).name[:4]): m for m in archive.getmembers() if m.name.endswith(".nc.gz")}
        for year in years:
            raw = gzip.decompress(archive.extractfile(members[year]).read())
            engine = "scipy" if raw[:3] == b"CDF" else "h5netcdf"
            with xr.open_dataset(io.BytesIO(raw), engine=engine) as ds:
                yield ascending(ds, "lat", "lon").sel(**BOX)["mean_wind_10m"].load()


def build(name, arrays, dates, cells, cell_lat, cell_lon):
    pieces, regrid = [], None
    for array in arrays:
        wanted = dates[(dates >= pd.Timestamp(array.time.values[0]).normalize()) & (dates <= pd.Timestamp(array.time.values[-1]).normalize())]
        array = array.assign_coords(time=pd.DatetimeIndex(array.time.values).normalize()).sel(time=wanted)
        if regrid is None:
            regrid = Bilinear(array.lat.values, array.lon.values, cell_lat, cell_lon)
        pieces.append(xr.DataArray(regrid(array.values), dims=("date", "cell"), coords={"date": wanted, "cell": cells}))
        print(f"{name}: {pd.Timestamp(wanted[0]).year} done", flush=True)
    result = xr.concat(pieces, dim="date")
    missing = dates.difference(pd.DatetimeIndex(result.date.values))
    if len(missing):
        raise ValueError(f"{name}: {len(missing)} dates missing, first {missing[0]}")
    result.name = name
    result.attrs = {"units": array.attrs.get("units", ""), "long_name": array.attrs.get("long_name", name), "method": "bilinear from 0.05 degree grid, sea cells excluded from weights"}
    OUT.mkdir(parents=True, exist_ok=True)
    result.to_netcdf(OUT / f"{name}.nc", encoding={name: {"zlib": True, "complevel": 4, "dtype": "float32"}})


def main():
    spec, cell_id, _ = load_grid()
    _, _, lon, lat = cell_centres(spec)
    inside = cell_id >= 0
    order = np.argsort(cell_id[inside])
    cells = cell_id[inside][order]
    cell_lat, cell_lon = lat[inside][order], lon[inside][order]

    dates = feature_dates()
    years = sorted(set(dates.year))
    for variable in SILO_VARIABLES:
        build(variable, silo_years(variable, years), dates, cells, cell_lat, cell_lon)
    build("wind_10m", wind_years(years), dates, cells, cell_lat, cell_lon)


if __name__ == "__main__":
    main()
