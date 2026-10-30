import csv
import statistics
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
TABLE = ROOT / "data" / "table.csv"
SUMMARY = ROOT / "results" / "baselines.csv"
JULY = ROOT / "results" / "model_july.csv"
PLOT = ROOT / "results" / "plot_2026-07-13_17.png"

SUN = "shortwave_radiation_sum"
TMAX = "temperature_2m_max"
PLOT_DAYS = ["2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16", "2026-07-17"]


def read_table():
    with TABLE.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 122:
        raise SystemExit(f"{TABLE.name}: {len(rows)} rows, expected 122")
    by_date = {}
    for row in rows:
        by_date[row["date"]] = {
            "plan_kwh": float(row["plan_kwh"]),
            "real_kwh": float(row["real_kwh"]),
            "note": row["note"],
            SUN: float(row[SUN]),
            TMAX: float(row[TMAX]),
        }
    return by_date


def prev_day(day):
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def features_a(rows, day):
    return [1.0, rows[day][SUN], rows[day][TMAX]]


def change_b(rows, day):
    prev = prev_day(day)
    return [
        1.0,
        rows[day][SUN] - rows[prev][SUN],
        rows[day][TMAX] - rows[prev][TMAX],
    ]


def predict_a(rows, coef, day):
    return float(np.array(features_a(rows, day)) @ coef)


def predict_b(rows, coef, day):
    return float(rows[prev_day(day)]["real_kwh"] + np.array(change_b(rows, day)) @ coef)


def fit(x_rows, y):
    coef, _, _, _ = np.linalg.lstsq(np.array(x_rows), np.array(y), rcond=None)
    return coef


def mae(pairs):
    return sum(abs(pred - real) for pred, real in pairs) / len(pairs)


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
    ymax = 8000
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
        label = f"{int(day[8:10])} Jul"
        draw.text((x, top + plot_h + 10), label, font=f_tick, fill=(60, 60, 60), anchor="ma")

    draw.line([(left, top), (left, top + plot_h)], fill=(80, 80, 80), width=2)
    draw.line([(left, top + plot_h), (left + plot_w, top + plot_h)], fill=(80, 80, 80), width=2)

    series = [
        ("Plan", [rows[d]["plan_kwh"] for d in days], (230, 140, 30)),
        ("Real", [rows[d]["real_kwh"] for d in days], (30, 90, 200)),
        ("My model", [pred[d] for d in days], (20, 150, 80)),
    ]
    for name, values, colour in series:
        points = [(x_of(i), y_of(v)) for i, v in enumerate(values)]
        draw.line(points, fill=colour, width=3)
        for px, py in points:
            draw.ellipse([(px - 4, py - 4), (px + 4, py + 4)], fill=colour)

    draw.text((left, top - 60), "Plan, real and my forecast, 13-17 July 2026", font=f_title, fill=(20, 20, 20))
    draw.text(
        (left, top - 34),
        "Kargaly 42.866 N, 68.376 E; model A learned only on June days without a note",
        font=f_axis,
        fill=(90, 90, 90),
    )
    draw.text((left + 6, top + 6), "kWh per day", font=f_small, fill=(60, 60, 60))

    legend_x, legend_y = left + plot_w - 170, top + 10
    for i, (name, _, colour) in enumerate(series):
        y = legend_y + i * 24
        draw.line([(legend_x, y + 7), (legend_x + 26, y + 7)], fill=colour, width=3)
        draw.text((legend_x + 34, y), name, font=f_small, fill=(50, 50, 50))

    PLOT.parent.mkdir(parents=True, exist_ok=True)
    img.save(PLOT)
    return PLOT


def main():
    rows = read_table()
    dates = sorted(rows)

    june_clean = [d for d in dates if d.startswith("2026-06") and rows[d]["note"] == ""]
    june_prev = [d for d in june_clean if prev_day(d) in rows]
    july_clean = [d for d in dates if d.startswith("2026-07") and rows[d]["note"] == ""]

    coef_a = fit(
        [features_a(rows, d) for d in june_clean],
        [rows[d]["real_kwh"] for d in june_clean],
    )
    coef_b = fit(
        [change_b(rows, d) for d in june_prev],
        [rows[d]["real_kwh"] - rows[prev_day(d)]["real_kwh"] for d in june_prev],
    )

    june_a = [(predict_a(rows, coef_a, d), rows[d]["real_kwh"]) for d in june_prev]
    june_b = [(predict_b(rows, coef_b, d), rows[d]["real_kwh"]) for d in june_prev]
    june_mae_a = mae(june_a)
    june_mae_b = mae(june_b)
    chosen = "A" if june_mae_a <= june_mae_b else "B"
    predict = (lambda day: predict_a(rows, coef_a, day)) if chosen == "A" else (
        lambda day: predict_b(rows, coef_b, day)
    )

    pred = {d: predict(d) for d in july_clean}
    avg_real = sum(rows[d]["real_kwh"] for d in july_clean) / len(july_clean)
    model_miss = sum(abs(pred[d] - rows[d]["real_kwh"]) for d in july_clean) / len(july_clean)
    model_pct = 100.0 * model_miss / avg_real

    JULY.parent.mkdir(parents=True, exist_ok=True)
    with JULY.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "real_kwh", "plan_kwh", "model_a_kwh", "model_b_kwh", "chosen_kwh"])
        for d in july_clean:
            writer.writerow(
                [
                    d,
                    f"{rows[d]['real_kwh']:.3f}",
                    f"{rows[d]['plan_kwh']:.3f}",
                    f"{predict_a(rows, coef_a, d):.3f}",
                    f"{predict_b(rows, coef_b, d):.3f}",
                    f"{pred[d]:.3f}",
                ]
            )

    with SUMMARY.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        summary = [row for row in reader if row["forecast"] != "my model"]
    summary.append(
        {
            "forecast": "my model",
            "all31_days": "",
            "all31_avg_real_kwh": "",
            "all31_miss_kwh": "",
            "all31_miss_pct": "",
            "clean25_days": str(len(july_clean)),
            "clean25_avg_real_kwh": f"{avg_real:.3f}",
            "clean25_miss_kwh": f"{model_miss:.3f}",
            "clean25_miss_pct": f"{model_pct:.2f}",
        }
    )
    with SUMMARY.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary)

    plot = write_plot(rows, pred)

    with SUMMARY.open(newline="", encoding="utf-8") as f:
        saved = list(csv.DictReader(f))
    saved_model = [r for r in saved if r["forecast"] == "my model"]
    checks = [
        ("30 June days without a note", len(june_clean) == 30, len(june_clean)),
        ("model B fitted on 29 June days", len(june_prev) == 29, len(june_prev)),
        ("no July day in the June fit", all(d.startswith("2026-06") for d in june_clean), len(june_clean)),
        ("25 July days without a note", len(july_clean) == 25, len(july_clean)),
        ("chosen by June MAE only (A)", chosen == "A", f"A {june_mae_a:.3f} vs B {june_mae_b:.3f}"),
        (
            "saved my-model miss = recomputed",
            len(saved_model) == 1
            and abs(float(saved_model[0]["clean25_miss_kwh"]) - model_miss) < 0.001,
            f"{model_miss:.3f} vs {saved_model[0]['clean25_miss_kwh'] if saved_model else 'missing'}",
        ),
        (
            "saved pct = miss / avg real",
            len(saved_model) == 1
            and abs(float(saved_model[0]["clean25_miss_pct"]) - model_pct) < 0.01,
            f"{model_pct:.2f}%",
        ),
        ("baselines.csv has 4 rows", len(saved) == 4, [r["forecast"] for r in saved]),
        (
            "plan / yesterday / median7 rows unchanged",
            [r["clean25_miss_kwh"] for r in saved if r["forecast"] != "my model"]
            == ["879.280", "622.280", "723.640"],
            [r["clean25_miss_kwh"] for r in saved if r["forecast"] != "my model"],
        ),
        ("model_july.csv has 25 rows", len(july_clean) == 25, len(july_clean)),
        (
            "plot written",
            plot.exists() and plot.stat().st_size > 5000,
            f"{plot.name} {plot.stat().st_size if plot.exists() else 0} B",
        ),
        (
            "plot covers 13-17 July",
            all(d in pred for d in PLOT_DAYS) and len(PLOT_DAYS) == 5,
            len(PLOT_DAYS),
        ),
    ]

    print(f"June fit: A {june_mae_a:.3f} kWh, B {june_mae_b:.3f} kWh on {len(june_prev)} June days")
    print(f"chosen: model {chosen}")
    print(f"July 25 days: my model {model_miss:.3f} kWh ({model_pct:.2f}%)")
    print("13-17 July: date, plan, real, my model")
    for d in PLOT_DAYS:
        print(f"  {d}  {rows[d]['plan_kwh']:.0f}  {rows[d]['real_kwh']:.0f}  {pred[d]:.0f}")
    for name, ok, value in checks:
        print(f"  {'OK' if ok else 'WRONG'}  {name}  -> {value}")
    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        raise SystemExit(f"checks failed: {failed}")


if __name__ == "__main__":
    main()
