# Talk: A Solar Forecast That Beats the Plan

3 minutes, 5 slides. Every number comes from `results/`.

## Slide 1 — The problem

Good morning. I work with a solar plant in Kargaly village, near Otrar. Every day the plant must send the grid a plan for tomorrow, hour by hour. The sun does not follow a plan. When real output differs from the plan, the plant pays for every kWh of the difference. My question: can a small, honest forecast make that difference smaller?

## Slide 2 — My data

June to September gives 122 days; October adds 27: 149 days in all. Days when the plant was off or sent no plan are marked and counted apart. Hourly reports run from August to October: 61 report days to September and 27 in October, 2,112 hours. Two traps. The plan cards come in UTC+1, so I moved them four hours to plant time. And a report day does not start at midnight: it runs from 04:00 to 03:00 the next morning. Get those wrong and every number is wrong.

## Slide 3 — Method

I tested three simple forecasts: yesterday's real output, the middle value of the last seven days, and the plant's plan. I also built two weather models: a straight line from sun and temperature, and a small random forest. The rule: learn only on the past, test on days the model never saw. On September, a month I held back, the weather models lost. The straight line missed by 20.9 percent, the forest by 20.4. "Tomorrow equals today" missed by 6.8. The simplest idea won.

## Slide 4 — My number

The real exam: October, 26 normal days the forecast never saw. The plant's plan was 75 percent accurate, mine was 83 percent, and my daily miss was about one third smaller. The plan missed 1,651 kWh a day, 25 percent, inside 10 percent on only 10 of 26 days. My forecast, tomorrow equals today, missed 1,110 kWh, 16.8 percent, inside 10 percent on 15 of 26 days. Hour by hour, I missed 52.7 kWh against 76.3 for the plan, inside 10 percent on 155 of 292 producing hours against 84. One good day: 2 September. Real output 8,355 kWh. My forecast 7,870, 5.8 percent low. The plan 5,192, 37.9 percent low.

## Slide 5 — Limits

Cloudy days still break it: on 30 September real output fell to 4,631 kWh, and my forecast was 59.6 percent too high, the plan 63.5. On 1 October my forecast said 4,631 against 1,679 real. Outage days, like 4 October, are counted apart. September was looked at many times, so October is the honest test. One question is still open: how early must the plant send its plan? In September my forecast beat the plan even three days early: 11.7 percent against 13.4. Thank you.
