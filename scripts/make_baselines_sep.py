import csv
import statistics
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data" / "daily.csv"
RESULTS = ROOT / "results"
SUMMARY = RESULTS / "baselines_sep.csv"
DAYS = RESULTS / "baselines_sep_days.csv"
MAIN = RESULTS / "baselines.csv"

FORECASTS = ("plan", "yesterday", "median7")


def read_daily():
    with DAILY.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 122:
        raise SystemExit(f"{DAILY.name}: {len(rows)} rows, expected 122")
    return {
        row["date"]: {
            "plan_kwh": float(row["plan_kwh"]),
            "real_kwh": float(row["real_kwh"]),
            "note": row["note"],
        }
        for row in rows
    }


def forecast(rows, day, kind):
    if kind == "plan":
        return rows[day]["plan_kwh"]
    if kind == "yesterday":
        prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
        return rows[prev]["real_kwh"]
    if kind == "median7":
        start = date.fromisoformat(day)
        window = [rows[(start - timedelta(days=k)).isoformat()]["real_kwh"] for k in range(1, 8)]
        return statistics.median(window)
    raise ValueError(kind)


def build():
    rows = read_daily()
    september = sorted(day for day in rows if day.startswith("2026-09"))
    if len(september) != 30:
        raise SystemExit(f"{len(september)} September days, expected 30")
    clean = [day for day in september if rows[day]["note"] == ""]

    day_rows = []
    for day in september:
        row = {"date": day, "note": rows[day]["note"], "real_kwh": rows[day]["real_kwh"]}
        for kind in FORECASTS:
            value = forecast(rows, day, kind)
            row[f"{kind}_kwh"] = value
            row[f"{kind}_miss_kwh"] = abs(value - rows[day]["real_kwh"])
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
                [row["date"], row["note"]]
                + [
                    f"{row[key]:.3f}"
                    for key in (
                        "real_kwh",
                        "plan_kwh",
                        "yesterday_kwh",
                        "median7_kwh",
                        "plan_miss_kwh",
                        "yesterday_miss_kwh",
                        "median7_miss_kwh",
                    )
                ]
            )

    avg_real = sum(rows[day]["real_kwh"] for day in clean) / len(clean)
    table = []
    for kind in FORECASTS:
        value = sum(abs(forecast(rows, day, kind) - rows[day]["real_kwh"]) for day in clean) / len(clean)
        table.append((kind, len(clean), avg_real, value, 100.0 * value / avg_real))

    with SUMMARY.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["forecast", "days", "avg_real_kwh", "miss_kwh", "miss_pct"])
        for kind, days, avg, value, pct in table:
            writer.writerow([kind, days, f"{avg:.3f}", f"{value:.3f}", f"{pct:.2f}"])

    with MAIN.open(newline="", encoding="utf-8") as f:
        main_rows = list(csv.DictReader(f))

    first = day_rows[0]
    july_clean = [d for d in rows if d.startswith("2026-07") and rows[d]["note"] == ""]
    checks = [
        ("30 September days", len(september) == 30, len(september)),
        ("30 September days without a note", len(clean) == 30, len(clean)),
        (
            "1 Sep yesterday = 31 Aug real",
            first["yesterday_kwh"] == rows["2026-08-31"]["real_kwh"],
            f"{first['yesterday_kwh']:.3f}",
        ),
        (
            "1 Sep median7 = median(25-31 Aug)",
            first["median7_kwh"]
            == statistics.median(
                rows[(date(2026, 9, 1) - timedelta(days=k)).isoformat()]["real_kwh"]
                for k in range(1, 8)
            ),
            f"{first['median7_kwh']:.3f}",
        ),
        (
            "baselines_sep.csv has 3 rows",
            len(table) == 3,
            [row[0] for row in table],
        ),
        (
            "baselines_sep_days.csv has 30 rows",
            len(day_rows) == 30,
            len(day_rows),
        ),
        (
            "results/baselines.csv unchanged (4 rows, my model kept)",
            len(main_rows) == 4
            and [r["forecast"] for r in main_rows] == ["plan", "yesterday", "median7", "my model"],
            [r["forecast"] for r in main_rows],
        ),
        (
            "25 clean July days still available for reference",
            len(july_clean) == 25,
            len(july_clean),
        ),
    ]

    print(f"wrote {DAYS.relative_to(ROOT)}: {len(day_rows)} rows")
    print(f"wrote {SUMMARY.relative_to(ROOT)}: {len(table)} rows")
    print("3 September days:")
    for row in day_rows[:3]:
        print(
            f"  {row['date']}  real {row['real_kwh']:.0f}  plan {row['plan_kwh']:.0f}  "
            f"yesterday {row['yesterday_kwh']:.0f}  median7 {row['median7_kwh']:.0f}"
        )
    for kind, days, _, value, pct in table:
        print(f"  {kind}: {value:.3f} kWh ({pct:.2f}%) on {days} days")
    for name, ok, value in checks:
        print(f"  {'OK' if ok else 'WRONG'}  {name}  -> {value}")
    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        raise SystemExit(f"checks failed: {failed}")


if __name__ == "__main__":
    build()
