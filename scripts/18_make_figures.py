"""Make PNG images of the workflow runs and outputs, for sharing.

figures/runs/     the console log of the full rerun and of each step, drawn as terminal screenshots
figures/outputs/  maps, charts and tables of the main results

Usage: .venv/Scripts/python scripts/18_make_figures.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from matplotlib.colors import ListedColormap

from grid import OUTPUTS, PROCESSED, ROOT

RUNS = ROOT / "figures" / "runs"
OUT = ROOT / "figures" / "outputs"
LOGS = OUTPUTS / "logs"
MONO = ["Consolas", "DejaVu Sans Mono"]
X0, Y0, CELL, NROW, NCOL = 8_710_000, 5_050_000, 5000, 206, 249
DPI = 150


# ---------- terminal-style images of the real logs ----------

def terminal(lines, title, path, width=150):
    lines = [l.rstrip("\n")[:width] for l in lines]
    height = 0.6 + 0.165 * (len(lines) + 2)
    fig = plt.figure(figsize=(13, height), dpi=DPI)
    fig.patch.set_facecolor("#1e1e1e")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.add_patch(plt.Rectangle((0, 1 - 0.36 / height), 1, 0.36 / height, color="#333333", transform=ax.transAxes))
    for i, colour in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
        ax.add_patch(plt.Circle((0.015 + i * 0.015, 1 - 0.18 / height), 0.05 / height * 0.9, color=colour, transform=ax.transAxes))
    ax.text(0.5, 1 - 0.18 / height, title, color="#cccccc", ha="center", va="center", family=MONO, fontsize=9, transform=ax.transAxes)
    text = "\n".join(lines)
    ax.text(0.012, 1 - 0.5 / height, text, color="#d4d4d4", va="top", ha="left", family=MONO, fontsize=8, linespacing=1.35, transform=ax.transAxes)
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def excerpt(lines, head=30, tail=20):
    if len(lines) <= head + tail + 1:
        return lines
    return lines[:head] + [f"... ({len(lines) - head - tail} lines not shown; full log in outputs/logs) ..."] + lines[-tail:]


def run_images():
    RUNS.mkdir(parents=True, exist_ok=True)
    before = json.loads((OUTPUTS / "fingerprint_before.json").read_text())
    after = json.loads((OUTPUTS / "fingerprint_after.json").read_text())
    root = r"C:\Users\yuvra\nsw-bushfire-risk-mapping"
    lines = [f"PS {root}> .venv/Scripts/python scripts/run_all.py", ""]
    lines += (OUTPUTS / "run_all.log").read_text().splitlines()
    lines += ["", f"PS {root}> .venv/Scripts/python scripts/fingerprint.py outputs/fingerprint_after.json", ""]
    lines += [f"sample:     {after['sample']['rows']:,} rows, {after['sample']['fire']:,} fire, sha256 {after['sample']['hash'][:16]}...",
              f"labels:     {after['labels']['rows']:,} rows, sha256 {after['labels']['hash'][:16]}...",
              f"pixel_day:  {sum(v['rows'] for v in after['pixel_day'].values()):,} rows in {len(after['pixel_day'])} yearly files",
              f"readiness:  all_passed = {after['readiness_all_passed']}",
              "",
              f"Compared with the previous run (outputs/fingerprint_before.json): {'IDENTICAL' if before == after else 'DIFFERENT'}"]
    terminal(lines, "run_all.py: full workflow rerun, 18 November 2026", RUNS / "00_full_rerun.png")

    timings = json.loads((LOGS / "run_all.json").read_text())
    for t in timings:
        stem = Path(t["script"]).stem
        log = (LOGS / f"{stem}.log").read_text(errors="replace").splitlines()
        body = [f"PS {root}> .venv/Scripts/python scripts/{t['script']}{' 1000000' if stem.startswith('15') else ''}", ""]
        body += excerpt(log)
        body += ["", f"[finished in {t['minutes']} min, exit code {t['exit_code']}]"]
        terminal(body, f"{t['script']}", RUNS / f"{stem}.png")


# ---------- output figures ----------

def to_grid(cells, values):
    grid = np.full((NROW, NCOL), np.nan)
    col = ((cells["x"].to_numpy() - X0 - CELL / 2) / CELL).round().astype(int)
    row = ((Y0 - cells["y"].to_numpy() - CELL / 2) / CELL).round().astype(int)
    grid[row, col] = values
    return grid


def map_axes(ax, title):
    ax.set_title(title, fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_aspect("equal")


def table_image(frame, title, path, col_width=1.6, note=None):
    fig_w = max(8, col_width * len(frame.columns))
    fig_h = 1.0 + 0.32 * (len(frame) + 1) + (0.4 if note else 0)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=DPI)
    ax.set_axis_off()
    tab = ax.table(cellText=frame.values, colLabels=frame.columns, loc="center", cellLoc="left")
    tab.auto_set_font_size(False)
    tab.set_fontsize(8)
    tab.scale(1, 1.35)
    for (r, c), cell in tab.get_celld().items():
        if r == 0:
            cell.set_facecolor("#2f4b7c")
            cell.set_text_props(color="white", weight="bold")
        elif r % 2 == 0:
            cell.set_facecolor("#f2f2f2")
        if str(cell.get_text().get_text()) in ("PASS", "IDENTICAL"):
            cell.set_text_props(color="#1a7f37", weight="bold")
    tab.auto_set_column_width(list(range(len(frame.columns))))
    ax.set_title(title, fontsize=11, weight="bold")
    if note:
        fig.text(0.01, 0.01, note, fontsize=8, color="#444444")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def output_images():
    OUT.mkdir(parents=True, exist_ok=True)
    cells = pd.read_csv(ROOT / "splits" / "cells.csv")

    # 1. Rerun comparison
    before = json.loads((OUTPUTS / "fingerprint_before.json").read_text())
    after = json.loads((OUTPUTS / "fingerprint_after.json").read_text())
    rows = [["1 million row sample", f"{before['sample']['rows']:,}", before["sample"]["hash"][:20], after["sample"]["hash"][:20]],
            ["Fire label table", f"{before['labels']['rows']:,}", before["labels"]["hash"][:20], after["labels"]["hash"][:20]]]
    for year in sorted(after["pixel_day"]):
        rows.append([f"Pixel-day table {year}", f"{after['pixel_day'][year]['rows']:,}", before["pixel_day"][year]["hash"][:20], after["pixel_day"][year]["hash"][:20]])
    rows.append(["Population counts", "", before["population_counts_hash"][:20], after["population_counts_hash"][:20]])
    rows.append(["Holdout assignments", "", before["splits_hash"][:20], after["splits_hash"][:20]])
    frame = pd.DataFrame(rows, columns=["Result", "Rows", "Hash before rerun", "Hash after rerun"])
    frame["Match"] = np.where(frame["Hash before rerun"] == frame["Hash after rerun"], "IDENTICAL", "DIFFERENT")
    table_image(frame, "Full rerun from scratch reproduced every result", OUT / "01_rerun_comparison.png",
                note="Hashes are SHA-256 of the sorted data (first 20 characters shown). Script: scripts/fingerprint.py")

    # 2. Readiness checks
    ready = json.loads((OUTPUTS / "readiness_checks.json").read_text())
    names = {"1_same_grid": "Every raster has the same CRS, transform, origin, size and 5 km cell",
             "2_time_safe_features": "All features come from before the target day (no leakage)",
             "3_burn_labels": "Wildfire and prescribed burns distinguished; doubtful detections flagged",
             "4_counts_and_missingness": "Fire / no-fire counts and missingness by year, season and block",
             "5_reproducible_sampling": "Sampling reproducible: saved seed, strata and weights",
             "6_no_duplicates_and_separate_test": "No duplicate rows; test set separate in space and time"}
    frame = pd.DataFrame([[k[0], v, "PASS" if ready[k].get("passed") else "FAIL"] for k, v in names.items()], columns=["#", "Readiness check (workflow report, Step 6)", "Result"])
    table_image(frame, "Step 6 readiness checks", OUT / "02_readiness_checks.png", col_width=3)

    # 3. Run timings
    timings = pd.DataFrame(json.loads((LOGS / "run_all.json").read_text()))
    fig, ax = plt.subplots(figsize=(9, 5.5), dpi=DPI)
    ax.barh(timings["script"][::-1], timings["minutes"][::-1], color="#2f4b7c")
    for i, m in enumerate(timings["minutes"][::-1]):
        ax.text(m + 0.2, i, f"{m}", va="center", fontsize=8)
    ax.set_xlabel("minutes")
    ax.set_title(f"Time per step in the full rerun (total {timings['minutes'].sum():.0f} min, all exit code 0)")
    fig.tight_layout()
    fig.savefig(OUT / "03_run_timings.png", bbox_inches="tight")
    plt.close(fig)

    # 4. Grid and holdouts
    status = np.where(cells["spatial_holdout"] == 1, 1, 0)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), dpi=DPI)
    axes[0].imshow(to_grid(cells, status), cmap=ListedColormap(["#9ecae1", "#e6550d"]), interpolation="nearest")
    for b in range(0, NCOL, 20):
        axes[0].axvline(b - 0.5, color="white", lw=0.4)
    for b in range(0, NROW, 20):
        axes[0].axhline(b - 0.5, color="white", lw=0.4)
    map_axes(axes[0], f"5 km grid: {len(cells):,} NSW cells in 100 km blocks\nblue = training/validation, orange = held-out test blocks ({int(status.sum()):,} cells)")
    region_codes = {"far_west": 0, "west": 1, "central": 2, "east": 3}
    im = axes[1].imshow(to_grid(cells, cells["region"].map(region_codes) * 3 + cells["veg_band"].map({"low_cover": 0, "mid_cover": 1, "high_cover": 2})), cmap="tab20", interpolation="nearest")
    map_axes(axes[1], "Sampling strata: 4 longitude regions x 3 vegetation-cover bands")
    cmap = matplotlib.colormaps["tab20"]
    handles = [matplotlib.patches.Patch(color=cmap(im.norm(r * 3 + v)), label=f"{rn}, {vn}")
               for rn, r in region_codes.items() for v, vn in enumerate(["low cover", "mid cover", "high cover"])]
    axes[1].legend(handles=handles, loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=8, title="region, vegetation band")
    fig.tight_layout()
    fig.savefig(OUT / "04_grid_and_holdouts.png", bbox_inches="tight")
    plt.close(fig)

    # 5. Aligned layers for one example day
    labels = pd.read_parquet(PROCESSED / "labels" / "burn_cell_days.parquet")
    study = labels[labels["in_study_period"]]
    day = study.loc[study["burned"]].groupby("date").size().idxmax()
    prev = day - pd.Timedelta(days=1)
    veg_month = (day.to_period("M") - 1).to_timestamp()
    rast = PROCESSED / "rasters"
    tmax = xr.open_dataset(rast / "daily" / "max_temp.nc")["max_temp"].sel(date=prev).values
    rain = xr.open_dataset(rast / "daily" / "daily_rain.nc")["daily_rain"].sel(date=prev).values
    wind = xr.open_dataset(rast / "daily" / "wind_10m.nc")["wind_10m"].sel(date=prev).values
    cover = xr.open_dataset(rast / "monthly" / "vegetation.nc")["tot_cov"].sel(month=veg_month).values
    burned = xr.open_dataset(rast / "label" / "burned_area_label.nc")["burned_fraction"].sel(date=day).values.astype(float)
    with rasterio.open(rast / "static" / "terrain.tif") as src:
        elev, slope = src.read(1), src.read(2)
    burned[np.isnan(tmax)] = np.nan
    burned[burned == 0] = np.nan
    panels = [(tmax, "inferno", f"Max temperature (C), {prev:%d %b %Y} (t-1)"), (rain, "Blues", f"Rainfall (mm), {prev:%d %b %Y} (t-1)"),
              (wind, "viridis", f"10 m wind (m/s), {prev:%d %b %Y} (t-1)"), (cover, "YlGn", f"Total vegetation cover (%), {veg_month:%b %Y}"),
              (elev, "terrain", "Elevation (m), static"), (slope, "copper", "Mean slope (degrees), static")]
    fig, axes = plt.subplots(2, 4, figsize=(18, 8.5), dpi=DPI)
    for ax, (data, cmap, title) in zip(axes.flat, panels):
        im = ax.imshow(data, cmap=cmap, interpolation="nearest")
        fig.colorbar(im, ax=ax, shrink=0.7)
        map_axes(ax, title)
    ax = axes.flat[6]
    ax.imshow(np.where(np.isnan(tmax), np.nan, 0), cmap=ListedColormap(["#e0e0e0"]))
    im = ax.imshow(burned, cmap="Reds", vmin=0, vmax=1, interpolation="nearest")
    fig.colorbar(im, ax=ax, shrink=0.7)
    map_axes(ax, f"Label: burned fraction on {day:%d %b %Y} (day t)")
    axes.flat[7].set_axis_off()
    axes.flat[7].text(0, 0.5, "All layers on the same 5 km grid\n(EPSG:8058, 249 x 206 cells).\n\nEach row of the pixel-day table\njoins one cell's values for day t:\nweather and wind from t-1,\nvegetation from the previous month,\nterrain, and the fire label for t.", fontsize=11, va="center")
    fig.suptitle(f"Aligned layers for one example day: {day:%d %B %Y} (busiest fire day in the study period)", fontsize=13, weight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "05_aligned_layers_example_day.png", bbox_inches="tight")
    plt.close(fig)

    # 6. Fire label maps: all detections against NPWS-confirmed
    burned_study = study[study["burned"]]
    all_days = burned_study.groupby("cell").size()
    confirmed = burned_study[burned_study["burn_type"].isin(["wildfire", "prescribed"])].groupby("cell").size()
    base = np.where(np.isnan(to_grid(cells, np.zeros(len(cells)))), np.nan, 0)
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), dpi=DPI)
    for ax, series, title in [(axes[0], all_days, f"All TERN burn detections: burned days per cell\n({len(burned_study):,} burned cell-days)"),
                              (axes[1], confirmed, f"Detections confirmed by an NPWS fire of the same season\n({int(confirmed.sum()):,} burned cell-days)")]:
        values = cells["cell_id"].map(series).fillna(0).to_numpy()
        grid = to_grid(cells, values)
        ax.imshow(base, cmap=ListedColormap(["#e0e0e0"]))
        im = ax.imshow(np.where(grid > 0, grid, np.nan), cmap="YlOrRd", interpolation="nearest", norm=matplotlib.colors.LogNorm(vmin=1, vmax=max(2, np.nanmax(grid))))
        fig.colorbar(im, ax=ax, shrink=0.75, label="burned days (log scale)")
        map_axes(ax, title)
    fig.suptitle("Large error in the fire label: most TERN detections are in the cropping belt and match no NPWS fire", fontsize=12, weight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "06_fire_label_maps.png", bbox_inches="tight")
    plt.close(fig)

    # 7. TERN against NPWS by season
    seasons = pd.read_csv(OUTPUTS / "fire_label_checks.csv")
    fig, ax = plt.subplots(figsize=(12, 5.5), dpi=DPI)
    x = np.arange(len(seasons))
    ax.bar(x - 0.27, seasons["tern_burned_km2"].fillna(0), 0.27, label="TERN burnt area (label)", color="#e6550d")
    ax.bar(x, seasons["npws_wildfire_km2"], 0.27, label="NPWS wildfire", color="#756bb1")
    ax.bar(x + 0.27, seasons["npws_prescribed_km2"], 0.27, label="NPWS prescribed burn", color="#31a354")
    for i, v in enumerate(seasons["tern_burned_km2"]):
        if np.isnan(v):
            ax.text(i - 0.27, 2000, "no TERN\nfiles", ha="center", fontsize=7, rotation=90)
    ax.set_xticks(x, seasons["season"], rotation=45)
    ax.set_ylabel("burned area in NSW (km2)")
    ax.set_title("Burned area by fire season (1 July - 30 June): TERN label against NSW NPWS records")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "07_tern_vs_npws_by_season.png", bbox_inches="tight")
    plt.close(fig)

    # 8. Burn label quality flags
    flags = ready["3_burn_labels"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), dpi=DPI)
    types = flags["burned_rows_by_type"]
    axes[0].bar(["unknown\n(no NPWS match)", "wildfire", "prescribed"], [types["unknown"], types["wildfire"], types["prescribed"]], color=["#bdbdbd", "#756bb1", "#31a354"])
    axes[0].set_yscale("log")
    for i, v in enumerate([types["unknown"], types["wildfire"], types["prescribed"]]):
        axes[0].text(i, v * 1.1, f"{v:,}", ha="center", fontsize=9)
    axes[0].set_title(f"Burned rows by burn type ({flags['flags']['burned']:,} burned rows)")
    total = flags["flags"]["burned"]
    vals = [flags["flags"]["burn_unconfirmed"] / total * 100, flags["flags"]["burn_small"] / total * 100]
    axes[1].bar(["burn_unconfirmed\n(no NPWS fire)", "burn_small\n(< 5% of cell)"], vals, color="#e6550d")
    for i, v in enumerate(vals):
        axes[1].text(i, v + 1, f"{v:.1f}%", ha="center", fontsize=10)
    axes[1].set_ylim(0, 110)
    axes[1].set_ylabel("% of burned rows")
    axes[1].set_title("Quality flags on burned rows")
    fig.tight_layout()
    fig.savefig(OUT / "08_burn_label_flags.png", bbox_inches="tight")
    plt.close(fig)

    # 9. Missingness
    miss = pd.read_csv(OUTPUTS / "missingness_by_layer_year.csv").pivot(index="layer", columns="year", values="missing_share") * 100
    fig, ax = plt.subplots(figsize=(13, 4.5), dpi=DPI)
    im = ax.imshow(miss.values, cmap="Reds", aspect="auto", vmin=0, vmax=max(0.2, np.nanmax(miss.values)))
    for (r, c), v in np.ndenumerate(miss.values):
        ax.text(c, r, "n/a" if np.isnan(v) else f"{v:.2f}", ha="center", va="center", fontsize=7)
    ax.set_xticks(range(len(miss.columns)), miss.columns)
    ax.set_yticks(range(len(miss.index)), miss.index)
    fig.colorbar(im, ax=ax, label="% of NSW cell-days missing")
    ax.set_title("Missing values by layer and year (% of NSW cell-days; n/a = year not in that layer's study days)")
    fig.tight_layout()
    fig.savefig(OUT / "09_missingness_by_layer_year.png", bbox_inches="tight")
    plt.close(fig)
    excl = pd.read_csv(OUTPUTS / "pixel_day_exclusions.csv")
    excl = excl[excl["reason"] == "missing total_cover"][["year", "rows"]].astype(object)
    excl.loc[len(excl)] = ["Total", excl["rows"].sum()]
    excl["rows"] = excl["rows"].map(lambda v: f"{int(v):,}")
    table_image(excl.rename(columns={"year": "Year", "rows": "Rows dropped (missing vegetation)"}), "Rows excluded from the pixel-day table", OUT / "10_excluded_rows.png", col_width=3)

    # 11. Missing-share maps
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), dpi=DPI)
    for ax, name, title in [(axes[0], "missing_share_tot_cov", "Vegetation cover: share of months missing"),
                            (axes[1], "vegetation_mean_valid_fraction", "Vegetation: mean share of valid pixels per cell"),
                            (axes[2], "missing_share_max_temp", "Max temperature: share of days missing (0 in every cell)")]:
        with rasterio.open(OUTPUTS / "maps" / f"{name}.tif") as src:
            data = src.read(1)
        im = ax.imshow(data, cmap="magma_r" if "missing" in name else "viridis", interpolation="nearest", vmin=0, vmax=1)
        fig.colorbar(im, ax=ax, shrink=0.75)
        map_axes(ax, title)
    fig.tight_layout()
    fig.savefig(OUT / "11_missingness_maps.png", bbox_inches="tight")
    plt.close(fig)

    # 12. Pixel-day table: rows per year and a preview
    summary = []
    for path in sorted((PROCESSED / "pixel_day").glob("*/part-0.parquet")):
        b = pd.read_parquet(path, columns=["burned"])
        summary.append((int(path.parent.name), len(b), int(b["burned"].sum())))
    summary = pd.DataFrame(summary, columns=["year", "rows", "burned"])
    fig, ax = plt.subplots(figsize=(11, 4.5), dpi=DPI)
    ax.bar(summary["year"].astype(str), summary["rows"] / 1e6, color="#2f4b7c")
    for i, r in summary.iterrows():
        ax.text(i, r["rows"] / 1e6 + 0.2, f"{r['burned'] / r['rows'] * 100:.2f}%\nburned", ha="center", fontsize=7)
    ax.set_ylabel("rows (millions)")
    ax.set_title(f"Pixel-day table: {summary['rows'].sum():,} rows, {summary['burned'].sum():,} burned\nno burnt-area files for 2009 or 2014; 2010 and 2015 have December only")
    ax.set_ylim(0, summary["rows"].max() / 1e6 * 1.15)
    fig.tight_layout()
    fig.savefig(OUT / "12_pixel_day_rows_by_year.png", bbox_inches="tight")
    plt.close(fig)

    table = pd.read_parquet(PROCESSED / "pixel_day" / "2006" / "part-0.parquet")
    preview = pd.concat([table[table["burned"] == 0].head(4), table[(table["burned"] == 1) & (table["burn_type"] == "wildfire")].head(2), table[(table["burned"] == 1) & (table["burn_type"] == "unknown")].head(2)])
    cols = ["cell_id", "date", "weather_date", "veg_month", "max_temp_prev", "rain_30d", "dry_days", "vpd_prev", "wind_prev", "total_cover", "elevation", "slope_mean", "burned", "burned_fraction", "burn_type", "burn_unconfirmed"]
    preview = preview[cols].copy()
    for c in ["date", "weather_date", "veg_month"]:
        preview[c] = pd.to_datetime(preview[c]).dt.strftime("%Y-%m-%d")
    for c in ["max_temp_prev", "rain_30d", "vpd_prev", "wind_prev", "total_cover", "elevation", "slope_mean", "burned_fraction"]:
        preview[c] = preview[c].map(lambda v: f"{v:.2f}")
    table_image(preview, "Pixel-day table: example rows (16 of 38 fields, 2006 file)", OUT / "13_pixel_day_preview.png", col_width=1.1,
                note="One row = one 5 km cell on one day t. Weather is from t-1 and vegetation from the previous month. Field definitions: docs/field_dictionary.md")

    # 14. Partitions and the sample
    counts = pd.read_csv(OUTPUTS / "population_counts.csv").groupby("partition")[["rows", "burned"]].sum().reindex(["train", "validation", "test", "unused"])
    counts["Fire rate"] = (counts["burned"] / counts["rows"] * 100).map(lambda v: f"{v:.2f}%")
    counts["rows"] = counts["rows"].map(lambda v: f"{v:,}")
    counts["burned"] = counts["burned"].map(lambda v: f"{v:,}")
    counts = counts.reset_index().rename(columns={"partition": "Partition", "rows": "Rows", "burned": "Burned rows"})
    counts["Definition"] = ["2002-2008, blocks not held out", "2010-2013, all cells", "2015-2017, held-out blocks only", "test period outside held-out blocks, or held-out blocks in 2002-2013"]
    table_image(counts, "Train / validation / test partitions of the pixel-day table", OUT / "14_partitions.png", col_width=2.2)

    sample = pd.read_parquet(PROCESSED / "sample" / "sample_1000000.parquet", columns=["year", "burned", "sample_weight"])
    by_year = sample.groupby(["year", "burned"]).size().unstack(fill_value=0)
    manifest = json.loads((ROOT / "manifests" / "sample_manifest_1000000.json").read_text())
    fig, ax = plt.subplots(figsize=(10, 5), dpi=DPI)
    ax.bar(by_year.index.astype(str), by_year[0], label="unburned (stratified, weighted)", color="#9ecae1")
    ax.bar(by_year.index.astype(str), by_year[1], bottom=by_year[0], label="fire (all training fires kept)", color="#e6550d")
    ax.set_ylabel("rows in sample")
    ax.legend()
    ax.set_title(f"1,000,000 row training sample: {manifest['fire_rows']:,} fire + {manifest['unburned_rows']:,} unburned, {manifest['strata_count']} strata, seed {manifest['seed']}\n"
                 f"weighted fire rate {manifest['sample_prevalence_weighted'] * 100:.3f}% = population rate {manifest['training_population']['prevalence'] * 100:.3f}%", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "15_sample_composition.png", bbox_inches="tight")
    plt.close(fig)

    # 16. Data sources
    inv = pd.read_csv(ROOT / "inventory" / "download_manifest.csv")
    size_col, src_col = "bytes", "source"
    inv[src_col] = inv["file"].str.replace("\\", "/", regex=False).str.split("/").str[2]
    sources = inv.groupby(src_col).agg(files=(size_col, "size"), gb=(size_col, "sum")).reset_index()
    sources["gb"] = (sources["gb"] / 1e9).map(lambda v: f"{v:.2f}")
    sources.loc[len(sources)] = ["Total", sources["files"].sum(), f"{inv[size_col].sum() / 1e9:.2f}"]
    table_image(sources.rename(columns={src_col: "Source", "files": "Files", "gb": "Size (GB)"}), "Step 2: downloaded source files (each with a SHA-256 checksum)", OUT / "16_downloads.png", col_width=2.5)


def main():
    run_images()
    output_images()
    for folder in (RUNS, OUT):
        print(folder, len(list(folder.glob("*.png"))), "images")


if __name__ == "__main__":
    main()
