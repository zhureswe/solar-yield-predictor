import csv
import hashlib
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import model as m
from make_hourly import file_date, read_plan, read_report

TABLE = ROOT / "data" / "table.csv"
BASE = ROOT / "results" / "baselines_july_days.csv"
MODEL_JULY = ROOT / "results" / "model_july.csv"
OUT = ROOT / "results" / "july_daily_table.csv"
SYP = ROOT / "SYP"
RESULTS = ROOT / "results"
JULY = [f"2026-07-{day:02d}" for day in range(1, 32)]


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def accuracy(forecast, real):
    return 100.0 - abs(forecast - real) / real * 100.0


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def uploaded_days(month):
    reports = {}
    plans = {}
    for path in SYP.glob("Суточный отчет*.xlsx"):
        try:
            day = file_date(path)
        except ValueError:
            continue
        if day.year == 2026 and day.month == month:
            reports[day] = path
    for path in SYP.glob("план *.xlsx"):
        try:
            day = file_date(path)
        except ValueError:
            continue
        if day.year == 2026 and day.month == month:
            plans[day] = path
    return reports, plans


def check_uploaded(month, rows):
    reports, plans = uploaded_days(month)
    errors = []
    max_real = 0.0
    max_plan = 0.0
    for day in sorted(set(reports) & set(plans)):
        report_date, _, _, real_total = read_report(reports[day])
        _, plan_total = read_plan(plans[day])
        if report_date != day:
            errors.append(f"{reports[day].name}: date {report_date} != {day}")
        row = rows[day.isoformat()]
        max_real = max(max_real, abs(real_total - row["real_kwh"]))
        max_plan = max(max_plan, abs(plan_total - row["plan_kwh"]))
    return reports, plans, errors, max_real, max_plan


def main():
    before = {
        path.name: md5(path)
        for path in RESULTS.glob("*")
        if path.is_file() and path.name != OUT.name
    }
    table_before = md5(TABLE)

    rows = m.read_table()
    if len(rows) != 122:
        raise SystemExit(f"table.csv: {len(rows)} rows")
    baselines = {row["date"]: row for row in read_csv(BASE)}
    saved_model = {row["date"]: row for row in read_csv(MODEL_JULY)}
    if set(baselines) != set(JULY):
        raise SystemExit(f"baselines: {len(baselines)} July rows")
    if set(saved_model) != {d for d in JULY if rows[d]["note"] == ""}:
        raise SystemExit(f"model_july: {len(saved_model)} clean July rows")

    june_clean = [
        d for d in sorted(rows) if d.startswith("2026-06") and rows[d]["note"] == ""
    ]
    coef_a = m.fit(
        [m.features_a(rows, d) for d in june_clean],
        [rows[d]["real_kwh"] for d in june_clean],
    )
    weather = {d: m.predict_a(rows, coef_a, d) for d in JULY}

    max_saved = 0.0
    for d in sorted(saved_model):
        max_saved = max(max_saved, abs(weather[d] - float(saved_model[d]["model_a_kwh"])))

    max_yesterday = 0.0
    for d in JULY:
        prev = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
        max_yesterday = max(
            max_yesterday, abs(float(baselines[d]["yesterday_kwh"]) - rows[prev]["real_kwh"])
        )

    records = []
    for d in JULY:
        real = rows[d]["real_kwh"]
        plan = rows[d]["plan_kwh"]
        yesterday = float(baselines[d]["yesterday_kwh"])
        note = rows[d]["note"]
        clean = note == "" and real > 0
        records.append(
            {
                "date": d,
                "weather": weather[d],
                "yesterday": yesterday,
                "real": real,
                "plan": plan,
                "my_acc": accuracy(weather[d], real) if clean else None,
                "plan_acc": accuracy(plan, real) if clean else None,
                "note": note,
            }
        )

    clean = [r for r in records if r["my_acc"] is not None]
    avg_real = sum(r["real"] for r in clean) / len(clean)
    weather_miss = sum(abs(r["weather"] - r["real"]) for r in clean) / len(clean)
    yesterday_miss = sum(abs(r["yesterday"] - r["real"]) for r in clean) / len(clean)
    plan_miss = sum(abs(r["plan"] - r["real"]) for r in clean) / len(clean)
    weather_acc = sum(r["my_acc"] for r in clean) / len(clean)
    plan_acc = sum(r["plan_acc"] for r in clean) / len(clean)
    yesterday_acc = sum(
        accuracy(r["yesterday"], r["real"]) for r in clean
    ) / len(clean)

    june_reports, june_plans, june_errors, june_real, june_plan = check_uploaded(6, rows)
    july_reports, july_plans, july_errors, july_real, july_plan = check_uploaded(7, rows)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "date",
                "my_forecast_weather_kwh",
                "yesterday_kwh",
                "real_kwh",
                "plan_kwh",
                "my_accuracy_pct",
                "plan_accuracy_pct",
                "note",
            ]
        )
        for r in records:
            writer.writerow(
                [
                    r["date"],
                    f"{r['weather']:.3f}",
                    f"{r['yesterday']:.3f}",
                    f"{r['real']:.3f}",
                    f"{r['plan']:.3f}",
                    "" if r["my_acc"] is None else f"{r['my_acc']:.2f}",
                    "" if r["plan_acc"] is None else f"{r['plan_acc']:.2f}",
                    r["note"],
                ]
            )

    after = {
        path.name: md5(path)
        for path in RESULTS.glob("*")
        if path.is_file() and path.name != OUT.name
    }
    table_after = md5(TABLE)

    def fmt(value):
        return "" if value is None else f"{value:.2f}"

    print("date,my_forecast_weather_kwh,yesterday_kwh,real_kwh,plan_kwh,my_accuracy_pct,plan_accuracy_pct,note")
    for r in records:
        print(
            f"{r['date']},{r['weather']:.3f},{r['yesterday']:.3f},{r['real']:.3f},"
            f"{r['plan']:.3f},{fmt(r['my_acc'])},{fmt(r['plan_acc'])},{r['note']}"
        )
    print(
        f"clean days {len(clean)}; avg real {avg_real:.3f}; "
        f"weather {weather_miss:.3f} kWh ({100*weather_miss/avg_real:.2f}%), mean per-day {weather_acc:.2f}%; "
        f"yesterday {yesterday_miss:.3f} ({100*yesterday_miss/avg_real:.2f}%), mean {yesterday_acc:.2f}%; "
        f"plan {plan_miss:.3f} ({100*plan_miss/avg_real:.2f}%), mean {plan_acc:.2f}%"
    )
    print(
        "data note: 2026-06-03 daily report missing; the monthly plan-fact value is used for that day."
    )

    checks = [
        ("31 July rows", len(records) == 31 and [r["date"] for r in records] == JULY, len(records)),
        ("25 clean days + 6 notes", len(clean) == 25 and len(records) - len(clean) == 6, f"{len(clean)} / {len(records)-len(clean)}"),
        ("note days 7-9 outage, 10-12 plan_zero", [r["date"][8:] + ":" + r["note"] for r in records if r["note"]] == ["07:outage", "08:outage", "09:outage", "10:plan_zero", "11:plan_zero", "12:plan_zero"], [r["date"][8:] for r in records if r["note"]]),
        ("30 clean June days used for fit", len(june_clean) == 30, len(june_clean)),
        ("25 saved July model A values match", max_saved <= 0.001, f"max diff {max_saved:.6f}"),
        ("yesterday = calendar previous day real", max_yesterday <= 1e-9, f"max diff {max_yesterday:.9f}"),
        ("clean real average 4768.400", abs(avg_real - 4768.400) <= 0.001, f"{avg_real:.3f}"),
        ("weather miss 974.721 (20.44%), mean per-day 78.37%", abs(weather_miss - 974.721) <= 0.01 and abs(100*weather_miss/avg_real - 20.44) <= 0.01 and abs(weather_acc - 78.37) <= 0.02, f"{weather_miss:.3f} / {100*weather_miss/avg_real:.2f}% / {weather_acc:.2f}%"),
        ("yesterday miss 622.280 (13.05%), mean per-day 87.97%", abs(yesterday_miss - 622.280) <= 0.01 and abs(100*yesterday_miss/avg_real - 13.05) <= 0.01 and abs(yesterday_acc - 87.97) <= 0.02, f"{yesterday_miss:.3f} / {100*yesterday_miss/avg_real:.2f}% / {yesterday_acc:.2f}%"),
        ("plan miss 879.280 (18.44%), mean per-day 82.38%", abs(plan_miss - 879.280) <= 0.01 and abs(100*plan_miss/avg_real - 18.44) <= 0.01 and abs(plan_acc - 82.38) <= 0.02, f"{plan_miss:.3f} / {100*plan_miss/avg_real:.2f}% / {plan_acc:.2f}%"),
        ("note days have no accuracy", all(r["my_acc"] is None and r["plan_acc"] is None for r in records if r["note"]), "blank"),
        ("June upload: 29/30 reports (3 Jun missing), 30 plans", len(june_reports) == 29 and len(june_plans) == 30 and not june_errors, f"{len(june_reports)} / {len(june_plans)}; max real {june_real:.3f}, plan {june_plan:.3f}"),
        ("July upload 31 reports + 31 plans", len(july_reports) == 31 and len(july_plans) == 31 and not july_errors, f"{len(july_reports)} / {len(july_plans)}; max real {july_real:.3f}, plan {july_plan:.3f}"),
        ("uploaded totals match table (real <=1.5, plan <=0.01)", june_real <= 1.5 and june_plan <= 0.01 and july_real <= 1.5 and july_plan <= 0.01, f"real {max(june_real, july_real):.3f}, plan {max(june_plan, july_plan):.3f}"),
        ("new CSV has 31 rows", len(read_csv(OUT)) == 31, len(read_csv(OUT))),
        ("data/table.csv unchanged", table_before == table_after, table_after[:12]),
        ("other results/ files unchanged", before == after, f"{len(before)} files"),
        ("only new results file", OUT.exists() and OUT.stat().st_size > 0, str(OUT.relative_to(ROOT))),
    ]
    print(f"wrote {OUT.relative_to(ROOT)}")
    failed = []
    for name, ok, value in checks:
        print(f"  {'OK' if ok else 'WRONG'}  {name}  -> {value}")
        if not ok:
            failed.append(name)
    if failed:
        raise SystemExit(f"checks failed: {failed}")


if __name__ == "__main__":
    main()
