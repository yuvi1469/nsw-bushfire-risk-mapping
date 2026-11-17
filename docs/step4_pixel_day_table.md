# Step 4: Build the pixel-day table

Completed 17 November 2026 with `scripts/11_build_pixel_day_table.py` and checked with `scripts/12_check_pixel_day.py`.

## The table

| Item | Value |
|---|---|
| Location | `data/processed/pixel_day/YYYY/part-0.parquet`, one folder per year |
| Format | Parquet, zstd compression, 5.4 GB in total |
| Row | One NSW 5 km cell on one study day |
| Rows | **122,877,196** |
| Labelled burned (`burned = 1`) | **902,035** (0.73%) |
| Rows with any burned pixel | 2,689,197 |
| Fields | 36 (see `docs/field_dictionary.md`) |

The aligned rasters and gridded layers in `data/processed/` remain the source of truth; the table can be rebuilt from them.

## Rows by year

| Year | Days | Rows | Burned rows |
|---|---|---|---|
| 2002 | 153 | 4,898,904 | 9,427 |
| 2003 | 365 | 11,687,626 | 101,084 |
| 2004 | 366 | 11,718,193 | 102,954 |
| 2005 | 365 | 11,687,816 | 82,396 |
| 2006 | 365 | 11,687,189 | 76,360 |
| 2007 | 365 | 11,687,532 | 68,335 |
| 2008 | 335 | 10,713,301 | 96,018 |
| 2010 | 31 | 992,496 | 17,033 |
| 2011 | 365 | 11,684,593 | 109,057 |
| 2012 | 366 | 11,718,944 | 103,657 |
| 2013 | 334 | 10,695,802 | 59,626 |
| 2015 | 31 | 992,713 | 3,210 |
| 2016 | 366 | 11,719,343 | 69,379 |
| 2017 | 31 | 992,744 | 3,499 |

Monthly counts are in `outputs/pixel_day_counts_by_year_month.csv`.

## Feature rules

Following the report's feature groups and time-safe rule:

| Group | Fields | Rule |
|---|---|---|
| Weather | `max_temp_prev`, `min_temp_prev`, `rain_prev`, `vp_prev`, `vpd_prev` | Day t-1 |
| Rainfall windows | `rain_7d`, `rain_30d` | Totals for t-7 to t-1 and t-30 to t-1 |
| Rainfall deficit | `dry_days` | Consecutive days below 2 mm ending t-1, capped at 30 |
| Wind | `wind_prev` | Day t-1 |
| Vegetation | `pv`, `npv`, `bare_soil`, `total_cover` | Month before t's month |
| Terrain | `elevation`, `slope_mean`, `slope_p90`, `aspect_sin`, `aspect_cos`, `flat_cell` | Static |
| Label | `burned`, `burned_fraction`, `burn_type`, ... | Day t; never a predictor |
| Identifiers | `cell_id`, `date`, `x`, `y`, `block_id`, `year`, `month` | Audit, sampling and splitting only |

**Rainfall-deficit choice:** a deficit against long-term average rainfall would need either SILO data from before 2002 (not downloaded) or an average over the study years, which would leak later information into earlier rows. `dry_days` uses only rainfall up to t-1. The 30-day cap matches the 30-day lookback available before each block, so every row is calculated the same way.

**Vapour-pressure deficit:** `vpd_prev = es(max_temp_prev) - vp_prev`, using the Tetens formula `es(T) = 6.1078 exp(17.27 T / (T + 237.3))` hPa. This uses maximum temperature, so it describes the driest part of the day.

## Excluded rows

Rows missing a required predictor were dropped, not filled (`outputs/pixel_day_exclusions.csv`):

| Reason | Rows |
|---|---|
| Missing vegetation (PV, NPV, bare soil and total cover all missing together) | 50,106 |
| Missing weather, wind or terrain | 0 |

That is 0.04% of the 122,927,302 possible cell-days. 127 of the dropped rows were labelled burned.

## Checks (`outputs/pixel_day_checks.json`)

| Check | Result |
|---|---|
| Duplicate cell-date rows | 0 in every year |
| Missing required predictors | 0 |
| Weather date is always t-1 | Yes, every row |
| Vegetation month is always before t's month | Yes, every row |
| Spot check: 1,470 values in 210 random rows recalculated from the aligned layers (`max_temp_prev`, `rain_7d`, `rain_30d`, `vp_prev`, `wind_prev`, `pv`, `burned_fraction`) | 0 mismatches |

## Notes for Step 5

- Fire is rare: 0.73% of rows are labelled burned, so a purely random sample would contain few fires.
- Of the burned rows, almost all have `burn_type = unknown` (no NPWS match). The Step 3 notes describe the likely false fires in the cropping belt. Step 5 should keep `burn_type` and `burned_fraction` so prevalence and sensitivity can be reported both ways.
- `block_id` gives 100 km spatial blocks for the spatial holdout.
- The report's strata include "fire region" and "vegetation class". Neither layer is in the source list, so Step 5 needs a documented substitute, for example vegetation bands from long-term mean cover.
