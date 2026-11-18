"""Record a fingerprint of the main results, so a full rerun can be compared with the last one.

Usage: python fingerprint.py <output.json>
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from grid import OUTPUTS, PROCESSED, ROOT


def frame_hash(frame):
    return hashlib.sha256(pd.util.hash_pandas_object(frame, index=False).values.tobytes()).hexdigest()


def main():
    sample = pd.read_parquet(PROCESSED / "sample" / "sample_1000000.parquet").sort_values(["date", "cell_id"]).reset_index(drop=True)
    labels = pd.read_parquet(PROCESSED / "labels" / "burn_cell_days.parquet").sort_values(["cell", "date"]).reset_index(drop=True)
    table = {}
    for path in sorted((PROCESSED / "pixel_day").glob("*/part-0.parquet")):
        frame = pd.read_parquet(path).sort_values(["date", "cell_id"]).reset_index(drop=True)
        table[path.parent.name] = {"rows": len(frame), "burned": int(frame["burned"].sum()), "hash": frame_hash(frame)}
    print_keys = ["readiness_checks.json", "quality_checks.json", "pixel_day_checks.json"]
    result = {
        "sample": {"rows": len(sample), "fire": int(sample["burned"].sum()), "hash": frame_hash(sample)},
        "labels": {"rows": len(labels), "burned_in_study": int(labels.loc[labels["in_study_period"], "burned"].sum()), "hash": frame_hash(labels)},
        "pixel_day": table,
        "population_counts_hash": frame_hash(pd.read_csv(OUTPUTS / "population_counts.csv")),
        "splits_hash": frame_hash(pd.read_csv(ROOT / "splits" / "cells.csv")),
        "readiness_all_passed": json.loads((OUTPUTS / "readiness_checks.json").read_text())["all_passed"],
        "reports_present": [k for k in print_keys if (OUTPUTS / k).exists()],
    }
    Path(sys.argv[1]).write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "pixel_day"}, indent=2))


if __name__ == "__main__":
    main()
