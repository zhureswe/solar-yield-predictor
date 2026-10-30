import csv
import hashlib
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import model as m

TABLE = ROOT / "data" / "table.csv"
OUT = ROOT / "results" / "august_daily_table.csv"
RESULTS = ROOT / "results"
AUGUST = [f"2026-08-{day:02d}" for day in range(1, 32)]


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def accuracy(forecast, real):
    return 100.0 - abs(forecast - real) / real * 100.0


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


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
    if not set(AUGUST) <= set(rows):
        raise SystemExit("table.csv is missing August days")

    july_clean = [
        d for d in sorted(rows) if d.startswith("2026-07") and rows[d]["note"] == ""
    ]
    coef = m.fit(
        [m.features_a(rows, d) for d in july_clean],
        [rows[d]["real_kwh"] for d in july_clean],
    )
    forecast = {d: m.predict_a(rows, coef, d) for d in AUGUST}

    records = []
    for d in AUGUST:
        real = rows[d]["real_kwh"]
        plan = rows[d]["plan_kwh"]
        note = rows[d]["note"]
        clean = note == "" and real > 0
        records.append(
            {
                "date": d,
                "forecast": forecast[d],
                "real": real,
                "plan": plan,
                "my_acc": accuracy(forecast[d], real) if clean else None,
                "plan_acc": accuracy(plan, real) if clean else None,
                "note": note,
            }
        )

    clean = [r for r in records if r["my_acc"] is not None]
    avg_real = sum(r["real"] for r in clean) / len(clean)
    model_miss = sum(abs(r["forecast"] - r["real"]) for r in clean) / len(clean)
    plan_miss = sum(abs(r["plan"] - r["real"]) for r in clean) / len(clean)
    model_acc = sum(r["my_acc"] for r in clean) / len(clean)
    plan_acc = sum(r["plan_acc"] for r in clean) / len(clean)

    clean_dates = {r["date"] for r in clean}

    def last_clean(day):
        x = date.fromisoformat(day) - timedelta(days=1)
        while x.isoformat() in rows:
            row = rows[x.isoformat()]
            if row["note"] == "" and row["real_kwh"] > 0:
                return row["real_kwh"]
            x -= timedelta(days=1)
        raise SystemExit(f"no clean day before {day}")

    last_miss = sum(
        abs(last_clean(d) - rows[d]["real_kwh"]) for d in clean_dates
    ) / len(clean_dates)
    last_acc = sum(
        accuracy(last_clean(d), rows[d]["real_kwh"]) for d in clean_dates
    ) / len(clean_dates)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "date",
                "my_forecast_weather_kwh",
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
                    f"{r['forecast']:.3f}",
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

    print("date,my_forecast_weather_kwh,real_kwh,plan_kwh,my_accuracy_pct,plan_accuracy_pct,note")
    for r in records:
        print(
            f"{r['date']},{r['forecast']:.3f},{r['real']:.3f},{r['plan']:.3f},"
            f"{fmt(r['my_acc'])},{fmt(r['plan_acc'])},{r['note']}"
        )
    print(
        f"clean days {len(clean)}; avg real {avg_real:.3f}; "
        f"model {model_miss:.3f} kWh ({100*model_miss/avg_real:.2f}%), mean per-day {model_acc:.2f}%; "
        f"plan {plan_miss:.3f} ({100*plan_miss/avg_real:.2f}%), mean {plan_acc:.2f}%; "
        f"yesterday last clean {last_miss:.3f} ({100*last_miss/avg_real:.2f}%), mean {last_acc:.2f}%"
    )
    print(
        "note: August was already seen in Steps 5c/5d; this is a check, not the honest test. "
        "The final choice and the page stay yesterday (September 512.600 kWh, 6.78%)."
    )

    checks = [
        ("31 August rows", len(records) == 31 and [r["date"] for r in records] == AUGUST, len(records)),
        ("26 clean days + 5 notes", len(clean) == 26 and len(records) - len(clean) == 5, f"{len(clean)} / {len(records)-len(clean)}"),
        ("note days 13,14,17 outage; 18,20 plan_zero", [r["date"][8:] + ":" + r["note"] for r in records if r["note"]] == ["13:outage", "14:outage", "17:outage", "18:plan_zero", "20:plan_zero"], [r["date"][8:] for r in records if r["note"]]),
        ("25 clean July days used for fit", len(july_clean) == 25, len(july_clean)),
        ("model miss 1174.021 (22.25%), mean per-day 78.66%", abs(model_miss - 1174.021) <= 0.01 and abs(100*model_miss/avg_real - 22.25) <= 0.01 and abs(model_acc - 78.66) <= 0.02, f"{model_miss:.3f} / {100*model_miss/avg_real:.2f}% / {model_acc:.2f}%"),
        ("plan miss 1883.462 (35.70%), mean per-day 60.58%", abs(plan_miss - 1883.462) <= 0.01 and abs(100*plan_miss/avg_real - 35.70) <= 0.01 and abs(plan_acc - 60.58) <= 0.02, f"{plan_miss:.3f} / {100*plan_miss/avg_real:.2f}% / {plan_acc:.2f}%"),
        ("yesterday (last clean) miss 1250.923 (23.71%), mean 76.35%", abs(last_miss - 1250.923) <= 0.01 and abs(100*last_miss/avg_real - 23.71) <= 0.01 and abs(last_acc - 76.35) <= 0.02, f"{last_miss:.3f} / {100*last_miss/avg_real:.2f}% / {last_acc:.2f}%"),
        ("note days have no accuracy", all(r["my_acc"] is None and r["plan_acc"] is None for r in records if r["note"]), "blank"),
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
