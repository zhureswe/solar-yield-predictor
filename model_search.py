import csv
import hashlib
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
TABLE = ROOT / "data" / "table.csv"
RESULTS = ROOT / "results"
SEP = RESULTS / "baselines_sep.csv"
SEARCH = RESULTS / "model_search_jul_aug.csv"
SEARCH_DAYS = RESULTS / "model_search_days.csv"
SEP_FORECAST = RESULTS / "model3_sep.csv"
PLOT = RESULTS / "plot_2026-09-01_05_model3.png"

SUN = "shortwave_radiation_sum"
CLOUD = "cloud_cover_mean"
TMAX = "temperature_2m_max"
START, END = "2026-07-01", "2026-08-31"
PLOT_DAYS = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05"]


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
            CLOUD: float(row[CLOUD]),
            TMAX: float(row[TMAX]),
        }
        for row in rows
    }


def clean_before(rows, day):
    return [d for d in sorted(rows) if d < day and rows[d]["note"] == ""]


def last_clean(rows, day):
    hist = clean_before(rows, day)
    return hist[-1] if hist else None


def lag_days(rows, day, n):
    return clean_before(rows, day)[-n:]


def yesterday(rows, day):
    return rows[last_clean(rows, day)]["real_kwh"]


def mean_last(rows, day, n):
    days = lag_days(rows, day, n)
    return sum(rows[d]["real_kwh"] for d in days) / len(days)


def yesterday_sun_ratio(rows, day):
    prev = last_clean(rows, day)
    return rows[prev]["real_kwh"] * rows[day][SUN] / rows[prev][SUN]


def ratio_median(rows, day, n):
    days = lag_days(rows, day, n)
    ratios = [rows[d]["real_kwh"] / rows[d][SUN] for d in days]
    return float(np.median(ratios)) * rows[day][SUN]


def feature_row(rows, day):
    prev = last_clean(rows, day)
    if prev is None:
        return None
    return [
        rows[prev]["real_kwh"],
        rows[day][SUN],
        rows[day][CLOUD],
        rows[day][TMAX],
    ]


def fit_line(rows, train_days):
    days = [d for d in train_days if feature_row(rows, d) is not None]
    X = np.array([feature_row(rows, d) for d in days])
    y = np.array([rows[d]["real_kwh"] for d in days])
    X = np.column_stack([np.ones(len(X)), X])
    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)

    def predict(day):
        return float(np.concatenate([[1.0], np.array(feature_row(rows, day))]) @ coef)

    return predict


class TinyForest:
    def __init__(self, n_trees=40, max_depth=4, min_leaf=3, seed=0):
        self.n_trees = n_trees
        self.max_depth = max_depth
        self.min_leaf = min_leaf
        self.seed = seed

    def fit(self, X, y):
        rng = random.Random(self.seed)
        n = len(y)
        self.trees = []
        for _ in range(self.n_trees):
            idx = [rng.randrange(n) for _ in range(n)]
            self.trees.append(self._build(np.asarray(X)[idx], np.asarray(y)[idx], rng, 0))
        return self

    def _build(self, X, y, rng, depth):
        if depth >= self.max_depth or len(y) < 2 * self.min_leaf or np.ptp(y) == 0:
            return ("leaf", float(np.mean(y)))
        k = max(1, int(np.sqrt(X.shape[1])))
        best = None
        for f in rng.sample(range(X.shape[1]), k):
            values = np.unique(X[:, f])
            if len(values) < 2:
                continue
            cuts = (values[:-1] + values[1:]) / 2
            if len(cuts) > 12:
                cuts = np.quantile(cuts, np.linspace(0.0, 1.0, 12))
            for cut in cuts:
                mask = X[:, f] <= cut
                left, right = int(mask.sum()), int((~mask).sum())
                if left < self.min_leaf or right < self.min_leaf:
                    continue
                sse = np.var(y[mask]) * left + np.var(y[~mask]) * right
                if best is None or sse < best[0]:
                    best = (sse, f, cut, mask)
        if best is None:
            return ("leaf", float(np.mean(y)))
        _, f, cut, mask = best
        return (
            "node",
            f,
            float(cut),
            self._build(X[mask], y[mask], rng, depth + 1),
            self._build(X[~mask], y[~mask], rng, depth + 1),
        )

    def _predict_one(self, node, x):
        while node[0] == "node":
            node = node[3] if x[node[1]] <= node[2] else node[4]
        return node[1]

    def predict(self, x):
        return float(np.mean([self._predict_one(tree, x) for tree in self.trees]))


def fit_forest(rows, train_days):
    days = [d for d in train_days if feature_row(rows, d) is not None]
    X = np.array([feature_row(rows, d) for d in days])
    y = np.array([rows[d]["real_kwh"] for d in days])
    forest = TinyForest().fit(X, y)

    def predict(day):
        return forest.predict(np.array(feature_row(rows, day)))

    return predict


LAG_MODELS = [
    ("1 yesterday", lambda rows, day: yesterday(rows, day)),
    ("2 mean of last 2 days", lambda rows, day: mean_last(rows, day, 2)),
    ("3 mean of last 3 days", lambda rows, day: mean_last(rows, day, 3)),
    (
        "4 yesterday x (tomorrow sun / yesterday sun)",
        lambda rows, day: yesterday_sun_ratio(rows, day),
    ),
    ("5 median(realsun) 3 days x tomorrow sun", lambda rows, day: ratio_median(rows, day, 3)),
    ("6a median(realsun) 5 days x tomorrow sun", lambda rows, day: ratio_median(rows, day, 5)),
    ("6b median(realsun) 7 days x tomorrow sun", lambda rows, day: ratio_median(rows, day, 7)),
    (
        "9 average of 1 and 5",
        lambda rows, day: 0.5 * (yesterday(rows, day) + ratio_median(rows, day, 3)),
    ),
]

FIT_MODELS = [
    ("7 straight line: yesterday real, sun, cloud, tmax", fit_line),
    ("8 small random forest: same 4 inputs", fit_forest),
]


def walk_days(rows):
    days = []
    day = date.fromisoformat(START)
    while day <= date.fromisoformat(END):
        key = day.isoformat()
        if key in rows:
            days.append(key)
        day += timedelta(days=1)
    return days


def fit_predictions(rows, train_days, targets, fitter):
    predict = fitter(rows, train_days)
    return {d: predict(d) for d in targets}


def mae(rows, days, pred):
    return sum(abs(pred[d] - rows[d]["real_kwh"]) for d in days) / len(days)


def md5_tree():
    return {
        path.name: hashlib.md5(path.read_bytes()).hexdigest()
        for path in sorted(RESULTS.iterdir())
        if path.name not in {SEP.name, SEARCH.name, SEARCH_DAYS.name, SEP_FORECAST.name, PLOT.name}
    }


def write_plot(rows, pred, yday):
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
        ("Yesterday", [yday[d] for d in days], (40, 150, 90)),
        ("My model 3", [pred[d] for d in days], (150, 40, 160)),
    ]
    for name, values, colour in series:
        points = [(x_of(i), y_of(v)) for i, v in enumerate(values)]
        draw.line(points, fill=colour, width=3)
        for px, py in points:
            draw.ellipse([(px - 4, py - 4), (px + 4, py + 4)], fill=colour)

    draw.text((left, top - 60), "Plan, real, yesterday and my model 3, 1-5 September 2026", font=f_title, fill=(20, 20, 20))
    draw.text(
        (left, top - 34),
        "Kargaly 42.866 N, 68.376 E; model chosen on July-August, tested once on September",
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
    sep_days = [d for d in sorted(rows) if d.startswith("2026-09")]
    if len(sep_days) != 30 or any(rows[d]["note"] for d in sep_days):
        raise SystemExit("September must be 30 days without a note")
    before_md5 = md5_tree()
    sep_csv_before = []
    with SEP.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        for row in reader:
            if row["forecast"] != "my model 3":
                sep_csv_before.append(row)

    days = walk_days(rows)
    scored = [d for d in days if rows[d]["note"] == ""]
    if any(d >= "2026-09-01" for d in days):
        raise SystemExit("the search must not see September")

    preds = {}
    for name, fn in LAG_MODELS:
        preds[name] = {d: fn(rows, d) for d in days}
    for name, fitter in FIT_MODELS:
        preds[name] = {d: fit_predictions(rows, clean_before(rows, d), [d], fitter)[d] for d in days}

    avg_scored = sum(rows[d]["real_kwh"] for d in scored) / len(scored)
    table = []
    for name in [n for n, _ in LAG_MODELS] + [n for n, _ in FIT_MODELS]:
        miss = mae(rows, scored, preds[name])
        table.append((name, miss, 100.0 * miss / avg_scored))
    table.sort(key=lambda item: item[1])
    chosen = table[0][0]

    writer_rows = [(rank + 1, name, miss, pct) for rank, (name, miss, pct) in enumerate(table)]
    with SEARCH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "model", "scored_days", "miss_kwh", "miss_pct"])
        for rank, name, miss, pct in writer_rows:
            writer.writerow([rank, name, len(scored), f"{miss:.3f}", f"{pct:.2f}"])

    with SEARCH_DAYS.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "note", "real_kwh"] + [name for name, _ in LAG_MODELS + FIT_MODELS])
        for d in days:
            writer.writerow(
                [d, rows[d]["note"], f"{rows[d]['real_kwh']:.3f}"]
                + [f"{preds[name][d]:.3f}" for name, _ in LAG_MODELS + FIT_MODELS]
            )

    if chosen in dict(LAG_MODELS):
        fn = dict(LAG_MODELS)[chosen]
        final = lambda day: fn(rows, day)
        sep_pred = {d: final(d) for d in sep_days}
    else:
        fitter = dict(FIT_MODELS)[chosen]
        train = clean_before(rows, "2026-09-01")
        if any(d >= "2026-09-01" for d in train):
            raise SystemExit("September leaked into the final learning set")
        sep_pred = fit_predictions(rows, train, sep_days, fitter)

    yday = {d: yesterday(rows, d) for d in sep_days}
    avg_real = sum(rows[d]["real_kwh"] for d in sep_days) / len(sep_days)
    sep_miss = mae(rows, sep_days, sep_pred)
    sep_pct = 100.0 * sep_miss / avg_real

    with SEP_FORECAST.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "real_kwh", "plan_kwh", "yesterday_kwh", "my_model3_kwh"])
        for d in sep_days:
            writer.writerow(
                [
                    d,
                    f"{rows[d]['real_kwh']:.3f}",
                    f"{rows[d]['plan_kwh']:.3f}",
                    f"{yday[d]:.3f}",
                    f"{sep_pred[d]:.3f}",
                ]
            )

    saved = [row for row in sep_csv_before]
    saved.append(
        {
            "forecast": "my model 3",
            "days": str(len(sep_days)),
            "avg_real_kwh": f"{avg_real:.3f}",
            "miss_kwh": f"{sep_miss:.3f}",
            "miss_pct": f"{sep_pct:.2f}",
        }
    )
    with SEP.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(saved)

    plot = write_plot(rows, sep_pred, yday)
    after_md5 = md5_tree()

    with SEP.open(newline="", encoding="utf-8") as f:
        sep_csv_after = list(csv.DictReader(f))

    min_pred = min(min(sep_pred.values()), min(min(p.values()) for p in preds.values()))
    checks = [
        ("table has 122 rows", len(rows) == 122, len(rows)),
        ("walk-forward days = 62", len(days) == 62, len(days)),
        ("scored days without a note = 51", len(scored) == 51, len(scored)),
        ("no September in the search days", max(days) < "2026-09-01", max(days)),
        ("September test days = 30, all clean", len(sep_days) == 30 and not any(rows[d]["note"] for d in sep_days), len(sep_days)),
        ("10 models ranked", len(table) == 10, len(table)),
        ("chosen = lowest July-August miss", all(table[0][1] <= other[1] for other in table), chosen),
        ("baselines_sep.csv now 5 rows", len(sep_csv_after) == 5, len(sep_csv_after)),
        (
            "other 4 rows unchanged",
            [(r["forecast"], r["days"], r["avg_real_kwh"], r["miss_kwh"], r["miss_pct"]) for r in sep_csv_after if r["forecast"] != "my model 3"]
            == [(r["forecast"], r["days"], r["avg_real_kwh"], r["miss_kwh"], r["miss_pct"]) for r in sep_csv_before],
            [r["forecast"] for r in sep_csv_after],
        ),
        (
            "saved my-model-3 miss = recomputed",
            abs(float(sep_csv_after[-1]["miss_kwh"]) - sep_miss) < 0.001 if sep_csv_after[-1]["forecast"] == "my model 3" else False,
            f"{sep_miss:.3f}",
        ),
        ("saved pct = miss / avg real", abs(float(sep_csv_after[-1]["miss_pct"]) - sep_pct) < 0.01, f"{sep_pct:.2f}%"),
        (
            "no other results file changed",
            before_md5 == after_md5,
            [name for name in before_md5 if before_md5[name] != after_md5.get(name)],
        ),
        ("model3 forecast CSV has 30 rows", len(sep_pred) == 30, len(sep_pred)),
        ("no negative forecast", min_pred >= 0, round(min_pred, 3)),
        ("plot written", plot.exists() and plot.stat().st_size > 5000, f"{plot.name} {plot.stat().st_size if plot.exists() else 0} B"),
        ("plot covers 1-5 September", all(d in sep_pred for d in PLOT_DAYS), len(PLOT_DAYS)),
    ]

    print(f"walk-forward {START}..{END}: {len(days)} days predicted, {len(scored)} without a note scored")
    print(f"{'model':<52}{'miss kWh':>12}{'%':>8}")
    for rank, (name, miss, pct) in enumerate(table, 1):
        print(f"{rank:>2} {name:<49}{miss:>12.3f}{pct:>7.2f}%")
    print(f"chosen: {chosen}")
    print(f"September, 30 days: {sep_miss:.3f} kWh ({sep_pct:.2f}% of {avg_real:.3f})")
    print("1-5 September: date, plan, real, yesterday, my model 3")
    for d in PLOT_DAYS:
        print(
            f"  {d}  {rows[d]['plan_kwh']:.0f}  {rows[d]['real_kwh']:.0f}  "
            f"{yday[d]:.0f}  {sep_pred[d]:.0f}"
        )
    for name, ok, value in checks:
        print(f"  {'OK' if ok else 'WRONG'}  {name}  -> {value}")
    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        raise SystemExit(f"checks failed: {failed}")


if __name__ == "__main__":
    main()
