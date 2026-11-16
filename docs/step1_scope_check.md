# Step 1: Prediction question and data period

Checked 9 November 2026 from provider metadata and file listings. No data files were downloaded.

## Prediction question

Does a 5 km map cell burn on a given day, using only information available before that day? This is a historical modelling study, not an operational fire-warning system.

## Coverage check

| Layer | Stated period | Files found for the study period |
|---|---|---|
| SILO max_temp, min_temp, daily_rain, vp | 1889 to current year | All 16 annual files, 2002-2017, for each variable |
| TERN wind, 10 m | 1 Jan 1975 to 31 Dec 2018 | All 44 annual files |
| TERN fractional cover | 2001 onwards | 2002-2017 for all 5 NSW tiles; 12 months per year checked on h30v12 |
| TERN burnt area | 1 Aug 2002 to 28 Feb 2017 | **127 of 175 months** |

## Missing burnt area months

There are no monthly files for **January 2009 to December 2010** or **January 2014 to December 2015**.

Evidence:
- The monthly catalogue lists no files for those months.
- Direct requests for January of each of the four years returned 404.
- The yearly catalogue also has no files for those four years.
- The full-period composite has 127 time steps, jumping from December 2008 to January 2011 and from December 2013 to January 2016.

## Final period

Per the report's instruction to verify file coverage before fixing the extent:

| Block | Dates | Months | Days |
|---|---|---|---|
| 1 | 1 Aug 2002 - 31 Dec 2008 | 77 | 2,345 |
| 2 | 1 Jan 2011 - 31 Dec 2013 | 36 | 1,096 |
| 3 | 1 Jan 2016 - 28 Feb 2017 | 14 | 425 |
| **Total** | | **127** | **3,866** |

The excluded months have no fire label, so they produce no rows. This is 3,866 of the 5,326 days in the stated period (73%).

At roughly 32,000 cells for NSW (estimate from area), this gives about 124 million possible cell-days before quality filtering, which is still well above the 1-2 million target.

Weather for the first days after a gap, such as 7-day and 30-day rainfall in January 2011, is still available because SILO has no gap. Vegetation and wind are also continuous.

## Other points recorded

- The burnt area link in the report PDF ends in `81f7-fff2c6d54d32` and returns 404. The correct record ends in `81e7-fff2c6d54d32`.
- The burn variable is named `julian_date_of_burn`, but its units are days since 1970-01-01. Confirm against real values in Step 3.
- The burnt area accuracy (95.2% overall, 3.7% commission, 6.2% omission) is stated for northern Australia only. Low-intensity understorey fires and fires covering a small part of a 250 m pixel are not detected.
- Wind is confirmed at 0.05 degrees.

## Still to confirm from the files after download

- SILO grid, coordinate system, temperature units and no-data value
- Wind variable name, units and no-data value
- Exact fractional cover projection and the NSW tile list
- NPWS fields, coordinate system and whether a date field exists
- ELVIS DEM product details
- Missing dates inside the annual files; this check used file listings

## Correction from Step 3

Step 3 found that every burnt area file holds the burn dates for the month **before** its file name (checked for all 127 files; `outputs/burn_date_check.csv`). The study period therefore follows the burn dates inside the files, within the stated product period:

| Block | Dates | Days |
|---|---|---|
| 1 | 1 Aug 2002 - 30 Nov 2008 | 2,314 |
| 2 | 1 Dec 2010 - 30 Nov 2013 | 1,096 |
| 3 | 1 Dec 2015 - 31 Jan 2017 | 428 |
| **Total** | | **3,838** |

This replaces the table above. The blocks are set in `scripts/grid.py`.
