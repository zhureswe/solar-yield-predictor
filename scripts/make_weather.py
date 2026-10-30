import csv
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
DAILY = DATA / "daily.csv"
CACHE = RAW / "weather_daily_2026-06-01_2026-09-30.json"
WEATHER = DATA / "weather.csv"
TABLE = DATA / "table.csv"
META = DATA / "weather_meta.json"
PLOT_SUN = ROOT / "results" / "plot_real_vs_sun.png"
PLOT_TEMP = ROOT / "results" / "plot_real_vs_temp.png"

LAT = 42.866
LON = 68.376
TIMEZONE = "Asia/Almaty"
START_DATE = "2026-06-01"
END_DATE = "2026-09-30"
DAYS = 122
VARS = ("shortwave_radiation_sum", "cloud_cover_mean", "temperature_2m_max")
URL = (
    "https://historical-forecast-api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}"
    f"&daily={','.join(VARS)}"
    f"&start_date={START_DATE}&end_date={END_DATE}"
    f"&timezone={TIMEZONE.replace('/', '%2F')}"
)


def fetch():
    RAW.mkdir(parents=True, exist_ok=True)
    if CACHE.exists():
        print(f"using cache {CACHE.relative_to(ROOT)}")
        return json.loads(CACHE.read_text(encoding="utf-8"))
    print(f"fetching {URL}")
    try:
        with urllib.request.urlopen(URL, timeout=60) as response:
            text = response.read().decode("utf-8")
    except urllib.error.URLError as error:
        raise SystemExit(f"Open-Meteo request failed: {error}") from error
    payload = json.loads(text)
    if "error" in payload:
        raise SystemExit(f"Open-Meteo error: {payload.get('reason')}")
    CACHE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def check_payload(payload):
    if payload.get("utc_offset_seconds") != 18000:
        raise SystemExit(
            f"utc_offset_seconds is {payload.get('utc_offset_seconds')}, expected 18000"
        )
    if payload.get("timezone") != TIMEZONE:
        raise SystemExit(f"timezone is {payload.get('timezone')}, expected {TIMEZONE}")
    daily = payload.get("daily") or {}
    for key in ("time",) + VARS:
        if key not in daily:
            raise SystemExit(f"daily.{key} is missing from the response")
    if len(daily["time"]) != DAYS:
        raise SystemExit(f"{len(daily['time'])} days, expected {DAYS}")
    if daily["time"][0] != START_DATE or daily["time"][-1] != END_DATE:
        raise SystemExit(
            f"dates are {daily['time'][0]}..{daily['time'][-1]}, "
            f"expected {START_DATE}..{END_DATE}"
        )
    for key in VARS:
        missing = [day for day, value in zip(daily["time"], daily[key]) if value is None]
        if missing:
            raise SystemExit(f"{key} is empty on {len(missing)} days: {missing[:3]}")


def write_weather(payload):
    daily = payload["daily"]
    rows = []
    for i, day in enumerate(daily["time"]):
        rows.append({"date": day, **{key: daily[key][i] for key in VARS}})
    with WEATHER.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date"] + list(VARS))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def write_meta(payload, rows):
    meta = {
        "source": "Open-Meteo historical forecast API",
        "url": URL,
        "requested_latitude": LAT,
        "requested_longitude": LON,
        "returned_latitude": payload.get("latitude"),
        "returned_longitude": payload.get("longitude"),
        "elevation_m": payload.get("elevation"),
        "timezone": payload.get("timezone"),
        "timezone_abbreviation": payload.get("timezone_abbreviation"),
        "utc_offset_seconds": payload.get("utc_offset_seconds"),
        "start_date": START_DATE,
        "end_date": END_DATE,
        "rows": len(rows),
        "variables": {
            "shortwave_radiation_sum": "MJ/m2 per day",
            "cloud_cover_mean": "%",
            "temperature_2m_max": "C",
        },
        "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def read_daily():
    with DAILY.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != DAYS:
        raise SystemExit(f"{DAILY.name}: {len(rows)} rows, expected {DAYS}")
    return rows


def write_table(daily_rows, weather_rows):
    by_date = {row["date"]: row for row in weather_rows}
    out = []
    missing = [row["date"] for row in daily_rows if row["date"] not in by_date]
    if missing:
        raise SystemExit(f"no weather for {len(missing)} days: {missing[:3]}")
    for row in daily_rows:
        weather = by_date[row["date"]]
        out.append(
            {
                "date": row["date"],
                "plan_kwh": row["plan_kwh"],
                "real_kwh": row["real_kwh"],
                "note": row["note"],
                **{key: weather[key] for key in VARS},
            }
        )
    with TABLE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["date", "plan_kwh", "real_kwh", "note"] + list(VARS),
        )
        writer.writeheader()
        writer.writerows(out)
    return out


def scatter(rows, x_key, x_label, title, out_path):
    from PIL import Image, ImageDraw, ImageFont

    def font(size):
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    width, height = 1000, 600
    left, right, top, bottom = 100, 50, 90, 90
    plot_w = width - left - right
    plot_h = height - top - bottom

    xs = [float(row[x_key]) for row in rows]
    ys = [float(row["real_kwh"]) for row in rows]
    xmin, xmax = min(xs), max(xs)
    pad = (xmax - xmin) * 0.05 or 1.0
    xmin, xmax = xmin - pad, xmax + pad
    ymax = ((int(max(ys)) + 999) // 1000) * 1000

    def point(x, y):
        return (
            left + (x - xmin) / (xmax - xmin) * plot_w,
            top + plot_h - y / ymax * plot_h,
        )

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    f_title = font(22)
    f_axis = font(15)
    f_tick = font(13)

    for value in range(0, ymax + 1, 2000):
        y = top + plot_h - value / ymax * plot_h
        draw.line([(left, y), (left + plot_w, y)], fill=(232, 232, 232))
        draw.text(
            (left - 12, y), f"{value:,}", font=f_tick, fill=(60, 60, 60), anchor="rm"
        )
    for i in range(6):
        x = left + i / 5 * plot_w
        value = xmin + i / 5 * (xmax - xmin)
        draw.line([(x, top + plot_h), (x, top + plot_h + 5)], fill=(80, 80, 80))
        draw.text(
            (x, top + plot_h + 10),
            f"{value:.1f}",
            font=f_tick,
            fill=(60, 60, 60),
            anchor="ma",
        )

    draw.line([(left, top), (left, top + plot_h)], fill=(80, 80, 80), width=2)
    draw.line(
        [(left, top + plot_h), (left + plot_w, top + plot_h)],
        fill=(80, 80, 80),
        width=2,
    )

    color = (30, 90, 200)
    for x, y in zip(xs, ys):
        px, py = point(x, y)
        draw.ellipse([(px - 3.5, py - 3.5), (px + 3.5, py + 3.5)], fill=color)

    draw.text((left, top - 52), title, font=f_title, fill=(20, 20, 20))
    draw.text(
        (left, top - 28),
        f"Kargaly 42.866 N, 68.376 E; days without a note, n={len(rows)}",
        font=f_axis,
        fill=(90, 90, 90),
    )
    draw.text((left + 6, top + 4), "Real, kWh/day", font=f_axis, fill=(60, 60, 60))
    draw.text(
        (left + plot_w / 2, height - 34),
        x_label,
        font=f_axis,
        fill=(60, 60, 60),
        anchor="ma",
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def main():
    payload = fetch()
    check_payload(payload)
    weather_rows = write_weather(payload)
    meta = write_meta(payload, weather_rows)
    daily_rows = read_daily()
    table_rows = write_table(daily_rows, weather_rows)

    clean = [row for row in table_rows if row["note"] == ""]
    plot_sun = scatter(
        clean,
        "shortwave_radiation_sum",
        "Daily sun, shortwave radiation sum (MJ/m2)",
        "Real output vs daily sun, Jun-Sep 2026",
        PLOT_SUN,
    )
    plot_temp = scatter(
        clean,
        "temperature_2m_max",
        "Daily maximum temperature (C)",
        "Real output vs daily maximum temperature, Jun-Sep 2026",
        PLOT_TEMP,
    )

    weather_dates = [row["date"] for row in weather_rows]
    daily_dates = [row["date"] for row in daily_rows]
    table_by_date = {row["date"]: row for row in table_rows}
    join_ok = all(
        str(table_by_date[row["date"]][key]) == str(row[key])
        for row in weather_rows
        for key in VARS
    )
    june_first = table_by_date["2026-06-01"]

    checks = [
        (
            "weather.csv has 122 rows",
            len(weather_rows) == DAYS,
            len(weather_rows),
        ),
        ("weather dates = daily dates, 122/122", weather_dates == daily_dates, len(weather_dates)),
        ("utc_offset_seconds = 18000", meta["utc_offset_seconds"] == 18000, meta["utc_offset_seconds"]),
        ("timezone = Asia/Almaty", meta["timezone"] == TIMEZONE, meta["timezone"]),
        (
            "1 June sun about 25 MJ/m2 (24-26)",
            24.0 <= float(june_first["shortwave_radiation_sum"]) <= 26.0,
            june_first["shortwave_radiation_sum"],
        ),
        (
            "no empty weather values",
            all(
                str(row[key]).strip() not in ("", "None")
                for row in weather_rows
                for key in VARS
            ),
            len(weather_rows) * len(VARS),
        ),
        ("table.csv has 122 rows", len(table_rows) == DAYS, len(table_rows)),
        ("table weather = weather.csv, 122/122", join_ok, len(table_rows)),
        (
            "table plan/real = daily.csv, 122/122",
            all(
                table_by_date[row["date"]]["plan_kwh"] == row["plan_kwh"]
                and table_by_date[row["date"]]["real_kwh"] == row["real_kwh"]
                for row in daily_rows
            ),
            len(daily_rows),
        ),
        (
            "plots use 111 days without a note",
            len(clean) == 111,
            len(clean),
        ),
        (
            "both plots written",
            all(p.exists() and p.stat().st_size > 5000 for p in (plot_sun, plot_temp)),
            f"{plot_sun.name} {plot_sun.stat().st_size} B, {plot_temp.name} {plot_temp.stat().st_size} B",
        ),
        (
            "requested point 42.866 / 68.376",
            meta["requested_latitude"] == LAT and meta["requested_longitude"] == LON,
            f"{meta['requested_latitude']} / {meta['requested_longitude']}",
        ),
    ]

    print(f"wrote {WEATHER.relative_to(ROOT)}: {len(weather_rows)} rows")
    print(f"wrote {TABLE.relative_to(ROOT)}: {len(table_rows)} rows")
    print(f"wrote {META.relative_to(ROOT)}")
    print("first 3 rows of table.csv:")
    for row in table_rows[:3]:
        print(
            f"  {row['date']},{row['plan_kwh']},{row['real_kwh']},"
            f"{row['note'] or '-'},{row['shortwave_radiation_sum']},"
            f"{row['cloud_cover_mean']},{row['temperature_2m_max']}"
        )
    for name, ok, value in checks:
        print(f"  {'OK' if ok else 'WRONG'}  {name}  -> {value}")
    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        raise SystemExit(f"checks failed: {failed}")


if __name__ == "__main__":
    main()
