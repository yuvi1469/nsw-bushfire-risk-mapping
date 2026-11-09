"""Workflow Step 2: download the source files that have direct links.

Finished files are skipped and partial files resume, so this can be re-run.
Every file is recorded in inventory/download_manifest.csv with its SHA-256.
"""
import csv
import hashlib
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "inventory" / "download_manifest.csv"

SILO = "https://s3-ap-southeast-2.amazonaws.com/silo-open-data/Official/annual"
SILO_VARIABLES = ["max_temp", "min_temp", "daily_rain", "vp"]
WIND = (
    "https://object-store.rc.nectar.org.au/v1/AUTH_05bca33fce34447ba7033b9305947f11/"
    "data_submission_tool_attachments/1f1f6f81-da2e-4f33-9757-d7e05becc10a/mean_wind_10m.tar"
)
VEGETATION = "https://thredds.nci.org.au/thredds/fileServer/tc43/modis-fc/v310/tiles/monthly/cover"
VEGETATION_TILES = ["h29v12", "h30v11", "h30v12", "h31v11", "h31v12"]
BURN_SERVER = "https://dap.tern.org.au/thredds"
BURN_PATH = "landscapes/remote-sensing/modis/burnt_area/monthly"
NPWS = (
    "https://datasets.seed.nsw.gov.au/dataset/1d05e145-80cb-4275-af9b-327a1536798d/"
    "resource/3853d6c0-6517-4cba-8482-68f93a6d43b1/download/fire_npwsfirehistory.zip"
)

DEM = "https://elevation-direct-downloads.s3-ap-southeast-2.amazonaws.com/1sec-dem/70715.zip"

YEARS = range(2002, 2018)
HEADERS = {"User-Agent": "nsw-bushfire-risk-mapping/1.0"}
CHUNK = 1024 * 1024
RETRIES = 6


def burn_files():
    request = urllib.request.Request(f"{BURN_SERVER}/catalog/{BURN_PATH}/catalog.xml", headers=HEADERS)
    with urllib.request.urlopen(request, timeout=120) as response:
        catalog = response.read().decode("utf8")
    names = sorted(set(re.findall(r'dataset name="(dob_\d{8}_\d{8}\.nc)"', catalog)))
    if len(names) != 127:
        raise RuntimeError(f"Expected 127 burnt area months, found {len(names)}")
    return [(f"{BURN_SERVER}/fileServer/{BURN_PATH}/{name}", RAW / "tern_burnt_area" / name) for name in names]


def all_files():
    files = []
    for variable in SILO_VARIABLES:
        for year in YEARS:
            name = f"{year}.{variable}.nc"
            files.append((f"{SILO}/{variable}/{name}", RAW / "silo" / variable / name))
    files.append((WIND, RAW / "tern_wind" / "mean_wind_10m.tar"))
    for tile in VEGETATION_TILES:
        for year in YEARS:
            name = f"FC_Monthly_Medoid.v310.MCD43A4.{tile}.{year}.006.nc"
            files.append((f"{VEGETATION}/{name}", RAW / "tern_fractional_cover" / name))
    files.append((NPWS, RAW / "npws_fire_history" / "fire_npwsfirehistory.zip"))
    files.append((DEM, RAW / "ga_dem_s_1sec" / "70715.zip"))
    return files + burn_files()


def remote_size(url):
    request = urllib.request.Request(url, headers={**HEADERS, "Range": "bytes=0-0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return int(response.headers["Content-Range"].rsplit("/", 1)[1])


def fetch(url, path):
    size = remote_size(url)
    if path.exists() and path.stat().st_size == size:
        return url, path, size, "already present"
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    for attempt in range(1, RETRIES + 1):
        have = part.stat().st_size if part.exists() else 0
        try:
            if have < size:
                request = urllib.request.Request(url, headers={**HEADERS, "Range": f"bytes={have}-"})
                with urllib.request.urlopen(request, timeout=120) as response, part.open("ab") as out:
                    if response.status != 206:
                        raise OSError(f"Server ignored resume request: {response.status}")
                    while chunk := response.read(CHUNK):
                        out.write(chunk)
            if part.stat().st_size != size:
                raise OSError(f"Incomplete: {part.stat().st_size} of {size} bytes")
            part.replace(path)
            return url, path, size, "downloaded"
        except (OSError, urllib.error.URLError) as error:
            if attempt == RETRIES:
                raise
            print(f"Retry {attempt} for {path.name}: {error}", flush=True)
            time.sleep(10 * attempt)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def read_retrieval_dates():
    if not MANIFEST.exists():
        return {}
    with MANIFEST.open(newline="") as handle:
        return {row["file"]: row["retrieval_date"] for row in csv.DictReader(handle)}


def main():
    files = all_files()
    print(f"{len(files)} files to check", flush=True)
    dates = read_retrieval_dates()
    finished, failed = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(fetch, url, path): (url, path) for url, path in files}
        for number, job in enumerate(as_completed(jobs), 1):
            url, path = jobs[job]
            try:
                _, _, size, status = job.result()
                finished.append((url, path, size))
                print(f"[{number}/{len(files)}] {status}: {path.name}", flush=True)
            except Exception as error:
                failed.append(path.name)
                print(f"[{number}/{len(files)}] FAILED: {path.name}: {error}", flush=True)

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "url", "bytes", "sha256", "retrieval_date"])
        for url, path, size in sorted(finished, key=lambda item: str(item[1])):
            name = path.relative_to(ROOT).as_posix()
            writer.writerow([name, url, size, sha256(path), dates.get(name, date.today().isoformat())])

    print(f"Finished {len(finished)} of {len(files)} files", flush=True)
    if failed:
        raise SystemExit(f"{len(failed)} files failed: {failed}")


if __name__ == "__main__":
    main()
