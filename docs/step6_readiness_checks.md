# Step 6: Readiness checks

Run 17 November 2026 with `scripts/17_readiness_checks.py`. Full results: `reports/readiness_checks.json`. **All six checks passed.**

| # | Report checklist item | Result | Evidence |
|---|---|---|---|
| 1 | Every raster has the same CRS, transform, grid origin, dimensions, extent and 5 km cell size | ✅ 21 raster files all match EPSG:8058, origin (8,710,000, 5,050,000), 249 x 206 cells, 5,000 m | `1_same_grid` |
| 2 | All dynamic features precede the target date; vegetation is the latest observation before it | ✅ Weather is t-1 and vegetation is from an earlier month in every one of 122,877,196 rows; 0 mismatches in 1,470 spot-check values and 570,000 pilot values | `2_time_safe_features` |
| 3 | Wildfire and prescribed-burn labels are distinguished, and low-quality or ambiguous detections are flagged | ✅ `burn_type` separates wildfire (4,990 burned rows) and prescribed burns (239); `burn_unconfirmed` flags 896,806 burned rows with no NPWS match and `burn_small` flags 735,553 covering under 5% of the cell | `3_burn_labels` |
| 4 | Positive/negative counts and missingness are reported by year, season and spatial block | ✅ Counts by partition, year, month, region, vegetation band and block, and by fire season and block; missingness by layer and year, and by season and block | `reports/population_counts.csv`, `reports/counts_by_season_block.csv`, `reports/missingness_by_layer_year.csv`, `reports/missingness_by_season_block.csv` |
| 5 | Sampling is reproducible, with a saved seed, strata and inclusion weights | ✅ Redrawing gave identical rows and weights; seed 20261117, strata and weights are saved | `5_reproducible_sampling`, `manifests/sample_manifest_1000000.json` |
| 6 | The final sample has no duplicate cell-date rows, and the test partition is spatially and temporally separate | ✅ 0 duplicates; 0 sample rows in the 6,627 test cells, in the test period, or outside the training period | `6_no_duplicates_and_separate_test` |

## Fixes made while running the checks

- **Burn-quality flags (item 3):** the table had burn type but no explicit flag. `scripts/11_build_pixel_day_table.py` now adds `burn_unconfirmed` and `burn_small`, and Steps 4 and 5 were rerun. The table checks still showed 0 duplicates, 0 missing predictors and 0 spot-check mismatches.
- **Projection in NetCDF rasters (item 1):** the first export stored the CRS without linking it to the data, so GIS tools did not read it. Each variable now names its `grid_mapping`.
- **Cell list (item 4):** `splits/cells.csv` was first built from the 2003 table, which misses three lake cells (Menindee Lakes and Lake Victoria) that have no vegetation data that year. It is now built from the grid, so all 32,029 cells are listed. This added 976 rows (3 burned) that the counts had left out. Every other cell kept the same block and holdout assignment, and the sample was redrawn: training now has 440,373 fire rows, all kept.
