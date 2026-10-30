import csv
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from make_hourly import file_date, read_plan, read_report

SYP = ROOT / "SYP"
DAILY = ROOT / "data" / "october_daily.csv"
OUT = ROOT / "data" / "october_hourly.csv"
START = date(2026, 10, 1)
END = date(2026, 10, 27)
DAYS = [START + timedelta(days=i) for i in range((END - START).days + 1)]


def main():
    with DAILY.open(newline="", encoding="utf-8") as f:
        daily = {
            row["date"]: (float(row["plan_kwh"]), float(row["real_kwh"]))
            for row in csv.DictReader(f)
        }
    if len(daily) != 27:
        raise SystemExit(f"{DAILY.name}: {len(daily)} rows, expected 27")

    reports = {
        file_date(p): p for p in SYP.glob("*10.26.xlsx") if "отчет" in p.name.lower()
    }
    plans = {
        file_date(p): p for p in SYP.glob("*10.26.xlsx") if "план" in p.name.lower()
    }
    if set(reports) != set(DAYS) or not set(DAYS) <= set(plans):
        raise SystemExit("October report/plan files are incomplete")

    rows = []
    max_real_diff = 0.0
    max_plan_diff = 0.0
    for day in DAYS:
        report_date, values, start_hour, report_total = read_report(reports[day])
        if report_date != day:
            raise SystemExit(f"{day}: report date {report_date}")
        plan_by_start, plan_total = read_plan(plans[day])
        plan_map = {
            datetime.combine(day, time(0, 0)) + timedelta(hours=start + 4): value
            for start, value in plan_by_start.items()
        }
        for i, produced in enumerate(values):
            ts = datetime.combine(day, time(start_hour, 0)) + timedelta(hours=i)
            if ts not in plan_map:
                raise SystemExit(f"{day}: no plan for {ts}")
            rows.append((day, ts.strftime("%H:%M"), produced, plan_map[ts]))
        real_sum = sum(values)
        plan_sum = sum(plan_map.values())
        daily_plan, daily_real = daily[day.isoformat()]
        max_real_diff = max(max_real_diff, abs(real_sum - daily_real))
        max_plan_diff = max(max_plan_diff, abs(plan_sum - daily_plan))
        if abs(report_total - daily_real) > 1e-3:
            raise SystemExit(f"{day}: report total {report_total} != daily {daily_real}")
        if abs(plan_total - daily_plan) > 1e-3:
            raise SystemExit(f"{day}: plan total {plan_total} != daily {daily_plan}")

    counts = Counter(item[0] for item in rows)
    checks = [
        ("27 days in file", set(counts) == set(DAYS), len(counts)),
        ("24 rows every day", set(counts.values()) == {24}, sorted(set(counts.values()))),
        ("648 data rows", len(rows) == 648, len(rows)),
        ("real day sums vs october_daily.csv < 1 kWh", max_real_diff < 1.0, f"{max_real_diff:.6f}"),
        ("plan day sums vs october_daily.csv < 1 kWh", max_plan_diff < 1.0, f"{max_plan_diff:.6f}"),
        ("hours are 04:00..03:00 Astana", all(r[1] in {f"{(h + 4) % 24:02d}:00" for h in range(24)} for r in rows), "ok"),
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "hour_start", "real_kwh", "plan_kwh"])
        for day, hour_start, real, plan in rows:
            writer.writerow([day.isoformat(), hour_start, f"{real:.6f}", f"{plan:.3f}"])

    with OUT.open(newline="", encoding="utf-8") as f:
        got = list(csv.DictReader(f))
    checks.append(("CSV rows read back", len(got) == 648, len(got)))

    for name, ok, value in checks:
        print(f"{'OK ' if ok else 'FAIL'} {name}: {value}")
    if not all(ok for _, ok, _ in checks):
        raise SystemExit("checks failed")

    print("\ndate,hour_start,real,plan")
    for day in (date(2026, 10, 1), date(2026, 10, 4), date(2026, 10, 27)):
        r = next(x for x in rows if x[0] == day and x[1] == "12:00")
        print(f"{r[0]},{r[1]},{r[2]:.3f},{r[3]:.1f}")


if __name__ == "__main__":
    main()
