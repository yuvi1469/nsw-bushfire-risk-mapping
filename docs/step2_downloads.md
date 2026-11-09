# Step 2: Source data download

Downloaded 9 November 2026. Every file is listed with its URL, size and SHA-256 in `inventory/download_manifest.csv`. Source files are kept unchanged in `data/raw/`.

| Folder | Contents | Files |
|---|---|---|
| `silo/` | `max_temp`, `min_temp`, `daily_rain`, `vp`, annual NetCDF, 2002-2017 | 64 |
| `tern_wind/` | 10 m daily mean wind archive, 1975-2018 | 1 |
| `tern_fractional_cover/` | Monthly vegetation cover, 5 MODIS tiles, 2002-2017 | 80 |
| `tern_burnt_area/` | Monthly burn dates, the 127 available months | 127 |
| `npws_fire_history/` | NSW fire boundaries, shapefile in a ZIP | 1 |
| `ga_dem_s_1sec/` | National smoothed 1-second DEM, GeoTIFF in a ZIP | 1 |

## Checks done

- File sizes match the sizes reported by the servers.
- All 271 NetCDF files have a valid file signature.
- The DEM ZIP lists 12 files and the wind archive lists 44 annual files.

## Checks still to do in Step 3

These checks only confirm the files arrived complete. The contents have not been opened yet. Step 3 reads each file's dates, grid, units and no-data values, and looks for missing days inside the annual files.

## Difference from the report

The report says to download the DEM through ELVIS. ELVIS limits searches to about 1.5 degrees square, which is too small for one NSW order. The DEM used is a product ELVIS lists, downloaded as one national file directly from Geoscience Australia.
