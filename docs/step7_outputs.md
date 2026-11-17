# Step 7: Outputs required before model training

Completed 17 November 2026. These are the five outputs the workflow report lists, with where each one is. Paths under `data/` are on the project computer only (too large for GitHub) and can be rebuilt with the scripts; everything else is in the repository.

## 1. Source-data inventory

| Item | Location |
|---|---|
| Versions, time ranges, licences, units, nodata codes, CRS, resolution and missing-data notes for all nine sources | `inventory/source_inventory.csv` |
| Every downloaded file with URL, size, SHA-256 and retrieval date (275 files, 81.6 GB) | `inventory/download_manifest.csv` |
| Details read from each file | `reports/source_inspection.json` |
| Notes | `docs/step1_scope_check.md`, `docs/step2_downloads.md`, `docs/step3_prepare_layers.md` (3.1) |

## 2. Aligned predictor rasters, common-grid specification and valid-data mask

| Item | Location |
|---|---|
| Grid specification (EPSG:8058, 5 km, 249 x 206, origin 8,710,000 / 5,050,000, 32,029 NSW cells) | `manifests/grid_spec.json`; cell ID raster `data/processed/grid/nsw_grid_5km.tif` |
| Daily weather and wind rasters (date, y, x) | `data/processed/rasters/daily/{max_temp,min_temp,daily_rain,vp,wind_10m}.nc` |
| Monthly vegetation rasters (month, y, x) | `data/processed/rasters/monthly/vegetation.nc` |
| Terrain raster (7 bands) | `data/processed/rasters/static/terrain.tif` |
| Valid-data mask | `data/processed/masks/valid_static_mask.tif` |
| Missing-data maps by layer | `outputs/maps/*.tif` |
| Methods | `docs/step3_prepare_layers.md` |

## 3. Burned-area label raster, partial-cell rule and NSW cross-check

| Item | Location |
|---|---|
| Label raster: `burned_fraction` and `burned` for every study day (date, y, x) | `data/processed/rasters/label/burned_area_label.nc` |
| Cell-day label table with burn type and NPWS match shares | `data/processed/labels/burn_cell_days.parquet` |
| Partial-cell rule: burned when at least 1% of the cell's 250 m pixels burned that day; fraction kept | `docs/step3_prepare_layers.md` (3.7) |
| Burn-date check showing the one-month file offset | `reports/burn_date_check.csv` |
| Season-by-season comparison with NSW NPWS fire history | `reports/fire_label_checks.csv` |

## 4. Pixel-day feature table with field dictionary and provenance

| Item | Location |
|---|---|
| Table: 122,877,196 rows, 38 fields, Parquet by year | `data/processed/pixel_day/YYYY/part-0.parquet` |
| Field dictionary with source and rule for every field | `docs/field_dictionary.md` |
| Checks: duplicates, leakage and recalculated values | `reports/pixel_day_checks.json` |
| Excluded rows and reasons (50,106, all missing vegetation) | `reports/pixel_day_exclusions.csv` |
| Notes | `docs/step4_pixel_day_table.md` |

## 5. One-million-row sample, sampling manifest and holdout assignments

| Item | Location |
|---|---|
| Sample: 1,000,000 rows (440,373 fire, 559,627 unburned), training partition | `data/processed/sample/sample_1000000.parquet` |
| Manifest: seed, strata, selection probabilities, inclusion counts, coverage audit, source versions | `manifests/sample_manifest_1000000.json` |
| Per-stratum plan (912 strata) | `manifests/sample_strata_1000000.csv` |
| Holdout assignments | `splits/cells.csv` (spatial holdout per cell), `splits/periods.json` (train, validation and test dates) |
| Pilot extract and checks | `data/processed/sample/pilot_30k.parquet`, `manifests/pilot_checks.json` |
| Notes | `docs/step5_sample.md` |

## Readiness

All six readiness checks passed (`docs/step6_readiness_checks.md`, `reports/readiness_checks.json`).

## Known limitations to carry into modelling

1. **Likely false fires in the label.** TERN marks 19,000-144,000 km2 of NSW burned per season against a few thousand km2 in NPWS records. 99.4% of burned rows have no NPWS match (`burn_unconfirmed`) and 82% cover under 5% of the cell (`burn_small`). Much of it is in the central cropping belt. The flags and `burned_fraction` allow the label to be tightened and the results compared.
2. **Gaps in the study period.** No burnt area files exist for 2009, 2010, 2014 or 2015, so the study covers 3,838 days in three blocks.
3. **Substitute strata.** "Fire region" and "vegetation class" are replaced by longitude bands and cover tertiles because neither layer was in the source list.
4. **Rainfall deficit.** `dry_days` (consecutive days under 2 mm, capped at 30) is used because a long-term deficit would need pre-2002 data or would leak later years.
5. **Coastal cells.** Sea pixels in the DEM are about 0 m, so coastal elevation means include some sea; 72 edge cells have less than half their vegetation pixels on average.
