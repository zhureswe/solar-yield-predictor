import csv
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from make_daily import note_for
from make_hourly import file_date, read_plan, read_report

SYP = ROOT / "SYP"
OUT = ROOT / "data" / "october_daily.csv"
START = date(2026, 10, 1)
END = date(2026, 10, 27)
DAYS = [START + timedelta(days=i) for i in range((END - START).days + 1)]


def fmt(value):
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.3f}"


def main():
    reports = {
        file_date(p): p for p in SYP.glob("*10.26.xlsx") if "отчет" in p.name.lower()
    }
    plans = {
        file_date(p): p for p in SYP.glob("*10.26.xlsx") if "план" in p.name.lower()
    }
    checks = []
    checks.append(("reports = 27", len(reports) == 27, len(reports)))
    checks.append(("plans = 31", len(plans) == 31, len(plans)))
    checks.append(("report dates 1-27 Oct", set(reports) == set(DAYS), len(reports)))
    checks.append(("every report has a plan", set(DAYS) <= set(plans), len(plans)))

    rows = []
    for day in DAYS:
        report_date, hours, start_hour, real_kwh = read_report(reports[day])
        if report_date != day:
            raise SystemExit(f"{day}: report cell C4 says {report_date}")
        if len(hours) != 24 or start_hour != 4:
            raise SystemExit(f"{day}: bad report hours/labels")
        _, plan_kwh = read_plan(plans[day])
        rows.append((day, plan_kwh, real_kwh, note_for(plan_kwh, real_kwh)))

    checks.append(("27 daily rows", len(rows) == 27, len(rows)))
    if [r[0] for r in rows] != DAYS:
        raise SystemExit("dates are not 1-27 October in order")

    plan_sum = sum(r[1] for r in rows)
    real_sum = sum(r[2] for r in rows)
    checks.append(("day plan = A32", all(r[1] > 0 for r in rows), f"{plan_sum:.1f} total"))
    checks.append(("day real = D10", all(r[2] >= 0 for r in rows), f"{real_sum:.1f} total"))

    notes = [(r[0].isoformat(), r[3]) for r in rows if r[3]]
    oct4 = next(r for r in rows if r[0] == date(2026, 10, 4))
    checks.append(
        ("4 Oct outage", oct4[3] == "outage", f"real {oct4[2]:.1f} / plan {oct4[1]:.1f}")
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "plan_kwh", "real_kwh", "note"])
        for d, plan_kwh, real_kwh, note in rows:
            writer.writerow([d.isoformat(), fmt(plan_kwh), fmt(real_kwh), note])

    with OUT.open(newline="", encoding="utf-8") as f:
        got = list(csv.DictReader(f))
    checks.append(("CSV rows", len(got) == 27, len(got)))
    checks.append(
        (
            "CSV plan/real match",
            all(
                abs(float(g["plan_kwh"]) - r[1]) <= 1e-3
                and abs(float(g["real_kwh"]) - r[2]) <= 1e-3
                and g["note"] == r[3]
                for g, r in zip(got, rows)
            ),
            f"{len(got)}/27",
        )
    )

    for name, ok, value in checks:
        print(f"{'OK ' if ok else 'FAIL'} {name}: {value}")
    if not all(ok for _, ok, _ in checks):
        raise SystemExit("checks failed")

    print("\nnotes:", notes if notes else "none")
    print("clean days:", sum(1 for r in rows if not r[3]))
    print("\ndate,plan,real,note")
    for day in (date(2026, 10, 1), date(2026, 10, 4), date(2026, 10, 27)):
        r = next(x for x in rows if x[0] == day)
        print(f"{r[0]},{fmt(r[1])},{fmt(r[2])},{r[3]}")


if __name__ == "__main__":
    main()
