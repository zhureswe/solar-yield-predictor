# Summary of all forecasts

Numbers come only from files in `results/` (no model was re-trained, no existing result file was changed). Two scopes:

- **July:** the 25 July days without a note (7–12 July are outage / plan-zero days and are excluded). Average real output: **4,768.400 kWh**.
- **September:** all 30 September days (all without a note). Average real output: **7,556.033 kWh**.

Definitions: **miss** = mean |forecast − real| in kWh; **miss %** = miss divided by the average real output of the scope; **accuracy** = 100% − miss % (as requested); **within 10%** = days where |forecast − real| ≤ 10% of the real value.

| Forecast | July 25 days: miss, kWh | July: miss % | July: accuracy | July: within 10% | September 30 days: miss, kWh | September: miss % | September: accuracy | September: within 10% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Plan | 879.280 | 18.44% | 81.56% | 10 of 25 (40%) | 1,015.100 | 13.43% | 86.57% | 12 of 30 (40%) |
| Yesterday | 622.280 | 13.05% | 86.95% | 14 of 25 (56%) | **512.600** | **6.78%** | **93.22%** | **23 of 30 (77%)** |
| 7-day median | 723.640 | 15.18% | 84.82% | 13 of 25 (52%) | 799.300 | 10.58% | 89.42% | 17 of 30 (57%) |
| My model (A) | 974.721 | 20.44% | 79.56% | 8 of 25 (32%) | — not run | — | — | — |
| My model 2 | — not run | — | — | — | 1,576.493 | 20.86% | 79.14% | 5 of 30 (17%) |
| My model 3 | 610.367 | 12.80% | 87.20% | 10 of 25 (40%) | 1,542.506 | 20.41% | 79.59% | 1 of 30 (3%) |

Sources:

- July plan / yesterday / 7-day median: `results/baselines.csv` summary; within-10% counts from `results/baselines_july_days.csv`.
- July my model (A): `results/baselines.csv`; within-10% count from `results/model_july.csv` (`chosen_kwh`).
- July my model 3: walk-forward predictions in `results/model_search_days.csv` (`8 small random forest: same 4 inputs`), scored here on the 25 clean July days. July was part of the search period, so this row is descriptive, not a fresh test.
- September plan / yesterday / 7-day median: `results/baselines_sep.csv`; within-10% counts from `results/baselines_sep_days.csv`.
- September my model 2: `results/baselines_sep.csv` and `results/model2_sep.csv`.
- September my model 3: `results/baselines_sep.csv` and `results/model3_sep.csv`.
- My model (A) was only ever tested on July; my model 2 was only tested on September. No July/September number exists for them in `results/`, so the cell is marked "not run" instead of inventing one.

## Final choice

**The forecast with the lowest September miss is "yesterday" (yesterday's real kWh): 512.600 kWh, 6.78%, accuracy 93.22%, within 10% on 23 of 30 days.** This is the forecast the page uses.

It also has the lowest July miss among the forecasts tested in both months (622.280 kWh, 13.05%), so the choice is consistent and not driven by a single month. No learned model beats it on September: my model 2 is 1,576.493 kWh and my model 3 is 1,542.506 kWh — both far worse. The page must not claim that a learned model is better.

## How this forecast can be improved later, honestly

1. **New unseen data (October).** Keep yesterday's output as the reference and test any new model once on October, after it is fixed. Do not re-pick a model on the same month it is judged on.
2. **Ask the plant about power limits and outages.** Inverter-station limits and planned outages explain part of the miss; with their calendar and limits the low-output days could be predicted instead of treated as surprises.
3. **Hourly shape from pvlib.** Keep the daily total from yesterday (or a better model) and split it into hours with a clear-sky curve from pvlib at Kargaly 42.866 N, 68.376 E; check the split on the 61 days of `data/hourly.csv`.

Any of these must be scored on data not used for choosing it; otherwise the apparent gain is cheating.
