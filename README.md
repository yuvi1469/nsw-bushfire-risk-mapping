# NSW Bushfire Risk Mapping

Builds a historical pixel-day dataset for New South Wales, following the *NSW Bushfire Risk Mapping Workflow* report.

- **Question:** does a 5 km map cell burn on a given day, using only information available before that day?
- **Row:** one eligible 5 km cell on one date.
- **Target:** a reproducible 1 million row sample, expanded to 2 million only if needed.
- **Period:** 3,838 days in three blocks: Aug 2002 - Nov 2008, Dec 2010 - Nov 2013 and Dec 2015 - Jan 2017, where burn dates exist.

## Folders

| Folder | Contents | In Git |
|---|---|---|
| `scripts/` | Project code | Yes |
| `inventory/` | Source inventory and download manifest | Yes |
| `docs/` | Notes on each workflow step | Yes |
| `data/raw/` | Unchanged source files | No |
| `data/processed/` | Aligned maps and the pixel-day table | No |
| `outputs/` | Generated maps and reports | No |
| `splits/` | Train, validation and test assignments | Yes |
| `manifests/` | Sample manifest, strata plan and pilot checks | Yes |

Data files are too large for GitHub, so they stay on the local machine.

## Getting the source data

```bash
python scripts/01_download_sources.py
```

This downloads the SILO, TERN wind, TERN vegetation, TERN burnt area, NSW NPWS and elevation files, about 81 GB in total. It can be re-run safely: finished files are skipped and partial files resume.

ELVIS limits searches to about 1.5 degrees square, too small for one NSW-wide order. The DEM is therefore the same product listed in ELVIS, the SRTM-derived Smoothed 1 Second DEM Version 1.0, downloaded as one national file directly from Geoscience Australia.

## Running the workflow

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

Then run the scripts in `scripts/` in number order with `.venv/Scripts/python`. `grid.py` holds the shared grid settings and study period.

| Script | Workflow step |
|---|---|
| `01_download_sources.py` | 2: download and checksum every source |
| `02_inspect_sources.py` | 3.1: read each source's grid, units, nodata and dates |
| `03_unpack_dem.py` | 3: unpack the Deflate64 DEM ZIP |
| `04_check_burn_dates.py` | 3.7: compare burn dates with file names |
| `05_define_grid.py` | 3.2: 5 km NSW grid |
| `06_grid_weather.py` | 3.3-3.4: weather and wind on the grid |
| `07_grid_vegetation.py` | 3.3-3.4: vegetation on the grid |
| `08_terrain.py` | 3.4-3.5: elevation, slope and aspect |
| `09_fire_label.py` | 3.7: fire label and NPWS cross-check |
| `10_quality_checks.py` | 3.8: missingness and quality checks |
| `11_build_pixel_day_table.py` | 4: build the pixel-day table |
| `12_check_pixel_day.py` | 4: check duplicates, leakage and values |
| `13_pilot_extract.py` | 5.1: 30,000 row pilot, every value rechecked |
| `14_split_and_count.py` | 5.2-5.3: holdouts and population counts |
| `15_draw_sample.py` | 5.4-5.6: seeded 1 million row sample and coverage audit |

Notes for each step are in `docs/`, and the table's fields are described in `docs/field_dictionary.md`.

## Data sources

| Layer | Source |
|---|---|
| Temperature, rainfall, vapour pressure | [SILO](https://longpaddock.qld.gov.au/silo/gridded-data/) |
| 10 m wind | [TERN near-surface wind](https://portal.tern.org.au/metadata/1f1f6f81-da2e-4f33-9757-d7e05becc10a) |
| Vegetation cover | [TERN MODIS fractional cover](https://portal.tern.org.au/metadata/a6ef2480-e397-4c42-9706-3865dd6ca380) |
| Fire label | [TERN burnt area and approximate day of burn](https://portal.tern.org.au/metadata/5e262fd7-261f-4c5d-81e7-fff2c6d54d32) |
| Fire cross-check | [NSW NPWS fire history](https://www.data.nsw.gov.au/data/dataset/fire-history-wildfires-and-prescribed-burns-1e8b6) |
| Elevation | [Smoothed 1 Second DEM](http://pid.geoscience.gov.au/dataset/ga/70715), listed in [ELVIS](https://elevation.fsdf.org.au/) |
| NSW boundary | [ABS state boundaries 2021](https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/digital-boundary-files) |
