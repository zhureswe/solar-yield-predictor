import csv
import hashlib
import statistics
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"
DAILY_FILES = [DATA / "daily.csv", DATA / "october_daily.csv"]
HOURLY_FILES = [DATA / "hourly.csv", DATA / "october_hourly.csv"]
TABLE = DATA / "table.csv"
OCT_WEATHER = DATA / "october_weather.csv"
OCT_DAYS = RESULTS / "october_days.csv"
OUT = RESULTS / "october_exam.csv"
HOURS = [f"{h:02d}:00" for h in range(24)]
PRODUCING = 1.0
THRESHOLD = 30
NOTE = "October 1-27; 4 Oct outage counted apart"
FIELDS = [
    "scope",
    "forecast",
    "days",
    "note_days",
    "hours",
    "miss_kwh",
    "miss_pct",
    "accuracy_pct",
    "within10_days",
    "producing_hours",
    "within10_hours",
    "within10_pct",
    "daily_miss_kwh",
    "daily_miss_pct",
    "note",
]


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_daily():
    daily = {}
    for path in DAILY_FILES:
        for row in read_csv(path):
            daily[row["date"]] = {
                "real": float(row["real_kwh"]),
                "plan": float(row["plan_kwh"]),
                "note": row["note"],
            }
    return daily


def load_hours():
    hours = {}
    for path in HOURLY_FILES:
        for row in read_csv(path):
            hours.setdefault(row["date"], {})[row["hour_start"]] = {
                "real": float(row["real_kwh"]),
                "plan": float(row["plan_kwh"]),
            }
    for day, slots in hours.items():
        if sorted(slots) != HOURS:
            raise SystemExit(f"{day}: {len(slots)} hours")
    return hours


def load_sun():
    sun = {}
    for row in read_csv(TABLE):
        sun[row["date"]] = float(row["shortwave_radiation_sum"])
    for row in read_csv(OCT_WEATHER):
        sun[row["date"]] = float(row["shortwave_radiation_sum"])
    return sun


def md5_others():
    return {
        p.name: hashlib.md5(p.read_bytes()).hexdigest()
        for p in sorted(RESULTS.iterdir())
        if p.is_file() and p.name != OUT.name
    }


def h4_split(day, daily, hours, clean):
    last7 = [d for d in clean if d < day and d in hours][-7:]
    if len(last7) != 7:
        raise SystemExit(f"{day}: H4 needs 7 clean days with hours, has {len(last7)}")
    weights = [sum(hours[d][h]["real"] for d in last7) / 7.0 for h in HOURS]
    total = sum(weights)
    if total <= 0:
        raise SystemExit(f"{day}: zero H4 weight")
    target = daily[last7[-1]]["real"]
    return [target * w / total for w in weights]


def hourly_metrics(days, preds, daily, hours):
    errors = []
    producing = within = 0
    total_real = 0.0
    for day in days:
        for i, h in enumerate(HOURS):
            real = hours[day][h]["real"]
            err = abs(preds[day][i] - real)
            errors.append(err)
            total_real += real
            if real > PRODUCING:
                producing += 1
                if err <= 0.10 * real:
                    within += 1
    miss = sum(errors) / len(errors)
    mean_real = total_real / len(errors)
    daily_miss = sum(abs(sum(preds[d]) - daily[d]["real"]) for d in days) / len(days)
    avg_daily = sum(daily[d]["real"] for d in days) / len(days)
    return {
        "hours": len(errors),
        "miss": miss,
        "miss_pct": 100.0 * miss / mean_real,
        "producing": producing,
        "within": within,
        "within_pct": 100.0 * within / producing,
        "daily_miss": daily_miss,
        "daily_miss_pct": 100.0 * daily_miss / avg_daily,
    }


def daily_metrics(days, cells, daily):
    errors = [abs(cells[d] - daily[d]["real"]) for d in days]
    miss = sum(errors) / len(errors)
    avg = sum(daily[d]["real"] for d in days) / len(days)
    within = sum(
        abs(cells[d] - daily[d]["real"]) <= 0.10 * daily[d]["real"] for d in days
    )
    return miss, 100.0 * miss / avg, 100.0 - 100.0 * miss / avg, within


def daily_forecasts(days, daily, sun, clean):
    def prev_clean(day):
        before = [d for d in clean if d < day]
        if not before:
            raise SystemExit(f"{day}: no clean day before")
        return before[-1]

    def median7(day):
        base = date.fromisoformat(day)
        return statistics.median(
            daily[(base - timedelta(days=i)).isoformat()]["real"] for i in range(1, 8)
        )

    yesterday, cloud, switches = {}, {}, []
    for day in days:
        prev = prev_clean(day)
        base = daily[prev]["real"]
        yesterday[day] = base
        ratio = sun[day] / sun[prev]
        if ratio < 1.0 - THRESHOLD / 100.0:
            cloud[day] = base * ratio
            switches.append(day)
        else:
            cloud[day] = base
    median = {d: median7(d) for d in days}
    plan = {d: daily[d]["plan"] for d in days}
    return yesterday, cloud, median, plan, switches


def main():
    daily = load_daily()
    hours = load_hours()
    sun = load_sun()
    before = md5_others()

    with OCT_DAYS.open(newline="", encoding="utf-8") as f:
        oct_rows = list(csv.DictReader(f))
    october = [r["date"] for r in oct_rows]
    if len(october) != 27 or october[0] != "2026-10-01" or october[-1] != "2026-10-27":
        raise SystemExit(f"{OCT_DAYS.name}: {len(october)} rows")
    clean_all = sorted(d for d in daily if daily[d]["note"] == "")
    clean = [d for d in october if daily[d]["note"] == ""]
    note_days = [d for d in october if daily[d]["note"]]

    yesterday, cloud, median, plan, switches = daily_forecasts(
        october, daily, sun, clean_all
    )

    h4 = {d: h4_split(d, daily, hours, clean_all) for d in october}
    plan_hours = {d: [hours[d][h]["plan"] for h in HOURS] for d in october}

    sep_days = [f"2026-09-{i:02d}" for i in range(1, 31)]
    sep_h4 = {d: h4_split(d, daily, hours, clean_all) for d in sep_days}
    sep_plan = {d: [hours[d][h]["plan"] for h in HOURS] for d in sep_days}

    h4_m = hourly_metrics(clean, h4, daily, hours)
    plan_m = hourly_metrics(clean, plan_hours, daily, hours)
    sep_h4_m = hourly_metrics(sep_days, sep_h4, daily, hours)
    sep_plan_m = hourly_metrics(sep_days, sep_plan, daily, hours)

    daily_rows = []
    for name, cells in (
        ("Yesterday", yesterday),
        (f"Cloud rule T={THRESHOLD}%", cloud),
        ("7-day median", median),
        ("Plant plan", plan),
    ):
        miss, pct, accuracy, within = daily_metrics(clean, cells, daily)
        extra = f"; switch days: {', '.join(switches)}" if switches and name.startswith("Cloud") else ""
        daily_rows.append(
            {
                "scope": "daily",
                "forecast": name,
                "days": len(clean),
                "note_days": len(note_days),
                "hours": "",
                "miss_kwh": f"{miss:.3f}",
                "miss_pct": f"{pct:.2f}",
                "accuracy_pct": f"{accuracy:.2f}",
                "within10_days": within,
                "producing_hours": "",
                "within10_hours": "",
                "within10_pct": "",
                "daily_miss_kwh": "",
                "daily_miss_pct": "",
                "note": NOTE + extra,
            }
        )
    hourly_rows = []
    for name, m in (
        ("My hourly forecast (H4 mean of last 7 clean days)", h4_m),
        ("Plant plan (hourly)", plan_m),
    ):
        hourly_rows.append(
            {
                "scope": "hourly",
                "forecast": name,
                "days": len(clean),
                "note_days": len(note_days),
                "hours": m["hours"],
                "miss_kwh": f"{m['miss']:.3f}",
                "miss_pct": f"{m['miss_pct']:.2f}",
                "accuracy_pct": f"{100.0 - m['miss_pct']:.2f}",
                "within10_days": "",
                "producing_hours": m["producing"],
                "within10_hours": m["within"],
                "within10_pct": f"{m['within_pct']:.1f}",
                "daily_miss_kwh": f"{m['daily_miss']:.3f}",
                "daily_miss_pct": f"{m['daily_miss_pct']:.2f}",
                "note": NOTE,
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(daily_rows + hourly_rows)

    written = read_csv(OUT)
    by_date = {r["date"]: r for r in oct_rows}
    max_sum_err = max(
        abs(sum(h4[d]) - float(by_date[d]["my_forecast_kwh"])) for d in october
    )
    checks = [
        ("88 days with 24 hours", len(hours) == 88, len(hours)),
        ("27 October days, 26 clean", len(october) == 27 and len(clean) == 26, f"{len(clean)} clean"),
        ("1 note day, 4 Oct", note_days == ["2026-10-04"], note_days),
        ("H4 hours sum to yesterday's total", max_sum_err < 1e-9, f"{max_sum_err:.2e}"),
        ("daily total = october_days.csv my_forecast", all(abs(float(by_date[d]["my_forecast_kwh"]) - sum(h4[d])) < 1e-6 for d in october), "27/27"),
        ("yesterday per-day matches october_days.csv", all(abs(float(by_date[d]["my_forecast_kwh"]) - yesterday[d]) < 1e-3 for d in october), "27/27"),
        ("September regression: H4 27.863 kWh/h, 233/386", abs(sep_h4_m["miss"] - 27.863) < 0.001 and sep_h4_m["within"] == 233 and sep_h4_m["producing"] == 386, f"{sep_h4_m['miss']:.3f} {sep_h4_m['within']}/{sep_h4_m['producing']}"),
        ("September regression: plan 45.393 kWh/h, 169/386", abs(sep_plan_m["miss"] - 45.393) < 0.001 and sep_plan_m["within"] == 169, f"{sep_plan_m['miss']:.3f} {sep_plan_m['within']}/{sep_plan_m['producing']}"),
        ("cloud rule October miss = 1018.777", abs(daily_metrics(clean, cloud, daily)[0] - 1018.777) < 0.001, f"{daily_metrics(clean, cloud, daily)[0]:.3f}"),
        ("2 cloud switch days", len(switches) == 2, switches),
        ("October hours scored = 26 x 24", h4_m["hours"] == 624, h4_m["hours"]),
        ("CSV 6 rows, 15 columns", len(written) == 6 and len(written[0]) == len(FIELDS), f"{len(written)} rows"),
    ]
    after = md5_others()
    checks.append(("no other results file changed", before == after, [n for n in before if before[n] != after.get(n)]))

    for name, ok, value in checks:
        print(f"{'OK ' if ok else 'FAIL'} {name}: {value}")
    if not all(ok for _, ok, _ in checks):
        raise SystemExit("checks failed")

    print(f"\nOctober 1-27: {len(october)} days, {len(clean)} without a note, {len(note_days)} with a note (4 Oct outage)")
    print(f"{'Forecast':<46}{'miss kWh':>10}{'miss %':>8}{'acc. %':>8}{'within 10%':>11}")
    for row in daily_rows:
        print(f"{row['forecast']:<46}{float(row['miss_kwh']):>10.3f}{float(row['miss_pct']):>7.2f}%{float(row['accuracy_pct']):>7.2f}%{row['within10_days']:>6}/{len(clean)}")
    print()
    print(f"{'Forecast (hourly)':<46}{'miss kWh':>10}{'miss %':>8}{'acc. %':>8}{'prod within 10%':>17}")
    for row in hourly_rows:
        print(f"{row['forecast']:<46}{float(row['miss_kwh']):>10.3f}{float(row['miss_pct']):>7.2f}%{float(row['accuracy_pct']):>7.2f}%{row['within10_hours']:>10}/{row['producing_hours']}")
    print(f"\nproducing hours (real > 1 kWh): {h4_m['producing']} of {h4_m['hours']}")
    print("cloud switch days:", switches)


if __name__ == "__main__":
    main()
