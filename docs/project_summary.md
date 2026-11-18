# NSW Bushfire Risk Mapping: project summary

This project follows the steps in *NSW Bushfire Risk Mapping Workflow Report* (working plan, 3 November 2026) and completes all seven. Each step has its own notes in `docs/step1_...` to `docs/step7_outputs.md`.

## Question

Does a 5 km cell of mainland NSW burn on a given day, using only information available before that day?

## What was built

| | |
|---|---|
| Sources combined | SILO weather (max/min temperature, rainfall, vapour pressure), TERN 10 m wind, TERN MODIS fractional cover, GA 1 second DEM (slope and aspect derived from it), TERN burnt area and day of burn (label), NSW NPWS fire history (cross-check), ABS state boundary |
| Downloaded | 275 files, 81.6 GB, each with a SHA-256 checksum (`inventory/download_manifest.csv`) |
| Common grid | 5 km cells, GDA2020 / NSW Lambert (EPSG:8058), 32,029 NSW cells |
| Study period | 3,838 days: Aug 2002 – Nov 2008, Dec 2010 – Nov 2013, Dec 2015 – Jan 2017 |
| Pixel-day table | 122,877,196 rows × 38 fields, 902,035 burned (0.73%) |
| Sample | 1,000,000 rows (all 440,373 training fires plus 559,627 unburned rows from 912 strata), seed 20261117, with sampling weights |
| Holdouts | Train 2002–2008, validation 2010–2013, test 2015–2017 in 20 held-out 100 km blocks |

All weather and wind features come from the day before, and vegetation from the month before, so no feature uses information from the target day or later.

## Data quality findings

| Issue | Finding | How it was handled |
|---|---|---|
| Missing periods | TERN burnt area has no files for 2009, 2010, 2014 or 2015 | Study period set to the years that exist |
| Wrong file dates | Every burnt area file holds the month **before** its file name (checked on all 127 files) | Burn dates read from the values inside the files |
| Large errors in the label | TERN marks 19,000–144,000 km² burned per season, against a few thousand km² in NPWS records. 99.4% of burned rows match no NPWS fire, 82% cover under 5% of the cell, and most lie in the central cropping belt (likely harvest or bare-ground detections) | Flagged per row (`burn_unconfirmed`, `burn_small`, `burned_fraction`, `burn_type`) so the label can be tightened and results compared |
| Missing vegetation | 50,106 rows (0.04%), mostly lake and coastal cells | Rows dropped, reasons recorded (`reports/pixel_day_exclusions.csv`) |
| Inconsistencies | Each source uses a different grid, projection, resolution and nodata code; vegetation fractions do not sum to 100% in about a third of cases | All aligned to one grid; nodata codes handled per source |
| Clean layers | Weather and wind have no gaps over NSW and no impossible values | – |

## Checks

- 0 duplicate cell-days; 0 mismatches when 1,470 table values and a 30,000 row pilot (570,000 values) were recalculated from the source layers.
- All six readiness checks in the report pass (`docs/step6_readiness_checks.md`).
- The whole workflow was rerun from scratch with `scripts/run_all.py` on 18 November 2026 (79 minutes) and produced identical results.

## Choices made where the report left it open

The 1% partial-cell burn rule, the NSW Lambert projection, `dry_days` as the rainfall-deficit feature, longitude bands and vegetation-cover tertiles in place of fire-region and vegetation-class layers, and the 100 km block holdout. Each is explained in the step notes.

## Where to find things

`docs/step7_outputs.md` lists the five required outputs and where each is. The large data files (Parquet table, rasters, sample) are not on GitHub because of their size; they can be rebuilt with the scripts or shared separately.
