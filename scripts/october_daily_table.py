import csv
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import model as m
from make_daily import note_for
from make_hourly import file_date, read_plan, read_report

SYP = ROOT / "SYP"
TABLE = ROOT / "data" / "table.csv"
WEATHER = ROOT / "data" / "raw" / "weather_daily_2026-10-01_2026-10-27.json"
OUT = ROOT / "results" / "october_daily_table.csv"
RESULTS = ROOT / "results"
LAT = 42.866
LON = 68.376
TIMEZONE = "Asia/Almaty"
START_DATE = "2026-10-01"
END_DATE = "2026-10-27"
DAYS = 27
VARS = ("shortwave_radiation_sum", "cloud_cover_mean", "temperature_2m_max")
URL = (
    "https://historical-forecast-api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}"
    f"&daily={','.join(VARS)}"
    f"&start_date={START_DATE}&end_date={END_DATE}"
    f"&timezone={TIMEZONE.replace('/', '%2F')}"
)
OCTOBER = [f"2026-10-{day:02d}" for day in range(1, 28)]


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def accuracy(forecast, real):
    return 100.0 - abs(forecast - real) / real * 100.0


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch_weather():
    if WEATHER.exists():
        return json.loads(WEATHER.read_text(encoding="utf-8"))
    WEATHER.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(URL, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise SystemExit(f"Open-Meteo request failed: {error}") from error
    if "error" in payload:
        raise SystemExit(f"Open-Meteo error: {payload.get('reason')}")
    WEATHER.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def main():
    before = {
        path.name: md5(path)
        for path in RESULTS.glob("*")
        if path.is_file() and path.name != OUT.name
    }
    table_before = md5(TABLE)

    reports = {
        file_date(p): p
        for p in SYP.glob("*10.26.xlsx")
        if "отчет" in p.name.lower()
    }
    plans = {
        file_date(p): p
        for p in SYP.glob("*10.26.xlsx")
        if "план" in p.name.lower()
    }
    if len(reports) != 27 or len(plans) != 31:
        raise SystemExit(f"files: {len(reports)} reports, {len(plans)} plans")
    if set(reports) != {date.fromisoformat(d) for d in OCTOBER}:
        raise SystemExit("report dates are not 1-27 October")
    if not set(reports) <= set(plans):
        raise SystemExit("a report day has no plan file")

    payload = fetch_weather()
    if payload.get("timezone") != TIMEZONE or payload.get("utc_offset_seconds") != 18000:
        raise SystemExit("weather timezone is not Asia/Almaty")
    daily = payload.get("daily") or {}
    if daily.get("time") != OCTOBER:
        raise SystemExit(f"weather dates: {daily.get('time')}")
    for key in VARS:
        if any(value is None for value in daily[key]):
            raise SystemExit(f"missing {key} values")
    weather = {
        day: {key: daily[key][i] for key in VARS}
        for i, day in enumerate(daily["time"])
    }

    rows = m.read_table()
    if len(rows) != 122:
        raise SystemExit(f"table.csv: {len(rows)} rows")
    sep_clean = [
        d for d in sorted(rows) if d.startswith("2026-09") and rows[d]["note"] == ""
    ]
    coef = m.fit(
        [m.features_a(rows, d) for d in sep_clean],
        [rows[d]["real_kwh"] for d in sep_clean],
    )

    october = {}
    for day in OCTOBER:
        report_date, hours, start_hour, total = read_report(reports[date.fromisoformat(day)])
        if report_date.isoformat() != day:
            raise SystemExit(f"{day}: report date {report_date}")
        if len(hours) != 24 or start_hour != 4:
            raise SystemExit(f"{day}: bad report hours")
        if abs(sum(hours) - total) > 1e-6:
            raise SystemExit(f"{day}: report sum != total")
        plan, plan_total = read_plan(plans[date.fromisoformat(day)])
        if abs(sum(plan.values()) - plan_total) > 1e-6:
            raise SystemExit(f"{day}: plan sum != total")
        october[day] = {
            "date": day,
            "plan_kwh": plan_total,
            "real_kwh": total,
            "note": note_for(plan_total, total),
            **weather[day],
        }
        october[day]["forecast"] = m.predict_a(october, coef, day)

    records = []
    for day in OCTOBER:
        row = october[day]
        clean = row["note"] == "" and row["real_kwh"] > 0
        records.append(
            {
                "date": day,
                "forecast": row["forecast"],
                "real": row["real_kwh"],
                "plan": row["plan_kwh"],
                "my_acc": accuracy(row["forecast"], row["real_kwh"]) if clean else None,
                "plan_acc": accuracy(row["plan_kwh"], row["real_kwh"]) if clean else None,
                "note": row["note"],
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

    def last_clean(day):
        x = date.fromisoformat(day) - timedelta(days=1)
        while True:
            key = x.isoformat()
            if key in october:
                row = october[key]
                if row["note"] == "" and row["real_kwh"] > 0:
                    return row["real_kwh"]
            elif key in rows:
                row = rows[key]
                if row["note"] == "" and row["real_kwh"] > 0:
                    return row["real_kwh"]
            else:
                raise SystemExit(f"no row for {key}")
            x -= timedelta(days=1)

    last_miss = sum(
        abs(last_clean(r["date"]) - r["real"]) for r in clean
    ) / len(clean)
    last_acc = sum(
        accuracy(last_clean(r["date"]), r["real"]) for r in clean
    ) / len(clean)
    last_within = sum(
        abs(last_clean(r["date"]) - r["real"]) <= 0.1 * r["real"] for r in clean
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
        f"clean days {len(clean)}; avg real {avg_real:.3f}; total {total_real:.3f}; "
        f"model {model_miss:.3f} kWh ({100*model_miss/avg_real:.2f}%), mean per-day {model_acc:.2f}%, "
        f"within 10% {model_within}/{len(clean)}; "
        f"plan {plan_miss:.3f} ({100*plan_miss/avg_real:.2f}%), mean {plan_acc:.2f}%, "
        f"within 10% {plan_within}/{len(clean)}; "
        f"yesterday last clean {last_miss:.3f} ({100*last_miss/avg_real:.2f}%), mean {last_acc:.2f}%, "
        f"within 10% {last_within}/{len(clean)}"
    )
    print(
        "note: this is the first unseen month. The September-fit model is better than yesterday "
        "and the plan here, which contradicts the older rule 'no learned model is better'. "
        "The page has NOT been changed."
    )

    checks = [
        ("27 October report files", len(reports) == 27, len(reports)),
        ("31 October plan files", len(plans) == 31, len(plans)),
        ("report dates are 1-27 October", set(reports) == {date.fromisoformat(d) for d in OCTOBER}, "1-27"),
        ("27 rows", len(records) == 27 and [r["date"] for r in records] == OCTOBER, len(records)),
        ("26 clean days + 1 note", len(clean) == 26 and records[3]["note"] == "outage", f"{len(clean)} / {records[3]['note']}"),
        ("4 Oct is the only note day", [r["date"][8:] for r in records if r["note"]] == ["04"], [r["date"][8:] for r in records if r["note"]]),
        ("30 clean September days used for fit", len(sep_clean) == 30, len(sep_clean)),
        ("weather 27 days, no empty values", daily.get("time") == OCTOBER and all(not any(v is None for v in daily[k]) for k in VARS), len(daily.get("time", []))),
        ("clean real average 6615.555, total 172004.428", abs(avg_real - 6615.555) <= 0.001 and abs(total_real - 172004.428) <= 0.01, f"{avg_real:.3f} / {total_real:.3f}"),
        ("model miss 650.815 (9.84%), mean 81.30%, 20/26 within 10%", abs(model_miss - 650.815) <= 0.01 and abs(100*model_miss/avg_real - 9.84) <= 0.01 and abs(model_acc - 81.30) <= 0.02 and model_within == 20, f"{model_miss:.3f} / {100*model_miss/avg_real:.2f}% / {model_acc:.2f}% / {model_within}"),
        ("yesterday 1109.877 (16.78%), mean 75.14%, 15/26 within 10%", abs(last_miss - 1109.877) <= 0.01 and abs(100*last_miss/avg_real - 16.78) <= 0.01 and abs(last_acc - 75.14) <= 0.02 and last_within == 15, f"{last_miss:.3f} / {100*last_miss/avg_real:.2f}% / {last_acc:.2f}% / {last_within}"),
        ("plan miss 1651.382 (24.96%), mean 64.32%, 10/26 within 10%", abs(plan_miss - 1651.382) <= 0.01 and abs(100*plan_miss/avg_real - 24.96) <= 0.01 and abs(plan_acc - 64.32) <= 0.02 and plan_within == 10, f"{plan_miss:.3f} / {100*plan_miss/avg_real:.2f}% / {plan_acc:.2f}% / {plan_within}"),
        ("4 Oct accuracy blank", records[3]["my_acc"] is None and records[3]["plan_acc"] is None, "blank"),
        ("new CSV has 27 rows", len(read_csv(OUT)) == 27, len(read_csv(OUT))),
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
