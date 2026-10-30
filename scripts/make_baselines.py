import csv
import statistics
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data" / "daily.csv"
RESULTS = ROOT / "results"
SUMMARY = RESULTS / "baselines.csv"
DAYS = RESULTS / "baselines_july_days.csv"

FORECASTS = ("plan", "yesterday", "median7")


def read_daily():
    with DAILY.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 122:
        raise SystemExit(f"{DAILY.name}: {len(rows)} rows, expected 122")
    by_date = {}
    for row in rows:
        by_date[row["date"]] = {
            "plan_kwh": float(row["plan_kwh"]),
            "real_kwh": float(row["real_kwh"]),
            "note": row["note"],
        }
    return by_date


def mean(values):
    return sum(values) / len(values)


def forecast(by_date, day, kind):
    if kind == "plan":
        return by_date[day]["plan_kwh"]
    if kind == "yesterday":
        prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
        return by_date[prev]["real_kwh"]
    if kind == "median7":
        start = date.fromisoformat(day)
        window = [
            by_date[(start - timedelta(days=k)).isoformat()]["real_kwh"]
            for k in range(1, 8)
        ]
        return statistics.median(window)
    raise ValueError(kind)


def miss(rows, kind):
    errors = [abs(forecast(rows["by_date"], day, kind) - rows["by_date"][day]["real_kwh"]) for day in rows["days"]]
    avg_real = mean([rows["by_date"][day]["real_kwh"] for day in rows["days"]])
    value = mean(errors)
    return value, 100.0 * value / avg_real, avg_real


def build():
    by_date = read_daily()
    july = sorted(day for day in by_date if day.startswith("2026-07"))
    if len(july) != 31:
        raise SystemExit(f"{len(july)} July days, expected 31")
    clean = [day for day in july if by_date[day]["note"] == ""]

    day_rows = []
    for day in july:
        row = {
            "date": day,
            "note": by_date[day]["note"],
            "real_kwh": by_date[day]["real_kwh"],
        }
        for kind in FORECASTS:
            value = forecast(by_date, day, kind)
            row[f"{kind}_kwh"] = value
            row[f"{kind}_miss_kwh"] = abs(value - by_date[day]["real_kwh"])
        day_rows.append(row)

    RESULTS.mkdir(parents=True, exist_ok=True)
    with DAYS.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "date",
                "note",
                "real_kwh",
                "plan_kwh",
                "yesterday_kwh",
                "median7_kwh",
                "plan_miss_kwh",
                "yesterday_miss_kwh",
                "median7_miss_kwh",
            ]
        )
        for row in day_rows:
            writer.writerow(
                [
                    row["date"],
                    row["note"],
                    f"{row['real_kwh']:.3f}",
                    f"{row['plan_kwh']:.3f}",
                    f"{row['yesterday_kwh']:.3f}",
                    f"{row['median7_kwh']:.3f}",
                    f"{row['plan_miss_kwh']:.3f}",
                    f"{row['yesterday_miss_kwh']:.3f}",
                    f"{row['median7_miss_kwh']:.3f}",
                ]
            )

    scopes = {
        "all31": {"days": july, "by_date": by_date},
        "clean25": {"days": clean, "by_date": by_date},
    }
    table = []
    for kind in FORECASTS:
        values = {name: miss(scope, kind) for name, scope in scopes.items()}
        table.append({"forecast": kind, **{name: values[name] for name in scopes}})

    with SUMMARY.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "forecast",
                "all31_days",
                "all31_avg_real_kwh",
                "all31_miss_kwh",
                "all31_miss_pct",
                "clean25_days",
                "clean25_avg_real_kwh",
                "clean25_miss_kwh",
                "clean25_miss_pct",
            ]
        )
        for row in table:
            a, c = row["all31"], row["clean25"]
            writer.writerow(
                [
                    row["forecast"],
                    len(scopes["all31"]["days"]),
                    f"{a[2]:.3f}",
                    f"{a[0]:.3f}",
                    f"{a[1]:.2f}",
                    len(scopes["clean25"]["days"]),
                    f"{c[2]:.3f}",
                    f"{c[0]:.3f}",
                    f"{c[1]:.2f}",
                ]
            )

    expected = {
        ("all31", "plan"): (1584, 38),
        ("all31", "yesterday"): (766, 18),
        ("all31", "median7"): (1194, 28),
        ("clean25", "plan"): (879, 18),
        ("clean25", "yesterday"): (622, 13),
        ("clean25", "median7"): (724, 15),
    }
    checks = []
    for (scope, kind), (want_kwh, want_pct) in expected.items():
        kwh, pct, _ = miss(scopes[scope], kind)
        checks.append(
            (
                f"{scope} {kind} = {want_kwh} kWh ({want_pct}%)",
                round(kwh) == want_kwh and round(pct) == want_pct,
                f"{kwh:.3f} kWh ({pct:.2f}%)",
            )
        )

    first = day_rows[0]
    june_window = [
        by_date[(date(2026, 7, 1) - timedelta(days=k)).isoformat()]["real_kwh"]
        for k in range(1, 8)
    ]
    checks.extend(
        [
            ("31 July days", len(july) == 31, len(july)),
            ("25 July days without a note", len(clean) == 25, len(clean)),
            (
                "1 July median7 = median of 24-30 June",
                first["median7_kwh"] == statistics.median(june_window),
                f"{first['median7_kwh']:.3f}",
            ),
            (
                "1 July yesterday = 30 June real",
                first["yesterday_kwh"] == by_date["2026-06-30"]["real_kwh"],
                f"{first['yesterday_kwh']:.3f}",
            ),
            (
                "every July day has all 3 forecasts",
                all(
                    all(row[f"{kind}_kwh"] is not None for kind in FORECASTS)
                    for row in day_rows
                ),
                len(day_rows) * len(FORECASTS),
            ),
            (
                "baselines.csv has 3 forecast rows",
                len(table) == 3,
                len(table),
            ),
        ]
    )

    print(f"wrote {DAYS.relative_to(ROOT)}: {len(day_rows)} rows")
    print("3 July days:")
    for row in day_rows[:3]:
        print(
            f"  {row['date']},{row['note'] or '-'},{row['real_kwh']:.0f},"
            f"plan {row['plan_kwh']:.0f},yesterday {row['yesterday_kwh']:.0f},"
            f"median7 {row['median7_kwh']:.0f}"
        )
    print(f"wrote {SUMMARY.relative_to(ROOT)}: {len(table)} rows")
    for name, ok, value in checks:
        print(f"  {'OK' if ok else 'WRONG'}  {name}  -> {value}")
    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        raise SystemExit(f"checks failed: {failed}")


if __name__ == "__main__":
    build()
