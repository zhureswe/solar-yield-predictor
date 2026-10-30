import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TABLE = ROOT / "data" / "table.csv"
OUT = ROOT / "results" / "cloud_rule.csv"
RESULTS = ROOT / "results"

THRESHOLDS = [10, 20, 30, 40]
SEL_START, SEL_END = "2026-07-01", "2026-08-31"
SEP_START, SEP_END = "2026-09-01", "2026-09-30"
YDAY_SEP_MISS = 512.600
PLAN_SEP_MISS = 1015.100
YDAY_SEL_MISS = 942.235
NOTE = "September was already seen, so the honest test is October."
FIELDS = [
    "scope",
    "forecast",
    "threshold_pct",
    "chosen",
    "days",
    "switch_days",
    "miss_kwh",
    "miss_pct",
    "accuracy_pct",
    "within10_days",
    "within10_pct",
    "note",
]


def read_rows():
    with TABLE.open(newline="", encoding="utf-8") as f:
        raw = list(csv.DictReader(f))
    if len(raw) != 122:
        raise SystemExit(f"{TABLE.name}: {len(raw)} rows, expected 122")
    rows = {}
    for row in raw:
        rows[row["date"]] = {
            "note": row["note"],
            "real": float(row["real_kwh"]),
            "plan": float(row["plan_kwh"]),
            "sun": float(row["shortwave_radiation_sum"]),
        }
    bad = [d for d, r in rows.items() if r["sun"] <= 0]
    if bad:
        raise SystemExit(f"sun <= 0 on {bad[:5]}")
    return rows


def in_scope(rows, start, end):
    return sorted(d for d in rows if start <= d <= end)


def score(rows, days, values):
    errors = [abs(values[d] - rows[d]["real"]) for d in days]
    mae = sum(errors) / len(errors)
    avg = sum(rows[d]["real"] for d in days) / len(days)
    within = 0
    for d in days:
        real = rows[d]["real"]
        if abs(values[d] - real) <= 0.10 * real:
            within += 1
    return {
        "miss_kwh": mae,
        "miss_pct": 100.0 * mae / avg,
        "accuracy_pct": 100.0 - 100.0 * mae / avg,
        "within10_days": within,
        "within10_pct": 100.0 * within / len(days),
    }


def prev_clean(clean, day):
    history = [d for d in clean if d < day]
    if not history:
        raise SystemExit(f"no clean day before {day}")
    return history[-1]


def make_forecast(rows, clean, days, threshold):
    values = {}
    switched = []
    for d in days:
        prev = prev_clean(clean, d)
        base = rows[prev]["real"]
        ratio = rows[d]["sun"] / rows[prev]["sun"]
        if ratio < 1.0 - threshold / 100.0:
            values[d] = base * ratio
            switched.append(d)
        else:
            values[d] = base
    return values, switched


def md5_others():
    return {
        p.name: hashlib.md5(p.read_bytes()).hexdigest()
        for p in sorted(RESULTS.iterdir())
        if p.name != OUT.name
    }


def route(scope, forecast, threshold, chosen, days, switched, metrics, note=""):
    return {
        "scope": scope,
        "forecast": forecast,
        "threshold_pct": "" if threshold is None else threshold,
        "chosen": chosen,
        "days": len(days),
        "switch_days": "" if switched is None else len(switched),
        "miss_kwh": round(metrics["miss_kwh"], 3),
        "miss_pct": round(metrics["miss_pct"], 2),
        "accuracy_pct": round(metrics["accuracy_pct"], 2),
        "within10_days": metrics["within10_days"],
        "within10_pct": round(metrics["within10_pct"], 1),
        "note": note,
    }


def main():
    rows = read_rows()
    clean = sorted(d for d, r in rows.items() if r["note"] == "")
    before = md5_others()

    sel_days = [d for d in in_scope(rows, SEL_START, SEL_END) if rows[d]["note"] == ""]
    sep_days = [d for d in in_scope(rows, SEP_START, SEP_END) if rows[d]["note"] == ""]
    if len(sel_days) != 51:
        raise SystemExit(f"July-August clean days: {len(sel_days)}, expected 51")
    if len(sep_days) != 30 or len(in_scope(rows, SEP_START, SEP_END)) != 30:
        raise SystemExit(f"September clean days: {len(sep_days)}, expected 30")

    base_values = {d: rows[prev_clean(clean, d)]["real"] for d in sel_days + sep_days}

    sel = []
    for threshold in THRESHOLDS:
        values, switched = make_forecast(rows, clean, sel_days, threshold)
        metrics = score(rows, sel_days, values)
        sel.append(
            {
                "threshold": threshold,
                "values": values,
                "switched": switched,
                "metrics": metrics,
            }
        )

    best_miss = min(round(item["metrics"]["miss_kwh"], 9) for item in sel)
    tied = [item["threshold"] for item in sel if round(item["metrics"]["miss_kwh"], 9) == best_miss]
    chosen_t = min(tied)
    chosen = next(item for item in sel if item["threshold"] == chosen_t)

    sep_values, sep_switched = make_forecast(rows, clean, sep_days, chosen_t)
    sep_cloud = score(rows, sep_days, sep_values)
    sep_yday = score(rows, sep_days, {d: base_values[d] for d in sep_days})
    sep_plan = score(rows, sep_days, {d: rows[d]["plan"] for d in sep_days})

    out_rows = [
        route("jul_aug", "cloud switch", item["threshold"], "yes" if item["threshold"] == chosen_t else "no", sel_days, item["switched"], item["metrics"])
        for item in sel
    ]
    out_rows += [
        route("sep", "cloud switch", chosen_t, "yes", sep_days, sep_switched, sep_cloud, NOTE),
        route("sep", "yesterday", None, "no", sep_days, None, sep_yday, NOTE),
        route("sep", "plant plan", None, "no", sep_days, None, sep_plan, NOTE),
    ]
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)

    after = md5_others()
    base_sel = score(rows, sel_days, {d: base_values[d] for d in sel_days})
    with OUT.open(newline="", encoding="utf-8") as f:
        written = list(csv.reader(f))
    widths = {len(r) for r in written}
    checks = [
        ("table rows = 122", len(rows) == 122, len(rows)),
        ("July-August clean days = 51", len(sel_days) == 51, len(sel_days)),
        ("September clean days = 30", len(sep_days) == 30, len(sep_days)),
        ("yesterday July-August miss = 942.235", abs(base_sel["miss_kwh"] - YDAY_SEL_MISS) < 0.001, f"{base_sel['miss_kwh']:.3f}"),
        ("chosen T is the lowest July-August miss", abs(chosen["metrics"]["miss_kwh"] - best_miss) < 1e-9, f"T={chosen_t} ({', '.join(str(t) for t in tied)} tied)"),
        ("non-switch days equal yesterday", all(
            item["values"][d] == base_values[d] for item in sel for d in sel_days if d not in item["switched"]
        ), True),
        ("September yesterday miss = 512.600", abs(sep_yday["miss_kwh"] - YDAY_SEP_MISS) < 0.001, f"{sep_yday['miss_kwh']:.3f}"),
        ("September plan miss = 1015.100", abs(sep_plan["miss_kwh"] - PLAN_SEP_MISS) < 0.001, f"{sep_plan['miss_kwh']:.3f}"),
        ("September cloud switch days = 0 for chosen T", len(sep_switched) == 0, len(sep_switched)),
        ("note says October", NOTE in {r["note"] for r in out_rows} and "October" in NOTE, NOTE),
        ("CSV 7 rows, 12 columns", len(written) - 1 == 7 and widths == {12}, f"{len(written) - 1} rows, {widths}"),
        ("no other results file changed", before == after, [n for n in before if before[n] != after.get(n)]),
    ]

    print(f"Walk-forward 1 Jul - 31 Aug: {len(sel_days)} clean days (11 note days excluded)")
    print(f"{'T':>3}%{'switch days':>13}{'miss kWh':>12}{'miss %':>9}{'accuracy':>10}{'within 10%':>13}")
    for item in sel:
        m = item["metrics"]
        print(
            f"{item['threshold']:>3}%{len(item['switched']):>13}{m['miss_kwh']:>12.3f}"
            f"{m['miss_pct']:>8.2f}%{m['accuracy_pct']:>9.2f}%"
            f"{m['within10_days']:>7}/{len(sel_days):<3}{m['within10_pct']:>4.0f}%"
        )
    tie_text = f"T={tied[0]} and T={tied[-1]} tie" if len(tied) > 1 else f"T={tied[0]} is alone"
    print(f"chosen T = {chosen_t}% ({tie_text}; smallest tied T taken)")
    print(f"switch dates: " + ", ".join(f"T={item['threshold']}%: {', '.join(item['switched']) or 'none'}" for item in sel))
    print()
    print(f"September: {len(sep_days)} days (already seen)")
    print(f"{'forecast':<24}{'switches':>9}{'miss kWh':>12}{'miss %':>9}{'accuracy':>10}{'within 10%':>13}")
    for name, m, sw in [
        (f"cloud rule T={chosen_t}%", sep_cloud, len(sep_switched)),
        ("yesterday", sep_yday, None),
        ("plant plan", sep_plan, None),
    ]:
        print(
            f"{name:<24}{'' if sw is None else sw:>9}{m['miss_kwh']:>12.3f}{m['miss_pct']:>8.2f}%"
            f"{m['accuracy_pct']:>9.2f}%{m['within10_days']:>7}/{len(sep_days):<3}{m['within10_pct']:>4.0f}%"
        )
    print(f"note: {NOTE}")
    for name, ok, value in checks:
        print(f"  {'OK' if ok else 'WRONG'}  {name}  -> {value}")
    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        raise SystemExit(f"checks failed: {failed}")


if __name__ == "__main__":
    main()
