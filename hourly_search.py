import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pvlib
import requests

ROOT = Path(__file__).resolve().parent
DAILY = ROOT / "data" / "daily.csv"
HOURLY = ROOT / "data" / "hourly.csv"
CACHE = ROOT / "data" / "raw" / "weather_hourly_sun_2026-08-01_2026-10-01.json"
AUG_OUT = ROOT / "results" / "hourly_search_aug.csv"
SEP_OUT = ROOT / "results" / "hourly_sep.csv"
PLOT = ROOT / "results" / "plot_2026-09-02_hourly.png"
RESULTS = ROOT / "results"

LAT, LON, ALT, TZ = 42.866, 68.376, 197, "Asia/Almaty"
HOURS = [f"{h:02d}:00" for h in range(24)]
PRODUCING = 1.0
PLOT_DAY = "2026-09-02"
PLAN_SEP_MISS = 1015.100
YDAY_SEP_MISS = 512.600

SHAPES = [
    ("H1 yesterday's hours", "h1"),
    ("H2 pvlib clear sky", "h2"),
    ("H3 Open-Meteo sun", "h3"),
    ("H4 mean of last 7 clean days", "h4"),
    ("H5 plant plan shape", "h5"),
]


def read_daily():
    with DAILY.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 122:
        raise SystemExit(f"{DAILY.name}: {len(rows)} rows, expected 122")
    return {
        row["date"]: {
            "real_kwh": float(row["real_kwh"]),
            "plan_kwh": float(row["plan_kwh"]),
            "note": row["note"],
        }
        for row in rows
    }


def read_hours():
    out = {}
    with HOURLY.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.setdefault(row["date"], {})[row["hour_start"]] = {
                "real_kwh": float(row["real_kwh"]),
                "plan_kwh": float(row["plan_kwh"]),
            }
    for day, hours in out.items():
        if sorted(hours) != sorted(HOURS):
            raise SystemExit(f"{day}: {len(hours)} hours, expected 24")
    if len(out) != 61:
        raise SystemExit(f"{HOURLY.name}: {len(out)} days, expected 61")
    return out


def fetch_sun():
    if CACHE.exists():
        with CACHE.open(encoding="utf-8") as f:
            return json.load(f)
    url = "https://historical-forecast-api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LAT,
        "longitude": LON,
        "start_date": "2026-08-01",
        "end_date": "2026-10-01",
        "hourly": "shortwave_radiation",
        "timezone": TZ,
    }
    response = requests.get(url, params=params, timeout=60)
    if response.status_code != 200:
        raise SystemExit(f"Open-Meteo {response.status_code}: {response.text[:300]}")
    data = response.json()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def sun_by_slot(data):
    out = {}
    for stamp, value in zip(data["hourly"]["time"], data["hourly"]["shortwave_radiation"]):
        moment = datetime.fromisoformat(stamp)
        out[(moment.strftime("%Y-%m-%d"), moment.hour)] = 0.0 if value is None else float(value)
    return out


def sun_for_slot(sun, day, hour):
    moment = datetime.fromisoformat(f"{day}T{hour}:00") + timedelta(hours=1)
    key = (moment.strftime("%Y-%m-%d"), moment.hour)
    if key not in sun:
        raise SystemExit(f"Open-Meteo sun missing for slot {day} {hour} (needs {key})")
    return sun[key]


def clearsky_by_slot():
    times = pd.date_range("2026-08-01", "2026-10-01", freq="h", tz=TZ, inclusive="left")
    site = pvlib.location.Location(LAT, LON, tz=TZ, altitude=ALT)
    ghi = site.get_clearsky(times)["ghi"]
    return {
        (stamp.strftime("%Y-%m-%d"), f"{stamp.hour:02d}:00"): max(float(value), 0.0)
        for stamp, value in ghi.items()
    }


def build_context(daily, hours):
    clean = sorted(d for d in daily if daily[d]["note"] == "")

    def clean_before(day):
        return [d for d in clean if d < day and d in hours]

    prev = {d: (clean_before(d)[-1] if clean_before(d) else None) for d in daily}
    return {
        "daily": daily,
        "hours": hours,
        "clean": clean,
        "clean_before": {d: clean_before(d) for d in daily},
        "prev": prev,
        "D": {d: daily[prev[d]]["real_kwh"] for d in daily if prev[d] is not None},
        "ghi": clearsky_by_slot(),
        "sun": sun_by_slot(fetch_sun()),
    }


def shape(ctx, name, day):
    hours = ctx["hours"]
    if name == "h1":
        return np.array([hours[ctx["prev"][day]][h]["real_kwh"] for h in HOURS])
    if name == "h2":
        return np.array([ctx["ghi"][(day, h)] for h in HOURS])
    if name == "h3":
        return np.array([sun_for_slot(ctx["sun"], day, h) for h in HOURS])
    if name == "h4":
        last7 = ctx["clean_before"][day][-7:]
        if len(last7) != 7:
            raise SystemExit(f"{day}: H4 needs 7 clean days before, has {len(last7)}")
        return np.array([sum(hours[d][h]["real_kwh"] for d in last7) / 7.0 for h in HOURS])
    if name == "h5":
        return np.array([hours[day][h]["plan_kwh"] for h in HOURS])
    raise SystemExit(f"unknown shape {name}")


def split_daily(ctx, name, day):
    weights = shape(ctx, name, day)
    total = float(weights.sum())
    if total <= 0:
        raise SystemExit(f"{day} {name}: shape has zero weight")
    return ctx["D"][day] * weights / total


def metrics(ctx, days, preds, label):
    hours = ctx["hours"]
    daily = ctx["daily"]
    errors = []
    producing = 0
    within = 0
    total_real = 0.0
    for day in days:
        for i, h in enumerate(HOURS):
            real = hours[day][h]["real_kwh"]
            err = abs(preds[day][i] - real)
            errors.append(err)
            total_real += real
            if real > PRODUCING:
                producing += 1
                if err <= 0.10 * real:
                    within += 1
    mae = float(np.mean(errors))
    mean_real = total_real / len(errors)
    daily_miss = float(np.mean([abs(preds[d].sum() - daily[d]["real_kwh"]) for d in days]))
    avg_daily = float(np.mean([daily[d]["real_kwh"] for d in days]))
    return {
        "forecast": label,
        "days": len(days),
        "hours": len(errors),
        "hourly_miss_kwh": mae,
        "hourly_miss_pct": 100.0 * mae / mean_real,
        "producing_hours": producing,
        "within10_hours": within,
        "within10_pct": 100.0 * within / producing,
        "daily_miss_kwh": daily_miss,
        "daily_miss_pct": 100.0 * daily_miss / avg_daily,
    }


def csv_shape(path):
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    widths = {len(row) for row in rows}
    return len(rows) - 1, widths


def write_route(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def md5_other_results():
    skip = {AUG_OUT.name, SEP_OUT.name, PLOT.name}
    return {
        path.name: hashlib.md5(path.read_bytes()).hexdigest()
        for path in sorted(RESULTS.iterdir())
        if path.name not in skip
    }


def write_plot(ctx, preds, plan):
    from PIL import Image, ImageDraw, ImageFont

    def font(size):
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    day = PLOT_DAY
    width, height = 1000, 620
    left, right, top, bottom = 100, 60, 110, 90
    plot_w = width - left - right
    plot_h = height - top - bottom
    ymax = 1200

    def x_of(h):
        return left + h / 23.0 * plot_w

    def y_of(v):
        return top + plot_h - min(max(v, 0.0), ymax) / ymax * plot_h

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    f_title, f_axis, f_tick, f_small = font(22), font(15), font(13), font(14)

    for value in range(0, ymax + 1, 200):
        y = y_of(value)
        draw.line([(left, y), (left + plot_w, y)], fill=(232, 232, 232))
        draw.text((left - 12, y), f"{value:,}", font=f_tick, fill=(60, 60, 60), anchor="rm")

    for h in range(0, 24, 3):
        x = x_of(h)
        draw.line([(x, top + plot_h), (x, top + plot_h + 5)], fill=(80, 80, 80))
        draw.text((x, top + plot_h + 10), f"{h:02d}:00", font=f_tick, fill=(60, 60, 60), anchor="ma")

    draw.line([(left, top), (left, top + plot_h)], fill=(80, 80, 80), width=2)
    draw.line([(left, top + plot_h), (left + plot_w, top + plot_h)], fill=(80, 80, 80), width=2)

    series = [
        ("Real", [ctx["hours"][day][h]["real_kwh"] for h in HOURS], (30, 90, 200)),
        ("Plant plan", [ctx["hours"][day][h]["plan_kwh"] for h in HOURS], (230, 140, 30)),
        ("My forecast", list(preds[day]), (150, 40, 160)),
    ]
    for name, values, colour in series:
        points = [(x_of(i), y_of(v)) for i, v in enumerate(values)]
        draw.line(points, fill=colour, width=3)
        for px, py in points:
            draw.ellipse([(px - 3, py - 3), (px + 3, py + 3)], fill=colour)

    draw.text((left, top - 60), "2 September 2026: real, plant plan and my hourly forecast", font=f_title, fill=(20, 20, 20))
    draw.text(
        (left, top - 34),
        "Daily total from yesterday; hourly shape chosen on August only (Kargaly 42.866 N, 68.376 E)",
        font=f_axis,
        fill=(90, 90, 90),
    )
    draw.text((left + 6, top + 6), "kWh per hour", font=f_small, fill=(60, 60, 60))

    legend_x, legend_y = left + plot_w - 170, top + 10
    for i, (name, _, colour) in enumerate(series):
        y = legend_y + i * 24
        draw.line([(legend_x, y + 7), (legend_x + 26, y + 7)], fill=colour, width=3)
        draw.text((legend_x + 34, y), name, font=f_small, fill=(50, 50, 50))

    PLOT.parent.mkdir(parents=True, exist_ok=True)
    img.save(PLOT)
    return PLOT


def fmt(row):
    return {
        "forecast": row["forecast"],
        "days": row["days"],
        "hours": row["hours"],
        "hourly_miss_kwh": round(row["hourly_miss_kwh"], 3),
        "hourly_miss_pct": round(row["hourly_miss_pct"], 2),
        "within10_hours": row["within10_hours"],
        "producing_hours": row["producing_hours"],
        "within10_pct": round(row["within10_pct"], 1),
        "daily_miss_kwh": round(row["daily_miss_kwh"], 3),
        "daily_miss_pct": round(row["daily_miss_pct"], 2),
    }


def main():
    daily = read_daily()
    hours = read_hours()
    before = md5_other_results()
    ctx = build_context(daily, hours)

    aug = [
        d
        for d in ctx["clean"]
        if d.startswith("2026-08") and len(ctx["clean_before"][d]) >= 7
    ]
    sep = [d for d in ctx["clean"] if d.startswith("2026-09")]
    if len(aug) != 19:
        raise SystemExit(f"August scored days: {len(aug)}, expected 19")
    if len(sep) != 30:
        raise SystemExit(f"September days: {len(sep)}, expected 30")

    aug_rows = []
    aug_preds = {}
    for label, name in SHAPES:
        preds = {d: split_daily(ctx, name, d) for d in aug}
        aug_preds[name] = preds
        aug_rows.append(metrics(ctx, aug, preds, label))
    chosen_name = min(
        aug_preds, key=lambda name: metrics(ctx, aug, aug_preds[name], name)["hourly_miss_kwh"]
    )
    chosen_label = dict((name, label) for label, name in SHAPES)[chosen_name]

    sep_preds = {d: split_daily(ctx, chosen_name, d) for d in sep}
    plan_preds = {d: np.array([hours[d][h]["plan_kwh"] for h in HOURS]) for d in sep}
    sep_rows = [
        metrics(ctx, sep, sep_preds, f"my forecast ({chosen_label})"),
        metrics(ctx, sep, plan_preds, "plant plan"),
    ]

    fields = [
        "forecast",
        "days",
        "hours",
        "hourly_miss_kwh",
        "hourly_miss_pct",
        "within10_hours",
        "producing_hours",
        "within10_pct",
        "daily_miss_kwh",
        "daily_miss_pct",
    ]
    write_route(AUG_OUT, [fmt(r) for r in aug_rows], fields)
    write_route(SEP_OUT, [fmt(r) for r in sep_rows], fields)
    plot = write_plot(ctx, sep_preds, plan_preds)

    after = md5_other_results()
    plan_sep = sep_rows[1]
    chosen_sep = sep_rows[0]
    yd_miss = float(np.mean([abs(ctx["D"][d] - daily[d]["real_kwh"]) for d in sep]))
    max_sum_error = max(
        max(abs(preds[d].sum() - ctx["D"][d]) for d in preds) for preds in aug_preds.values()
    )
    checks = [
        ("daily rows = 122", len(daily) == 122, len(daily)),
        ("hourly days = 61, 24 hours each", len(hours) == 61, len(hours)),
        ("August clean days = 26", len([d for d in ctx["clean"] if d.startswith("2026-08")]) == 26, len([d for d in ctx["clean"] if d.startswith("2026-08")])),
        ("August scored days = 19 (need 7 earlier clean days)", len(aug) == 19, len(aug)),
        ("September days = 30, all clean", len(sep) == 30 and not any(daily[d]["note"] for d in sep), len(sep)),
        (
            "chosen = lowest August hourly miss",
            abs(aug_rows[[name for _, name in SHAPES].index(chosen_name)]["hourly_miss_kwh"] - min(r["hourly_miss_kwh"] for r in aug_rows)) < 1e-9,
            chosen_name,
        ),
        ("all forecasts sum to yesterday's daily total", max_sum_error < 1e-6, f"{max_sum_error:.2e}"),
        ("September yesterday daily miss = 512.600", abs(yd_miss - YDAY_SEP_MISS) < 0.001, f"{yd_miss:.3f}"),
        ("September plan daily miss = 1015.100", abs(plan_sep["daily_miss_kwh"] - PLAN_SEP_MISS) < 0.001, f"{plan_sep['daily_miss_kwh']:.3f}"),
        ("September chosen daily miss = yesterday's (by construction)", abs(chosen_sep["daily_miss_kwh"] - YDAY_SEP_MISS) < 0.001, f"{chosen_sep['daily_miss_kwh']:.3f}"),
        ("no other results file changed", before == after, [n for n in before if before[n] != after.get(n)]),
        ("plot written", plot.exists() and plot.stat().st_size > 5000, f"{plot.name} {plot.stat().st_size if plot.exists() else 0} B"),
        ("plot day = 2 September", PLOT_DAY in sep_preds, PLOT_DAY),
        ("August CSV 5 rows, all 10 columns", csv_shape(AUG_OUT) == (5, {10}), csv_shape(AUG_OUT)),
        ("September CSV 2 rows, all 10 columns", csv_shape(SEP_OUT) == (2, {10}), csv_shape(SEP_OUT)),
    ]

    print(f"August scored days: {len(aug)} (clean, >=7 earlier clean days); hours: {len(aug) * 24}")
    print(f"{'shape':<34}{'h-miss kWh':>11}{'h-miss %':>9}{'prod within 10%':>17}{'day miss kWh':>14}{'day %':>7}")
    for row in aug_rows:
        print(
            f"{row['forecast']:<34}{row['hourly_miss_kwh']:>11.3f}{row['hourly_miss_pct']:>8.2f}%"
            f"{row['within10_hours']:>10}/{row['producing_hours']:<3}{row['within10_pct']:>4.0f}%"
            f"{row['daily_miss_kwh']:>14.3f}{row['daily_miss_pct']:>6.2f}%"
        )
    print(f"chosen shape: {chosen_name.upper()} ({chosen_label})")
    print()
    print(f"September: {len(sep)} days, {len(sep) * 24} hours")
    print(f"{'forecast':<34}{'h-miss kWh':>11}{'h-miss %':>9}{'prod within 10%':>17}{'day miss kWh':>14}{'day %':>7}")
    for row in sep_rows:
        print(
            f"{row['forecast']:<34}{row['hourly_miss_kwh']:>11.3f}{row['hourly_miss_pct']:>8.2f}%"
            f"{row['within10_hours']:>10}/{row['producing_hours']:<3}{row['within10_pct']:>4.0f}%"
            f"{row['daily_miss_kwh']:>14.3f}{row['daily_miss_pct']:>6.2f}%"
        )
    print(f"2 September ({PLOT_DAY}): hour, real, plan, my forecast")
    for i, h in enumerate(HOURS):
        if ctx["hours"][PLOT_DAY][h]["real_kwh"] > PRODUCING:
            print(
                f"  {h}  {ctx['hours'][PLOT_DAY][h]['real_kwh']:.0f}  "
                f"{ctx['hours'][PLOT_DAY][h]['plan_kwh']:.0f}  {sep_preds[PLOT_DAY][i]:.0f}"
            )
    for name, ok, value in checks:
        print(f"  {'OK' if ok else 'WRONG'}  {name}  -> {value}")
    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        raise SystemExit(f"checks failed: {failed}")


if __name__ == "__main__":
    main()
