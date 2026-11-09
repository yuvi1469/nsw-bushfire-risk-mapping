# NSW Bushfire Risk Mapping

Builds a historical pixel-day dataset for New South Wales, following the *NSW Bushfire Risk Mapping Workflow* report.

- **Question:** does a 5 km map cell burn on a given day, using only information available before that day?
- **Row:** one eligible 5 km cell on one date.
- **Target:** a reproducible 1 million row sample, expanded to 2 million only if needed.
- **Period:** August 2002 to February 2017, excluding 2009, 2010, 2014 and 2015, which have no burnt area files.

## Folders

| Folder | Contents | In Git |
|---|---|---|
| `scripts/` | Project code | Yes |
| `inventory/` | Source inventory and download manifest | Yes |
| `docs/` | Notes on each workflow step | Yes |
| `data/raw/` | Unchanged source files | No |
| `data/processed/` | Aligned maps and the pixel-day table | No |
| `outputs/` | Generated maps and reports | No |

Data files are too large for GitHub, so they stay on the local machine.

## Getting the source data

```bash
python scripts/01_download_sources.py
```

This downloads the SILO, TERN wind, TERN vegetation and TERN burnt area files. It can be re-run safely: finished files are skipped and partial files resume. The NSW NPWS fire history and the ELVIS DEM are downloaded by hand in a browser into `data/raw/npws_fire_history/` and `data/raw/elvis_dem/`.

## Data sources

| Layer | Source |
|---|---|
| Temperature, rainfall, vapour pressure | [SILO](https://longpaddock.qld.gov.au/silo/gridded-data/) |
| 10 m wind | [TERN near-surface wind](https://portal.tern.org.au/metadata/1f1f6f81-da2e-4f33-9757-d7e05becc10a) |
| Vegetation cover | [TERN MODIS fractional cover](https://portal.tern.org.au/metadata/a6ef2480-e397-4c42-9706-3865dd6ca380) |
| Fire label | [TERN burnt area and approximate day of burn](https://portal.tern.org.au/metadata/5e262fd7-261f-4c5d-81e7-fff2c6d54d32) |
| Fire cross-check | [NSW NPWS fire history](https://www.data.nsw.gov.au/data/dataset/fire-history-wildfires-and-prescribed-burns-1e8b6) |
| Elevation | [ELVIS](https://elevation.fsdf.org.au/) |
