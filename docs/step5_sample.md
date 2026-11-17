# Step 5: Select the sample

Completed 17 November 2026 with scripts `13` to `15`.

## 5.1 Pilot extract

`scripts/13_pilot_extract.py` took **30,000 rows** from 2003 and 2012 in two subregions: block 14 (inland) and block 36 (coastal). Every weather, rainfall-window, dry-day, vegetation, terrain and label value was recalculated from the aligned layers in `data/processed/` for every pilot row.

| Check | Result |
|---|---|
| Values recalculated | 570,000 (19 fields x 30,000 rows) |
| Mismatches | **0** |
| Duplicate cell-dates | 0 |
| Weather from t-1 | Yes, every row |

Units and ranges are recorded in `manifests/pilot_checks.json`. Pilot file: `data/processed/sample/pilot_30k.parquet`.

## 5.2 Holdouts, fixed before sampling

The report asks for a temporal holdout plus spatial blocks, with the test set separate in time and space. The three study blocks give a natural temporal split:

| Partition | Dates | Cells | Rows | Burned | Prevalence |
|---|---|---|---|---|---|
| Train | 1 Aug 2002 - 30 Nov 2008 | Not held out | 58,749,565 | 440,373 | 0.75% |
| Validation | 1 Dec 2010 - 30 Nov 2013 | Not held out | 27,828,643 | 236,115 | 0.85% |
| Test | 1 Dec 2015 - 31 Jan 2017 | Held out | 2,836,356 | 15,735 | 0.55% |
| Unused | Held-out cells in train or validation periods; other cells in the test period | | 33,462,632 | 209,812 | |

- **Spatial holdout:** 20% of the 100 km blocks in each longitude region were chosen at random (seed 20261117): 20 of 102 blocks, 6,627 of 32,029 cells.
- **Separation:** train and test share no cells and no dates. Train and validation share cells but not dates.
- **Prevalence:** validation and test are kept whole, so they keep their real fire prevalence.

Assignments are in `splits/cells.csv` (`spatial_holdout` per cell, built from the grid so all 32,029 cells are listed) and `splits/periods.json`.

## 5.3 Eligible population counts

`outputs/population_counts.csv` gives rows and burned rows for every partition x year x month x region x vegetation band x 100 km block. Excluded rows and reasons are in `outputs/pixel_day_exclusions.csv` (50,106 rows with missing vegetation; Step 4).

**Strata substitutes.** The report's "fire region" and "vegetation class" are not among the listed sources, so documented substitutes are used:
- `region`: longitude band of the cell centre: far west 141-144, west 144-147, central 147-150, east 150-154 E.
- `veg_band`: tertile of each cell's mean total cover over the training years: low below 60.3%, mid 60.3-80.3%, high above 80.3%.

Training rows by region and vegetation band:

| Region | Low cover | Mid cover | High cover |
|---|---|---|---|
| Far west | 10,552,118 (5,012 burned) | 1,802,606 (5,516) | 37,024 (200) |
| West | 6,501,951 (22,123) | 9,301,156 (97,139) | 307,762 (2,605) |
| Central | 1,266,001 (22,874) | 7,758,842 (180,281) | 8,353,613 (33,732) |
| East | 32,396 (1,223) | 1,733,186 (50,862) | 11,102,572 (18,803) |

Central mid-cover cells, largely the cropping belt, hold 41% of training fire rows. This matches the likely false fires described in Step 3.

## 5.4-5.5 Sample design and the 1 million row sample

Rules fixed before drawing (`scripts/15_draw_sample.py`):
- **Source:** the training partition only.
- **Fire rows:** keep all if they fit in half the sample. 440,373 fit, so **all are kept**.
- **Unburned rows:** fill the remaining 559,627, allocated in proportion to each stratum (year x month x region x veg_band; 912 strata), then chosen at random within the stratum.
- **Seed:** 20261117, with a separate random stream per year.
- **Weights:** stratum population / stratum sample, separately for fire and unburned rows.

| Result | Value |
|---|---|
| Rows | **1,000,000** |
| Fire rows | 440,373 (44.0% unweighted) |
| Unburned rows | 559,627 |
| Weighted prevalence | 0.750%, equal to the training population |
| Weighted rows | 58,749,565, equal to the training population |
| Unburned selection probability | 0.83% to 1.08% by stratum |
| Duplicate cell-dates | 0 |
| Rows from held-out cells or outside the training dates | 0 |

Fire rows by NPWS match: 437,307 unknown, 2,955 wildfire, 111 prescribed.

Files:
- sample: `data/processed/sample/sample_1000000.parquet` (43 columns: the table's 38 plus `region`, `veg_band`, `spatial_holdout`, `sample_weight` and `partition`);
- manifest: `manifests/sample_manifest_1000000.json` (seed, strata, selection probabilities, inclusion counts, git commit and SHA-256 of every source table file);
- per-stratum plan: `manifests/sample_strata_1000000.csv`.

## 5.6 Expand to 2 million?

The pre-set rule expands the sample only if a stratum with at least 1,000 unburned rows gets none, or if a weighted 1st, 50th or 99th percentile of sampled unburned rows is more than 5% of the feature's range away from the population's.

| Feature | Population 1% / 50% / 99% | Sample 1% / 50% / 99% | Largest gap (share of range) |
|---|---|---|---|
| max_temp_prev | 9.5 / 24.3 / 42.1 | 9.5 / 24.3 / 42.1 | 0.08% |
| vpd_prev | 3.0 / 18.6 / 70.5 | 3.0 / 18.7 / 70.4 | 0.12% |
| wind_prev | 1.07 / 3.19 / 7.29 | 1.10 / 3.17 / 7.22 | 0.34% |
| dry_days | 0.1 / 8.5 / 30.9 | 0 / 8 / 30 | 3.0% (population values are read from 1-day histogram bins) |
| rain_30d | 0.3 / 24.1 / 210.4 | 0 / 24.1 / 208.9 | 0.16% |
| npv | 5.6 / 40.6 / 69.0 | 5.6 / 40.6 / 68.9 | 0.11% |

Strata missed: none. **The audit passed, so the sample stays at 1 million.** Running `scripts/15_draw_sample.py 2000000` would draw a 2 million row sample with the same rules if needed later.
