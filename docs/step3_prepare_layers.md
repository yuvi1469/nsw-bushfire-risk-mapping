# Step 3: Prepare the map layers

Completed 17 November 2026. Scripts `02` to `10` in `scripts/` reproduce every result below. Aligned layers are in `data/processed/`; check results are in `outputs/`.

## 3.1 Source inventory

`inventory/source_inventory.csv` now records every source's dates, resolution, CRS, units, nodata code, time step and licence, read from the files themselves (`scripts/02_inspect_sources.py`, full detail in `outputs/source_inspection.json`).

Two sources needed extra handling:
- **DEM:** the ZIP uses Deflate64 compression, which Python and GDAL cannot read. `scripts/03_unpack_dem.py` unpacks it to `data/interim/` and checks each file's CRC-32. The ZIP itself is unchanged.
- **NSW boundary:** no listed source contains the state outline, so the ABS 2021 state boundaries (GDA2020) were added to `data/raw/abs_boundaries/` and the download script.

## 3.2 Project grid

| Setting | Value |
|---|---|
| CRS | GDA2020 / NSW Lambert (EPSG:8058) |
| Cell size | 5 km, origin snapped to multiples of 5 km |
| Extent | 249 x 206 cells |
| NSW cells | **32,029** (800,725 km2) |
| Rule | A cell is in NSW when its centre is inside the ABS NSW mainland polygon |

Lord Howe Island and other offshore islands are dropped by keeping only the mainland polygon. The ACT and Jervis Bay are holes in the NSW polygon, so they are excluded. Files: `data/processed/grid/`.

## 3.3-3.4 Reproject, crop and aggregate

| Layer | Source grid | Method | Output |
|---|---|---|---|
| max_temp, min_temp, daily_rain, vp | 0.05 degree | Bilinear from the 4 surrounding source cells at each cell centre; sea cells left out of the weights | `daily/<name>.nc` (date, cell) |
| wind_10m | 0.05 degree (identical to SILO) | As above | `daily/wind_10m.nc` |
| PV, NPV, bare soil, total cover | 463 m sinusoidal | Mean of the valid pixels whose centre lies in the cell (105-121 pixels per cell); `valid_fraction` kept | `monthly/vegetation.nc` (month, cell) |
| Elevation, slope, aspect | 1 arc-second | See 3.5 | `static/terrain.nc` (cell) |

Daily layers cover 2 July 2002 to 31 January 2017: the study days plus 30 days before each block for rolling rainfall. Vegetation covers January 2002 to December 2017.

## 3.5 Terrain from the DEM

`scripts/08_terrain.py`:
1. Warp the DEM to EPSG:8058 at 25 m (bilinear), giving exactly 200 x 200 pixels per cell.
2. Calculate slope (degrees) and aspect (compass degrees, facing downslope) with Horn's 3x3 method, as used in ArcGIS and GDAL.
3. Per cell, keep the mean elevation, mean slope, 90th percentile slope, and aspect as the mean sine and cosine over pixels steeper than 1 degree.
4. For 223 completely flat cells (0.7%), set aspect sine and cosine to 0 (no direction) and flag them with `flat_cell = 1`.

Sea pixels in this DEM are about 0 m rather than nodata, so coastal cell means include some sea.

## 3.6 Date alignment rule

For a target day t, the Step 4 table uses:
- weather and wind through day t-1, including 7 and 30 day rainfall totals ending at t-1;
- vegetation from the last full month before t, because a month's composite can include days after t;
- terrain for every date.

## 3.7 Fire label

`scripts/04_check_burn_dates.py` found that **every burnt area file holds the burn dates for the month before its file name** (98.6% of burns on average, all 127 files). The label therefore uses the burn dates stored inside the files, and the study period is corrected to 3,838 days (see `docs/step1_scope_check.md`).

`scripts/09_fire_label.py`:
- Each 250 m burned pixel is assigned to the cell containing its centre and weighted by its area. A pixel-date seen in two files is counted once (161 duplicates).
- **Partial-cell rule:** a cell-day is labelled burned when `burned_fraction >= 0.01`. This threshold was set before looking at the results. The fraction is kept for sensitivity analysis.
- **Burn type:** each burned pixel is matched to NPWS polygons from the same fire season. The cell-day takes the type covering most of its matched pixels, or `unknown` when none match.

| Result | Value |
|---|---|
| Cell-days with any burn in the study period | 2,689,570 |
| Cell-days labelled burned (>= 1%) | **902,162** |
| Burn type of labelled cell-days | 896,933 unknown, 4,990 wildfire, 239 prescribed |
| Median burned fraction | 0.5% of the cell |

### Cross-check against NSW NPWS fire history (`outputs/fire_label_checks.csv`)

| Season | TERN burned km2 | Share matched to NPWS | NPWS wildfire km2 | NPWS prescribed km2 |
|---|---|---|---|---|
| 2002-03 | 47,919 | 6.4% | 29,676 | 439 |
| 2003-04 | 143,496 | 0.1% | 1,386 | 854 |
| 2006-07 | 48,315 | 4.7% | 4,487 | 243 |
| 2010-11 | 112,580 | 0.0% | 34 | 479 |
| 2013-14 | 19,400 | 5.7% | 4,249 | 803 |
| 2016-17 | 77,400 | 0.9% | 1,673 | 464 |

Seasons are partly covered where the study period has gaps (2008-09, 2010-11, 2013-14, 2015-16).

**This is the largest data-quality problem found so far.** TERN marks 19,000 to 144,000 km2 of NSW as burned each season, against a few thousand km2 in NPWS records, and only 0-6% of TERN's burned area falls inside an NPWS polygon of the same season. By longitude, 52% of TERN's burned area is in central NSW (147-150 E), the cropping belt, and 31% in the west (144-147 E). Most detections cover a tiny part of a cell, and 42% of burned cell-seasons have five or more separate burn days.

This matches the product's documented limits: it was validated for northern Australia only, and rainfall on sparse ground and other sudden reflectance changes cause false fires. NPWS records mainly cover NPWS estate, so some unmatched burns are real fires on other land. No detections were removed. The burned fraction, burn type and NPWS match are kept so the threshold and filtering can be tested.

## 3.8 Missingness and quality

`scripts/10_quality_checks.py` (`outputs/missingness_by_layer_year.csv`, `outputs/quality_checks.json`, maps in `outputs/maps/`):

| Check | Result |
|---|---|
| Weather and wind missing values (study days x NSW cells) | 0 of 122,927,302 |
| Vegetation missing values | 0.02-0.14% per year |
| Terrain missing values | 0 |
| Cells with vegetation valid fraction below 0.5 on average | 72 (coastal and edge cells) |
| Weather and wind outside plausible ranges | 0. Highest daily rain is 546 mm; the NSW record is about 809 mm |
| Vegetation above 100% | 365 of 5.6 million cell-months |
| PV + NPV + bare soil outside 97-103% | 32% of cell-months; median sum 97.6% |
| Valid static cells | 32,029 (all NSW cells) |
| Possible cell-days | 122,927,302 |

The valid-data mask is `data/processed/masks/valid_static_mask.tif`. Rows missing a required predictor will be dropped in Step 4, not filled.
