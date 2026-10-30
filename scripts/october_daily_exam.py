import csv
import hashlib
import statistics
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"
TABLE = DATA / "table.csv"
DAILY = DATA / "daily.csv"
OCT_DAILY = DATA / "october_daily.csv"
OCT_WEATHER = DATA / "october_weather.csv"
CLOUD_RULE = RESULTS / "cloud_rule.csv"
OUT = RESULTS / "october_days.csv"
THRESHOLD = 30
FIELDS = [
    "date",
    "my_forecast_kwh",
    "real_kwh",
    "plan_kwh",
    "my_accuracy_pct",
    "plan_accuracy_pct",
    "note",
]


def read_october():
    with OCT_DAILY.open(newline="", encoding="utf-8") as f:
        daily = {r["date"]: r for r in csv.DictReader(f)}
    if len(daily) != 27:
        raise SystemExit(f"october_daily.csv: {len(daily)} rows")
    with OCT_WEATHER.open(newline="", encoding="utf-8") as f:
        weather = {r["date"]: r for r in csv.DictReader(f)}
    if set(daily) != set(weather):
        raise SystemExit("October daily and weather dates differ")
    return daily, weather


def read_history():
    with TABLE.open(newline="", encoding="utf-8") as f:
        table = {r["date"]: r for r in csv.DictReader(f)}
    with DAILY.open(newline="", encoding="utf-8") as f:
        daily = {r["date"]: r for r in csv.DictReader(f)}
    if len(table) != 122 or len(daily) != 122:
        raise SystemExit("history files must have 122 rows")
    return table, daily


def md5_others():
    return {
        p.name: hashlib.md5(p.read_bytes()).hexdigest()
        for p in sorted(RESULTS.iterdir())
        if p.is_file() and p.name != OUT.name
    }


def acc(forecast, real):
    return 100.0 - abs(forecast - real) / real * 100.0


def main():
    daily, weather = read_october()
    table, history = read_history()
    before = md5_others()

    with CLOUD_RULE.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    chosen = [r for r in rows if r["scope"] == "jul_aug" and r["chosen"] == "yes"]
    if len(chosen) != 1 or int(chosen[0]["threshold_pct"]) != THRESHOLD:
        raise SystemExit(f"cloud_rule.csv: chosen T is {[r['threshold_pct'] for r in chosen]}")

    values = {}
    for day in sorted(daily):
        values[day] = {
            "real": float(daily[day]["real_kwh"]),
            "plan": float(daily[day]["plan_kwh"]),
            "note": daily[day]["note"],
            "sun": float(weather[day]["shortwave_radiation_sum"]),
        }
    for day, row in table.items():
        values[day] = {
            "real": float(row["real_kwh"]),
            "plan": float(row["plan_kwh"]),
            "note": row["note"],
            "sun": float(row["shortwave_radiation_sum"]),
        }

    def prev_clean(day):
        x = date.fromisoformat(day) - timedelta(days=1)
        while True:
            key = x.isoformat()
            if key not in values:
                raise SystemExit(f"no history for {key}")
            if values[key]["note"] == "":
                return key
            x -= timedelta(days=1)

    def median7(day):
        base = date.fromisoformat(day)
        window = [
            values[(base - timedelta(days=i)).isoformat()]["real"] for i in range(1, 8)
        ]
        return statistics.median(window)

    days = sorted(daily)
    clean = [d for d in days if values[d]["note"] == ""]
    forecast, cloud, switches = {}, {}, []
    for day in days:
        prev = prev_clean(day)
        base = values[prev]["real"]
        forecast[day] = base
        ratio = values[day]["sun"] / values[prev]["sun"]
        if ratio < 1.0 - THRESHOLD / 100.0:
            cloud[day] = base * ratio
            switches.append((day, round(ratio, 4)))
        else:
            cloud[day] = base

    def score(cells):
        errors = [abs(cells[d] - values[d]["real"]) for d in clean]
        miss = sum(errors) / len(errors)
        avg = sum(values[d]["real"] for d in clean) / len(clean)
        within = sum(
            abs(cells[d] - values[d]["real"]) <= 0.10 * values[d]["real"] for d in clean
        )
        return miss, 100.0 * miss / avg, 100.0 - 100.0 * miss / avg, within

    med = {d: median7(d) for d in days}
    plan = {d: values[d]["plan"] for d in days}
    results = [
        ("Yesterday", *score(forecast)),
        (f"Cloud rule T={THRESHOLD}%", *score(cloud)),
        ("7-day median", *score(med)),
        ("Plant plan", *score(plan)),
    ]

    out_rows = []
    for day in days:
        row = values[day]
        note = row["note"]
        is_clean = note == "" and row["real"] > 0
        out_rows.append(
            {
                "date": day,
                "my_forecast_kwh": f"{forecast[day]:.3f}",
                "real_kwh": f"{row['real']:.3f}",
                "plan_kwh": f"{row['plan']:.3f}",
                "my_accuracy_pct": f"{acc(forecast[day], row['real']):.2f}" if is_clean else "—",
                "plan_accuracy_pct": f"{acc(row['plan'], row['real']):.2f}" if is_clean else "—",
                "note": note,
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)

    with OUT.open(newline="", encoding="utf-8") as f:
        written = list(csv.DictReader(f))

    checks = [
        ("27 rows", len(written) == 27, len(written)),
        ("26 clean days, 1 note day", len(clean) == 26 and len(days) - len(clean) == 1, f"{len(clean)} clean"),
        ("forecast filled on every day", all(r["my_forecast_kwh"] != "" for r in written), "27/27"),
        ("5 Oct = 3 Oct real (skips 4 Oct outage)", forecast["2026-10-05"] == values["2026-10-03"]["real"], f"{forecast['2026-10-05']:.3f}"),
        ("1 Oct median = median(24-30 Sep)", abs(med["2026-10-01"] - statistics.median([values[(date(2026, 10, 1) - timedelta(days=i)).isoformat()]["real"] for i in range(1, 8)])) < 1e-9, f"{med['2026-10-01']:.3f}"),
        ("accuracy is '—' on the note day", all(r["my_accuracy_pct"] == "—" and r["plan_accuracy_pct"] == "—" for r in written if r["note"]), "4 Oct"),
        ("accuracy filled on 26 clean days", sum(r["my_accuracy_pct"] != "—" for r in written) == 26, 26),
        ("cloud switch days listed", len(switches) == sum(cloud[d] != forecast[d] for d in days), len(switches)),
        ("CSV 7 columns", set(written[0]) == set(FIELDS), len(written[0])),
    ]
    after = md5_others()
    checks.append(("no other results file changed", before == after, [n for n in before if before[n] != after.get(n)]))

    for name, ok, value in checks:
        print(f"{'OK ' if ok else 'FAIL'} {name}: {value}")
    if not all(ok for _, ok, _ in checks):
        raise SystemExit("checks failed")

    avg = sum(values[d]["real"] for d in clean) / len(clean)
    print(f"\nOctober clean days: {len(clean)} of {len(days)} (avg real {avg:.3f} kWh)")
    print(f"{'Forecast':<20}{'miss kWh':>10}{'miss %':>9}{'acc. %':>9}{'within 10%':>12}")
    for name, miss, pct, accuracy, within in results:
        print(f"{name:<20}{miss:>10.3f}{pct:>8.2f}%{accuracy:>8.2f}%{within:>8}/{len(clean)}")
    print("\ncloud switch days:", switches if switches else "none")
    print("\n" + ",".join(FIELDS))
    for day in ("2026-10-01", "2026-10-05", "2026-10-27"):
        r = next(x for x in written if x["date"] == day)
        print(",".join(str(r[k]) for k in FIELDS))


if __name__ == "__main__":
    main()
