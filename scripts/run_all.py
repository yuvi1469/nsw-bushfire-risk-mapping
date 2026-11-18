"""Run the whole workflow from start to finish, in order, stopping at the first failure.

Usage: .venv/Scripts/python scripts/run_all.py
Each step's output goes to outputs/logs/<script>.log; timings go to outputs/logs/run_all.json.
Downloads are skipped when files are already present and complete.
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "outputs" / "logs"
STEPS = [
    ("01_download_sources.py", []),
    ("02_inspect_sources.py", []),
    ("03_unpack_dem.py", []),
    ("04_check_burn_dates.py", []),
    ("05_define_grid.py", []),
    ("06_grid_weather.py", []),
    ("07_grid_vegetation.py", []),
    ("08_terrain.py", []),
    ("09_fire_label.py", []),
    ("10_quality_checks.py", []),
    ("11_build_pixel_day_table.py", []),
    ("12_check_pixel_day.py", []),
    ("13_pilot_extract.py", []),
    ("14_split_and_count.py", []),
    ("15_draw_sample.py", ["1000000"]),
    ("16_export_rasters.py", []),
    ("17_readiness_checks.py", []),
]


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    timings = []
    for script, args in STEPS:
        start = time.time()
        print(f"{datetime.now():%H:%M:%S} running {script}", flush=True)
        with open(LOGS / f"{Path(script).stem}.log", "w") as log:
            result = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / script), *args], stdout=log, stderr=subprocess.STDOUT)
        minutes = round((time.time() - start) / 60, 1)
        timings.append({"script": script, "minutes": minutes, "exit_code": result.returncode})
        (LOGS / "run_all.json").write_text(json.dumps(timings, indent=2))
        if result.returncode != 0:
            sys.exit(f"{script} failed after {minutes} min; see outputs/logs/{Path(script).stem}.log")
        print(f"{datetime.now():%H:%M:%S} {script} done in {minutes} min", flush=True)
    print(f"All {len(STEPS)} steps finished in {round(sum(t['minutes'] for t in timings), 1)} min")


if __name__ == "__main__":
    main()
