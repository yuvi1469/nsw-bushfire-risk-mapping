# How to run the workflow

## What you need

- Python 3.13 (tested with 3.13.14) and Git
- About 135 GB of free disk space: 77 GB of source files, 44 GB for the unpacked elevation model, 8 GB of results
- An internet connection for the first run (the downloads are about 81 GB)
- No accounts or API keys: every source is public

## 1. Get the code

```bash
git clone https://github.com/yuvi1469/nsw-bushfire-risk-mapping.git
cd nsw-bushfire-risk-mapping
```

## 2. Install the Python packages

Windows:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

macOS or Linux: the same, with `.venv/bin/python` in place of `.venv\Scripts\python`.

## 3. Run everything

```bash
.venv\Scripts\python scripts\run_all.py
```

This runs the 17 scripts in order, from downloading the sources to the readiness checks, and stops at the first error. Progress is printed to the screen, each step's output goes to `outputs/logs/<script>.log`, and timings go to `outputs/logs/run_all.json`.

- **Time:** the downloads depend on the connection speed (several hours for 81 GB). After that the processing takes about 80 minutes. Downloads resume if interrupted, and running `run_all.py` again skips files already present.
- **Single steps:** each script can also be run on its own in number order, for example `.venv\Scripts\python scripts\09_fire_label.py`. Step 15 takes the sample size: `scripts\15_draw_sample.py 1000000`.

## 4. Check the result

The last step prints the readiness checks and ends with `"all_passed": true`.

To confirm the results match ours:

```bash
.venv\Scripts\python scripts\fingerprint.py outputs\fingerprint.json
```

The `hash` values printed should match the ones below, recorded on 18 November 2026:

| Result | Rows | SHA-256 (first 20 characters) |
|---|---|---|
| 1 million row sample | 1,000,000 | 1f4b132665e4d7c6294b |
| Fire label table | 2,701,360 | 221920f3f57bd72df5d1 |
| Population counts | | 8f7cd4b036c3fab8ab11 |
| Holdout assignments | | 50a7b872e13b1414c4d7 |

The images in `figures/` can be remade with `scripts\18_make_figures.py`. Its rerun comparison images need `outputs/fingerprint_before.json` and `outputs/fingerprint_after.json` from two runs of `fingerprint.py`.

## Where the results are

| Output | Location |
|---|---|
| 1 million row sample | `data/processed/sample/sample_1000000.parquet` |
| Pixel-day table (122.9 million rows) | `data/processed/pixel_day/<year>/part-0.parquet` |
| Aligned rasters and fire label | `data/processed/rasters/` |
| Checks, counts and missingness | `outputs/` (copies in `reports/`) |

`docs/step7_outputs.md` lists all five required outputs, and `docs/field_dictionary.md` describes every field.

## Opening the sample without running anything

```python
import pandas as pd
sample = pd.read_parquet("sample_1000000.parquet")
print(sample.shape)                      # (1000000, 43)
print(sample["burned"].value_counts())   # 559,627 unburned, 440,373 fire
```

Use the `sample_weight` column to recover population rates; the weighted fire rate is 0.75%.
