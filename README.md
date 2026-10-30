# Solar Yield Predictor

A day-ahead output forecast for a solar plant. The main forecast is simple: use yesterday's real output as tomorrow's forecast. The project checks that forecast against the plant's plan, day by day, and also splits the daily total into hours.

Public page: **https://kitan-a.com/frp/pub/s06/solar/**

## What is here

- `site/index.html` — the public page: upload the plant's files, see the forecast, the real values, the plan, and both accuracies. It is plain HTML, CSS and JavaScript, with no build step.
- `site/talk.html` — a short talk/demo page for the project.
- Python files at the top level and in `scripts/` — the analysis code used for the daily tables, baselines, hourly split and October checks.
- `results/` — aggregate result tables and two aggregate plots.
- `results.md`, `talk.md`, `TASKS.md` — notes and the result write-up.

## Results in short

On the 30 clean days of September 2026:

| Forecast | Mean miss | Miss % | Accuracy | Within 10% |
|---|---:|---:|---:|---:|
| Yesterday's real output | **512.600 kWh** | **6.78%** | **93.22%** | **23 / 30** |
| Plant plan | 1,015.100 kWh | 13.43% | 86.57% | 12 / 30 |

The same rule was the best simple forecast in July. Learned models did worse on September, so the page keeps yesterday's output.

On the 26 clean October days, yesterday's output had a mean miss of 1,109.877 kWh (16.78%) against 1,651.382 kWh (24.96%) for the plant plan. Source: `results/october_exam.csv`.

For the hourly split in September, the selected shape had a mean miss of 27.863 kWh per producing hour; the plant plan shape had 45.393 kWh per producing hour.

## The plant's data is not included

The daily reports, plan cards, plan-fact workbooks, raw weather files and the per-day result tables belong to the plant and are not public. This repository does not contain them: there are no `.xlsx` or `.pdf` files, no `data/` folder, and no per-day CSV files.

The page works with your own files. Nothing is uploaded: the browser reads the files locally.

## Run the page with your own files

1. Serve the `site/` folder with any static file server.
2. Open `index.html`.
3. Drop the plant's files into **Check the plant's files**: daily reports, plan cards, a plan-fact workbook, or a CSV. You can drop all of them at once; the page detects each file type.
4. The page shows tomorrow's forecast, the plant plan, the real output and the accuracy for every day it can read.

The page expects the same kind of files the project used:

- daily report workbooks (one day per file),
- plan cards (one day per file),
- a plan-fact workbook (one month),
- or CSV files with the same columns.

If your files have a different layout, adapt the reading code in `site/index.html` or the scripts in `scripts/`.

## Python code

The scripts expect the plant data in `data/` and do not run without it. They are included to show the method and the checks, not as a ready-made service. The main dependencies are `pandas`, `numpy`, `scikit-learn`, `pvlib`, `Pillow` and `requests`.

`app.py` is the old local demo server. It expects the old root pages and the excluded `data/` folder, so use the static `site/index.html` page instead.
