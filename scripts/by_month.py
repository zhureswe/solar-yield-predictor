import csv

rows = list(csv.DictReader(open("data/daily.csv"))) + list(csv.DictReader(open("data/october_daily.csv")))
rows.sort(key=lambda r: r["date"])
for r in rows:
    r["plan_kwh"] = float(r["plan_kwh"])
    r["real_kwh"] = float(r["real_kwh"])
assert len(rows) == 149, len(rows)
assert len({r["date"] for r in rows}) == 149, "duplicate dates"

MONTHS = ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
NAMES = {"2026-06": "June", "2026-07": "July", "2026-08": "August",
         "2026-09": "September", "2026-10": "October"}
NOTES = {"2026-06": "1 June left out: no yesterday for either forecast",
         "2026-07": "7-12 July note days left out",
         "2026-08": "13, 14, 17 August outage and 18, 20 August plan_zero left out",
         "2026-09": "no note days",
         "2026-10": "4 October outage left out (data/october_daily.csv)"}


def last_clean(rows, i):
    if i > 0 and rows[i - 1]["note"] == "":
        return rows[i - 1]
    for j in range(i - 1, -1, -1):
        if rows[j]["note"] == "":
            return rows[j]
    return None


def score(pairs):
    days = len(pairs)
    avg_real = sum(real for _, real in pairs) / days
    miss = sum(abs(f - real) for f, real in pairs) / days
    within = sum(1 for f, real in pairs if abs(f - real) <= 0.10 * real)
    return days, avg_real, miss, 100 * miss / avg_real, 100 * within / days, within


out = []
print(f"{'month':10s} {'forecast':10s} {'days':>4s} {'avg real':>9s} {'miss':>9s} {'miss %':>7s} {'acc %':>7s} {'within 10%':>10s}")
for m in MONTHS:
    clean = [r for r in rows if r["date"].startswith(m) and r["note"] == ""]
    plan, yday = [], []
    for i, r in enumerate(rows):
        if not r["date"].startswith(m) or r["note"] != "":
            continue
        prev = last_clean(rows, i)
        if prev is None:
            continue
        plan.append((r["plan_kwh"], r["real_kwh"]))
        yday.append((prev["real_kwh"], r["real_kwh"]))
    assert len(plan) == len(yday), (m, len(plan), len(yday))
    for name, pairs in (("plan", plan), ("yesterday", yday)):
        days, avg_real, miss, pct, wpct, within = score(pairs)
        print(f"{NAMES[m]:10s} {name:10s} {days:4d} {avg_real:9.3f} {miss:9.3f} {pct:6.2f}% {100 - pct:6.2f}% {within:4d}/{days:<4d} {wpct:4.0f}%")
        out.append([f"{m}", name, days, f"{avg_real:.3f}", f"{miss:.3f}", f"{pct:.2f}",
                    f"{100 - pct:.2f}", within, f"{wpct:.2f}", NOTES[m]])

with open("results/by_month.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["month", "forecast", "days", "avg_real_kwh", "miss_kwh", "miss_pct",
                "accuracy_pct", "within10_days", "within10_pct", "note"])
    w.writerows(out)
print("wrote results/by_month.csv", len(out), "rows")
