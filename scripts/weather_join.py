import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
HOURLY = DATA / "hourly.csv"
CACHE = RAW / "weather_2026-08-01_2026-10-01.json"
OUT_ALL = DATA / "weather_power.csv"
OUT_PLOT = DATA / "weather_power_3days.csv"
OUT_JSON = DATA / "weather_power.json"

PLOT_DAYS = ("2026-09-01", "2026-09-02", "2026-09-03")
PEAK_TOLERANCE = 0.01
START_DATE = "2026-08-01"
END_DATE = "2026-10-01"
WEATHER_URL = (
    "https://historical-forecast-api.open-meteo.com/v1/forecast"
    "?latitude=42.866&longitude=68.376"
    "&hourly=shortwave_radiation,cloud_cover,temperature_2m"
    f"&start_date={START_DATE}&end_date={END_DATE}"
    "&timezone=Asia/Almaty"
)
KEYS = ("time", "shortwave_radiation", "cloud_cover", "temperature_2m")
BAD_WORDS = (
    "ЖИЛ",
    "Жумаш",
    "Гаухар",
    "АСЕМ",
    "Отправил",
    "Пользователь",
)


def load_hourly():
    with HOURLY.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    detailed = []
    for row in rows:
        if row["level"] != "hourly":
            continue
        ts = datetime.strptime(row["hour"], "%Y-%m-%d %H:%M")
        day = ts.date() if ts.hour >= 4 else ts.date() - timedelta(days=1)
        detailed.append(
            {
                "time": ts,
                "hour": row["hour"],
                "report_day": day.isoformat(),
                "produced": float(row["kWh produced"]),
                "planned": float(row["kWh planned"]),
            }
        )
    detailed.sort(key=lambda item: item["time"])
    days = sorted({item["report_day"] for item in detailed})
    if len(detailed) != 24 * len(days):
        raise RuntimeError(f"hourly rows {len(detailed)} are not whole days")
    for day in days:
        block = [item for item in detailed if item["report_day"] == day]
        if len(block) != 24:
            raise RuntimeError(f"{day}: expected 24 hours, got {len(block)}")
    return detailed, days


def fetch_weather():
    if CACHE.exists():
        data = json.loads(CACHE.read_text(encoding="utf-8"))
    else:
        response = requests.get(WEATHER_URL, timeout=60)
        if not response.ok:
            raise RuntimeError(
                f"Open-Meteo HTTP {response.status_code}: {response.text[:800]}"
            )
        data = response.json()
        RAW.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if data.get("timezone") != "Asia/Almaty":
        raise RuntimeError(f"unexpected time zone: {data.get('timezone')}")
    if data.get("utc_offset_seconds") != 18000:
        raise RuntimeError(
            f"Open-Meteo offset is not UTC+5: {data.get('utc_offset_seconds')}"
        )
    hourly = data.get("hourly") or {}
    for key in KEYS:
        if key not in hourly:
            raise RuntimeError(f"Open-Meteo response has no {key}")
    lengths = {len(hourly[key]) for key in KEYS}
    if len(lengths) != 1:
        raise RuntimeError(f"Open-Meteo arrays differ in length: {lengths}")
    return data


def weather_by_hour(data):
    hourly = data["hourly"]
    mapped = {}
    for index, text in enumerate(hourly["time"]):
        end = datetime.strptime(text, "%Y-%m-%dT%H:%M")
        start = end - timedelta(hours=1)
        mapped[start.strftime("%Y-%m-%d %H:%M")] = {
            "ghi": hourly["shortwave_radiation"][index],
            "cloud": hourly["cloud_cover"][index],
            "temp": hourly["temperature_2m"][index],
        }
    return mapped


def join_weather(detailed, weather):
    joined = []
    missing = []
    for item in detailed:
        values = weather.get(item["hour"])
        if (
            values is None
            or values["ghi"] is None
            or values["cloud"] is None
            or values["temp"] is None
        ):
            missing.append(item["hour"])
            continue
        joined.append(
            {
                "hour": item["hour"],
                "report_day": item["report_day"],
                "produced": item["produced"],
                "planned": item["planned"],
                "ghi": round(float(values["ghi"]), 1),
                "cloud": round(float(values["cloud"]), 1),
                "temp": round(float(values["temp"]), 1),
            }
        )
    if missing:
        raise RuntimeError("missing weather for: " + ", ".join(missing[:12]))
    if len(joined) != len(detailed):
        raise RuntimeError(f"joined {len(joined)} of {len(detailed)} hours")
    return joined


def peak_day(block, day):
    peak_sun = max(block, key=lambda item: item["ghi"])
    peak_power = max(block, key=lambda item: item["produced"])
    threshold = peak_power["produced"] * (1 - PEAK_TOLERANCE)
    top = [item for item in block if item["produced"] >= threshold]
    top_indices = [block.index(item) for item in top]
    center_index = int(sum(top_indices) / len(top_indices) + 0.5)
    center = block[center_index]
    label = datetime.strptime(day, "%Y-%m-%d").strftime("%-d %b")
    return {
        "date": day,
        "label": label,
        "peak_sun": {"hour": peak_sun["hour"], "value": peak_sun["ghi"]},
        "peak_power": {
            "hour": peak_power["hour"],
            "value": round(peak_power["produced"], 6),
        },
        "power_top": {
            "hours": [item["hour"] for item in top],
            "values": [round(item["produced"], 6) for item in top],
            "center": {
                "hour": center["hour"],
                "value": round(center["produced"], 6),
            },
            "tolerance": PEAK_TOLERANCE,
        },
        "same_hour": peak_sun["hour"] == center["hour"],
        "exact_same_hour": peak_sun["hour"] == peak_power["hour"],
        "sun_in_power_top": peak_sun["hour"] in [item["hour"] for item in top],
    }


def day_blocks(joined):
    blocks = {}
    for item in joined:
        blocks.setdefault(item["report_day"], []).append(item)
    for day, block in blocks.items():
        block.sort(key=lambda item: item["hour"])
        if len(block) != 24:
            raise RuntimeError(f"{day}: expected 24 hours, got {len(block)}")
    return blocks


def write_csv(path, hours):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "hour",
                "kWh produced",
                "kWh planned",
                "ghi_wm2",
                "cloud_pct",
                "temp_c",
                "report_day",
            ]
        )
        for item in hours:
            writer.writerow(
                [
                    item["hour"],
                    f"{item['produced']:.6f}",
                    f"{item['planned']:.3f}",
                    f"{item['ghi']:.1f}",
                    f"{item['cloud']:.1f}",
                    f"{item['temp']:.1f}",
                    item["report_day"],
                ]
            )


def plot_label(days):
    if not days:
        return ""
    first = datetime.strptime(days[0], "%Y-%m-%d")
    last = datetime.strptime(days[-1], "%Y-%m-%d")
    if first.month == last.month:
        return f"{first.day}–{last.day} {first.strftime('%b %Y')}"
    return f"{first.day} {first.strftime('%b')} – {last.day} {last.strftime('%b %Y')}"


def build_payload():
    detailed, report_days = load_hourly()
    if len(report_days) < 60:
        raise RuntimeError(f"only {len(report_days)} report days")
    data = fetch_weather()
    weather = weather_by_hour(data)
    joined = join_weather(detailed, weather)
    blocks = day_blocks(joined)

    missing_plot = [day for day in PLOT_DAYS if day not in blocks]
    if missing_plot:
        raise RuntimeError("plot days without hours: " + ", ".join(missing_plot))
    plot_hours = [item for item in joined if item["report_day"] in PLOT_DAYS]
    plot_days = [peak_day(blocks[day], day) for day in PLOT_DAYS]

    if len(plot_hours) != 72:
        raise RuntimeError(f"expected 72 plot hours, got {len(plot_hours)}")
    for day in plot_days:
        if not day["exact_same_hour"]:
            raise RuntimeError(
                f"{day['date']}: sun and power do not peak in the same hour"
            )

    write_csv(OUT_ALL, joined)
    write_csv(OUT_PLOT, plot_hours)

    exact = sum(
        1
        for day in report_days
        if peak_day(blocks[day], day)["exact_same_hour"]
    )
    payload = {
        "source": "Open-Meteo historical forecast API",
        "source_url": WEATHER_URL,
        "timezone": data.get("timezone"),
        "utc_offset_seconds": data.get("utc_offset_seconds"),
        "coordinates": {"lat": 42.866, "lon": 68.376},
        "plot_days": list(PLOT_DAYS),
        "plot_label": plot_label(PLOT_DAYS),
        "total_days": len(report_days),
        "total_hours": len(joined),
        "peak_same_hour_days": exact,
        "peak_check_days": len(report_days),
        "table_csv": "data/weather_power.csv",
        "table_hours": "hour, kWh produced, kWh planned, GHI, clouds, temperature",
        "days": plot_days,
        "hours": plot_hours,
    }
    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for path in (OUT_ALL, OUT_PLOT, OUT_JSON):
        text = path.read_text(encoding="utf-8")
        for bad in BAD_WORDS:
            if bad.lower() in text.lower():
                raise RuntimeError(f"name leaked into {path}: {bad}")
    return payload


def build():
    payload = build_payload()
    print(f"wrote {OUT_ALL.relative_to(ROOT)}: {payload['total_hours']} hours, "
          f"{payload['total_days']} report days")
    print(f"wrote {OUT_PLOT.relative_to(ROOT)}: {len(payload['hours'])} hours, "
          f"{len(payload['plot_days'])} days")
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"source: {WEATHER_URL}")
    print(f"time zone: {payload['timezone']} "
          f"(UTC+{payload['utc_offset_seconds'] // 3600})")
    for day in payload["days"]:
        print(
            f"{day['date']}: sun peak {day['peak_sun']['hour'][-5:]} "
            f"({day['peak_sun']['value']:.0f} W/m2), "
            f"power peak {day['peak_power']['hour'][-5:]} "
            f"({day['peak_power']['value']:.1f} kWh), "
            f"same hour = {day['exact_same_hour']}"
        )
    print(f"peak check: sun and power peak in the same hour on "
          f"{payload['peak_same_hour_days']} of {payload['peak_check_days']} days")
    print("names in output: none")


if __name__ == "__main__":
    try:
        build()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
