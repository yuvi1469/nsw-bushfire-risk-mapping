# Pixel-day table: field dictionary

Table: `data/processed/pixel_day/YYYY/part-0.parquet`, built by `scripts/11_build_pixel_day_table.py`.
One row is one NSW 5 km cell on one study day **t**. Rows missing a required predictor are dropped (`outputs/pixel_day_exclusions.csv`).

## Identifiers and time

| Field | Type | Description | Use in a model |
|---|---|---|---|
| `cell_id` | int32 | Cell number, 0-32028, from `data/processed/grid/nsw_grid_5km.tif` | No: identifier |
| `date` | date | Target day t | No |
| `year`, `month` | int | Year and month of t | Sampling and splitting only |
| `x`, `y` | float32 | Cell centre, metres, GDA2020 / NSW Lambert (EPSG:8058) | No: identifier |
| `block_id` | int16 | 100 km spatial block (20 x 20 cells) | Splitting only |
| `weather_date` | date | Day the weather features come from (always t-1) | No: audit |
| `veg_month` | date | Month the vegetation features come from (always the month before t's month) | No: audit |

## Label (fire on day t)

Source: TERN Burnt Area and Approximate Day of Burn, MODIS (`scripts/09_fire_label.py`).

| Field | Type | Description | Use in a model |
|---|---|---|---|
| `burned` | int8 | **Target.** 1 when `burned_fraction >= 0.01`, else 0 | Target |
| `burned_fraction` | float32 | Area share of the cell's 250 m pixels with burn date t | No: post-event |
| `burned_pixels` | int32 | Number of 250 m pixels with burn date t | No: post-event |
| `burn_type` | category | `none` (no burned pixel), `unknown` (no NPWS match), `wildfire`, `prescribed` | No: post-event; use to filter labels |
| `share_wildfire`, `share_prescribed` | float32 | Share of burned pixels inside NPWS wildfire or prescribed-burn polygons of the same season | No: post-event |
| `burn_unconfirmed` | int8 | Quality flag: 1 when `burned = 1` and no NPWS polygon of the same season matches (ambiguous detection) | No: use to filter labels |
| `burn_small` | int8 | Quality flag: 1 when `burned = 1` and `burned_fraction < 0.05` (low-quality, small detection) | No: use to filter labels |

The 1 million row sample (`data/processed/sample/sample_1000000.parquet`) adds five fields: `region` and `veg_band` (sampling strata), `spatial_holdout`, `partition` and `sample_weight` (stratum population / stratum sample).

## Weather (day t-1)

Source: SILO gridded daily data, bilinear to the cell centre (`scripts/06_grid_weather.py`).

| Field | Units | Description |
|---|---|---|
| `max_temp_prev` | Celsius | Maximum temperature on t-1 |
| `min_temp_prev` | Celsius | Minimum temperature on t-1 |
| `rain_prev` | mm | Rainfall on t-1 |
| `rain_7d` | mm | Rainfall total for t-7 to t-1 |
| `rain_30d` | mm | Rainfall total for t-30 to t-1 |
| `dry_days` | days | **Rainfall-deficit feature:** consecutive days below 2 mm ending t-1, capped at 30 (the length of the lookback before each block, so every row uses the same cap) |
| `vp_prev` | hPa | Vapour pressure on t-1 |
| `vpd_prev` | hPa | Vapour-pressure deficit on t-1: `es(max_temp_prev) - vp_prev`, with `es(T) = 6.1078 * exp(17.27 T / (T + 237.3))` (Tetens), floored at 0 |

## Wind (day t-1)

Source: TERN gridded near-surface wind, same grid as SILO.

| Field | Units | Description |
|---|---|---|
| `wind_prev` | m/s | Mean 10 m wind speed on t-1 |

## Vegetation (month before t's month)

Source: TERN MODIS fractional cover v310 monthly, mean of 463 m pixels in the cell (`scripts/07_grid_vegetation.py`). The month of t is not used, because its composite can include days after t.

| Field | Units | Description |
|---|---|---|
| `pv` | % | Photosynthetic (green) vegetation cover |
| `npv` | % | Non-photosynthetic (dry) vegetation cover |
| `bare_soil` | % | Bare soil cover |
| `total_cover` | % | Total vegetation cover (product's `tot_cov`, PV + NPV) |
| `veg_valid_fraction` | 0-1 | Share of the cell's pixels with data that month |
| `veg_partial` | int8 | Quality flag: 1 when `veg_valid_fraction < 0.5` |

## Terrain (static)

Source: GA SRTM-derived Smoothed 1 Second DEM, warped to 25 m, Horn slope and aspect (`scripts/08_terrain.py`).

| Field | Units | Description |
|---|---|---|
| `elevation` | m | Mean elevation |
| `slope_mean` | degrees | Mean slope |
| `slope_p90` | degrees | 90th percentile slope |
| `aspect_sin`, `aspect_cos` | -1 to 1 | Mean sine and cosine of aspect over pixels steeper than 1 degree; 0 for flat cells |
| `flat_cell` | 0/1 | 1 when no pixel in the cell is steeper than 1 degree |

## Required predictors

A row is kept only when all of these exist: `max_temp_prev`, `min_temp_prev`, `rain_prev`, `rain_7d`, `rain_30d`, `dry_days`, `vp_prev`, `vpd_prev`, `wind_prev`, `pv`, `npv`, `bare_soil`, `total_cover`, `elevation`, `slope_mean`, `slope_p90`, `aspect_sin`, `aspect_cos`.
