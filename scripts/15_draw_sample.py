"""Workflow Step 5.3-5.6: draw the seeded, stratified sample from the training partition.

Design (fixed before drawing):
- The sample comes from the training partition only; validation and test stay whole,
  with their real fire prevalence (see 14_split_and_count.py).
- Fire rows: all are kept if they fit in half the sample; otherwise they are sampled
  proportionally by stratum to half the sample.
- Unburned rows fill the rest, allocated in proportion to each stratum's size
  (largest-remainder rounding), then chosen at random within the stratum.
- Strata: year x month x region x veg_band.
- Weight = stratum population / stratum sample, separately for fire and unburned rows,
  so weighted totals reproduce the training population and its true prevalence.

Coverage audit (pre-set rule for expanding to 2 million):
- every stratum with at least 1,000 unburned rows has at least one sampled unburned row; and
- for each audited feature, the weighted 1st, 50th and 99th percentiles of sampled unburned
  rows are within 5% of the feature range of the population's.
If either fails, the sample is redrawn at 2 million.

Usage: python 15_draw_sample.py [size]
Writes data/processed/sample/sample_<size>.parquet, outputs/sample_manifest_<size>.json and
outputs/sample_strata_<size>.csv.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from grid import OUTPUTS, PROCESSED, ROOT

SEED = 20261117
STRATA = ["year", "month", "region", "veg_band"]
MIN_STRATUM = 1000
QUANTILE_TOLERANCE = 0.05
OUT = PROCESSED / "sample"


def allocate(sizes, total):
    """Largest-remainder proportional allocation that sums exactly to total."""
    exact = sizes / sizes.sum() * total
    base = np.floor(exact).astype(int)
    extra = int(total - base.sum())
    order = np.argsort(-(exact - base).values, kind="stable")
    base.iloc[order[:extra]] += 1
    return np.minimum(base, sizes)


def weighted_quantiles(values, weights, qs):
    order = np.argsort(values)
    values, weights = values[order], weights[order]
    cumulative = np.cumsum(weights) / weights.sum()
    return np.interp(qs, cumulative, values)


def histogram_quantiles(counts, bins, qs):
    cumulative = np.cumsum(counts) / np.sum(counts)
    return np.interp(qs, np.concatenate([[0], cumulative]), bins)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(16 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
    cells = pd.read_csv(PROCESSED / "splits" / "cells.csv")
    counts = pd.read_csv(OUTPUTS / "population_counts.csv")
    train = counts.loc[counts["partition"] == "train"].groupby(STRATA).agg(rows=("rows", "sum"), burned=("burned", "sum")).reset_index()
    train["unburned"] = train["rows"] - train["burned"]

    total_fire = int(train["burned"].sum())
    fire_target = min(total_fire, size // 2)
    train["fire_sample"] = train["burned"] if fire_target == total_fire else allocate(train["burned"], fire_target)
    train["unburned_sample"] = allocate(train["unburned"], size - int(train["fire_sample"].sum()))
    train["fire_weight"] = np.where(train["fire_sample"] > 0, train["burned"] / train["fire_sample"].clip(lower=1), 0)
    train["unburned_weight"] = np.where(train["unburned_sample"] > 0, train["unburned"] / train["unburned_sample"].clip(lower=1), 0)
    train["fire_probability"] = np.where(train["burned"] > 0, train["fire_sample"] / train["burned"].clip(lower=1), 0)
    train["unburned_probability"] = np.where(train["unburned"] > 0, train["unburned_sample"] / train["unburned"].clip(lower=1), 0)
    plan = train.set_index(STRATA)

    period = ("2002-08-01", "2008-11-30")
    pieces = []
    for year in sorted(train["year"].unique()):
        frame = pd.read_parquet(PROCESSED / "pixel_day" / str(year) / "part-0.parquet")
        frame = frame.merge(cells[["cell_id", "region", "veg_band", "spatial_holdout"]], on="cell_id")
        dates = pd.to_datetime(frame["date"])
        frame = frame.loc[(frame["spatial_holdout"] == 0) & (dates >= period[0]) & (dates <= period[1])]
        rng = np.random.default_rng([SEED, size, int(year)])
        frame["_key"] = rng.random(len(frame))
        chosen = []
        for keys, group in frame.groupby(STRATA, observed=True):
            stratum = plan.loc[keys]
            for burned, n_col, w_col in [(1, "fire_sample", "fire_weight"), (0, "unburned_sample", "unburned_weight")]:
                rows = group.loc[group["burned"] == burned]
                n = int(stratum[n_col])
                if n:
                    chosen.append(rows.nsmallest(n, "_key").assign(sample_weight=float(stratum[w_col])))
        year_sample = pd.concat(chosen).drop(columns="_key")
        pieces.append(year_sample)
        print(f"{year}: {len(year_sample)} rows, {int(year_sample['burned'].sum())} burned", flush=True)

    sample = pd.concat(pieces, ignore_index=True).sort_values(["date", "cell_id"]).reset_index(drop=True)
    sample["partition"] = "train"
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"sample_{size}.parquet"
    sample.to_parquet(path, index=False)
    train.to_csv(OUTPUTS / f"sample_strata_{size}.csv", index=False)

    # Coverage audit.
    sampled = sample.groupby(STRATA).agg(unburned_drawn=("burned", lambda b: int((b == 0).sum()))).reset_index()
    audit_strata = train.merge(sampled, on=STRATA, how="left").fillna({"unburned_drawn": 0})
    missing_strata = audit_strata.loc[(audit_strata["unburned"] >= MIN_STRATUM) & (audit_strata["unburned_drawn"] == 0)]
    hist = json.loads((OUTPUTS / "population_histograms.json").read_text())
    unburned = sample.loc[sample["burned"] == 0]
    qs = np.array([0.01, 0.5, 0.99])
    features = {}
    for name, bins in hist["bins"].items():
        bins = np.array(bins)
        population = histogram_quantiles(np.array(hist["counts"][f"train|0|{name}"]), bins, qs)
        drawn = weighted_quantiles(unburned[name].values.astype("float64"), unburned["sample_weight"].values, qs)
        gap = np.abs(drawn - population) / (bins[-1] - bins[0])
        features[name] = {"population_q01_q50_q99": population.round(3).tolist(), "sample_q01_q50_q99": drawn.round(3).tolist(), "max_gap_share_of_range": round(float(gap.max()), 4), "ok": bool(gap.max() <= QUANTILE_TOLERANCE)}
    passed = missing_strata.empty and all(f["ok"] for f in features.values())

    weighted_rows = float(sample["sample_weight"].sum())
    weighted_fire = float(sample.loc[sample["burned"] == 1, "sample_weight"].sum())
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    manifest = {
        "size": len(sample),
        "seed": SEED,
        "random_generator": "numpy default_rng([seed, size, year]); smallest random keys chosen within each stratum",
        "partition": "train only: 1 Aug 2002 - 30 Nov 2008, blocks not spatially held out",
        "strata": STRATA,
        "strata_definitions": {"region": "longitude band of cell centre: far_west 141-144, west 144-147, central 147-150, east 150-154 E", "veg_band": "tertile of the cell's mean total cover 2002-2008"},
        "fire_rule": "all training fire rows kept if they fit in half the sample, else proportional by stratum",
        "fire_rows": int(sample["burned"].sum()),
        "unburned_rows": int((sample["burned"] == 0).sum()),
        "training_population": {"rows": int(train["rows"].sum()), "burned": total_fire, "prevalence": total_fire / int(train["rows"].sum())},
        "sample_prevalence_unweighted": float(sample["burned"].mean()),
        "sample_prevalence_weighted": weighted_fire / weighted_rows,
        "weighted_rows": weighted_rows,
        "selection_probabilities": {"fire": {"min": float(train.loc[train["burned"] > 0, "fire_probability"].min()), "max": float(train["fire_probability"].max())}, "unburned": {"min": float(train.loc[train["unburned"] > 0, "unburned_probability"].min()), "max": float(train["unburned_probability"].max())}},
        "strata_count": len(train),
        "strata_file": f"outputs/sample_strata_{size}.csv",
        "duplicate_cell_dates": int(sample.duplicated(["cell_id", "date"]).sum()),
        "coverage_audit": {
            "rule": f"every stratum with >= {MIN_STRATUM} unburned rows sampled at least once; weighted q01/q50/q99 of sampled unburned rows within {QUANTILE_TOLERANCE:.0%} of each feature's range",
            "strata_missed": missing_strata[STRATA + ["unburned"]].to_dict("records"),
            "features": features,
            "passed": passed,
            "expand_to_2_million": not passed,
        },
        "source_versions": {
            "git_commit": commit,
            "download_manifest": "inventory/download_manifest.csv",
            "pixel_day_files_sha256": {p.parent.name: sha256(p) for p in sorted((PROCESSED / "pixel_day").glob("*/part-0.parquet")) if int(p.parent.name) <= 2008},
        },
        "sample_file_sha256": sha256(path),
    }
    (OUTPUTS / f"sample_manifest_{size}.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(json.dumps({k: v for k, v in manifest.items() if k not in ("source_versions",)}, indent=2, default=str))


if __name__ == "__main__":
    main()
