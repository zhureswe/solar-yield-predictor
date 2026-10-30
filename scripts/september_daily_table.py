import csv
import hashlib
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import model as m

TABLE = ROOT / "data" / "table.csv"
OUT = ROOT / "results" / "september_daily_table.csv"
RESULTS = ROOT / "results"
SEPTEMBER = [f"2026-09-{day:02d}" for day in range(1, 31)]


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
    if not set(SEPTEMBER) <= set(rows):
        raise SystemExit("table.csv is missing September days")

    aug_clean = [
        d for d in sorted(rows) if d.startswith("2026-08") and rows[d]["note"] == ""
    ]
    coef = m.fit(
        [m.features_a(rows, d) for d in aug_clean],
        [rows[d]["real_kwh"] for d in aug_clean],
    )
    forecast = {d: m.predict_a(rows, coef, d) for d in SEPTEMBER}

    records = []
    for d in SEPTEMBER:
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
    total_real = sum(r["real"] for r in clean)
    model_miss = sum(abs(r["forecast"] - r["real"]) for r in clean) / len(clean)
    plan_miss = sum(abs(r["plan"] - r["real"]) for r in clean) / len(clean)
    model_acc = sum(r["my_acc"] for r in clean) / len(clean)
    plan_acc = sum(r["plan_acc"] for r in clean) / len(clean)
    model_within = sum(abs(r["forecast"] - r["real"]) <= 0.1 * r["real"] for r in clean)
    plan_within = sum(abs(r["plan"] - r["real"]) <= 0.1 * r["real"] for r in clean)

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
    last_within = sum(
        abs(last_clean(d) - rows[d]["real_kwh"]) <= 0.1 * rows[d]["real_kwh"]
        for d in clean_dates
    )

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
        f"clean days {len(clean)}; avg real {avg_real:.3f}; total {total_real:.0f}; "
        f"model {model_miss:.3f} kWh ({100*model_miss/avg_real:.2f}%), mean per-day {model_acc:.2f}%, "
        f"within 10% {model_within}/{len(clean)}; "
        f"plan {plan_miss:.3f} ({100*plan_miss/avg_real:.2f}%), mean {plan_acc:.2f}%, "
        f"within 10% {plan_within}/{len(clean)}; "
        f"yesterday {last_miss:.3f} ({100*last_miss/avg_real:.2f}%), mean {last_acc:.2f}%, "
        f"within 10% {last_within}/{len(clean)}"
    )
    print(
        "note: September was already seen; this is a check, not the honest test. "
        "The August-fit model is much worse than yesterday and the plan; the final choice and "
        "the page stay yesterday (September 512.600 kWh, 6.78%)."
    )

    checks = [
        ("30 September rows", len(records) == 30 and [r["date"] for r in records] == SEPTEMBER, len(records)),
        ("30 clean days, no note days", len(clean) == 30 and all(r["note"] == "" for r in records), f"{len(clean)} clean / {len(records)-len(clean)} notes"),
        ("26 clean August days used for fit", len(aug_clean) == 26, len(aug_clean)),
        ("clean real average 7556.033, total 226681", abs(avg_real - 7556.033) <= 0.001 and abs(total_real - 226681) <= 0.01, f"{avg_real:.3f} / {total_real:.0f}"),
        ("model miss 1556.814 (20.60%), mean 77.01%, 13/30 within 10%", abs(model_miss - 1556.814) <= 0.01 and abs(100*model_miss/avg_real - 20.60) <= 0.01 and abs(model_acc - 77.01) <= 0.02 and model_within == 13, f"{model_miss:.3f} / {100*model_miss/avg_real:.2f}% / {model_acc:.2f}% / {model_within}"),
        ("plan miss 1015.100 (13.43%), mean 86.02%, 12/30 within 10%", abs(plan_miss - 1015.100) <= 0.01 and abs(100*plan_miss/avg_real - 13.43) <= 0.01 and abs(plan_acc - 86.02) <= 0.02 and plan_within == 12, f"{plan_miss:.3f} / {100*plan_miss/avg_real:.2f}% / {plan_acc:.2f}% / {plan_within}"),
        ("yesterday 512.600 (6.78%), mean 92.44%, 23/30 within 10%", abs(last_miss - 512.600) <= 0.01 and abs(100*last_miss/avg_real - 6.78) <= 0.01 and abs(last_acc - 92.44) <= 0.02 and last_within == 23, f"{last_miss:.3f} / {100*last_miss/avg_real:.2f}% / {last_acc:.2f}% / {last_within}"),
        ("new CSV has 30 rows", len(read_csv(OUT)) == 30, len(read_csv(OUT))),
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
