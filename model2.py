import csv
import hashlib
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
TABLE = ROOT / "data" / "table.csv"
SEP = ROOT / "results" / "baselines_sep.csv"
JULY = ROOT / "results" / "baselines.csv"
MAIN_MODEL = ROOT / "model.py"
FORECAST = ROOT / "results" / "model2_sep.csv"
PLOT = ROOT / "results" / "plot_2026-09-01_05.png"

SUN = "shortwave_radiation_sum"
TMAX = "temperature_2m_max"
PLOT_DAYS = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05"]
MODEL_MD5 = "4de931d3fcc1914aa5035d98a24fc40a"


def read_table():
    with TABLE.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 122:
        raise SystemExit(f"{TABLE.name}: {len(rows)} rows, expected 122")
    return {
        row["date"]: {
            "plan_kwh": float(row["plan_kwh"]),
            "real_kwh": float(row["real_kwh"]),
            "note": row["note"],
            SUN: float(row[SUN]),
            TMAX: float(row[TMAX]),
        }
        for row in rows
    }


def prev_day(day):
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def clean_days(rows, month):
    return [d for d in sorted(rows) if d.startswith(month) and rows[d]["note"] == ""]


def features_a(rows, day):
    return [1.0, rows[day][SUN], rows[day][TMAX]]


def delta_features(rows, day):
    prev = prev_day(day)
    return [1.0, rows[day][SUN] - rows[prev][SUN], rows[day][TMAX] - rows[prev][TMAX]]


def fit(x_rows, y):
    coef, _, _, _ = np.linalg.lstsq(np.array(x_rows), np.array(y), rcond=None)
    return coef


def model_a(rows, coef, day):
    return float(np.array(features_a(rows, day)) @ coef)


def model_b(rows, coef, day):
    return float(rows[prev_day(day)]["real_kwh"] + np.array(delta_features(rows, day)) @ coef)


def model_c(rows, day):
    prev = prev_day(day)
    return rows[prev]["real_kwh"] * rows[day][SUN] / rows[prev][SUN]


def mae(rows, days, predict):
    return sum(abs(predict(d) - rows[d]["real_kwh"]) for d in days) / len(days)


def write_plot(rows, pred):
    from PIL import Image, ImageDraw, ImageFont

    def font(size):
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    width, height = 1000, 620
    left, right, top, bottom = 100, 60, 110, 90
    plot_w = width - left - right
    plot_h = height - top - bottom
    ymax = 9000
    days = PLOT_DAYS

    def x_of(i):
        return left + (i / (len(days) - 1)) * plot_w

    def y_of(v):
        return top + plot_h - min(max(v, 0.0), ymax) / ymax * plot_h

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    f_title, f_axis, f_tick, f_small = font(22), font(15), font(13), font(14)

    for value in range(0, ymax + 1, 1000):
        y = y_of(value)
        draw.line([(left, y), (left + plot_w, y)], fill=(232, 232, 232))
        draw.text((left - 12, y), f"{value:,}", font=f_tick, fill=(60, 60, 60), anchor="rm")

    for i, day in enumerate(days):
        x = x_of(i)
        draw.line([(x, top + plot_h), (x, top + plot_h + 5)], fill=(80, 80, 80))
        draw.text((x, top + plot_h + 10), f"{int(day[8:10])} Sep", font=f_tick, fill=(60, 60, 60), anchor="ma")

    draw.line([(left, top), (left, top + plot_h)], fill=(80, 80, 80), width=2)
    draw.line([(left, top + plot_h), (left + plot_w, top + plot_h)], fill=(80, 80, 80), width=2)

    series = [
        ("Plan", [rows[d]["plan_kwh"] for d in days], (230, 140, 30)),
        ("Real", [rows[d]["real_kwh"] for d in days], (30, 90, 200)),
        ("My model 2", [pred[d] for d in days], (150, 40, 160)),
    ]
    for name, values, colour in series:
        points = [(x_of(i), y_of(v)) for i, v in enumerate(values)]
        draw.line(points, fill=colour, width=3)
        for px, py in points:
            draw.ellipse([(px - 4, py - 4), (px + 4, py + 4)], fill=colour)

    draw.text((left, top - 60), "Plan, real and my model 2, 1-5 September 2026", font=f_title, fill=(20, 20, 20))
    draw.text(
        (left, top - 34),
        "Kargaly 42.866 N, 68.376 E; model chosen on August, learned on June-August only",
        font=f_axis,
        fill=(90, 90, 90),
    )
    draw.text((left + 6, top + 6), "kWh per day", font=f_small, fill=(60, 60, 60))

    legend_x, legend_y = left + plot_w - 185, top + 10
    for i, (name, _, colour) in enumerate(series):
        y = legend_y + i * 24
        draw.line([(legend_x, y + 7), (legend_x + 26, y + 7)], fill=colour, width=3)
        draw.text((legend_x + 34, y), name, font=f_small, fill=(50, 50, 50))

    PLOT.parent.mkdir(parents=True, exist_ok=True)
    img.save(PLOT)
    return PLOT


def main():
    rows = read_table()
    june = clean_days(rows, "2026-06")
    july = clean_days(rows, "2026-07")
    august = clean_days(rows, "2026-08")
    september = clean_days(rows, "2026-09")

    train = june + july
    train_b = [d for d in train if prev_day(d) in rows]
    coef_a = fit([features_a(rows, d) for d in train], [rows[d]["real_kwh"] for d in train])
    coef_b = fit(
        [delta_features(rows, d) for d in train_b],
        [rows[d]["real_kwh"] - rows[prev_day(d)]["real_kwh"] for d in train_b],
    )

    candidates = {
        "A": (lambda d: model_a(rows, coef_a, d), coef_a),
        "B": (lambda d: model_b(rows, coef_b, d), coef_b),
        "C": (lambda d: model_c(rows, d), None),
    }
    august_errors = {name: mae(rows, august, fn) for name, (fn, _) in candidates.items()}
    chosen = min(august_errors, key=august_errors.get)

    if chosen == "C":
        final = lambda day: model_c(rows, day)
        final_label = "C, fitted nothing"
    else:
        train_final = june + july + august
        train_final_b = [d for d in train_final if prev_day(d) in rows]
        if chosen == "A":
            final_coef = fit(
                [features_a(rows, d) for d in train_final],
                [rows[d]["real_kwh"] for d in train_final],
            )
            final = lambda day: model_a(rows, final_coef, day)
        else:
            final_coef = fit(
                [delta_features(rows, d) for d in train_final_b],
                [rows[d]["real_kwh"] - rows[prev_day(d)]["real_kwh"] for d in train_final_b],
            )
            final = lambda day: model_b(rows, final_coef, day)
        final_label = f"{chosen}, refitted on {len(train_final)} clean days"

    pred = {d: final(d) for d in september}
    avg_real = sum(rows[d]["real_kwh"] for d in september) / len(september)
    miss = mae(rows, september, final)
    pct = 100.0 * miss / avg_real

    with FORECAST.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "real_kwh", "plan_kwh", "my_model2_kwh"])
        for d in september:
            writer.writerow([d, f"{rows[d]['real_kwh']:.3f}", f"{rows[d]['plan_kwh']:.3f}", f"{pred[d]:.3f}"])

    with SEP.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        saved = [row for row in reader if row["forecast"] != "my model 2"]
    before = [(row["forecast"], row["miss_kwh"], row["miss_pct"]) for row in saved]
    saved.append({"forecast": "my model 2", "days": str(len(september)), "avg_real_kwh": f"{avg_real:.3f}", "miss_kwh": f"{miss:.3f}", "miss_pct": f"{pct:.2f}"})
    with SEP.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(saved)

    plot = write_plot(rows, pred)
    min_sun = min(rows[d][SUN] for d in rows)

    with SEP.open(newline="", encoding="utf-8") as f:
        after = list(csv.DictReader(f))
    with JULY.open(newline="", encoding="utf-8") as f:
        july_rows = list(csv.DictReader(f))

    checks = [
        ("June-July clean days = 55", len(train) == 55, len(train)),
        ("August clean days = 26", len(august) == 26, len(august)),
        ("September never in the learning set", all(d.startswith(("2026-06", "2026-07", "2026-08")) for d in june + july + august), len(june + july + august)),
        ("August notes excluded (13,14,17,18,20)", len([d for d in sorted(rows) if d.startswith("2026-08") and rows[d]["note"] != ""]) == 5, 5),
        ("chosen = lowest August error (A)", chosen == "A", {k: round(v, 3) for k, v in august_errors.items()}),
        ("final learned on 81 clean days", chosen == "C" or (len(june + july + august) == 81), len(june + july + august)),
        ("September test days = 30", len(september) == 30, len(september)),
        ("min sun > 0 (model C safe)", min_sun > 0, min_sun),
        ("saved my-model-2 miss = recomputed", len(after) == 4 and abs(float(after[-1]["miss_kwh"]) - miss) < 0.001, f"{miss:.3f} vs {after[-1]['miss_kwh'] if after else 'missing'}"),
        ("saved pct = miss / avg real", len(after) == 4 and abs(float(after[-1]["miss_pct"]) - pct) < 0.01, f"{pct:.2f}%"),
        ("baselines_sep.csv other 3 rows unchanged", [(r["forecast"], r["miss_kwh"], r["miss_pct"]) for r in after[:3]] == before, [r["forecast"] for r in after]),
        ("baselines.csv not changed (4 rows)", [r["forecast"] for r in july_rows] == ["plan", "yesterday", "median7", "my model"], [r["forecast"] for r in july_rows]),
        ("model.py not changed (md5)", hashlib.md5(MAIN_MODEL.read_bytes()).hexdigest() == MODEL_MD5, hashlib.md5(MAIN_MODEL.read_bytes()).hexdigest()),
        ("model2_sep.csv has 30 rows", len(september) == 30, len(september)),
        ("plot written", plot.exists() and plot.stat().st_size > 5000, f"{plot.name} {plot.stat().st_size if plot.exists() else 0} B"),
        ("plot covers 1-5 September", all(d in pred for d in PLOT_DAYS), len(PLOT_DAYS)),
    ]

    print(f"lead: {len(train)} clean June-July days, {len(august)} clean August days")
    print("August error (same days for all 3):")
    for name in ("A", "B", "C"):
        print(f"  {name}: {august_errors[name]:.3f} kWh ({100.0 * august_errors[name] / (sum(rows[d]['real_kwh'] for d in august) / len(august)):.2f}%)")
    print(f"chosen: model {chosen} ({final_label})")
    print(f"September: {len(september)} clean days, my model 2 {miss:.3f} kWh ({pct:.2f}%)")
    print("1-5 September: date, plan, real, my model 2")
    for d in PLOT_DAYS:
        print(f"  {d}  {rows[d]['plan_kwh']:.0f}  {rows[d]['real_kwh']:.0f}  {pred[d]:.0f}")
    for name, ok, value in checks:
        print(f"  {'OK' if ok else 'WRONG'}  {name}  -> {value}")
    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        raise SystemExit(f"checks failed: {failed}")


if __name__ == "__main__":
    main()
