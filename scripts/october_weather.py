import csv
import json
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "october_weather.csv"
CACHE = RAW / "weather_daily_2026-10-01_2026-10-27.json"
LAT = 42.866
LON = 68.376
TIMEZONE = "Asia/Almaty"
START_DATE = "2026-10-01"
END_DATE = "2026-10-27"
VARS = ("shortwave_radiation_sum", "cloud_cover_mean", "temperature_2m_max")
URL = (
    "https://historical-forecast-api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}"
    f"&daily={','.join(VARS)}"
    f"&start_date={START_DATE}&end_date={END_DATE}"
    f"&timezone={TIMEZONE.replace('/', '%2F')}"
)


def fetch():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8")), "cache"
    RAW.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(URL, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise SystemExit(f"Open-Meteo request failed: {error}") from error
    if "error" in payload:
        raise SystemExit(f"Open-Meteo error: {payload.get('reason')}")
    CACHE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload, "fresh"


def main():
    payload, source = fetch()
    daily = payload.get("daily") or {}
    first = date.fromisoformat(START_DATE)
    last = date.fromisoformat(END_DATE)
    days = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    checks = [
        ("source", True, source),
        ("27 dates 1-27 Oct", daily.get("time") == days, len(daily.get("time") or [])),
        ("utc_offset_seconds 18000", payload.get("utc_offset_seconds") == 18000, payload.get("utc_offset_seconds")),
        ("timezone Asia/Almaty", payload.get("timezone") == TIMEZONE, payload.get("timezone")),
        ("grid point 42.8471 / 68.4", (round(payload.get("latitude", 0), 4), round(payload.get("longitude", 0), 4)) == (42.8471, 68.4), f"{payload.get('latitude')} / {payload.get('longitude')}"),
        ("no missing values", all(all(v is not None for v in daily.get(k, [])) for k in VARS), "ok"),
    ]

    rows = []
    for i, day in enumerate(days):
        rows.append((day, *(float(daily[k][i]) for k in VARS)))

    sun = [r[1] for r in rows]
    checks.append(("27 rows", len(rows) == 27, len(rows)))
    checks.append(("sun within 0-35 MJ/m2", min(sun) >= 0 and max(sun) <= 35, f"{min(sun):.2f}..{max(sun):.2f}"))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", *VARS])
        for day, s, c, t in rows:
            writer.writerow([day, f"{s:.2f}", f"{c:.2f}", f"{t:.2f}"])

    with OUT.open(newline="", encoding="utf-8") as f:
        got = list(csv.DictReader(f))
    checks.append(("CSV rows", len(got) == 27, len(got)))
    checks.append(
        (
            "CSV values match response",
            all(
                abs(float(g[k]) - r[i + 1]) <= 0.005
                for g, r in zip(got, rows)
                for i, k in enumerate(VARS)
            ),
            f"{len(got)}/27",
        )
    )

    for name, ok, value in checks:
        print(f"{'OK ' if ok else 'FAIL'} {name}: {value}")
    if not all(ok for _, ok, _ in checks):
        raise SystemExit("checks failed")

    print("\nURL:", URL)
    print("\ndate,sun_mj,cloud_pct,tmax_c")
    for day in ("2026-10-01", "2026-10-04", "2026-10-27"):
        r = next(x for x in rows if x[0] == day)
        print(f"{r[0]},{r[1]:.2f},{r[2]:.2f},{r[3]:.2f}")


if __name__ == "__main__":
    main()
