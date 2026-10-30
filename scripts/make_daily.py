import csv
from datetime import date
from pathlib import Path

from make_hourly import parse_date, read_sheet

ROOT = Path(__file__).resolve().parents[1]
SYP = ROOT / "SYP"
OUT = ROOT / "data" / "daily.csv"

def fmt(value):
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.3f}"


def note_for(plan_kwh, real_kwh):
    if real_kwh < 0.10 * plan_kwh:
        return "outage"
    if plan_kwh < 0.10 * real_kwh:
        return "plan_zero"
    return ""


def read_month(path):
    sheet = read_sheet(path, "ImbalanceData")
    hdr_c = str(sheet.get((5, "C")) or "")
    hdr_g = str(sheet.get((5, "G")) or "")
    hdr_i = str(sheet.get((5, "I")) or "")
    if "Дата" not in hdr_c:
        raise ValueError(f"{path.name}: C5 is not a date header: {hdr_c!r}")
    if "Продажа" not in hdr_g:
        raise ValueError(f"{path.name}: G5 is not a plan header: {hdr_g!r}")
    if "Генерация" not in hdr_i:
        raise ValueError(f"{path.name}: I5 is not a real header: {hdr_i!r}")

    rows = []
    for r in range(6, 200):
        raw_date = sheet.get((r, "C"))
        if raw_date is None or str(raw_date).strip() == "":
            break
        d = parse_date(raw_date)
        plan_kwh = float(sheet.get((r, "G")) or 0)
        real_kwh = float(sheet.get((r, "I")) or 0)
        rows.append((d, plan_kwh, real_kwh, note_for(plan_kwh, real_kwh)))
    if not rows:
        raise ValueError(f"{path.name}: no data rows from row 6")
    return rows


def build():
    files = sorted(SYP.glob("план[- ]факт*.xlsx"))
    if len(files) != 4:
        raise ValueError(f"expected 4 plan-fact files, found {len(files)}: {files}")

    rows = []
    for path in files:
        rows.extend(read_month(path))
    rows.sort(key=lambda item: item[0])

    dates = [item[0] for item in rows]
    if len(set(dates)) != len(dates):
        raise ValueError("duplicate dates")
    if dates[0] != date(2026, 6, 1) or dates[-1] != date(2026, 9, 30):
        raise ValueError(f"date range {dates[0]}..{dates[-1]}")
    expected = (date(2026, 9, 30) - date(2026, 6, 1)).days + 1
    if len(rows) != expected:
        raise ValueError(f"{len(rows)} rows, expected {expected}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "plan_kwh", "real_kwh", "note"])
        for d, plan_kwh, real_kwh, note in rows:
            writer.writerow([d.isoformat(), fmt(plan_kwh), fmt(real_kwh), note])

    with OUT.open(newline="", encoding="utf-8") as f:
        got = list(csv.DictReader(f))
    if len(got) != len(rows):
        raise ValueError(f"CSV has {len(got)} rows, expected {len(rows)}")
    by_date = {r["date"]: r for r in got}

    def pair(day):
        r = by_date[day]
        return (int(r["plan_kwh"]), int(r["real_kwh"]))

    june_sum = sum(int(r["real_kwh"]) for r in got if r["date"].startswith("2026-06"))
    july_sum = sum(int(r["real_kwh"]) for r in got if r["date"].startswith("2026-07"))
    outage_days = [
        d["date"]
        for d in got
        if d["note"] == "outage" and d["date"].startswith("2026-07")
    ]
    plan_zero_days = [
        d["date"]
        for d in got
        if d["note"] == "plan_zero" and d["date"].startswith("2026-07")
    ]

    checks = [
        ("rows = 122", len(got) == 122, len(got)),
        (
            "outage 7-9 July",
            outage_days == ["2026-07-07", "2026-07-08", "2026-07-09"],
            outage_days,
        ),
        (
            "plan_zero 10-12 July",
            plan_zero_days == ["2026-07-10", "2026-07-11", "2026-07-12"],
            plan_zero_days,
        ),
    ]

    failed = [name for name, ok, _ in checks if not ok]
    print(f"wrote {OUT.relative_to(ROOT)}: {len(got)} rows from {len(files)} files")
    print("first 3 rows:")
    for r in got[:3]:
        print(f"  {r['date']},{r['plan_kwh']},{r['real_kwh']},{r['note']}")
    for name, ok, value in checks:
        print(f"  {'OK' if ok else 'WRONG'}  {name}  -> {value}")
    if failed:
        raise SystemExit(f"checks failed: {failed}")


if __name__ == "__main__":
    build()
