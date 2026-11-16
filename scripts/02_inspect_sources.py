"""Workflow Step 3.1: read every source and record its grid, units, nodata and dates.

Writes outputs/source_inspection.json. Nothing in data/raw is changed.
"""
import gzip
import io
import json
import tarfile
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import rasterio
import xarray as xr

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
OUT = ROOT / "outputs" / "source_inspection.json"

SILO_VARIABLES = ["max_temp", "min_temp", "daily_rain", "vp"]
YEARS = range(2002, 2018)


def text(value):
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value if isinstance(value, (int, float, str, bool, type(None))) else str(value)


def variable_info(ds, name):
    var = ds[name]
    return {
        "dims": dict(var.sizes),
        "dtype": str(var.dtype),
        "attrs": {k: text(v) for k, v in var.attrs.items()},
        "encoding": {k: text(v) for k, v in var.encoding.items() if k in ("_FillValue", "missing_value", "scale_factor", "add_offset", "dtype")},
    }


def axis_info(values):
    values = np.asarray(values, dtype="float64")
    steps = np.diff(values)
    return {"first": values[0], "last": values[-1], "size": len(values), "step_min": steps.min(), "step_max": steps.max()}


def missing_days(times, year):
    expected = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    found = pd.DatetimeIndex(pd.to_datetime(times)).normalize()
    return [str(d.date()) for d in expected.difference(found)]


def inspect_silo():
    result = {}
    for variable in SILO_VARIABLES:
        per_year = {}
        for year in YEARS:
            with xr.open_dataset(RAW / "silo" / variable / f"{year}.{variable}.nc", decode_times=True) as ds:
                per_year[year] = {"days": ds.sizes["time"], "missing_days": missing_days(ds["time"].values, year)}
                if year == 2010:
                    sample = {
                        "variables": list(ds.data_vars),
                        "data": variable_info(ds, variable),
                        "lat": axis_info(ds["lat"].values),
                        "lon": axis_info(ds["lon"].values),
                        "crs_attrs": {k: text(v) for k, v in ds["crs"].attrs.items()} if "crs" in ds else None,
                        "global_attrs": {k: text(v) for k, v in ds.attrs.items()},
                    }
        result[variable] = {"sample_2010": sample, "per_year": per_year}
    return result


def inspect_wind():
    per_year, sample = {}, None
    with tarfile.open(RAW / "tern_wind" / "mean_wind_10m.tar") as archive:
        for member in archive.getmembers():
            if not member.name.endswith(".nc.gz"):
                continue
            year = int(Path(member.name).name[:4])
            if year not in YEARS:
                continue
            raw = gzip.decompress(archive.extractfile(member).read())
            engine = "scipy" if raw[:3] == b"CDF" else "h5netcdf"
            with xr.open_dataset(io.BytesIO(raw), engine=engine) as ds:
                time_name = next(d for d in ds.dims if "time" in d.lower())
                per_year[year] = {"days": ds.sizes[time_name], "missing_days": missing_days(ds[time_name].values, year)}
                if year == 2010:
                    data_name = next(v for v in ds.data_vars if ds[v].ndim == 3)
                    lat = next(c for c in ds.coords if c.lower().startswith("lat"))
                    lon = next(c for c in ds.coords if c.lower().startswith("lon"))
                    sample = {
                        "variables": list(ds.data_vars),
                        "data_name": data_name,
                        "data": variable_info(ds, data_name),
                        "lat": axis_info(ds[lat].values),
                        "lon": axis_info(ds[lon].values),
                        "global_attrs": {k: text(v) for k, v in ds.attrs.items()},
                    }
    return {"sample_2010": sample, "per_year": dict(sorted(per_year.items()))}


def inspect_fractional_cover():
    files = sorted((RAW / "tern_fractional_cover").glob("*.nc"))
    per_file, sample = {}, None
    for path in files:
        with xr.open_dataset(path) as ds:
            months = pd.to_datetime(ds["time"].values).strftime("%Y-%m").tolist()
            per_file[path.name] = months
            if sample is None and ".h30v12.2010." in path.name:
                sample = {
                    "variables": list(ds.data_vars),
                    "phot_veg": variable_info(ds, "phot_veg"),
                    "x": axis_info(ds["x"].values),
                    "y": axis_info(ds["y"].values),
                    "grid_mapping": {k: text(v) for k, v in ds[ds["phot_veg"].attrs.get("grid_mapping", "sinusoidal")].attrs.items()}
                    if ds["phot_veg"].attrs.get("grid_mapping", "sinusoidal") in ds else None,
                    "global_attrs": {k: text(v) for k, v in ds.attrs.items()},
                }
    short = {name: len(months) for name, months in per_file.items() if len(months) != 12}
    return {"sample_h30v12_2010": sample, "files": len(files), "files_without_12_months": short}


def inspect_burnt_area():
    files = sorted((RAW / "tern_burnt_area").glob("dob_*.nc"))
    months, sample = [], None
    for path in files:
        with xr.open_dataset(path, decode_times=False) as ds:
            months.append(path.stem)
            if path.stem == "dob_20130101_20130131":
                values = ds["julian_date_of_burn"].isel(time=0).values
                burned = values[np.isfinite(values) & (values != -1)]
                sample = {
                    "variables": list(ds.data_vars),
                    "data": variable_info(ds, "julian_date_of_burn"),
                    "latitude": axis_info(ds["latitude"].values),
                    "longitude": axis_info(ds["longitude"].values),
                    "time_value": text(ds["time"].values[0]),
                    "burned_pixels": int(burned.size),
                    "burn_value_min": text(burned.min()) if burned.size else None,
                    "burn_value_max": text(burned.max()) if burned.size else None,
                    "burn_value_as_date_min": str(pd.Timestamp("1970-01-01") + pd.Timedelta(days=float(burned.min()))) if burned.size else None,
                    "burn_value_as_date_max": str(pd.Timestamp("1970-01-01") + pd.Timedelta(days=float(burned.max()))) if burned.size else None,
                    "unique_non_burn_values": [text(v) for v in np.unique(values[~np.isin(values, burned)])[:10]],
                }
    return {"files": len(months), "sample_2013_01": sample}


def inspect_npws():
    path = f"/vsizip/{(RAW / 'npws_fire_history' / 'fire_npwsfirehistory.zip').as_posix()}/NPWSFireHistory.shp"
    info = pyogrio.read_info(path)
    table = pyogrio.read_dataframe(path, read_geometry=False)
    summary = {}
    for column in table.columns:
        series = table[column]
        summary[column] = {
            "dtype": str(series.dtype),
            "missing": int(series.isna().sum()),
            "examples": [text(v) for v in series.dropna().unique()[:5]],
        }
    return {
        "crs": info["crs"],
        "features": int(info["features"]),
        "geometry_type": info["geometry_type"],
        "bounds": [text(v) for v in info["total_bounds"]],
        "fields": summary,
    }


def inspect_dem():
    # The ZIP uses Deflate64, so this reads the copy unpacked by 03_unpack_dem.py.
    folder = INTERIM / "ga_dem_s_1sec"
    readme = {name: (folder / name).read_text("utf8", "replace")[:3000] for name in ("Ancillary/readme.txt", "Ancillary/copyright.txt", "Ancillary/quality.txt")}
    with rasterio.open(folder / "srtm-1sec-dems-v1-COG.tif") as src:
        return {
            "crs": src.crs.to_string() if src.crs else None,
            "width": src.width,
            "height": src.height,
            "bounds": list(src.bounds),
            "resolution": list(src.res),
            "dtype": src.dtypes[0],
            "nodata": src.nodata,
            "units": src.units,
            "tags": src.tags(),
            "overviews": src.overviews(1),
            "ancillary": readme,
        }


def main():
    sources = {
        "silo": inspect_silo,
        "wind": inspect_wind,
        "fractional_cover": inspect_fractional_cover,
        "burnt_area": inspect_burnt_area,
        "npws": inspect_npws,
        "dem": inspect_dem,
    }
    chosen = sys.argv[1:] or list(sources)
    report = json.loads(OUT.read_text()) if OUT.exists() else {}
    for name in chosen:
        print(f"Inspecting {name}", flush=True)
        report[name] = sources[name]()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=text))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
