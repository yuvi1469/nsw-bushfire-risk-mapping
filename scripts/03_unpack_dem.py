"""Workflow Step 3: unpack the Geoscience Australia DEM ZIP.

The ZIP uses Deflate64 compression, which Python's zipfile and GDAL cannot read,
so each member is decompressed with inflate64. The ZIP in data/raw is not changed;
files are written to data/interim/ga_dem_s_1sec and checked against their CRC-32.
"""
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import inflate64

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "raw" / "ga_dem_s_1sec" / "70715.zip"
TARGET = ROOT / "data" / "interim" / "ga_dem_s_1sec"
CHUNK = 16 * 1024 * 1024
DEFLATE64 = 9


def unpack(handle, info, destination):
    handle.seek(info.header_offset)
    header = handle.read(30)
    if header[:4] != b"PK\x03\x04":
        raise ValueError(f"Bad local header for {info.filename}")
    name_length, extra_length = struct.unpack("<HH", header[26:30])
    handle.seek(info.header_offset + 30 + name_length + extra_length)

    inflater = inflate64.Inflater()
    remaining, written, crc = info.compress_size, 0, 0
    part = destination.with_name(destination.name + ".part")
    with part.open("wb") as out:
        while remaining:
            data = inflater.inflate(handle.read(min(CHUNK, remaining)))
            remaining -= min(CHUNK, remaining)
            out.write(data)
            written += len(data)
            crc = zlib.crc32(data, crc)
    if written != info.file_size or crc != info.CRC:
        raise ValueError(f"{info.filename}: wrote {written} of {info.file_size} bytes, CRC match {crc == info.CRC}")
    part.replace(destination)


def main():
    with zipfile.ZipFile(SOURCE) as archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
    with SOURCE.open("rb") as handle:
        for info in members:
            destination = TARGET / info.filename
            if ".." in Path(info.filename).parts or Path(info.filename).is_absolute():
                raise ValueError(f"Unsafe path in ZIP: {info.filename}")
            if destination.exists() and destination.stat().st_size == info.file_size:
                print(f"already unpacked: {info.filename}", flush=True)
                continue
            if info.compress_type != DEFLATE64:
                sys.exit(f"Unexpected compression {info.compress_type} for {info.filename}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            print(f"unpacking: {info.filename} ({info.file_size / 1e9:.1f} GB)", flush=True)
            unpack(handle, info, destination)
    print("DEM unpacked and CRC-checked")


if __name__ == "__main__":
    main()
