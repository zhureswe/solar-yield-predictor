# Solar Yield Predictor: tasks for the week

**Idea:** a day-ahead hourly forecast for the Otrar solar plant (Cascade NRG, 1,175 kW AC / 1,900 kW DC, lat 42.85,
lon 69.59) that cuts the imbalance between the plan the plant submits and what it really produces.
**Track:** Data and web (with a small model). The problem is real: 104.4 MWh of imbalance in 61 days (June-July 2026).

**Demo Day claim (measure it, then fill in):** "On N test days, my forecast would have cut the imbalance by X% against
the plan the plant really submitted."

Start: `page_v0.html` is your first page (it needs a backend at `/api/forecast`; today it shows demo weather).
`data/raw/` has your 3 Excel files.

## Tasks

1. **Day 2 - Collect and clean the data.** Get all hourly meter data you can (60+ days) and the plans the plant
   submitted. Turn the Excel files into one table `data/hourly.csv`: hour (Astana time, UTC+5), kWh produced,
   kWh planned. Remove people's names.
   Done when: the table has 60+ days, and on 3 days the hours match the original reports (the report also has UTC+1
   rows: check the time zone!).
   Use: the agent (Python, pandas), your Excel files.

2. **Day 2-3 - Real weather.** Get the weather for the plant: Open-Meteo (free, no key), lat 42.85, lon 69.59: sun
   (GHI), clouds, temperature. For the past days use the *historical forecast* API (the forecasts that were really
   made then), not measured weather.
   Done when: weather and generation are in one table per hour, and a plot shows sun and output peak at the same hour.
   Use: skill web-search, Open-Meteo.

3. **Day 3 - Baselines.** Make 3 simple forecasts for every day: (a) yesterday's output, (b) median of the last
   7 days, (c) the plan the plant really submitted. Also try `quartz_solar_forecast` (open-source, from Open Climate
   Fix).
   Done when: a table with the error of each baseline (hourly and daily, in kWh) on the same days.
   Use: the agent, materials/GPU-JOBS.md (not needed: a CPU is enough).

4. **Day 4 - Your model.** A physical model (sun position + panels) plus a small ML correction (gradient boosting)
   from hour, forecast GHI, clouds and temperature.
   Done when: the model trains, and its error on the training days is lower than the best baseline.
   Use: the agent (Python, scikit-learn).

5. **Day 5 - Test on days the model never saw (backtest).** Keep the last 2-3 weeks out of training. For each test
   day, forecast only with what was known the evening before. Count: hourly error, daily error, imbalance in kWh,
   against the 3 baselines and against the real plan. At least 10 test days.
   Done when: one table + one plot, with the number of test days.
   Use: the agent.

6. **Day 6 - Fix the worst part and connect the page.** Look at the worst days (often cloudy). Check that the 80%
   range really holds 80% of the test days. Run your backend in the workspace and connect `page_v0.html` to it
   (real weather, no demo).
   Done when: the page shows a real forecast for tomorrow at `https://kitan-a.com/frp/s06/proxy/8000/...`.
   Use: skill page-check.

7. **Day 7 - Page, paper and talk.** Problem (the imbalance) -> your method -> your numbers against the real plan
   -> limits. Remove every claim that you did not test.
   Done when: a 3-minute talk with 1 table and 1 plot, shown to your mentor.

## Risks

- **Not enough hourly data** (only a few days). Backup: daily totals for June-July are in the imbalance file; forecast
  the daily total first, the hourly shape second.
- **The weather forecast for past days is not available.** Backup: use measured weather for the past days, and say
  clearly that the real forecast error will be a bit bigger.

## Ask the plant (Day 2)

How many days of hourly data can you share? What does 1 kWh of imbalance cost (being short and being long)? When must
the plan be submitted (the gate closure time)?
