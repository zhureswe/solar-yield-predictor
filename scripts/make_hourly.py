import csv
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DATA = ROOT / "data"
DAILY = DATA / "daily.csv"
OUT = DATA / "hourly.csv"
MONTHLY_OUT = DATA / "monthly_daily.csv"
PLOT_OUT = ROOT / "results" / "plot_2026-09-04.png"

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def col_name(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def read_sheet(path, sheet_name):
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {
            x.get("Id"): x.get("Target")
            for x in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        }
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            ss = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = [
                "".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t"))
                for si in ss.findall(f"{{{NS['m']}}}si")
            ]
        target = None
        for sh in wb.find(f"{{{NS['m']}}}sheets"):
            if sh.get("name") == sheet_name:
                target = rels[sh.get(f"{{{NS['r']}}}id")]
                break
        if target is None:
            raise ValueError(f"{path}: sheet {sheet_name!r} not found")
        if target.startswith("/"):
            target = target.lstrip("/")
        elif not target.startswith("xl/"):
            target = "xl/" + target
        root = ET.fromstring(z.read(target))
        out = {}
        for c in root.iter(f"{{{NS['m']}}}c"):
            ref = c.get("r")
            m = re.fullmatch(r"([A-Z]+)(\d+)", ref or "")
            if not m:
                continue
            col, row = m.group(1), int(m.group(2))
            v = c.find(f"{{{NS['m']}}}v")
            if v is not None:
                if c.get("t") == "s":
                    val = shared[int(v.text)]
                else:
                    try:
                        val = float(v.text)
                    except (TypeError, ValueError):
                        val = v.text
            else:
                is_ = c.find(f"{{{NS['m']}}}is")
                if is_ is not None:
                    val = "".join(
                        t.text or "" for t in is_.iter(f"{{{NS['m']}}}t")
                    )
                else:
                    val = None
            out[(row, col)] = val
        return out


def parse_date(text):
    text = str(text).strip()
    for fmt in ("%d.%m.%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"bad date {text!r}")


def file_date(path):
    name = path.name
    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})\.xlsx$", name)
    if iso:
        return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    dotted = re.search(r"(\d{1,2})\.(\d{2})\.(\d{2,4})\.xlsx$", name)
    if dotted:
        year = int(dotted.group(3))
        if year < 100:
            year += 2000
        return date(year, int(dotted.group(2)), int(dotted.group(1)))
    raise ValueError(f"no date in {name}")


def read_daily(path):
    sheet = read_sheet(path, "ImbalanceData")
    hdr_c = str(sheet.get((5, "C")) or "")
    hdr_g = str(sheet.get((5, "G")) or "")
    hdr_i = str(sheet.get((5, "I")) or "")
    if "Дата" not in hdr_c or "Продажа" not in hdr_g or "Генерация" not in hdr_i:
        raise ValueError(f"{path}: unexpected daily header")
    rows = []
    for r in range(6, 200):
        raw_date = sheet.get((r, "C"))
        if raw_date is None or str(raw_date).strip() == "":
            break
        d = parse_date(raw_date)
        produced = float(sheet.get((r, "I")) or 0)
        planned = float(sheet.get((r, "G")) or 0)
        rows.append((d, produced, planned))
    return rows


def read_report(path):
    sheet = read_sheet(path, "Лист1")
    if "Астана" not in str(sheet.get((6, "A")) or ""):
        raise ValueError(f"{path}: Astana header row not found")
    if "Среднеевропейско" not in str(sheet.get((7, "A")) or ""):
        raise ValueError(f"{path}: UTC+1 header row not found")
    if "Wакт. Отдача" not in str(sheet.get((8, "A")) or ""):
        raise ValueError(f"{path}: active output row not found")
    if "ИТОГО" not in str(sheet.get((10, "B")) or ""):
        raise ValueError(f"{path}: total row not found")
    report_date = parse_date(sheet.get((4, "C")))
    ends = []
    for i in range(24):
        v = sheet.get((6, col_name(5 + i)))
        if v is None:
            raise ValueError(f"{path}: missing Astana time header {col_name(5 + i)}6")
        ends.append(round(float(v) * 24))
    if ends != list(range(5, 29)):
        raise ValueError(f"{path}: unexpected Astana interval labels {ends}")
    ends_utc = []
    for i in range(24):
        v = sheet.get((7, col_name(5 + i)))
        if v is None:
            raise ValueError(f"{path}: missing UTC+1 time header {col_name(5 + i)}7")
        ends_utc.append(round(float(v) * 24))
    if ends_utc != list(range(1, 25)):
        raise ValueError(f"{path}: unexpected UTC+1 interval labels {ends_utc}")
    start_hour = ends[0] - 1
    if start_hour != 4:
        raise ValueError(f"{path}: report day does not start at 04:00 Astana")
    values = [
        float(sheet.get((10, col_name(5 + i))) or 0) for i in range(24)
    ]
    total = float(sheet.get((10, "D")) or 0)
    if abs(sum(values) - total) > 1e-6:
        raise ValueError(f"{path}: interval sum {sum(values)} != total {total}")
    return report_date, values, start_hour, total


def read_plan(path):
    sheet = read_sheet(path, "Карточки заявок")
    plan = {}
    for r in range(7, 31):
        label = str(sheet.get((r, "C")) or "").strip()
        m = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})", label)
        if not m:
            raise ValueError(f"{path}: bad plan label {label!r} in row {r}")
        start = int(m.group(1))
        if start in plan:
            raise ValueError(f"{path}: duplicate plan hour {start}")
        plan[start] = float(sheet.get((r, "D")) or 0) * 1000.0
    if set(plan) != set(range(24)):
        raise ValueError(f"{path}: plan has hours {sorted(plan)}")
    total_raw = str(sheet.get((32, "A")) or "")
    m = re.search(r"(\d[\d\s]*)\s*кВтч", total_raw)
    if not m:
        raise ValueError(f"{path}: plan total not found in A32")
    total = float(re.sub(r"\s", "", m.group(1)))
    if abs(sum(plan.values()) - total) > 1e-6:
        raise ValueError(f"{path}: plan sum {sum(plan.values())} != total {total}")
    return plan, total


def read_daily_csv(path):
    out = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["date"]] = (float(row["plan_kwh"]), float(row["real_kwh"]))
    if len(out) != 122:
        raise ValueError(f"{path}: {len(out)} rows, expected 122")
    return out


def write_plot(day, block):
    from PIL import Image, ImageDraw, ImageFont

    def font(size):
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    width, height = 1000, 560
    left, right, top, bottom = 90, 40, 70, 80
    plot_w = width - left - right
    plot_h = height - top - bottom
    real = [item[1] for item in block]
    plan = [item[2] for item in block]
    step = 200
    ymax = max(max(real), max(plan), 1)
    ymax = ((int(ymax) + step - 1) // step) * step

    def point(i, value):
        return (
            left + i / (len(block) - 1) * plot_w,
            top + plot_h - value / ymax * plot_h,
        )

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    f_title = font(22)
    f_axis = font(15)
    f_tick = font(13)
    f_leg = font(15)

    for value in range(0, ymax + 1, step):
        y = top + plot_h - value / ymax * plot_h
        draw.line([(left, y), (left + plot_w, y)], fill=(232, 232, 232))
        draw.text(
            (left - 12, y), str(value), font=f_tick, fill=(60, 60, 60), anchor="rm"
        )

    draw.line([(left, top), (left, top + plot_h)], fill=(80, 80, 80), width=2)
    draw.line(
        [(left, top + plot_h), (left + plot_w, top + plot_h)],
        fill=(80, 80, 80),
        width=2,
    )
    for i in range(0, len(block), 2):
        x = left + i / (len(block) - 1) * plot_w
        draw.line([(x, top + plot_h), (x, top + plot_h + 5)], fill=(80, 80, 80))
        draw.text(
            (x, top + plot_h + 10),
            block[i][0],
            font=f_tick,
            fill=(60, 60, 60),
            anchor="ma",
        )

    real_color = (30, 90, 200)
    plan_color = (220, 120, 20)
    draw.line([point(i, real[i]) for i in range(len(real))], fill=real_color, width=3)
    draw.line([point(i, plan[i]) for i in range(len(plan))], fill=plan_color, width=3)
    for i in range(len(real)):
        for value, color in ((real[i], real_color), (plan[i], plan_color)):
            x, y = point(i, value)
            draw.ellipse([(x - 2.5, y - 2.5), (x + 2.5, y + 2.5)], fill=color)

    title = f"Otrar solar, {day.strftime('%-d %B %Y')}"
    draw.text((left, top - 42), title, font=f_title, fill=(20, 20, 20))
    draw.text(
        (left, top - 20),
        "Report day 04:00 to 03:00, Astana UTC+5",
        font=f_axis,
        fill=(90, 90, 90),
    )
    draw.text((left + 6, top + 4), "kWh", font=f_axis, fill=(60, 60, 60))
    draw.text(
        (left + plot_w / 2, height - 24),
        "Hour start",
        font=f_axis,
        fill=(60, 60, 60),
        anchor="ma",
    )

    lx = left + plot_w - 190
    ly = top + 10
    draw.line([(lx, ly + 8), (lx + 30, ly + 8)], fill=real_color, width=3)
    draw.text((lx + 38, ly), "real", font=f_leg, fill=(40, 40, 40), anchor="lm")
    draw.line([(lx, ly + 30), (lx + 30, ly + 30)], fill=plan_color, width=3)
    draw.text((lx + 38, ly + 30), "plan", font=f_leg, fill=(40, 40, 40), anchor="lm")

    PLOT_OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(PLOT_OUT)
    return PLOT_OUT


def build():
    daily_map = read_daily_csv(DAILY)

    monthly_files = sorted(RAW.glob("imbalance_*.xlsx"))
    if len(monthly_files) != 4:
        raise ValueError(f"expected 4 monthly imbalance files, found {len(monthly_files)}")
    monthly_rows = []
    for path in monthly_files:
        for d, produced, planned in read_daily(path):
            monthly_rows.append((path.name, d, produced, planned))
    monthly_rows.sort(key=lambda item: item[1])
    if len(monthly_rows) != 122:
        raise ValueError(f"{len(monthly_rows)} monthly rows, expected 122")
    for source, d, produced, planned in monthly_rows:
        if d.isoformat() not in daily_map:
            raise ValueError(f"{d}: missing from daily.csv")
        daily_plan, daily_real = daily_map[d.isoformat()]
        if abs(planned - daily_plan) > 0.01 or abs(produced - daily_real) > 0.01:
            raise ValueError(f"{d}: monthly raw does not match daily.csv")

    with MONTHLY_OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "kWh produced", "kWh planned", "source"])
        for source, d, produced, planned in monthly_rows:
            writer.writerow(
                [d.isoformat(), f"{produced:.6f}", f"{planned:.3f}", source]
            )

    reports = {
        file_date(path): path
        for path in sorted(RAW.glob("otrar_daily_report_*.xlsx"))
    }
    plans = {
        file_date(path): path for path in sorted(RAW.glob("bid_cards_*.xlsx"))
    }
    if len(reports) != 61 or len(plans) != 61:
        raise ValueError(f"reports {len(reports)}, plans {len(plans)}, expected 61 each")
    if set(reports) != set(plans):
        raise ValueError("report and plan dates differ")
    first, last = date(2026, 8, 1), date(2026, 9, 30)
    if set(reports) != {
        first + timedelta(days=i) for i in range((last - first).days + 1)
    }:
        raise ValueError("report days are not all August-September")

    rows = []
    info = {}
    max_real_diff = 0.0
    max_plan_diff = 0.0
    for day in sorted(reports):
        report_date, values, start_hour, report_total = read_report(reports[day])
        if report_date != day:
            raise ValueError(f"{reports[day]}: date {report_date} != {day}")
        plan_by_start, plan_total = read_plan(plans[day])
        plan_map = {
            datetime.combine(day, time(0, 0)) + timedelta(hours=start + 4): value
            for start, value in plan_by_start.items()
        }
        block = []
        for i, produced in enumerate(values):
            ts = datetime.combine(day, time(start_hour, 0)) + timedelta(hours=i)
            if ts not in plan_map:
                raise ValueError(f"{plans[day]}: no plan for {ts}")
            planned = plan_map[ts]
            rows.append((day, ts.strftime("%H:%M"), produced, planned))
            block.append((ts.strftime("%H:%M"), produced, planned))
        real_sum = sum(item[1] for item in block)
        plan_sum = sum(item[2] for item in block)
        daily_plan, daily_real = daily_map[day.isoformat()]
        max_real_diff = max(max_real_diff, abs(real_sum - daily_real))
        max_plan_diff = max(max_plan_diff, abs(plan_sum - daily_plan))
        info[day] = (real_sum, plan_sum, report_total, plan_total)

    counts = Counter(item[0] for item in rows)
    if len(counts) != 61 or set(counts.values()) != {24}:
        raise ValueError(f"expected 61 days x 24 rows, got {len(counts)} days")

    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "hour_start", "real_kwh", "plan_kwh"])
        for day, hour_start, real, plan in rows:
            writer.writerow(
                [day.isoformat(), hour_start, f"{real:.6f}", f"{plan:.3f}"]
            )

    plot_block = [
        (hour_start, real, plan)
        for day, hour_start, real, plan in rows
        if day == date(2026, 9, 4)
    ]
    if len(plot_block) != 24:
        raise ValueError(f"4 Sep has {len(plot_block)} rows, expected 24")
    plot_path = write_plot(date(2026, 9, 4), plot_block)

    checks = [
        ("61 report days + 61 plan files", len(reports) == 61 and len(plans) == 61, f"{len(reports)} / {len(plans)}"),
        ("61 days, 2026-08-01..2026-09-30", len(counts) == 61, len(counts)),
        ("1,464 data rows", len(rows) == 1464, len(rows)),
        ("24 rows every day", set(counts.values()) == {24}, sorted(set(counts.values()))),
        (
            "real sum = D10 for all 61 days",
            all(abs(info[d][0] - info[d][2]) <= 1e-6 for d in info),
            f"max diff {max(abs(info[d][0] - info[d][2]) for d in info):.9f}",
        ),
        (
            "plan sum = A32 for all 61 days",
            all(abs(info[d][1] - info[d][3]) <= 1e-6 for d in info),
            f"max diff {max(abs(info[d][1] - info[d][3]) for d in info):.9f}",
        ),
        (
            "day sums vs daily.csv <= 1 kWh",
            max_real_diff <= 1.0 and max_plan_diff <= 1.0,
            f"real {max_real_diff:.6f}, plan {max_plan_diff:.6f}",
        ),
        (
            "4 Sep plot written",
            plot_path.exists() and plot_path.stat().st_size > 0,
            str(plot_path.relative_to(ROOT)),
        ),
    ]

    print(f"wrote {OUT.relative_to(ROOT)}: {len(rows)} rows, {len(counts)} days")
    print(f"wrote {MONTHLY_OUT.relative_to(ROOT)}: {len(monthly_rows)} rows")
    print(f"wrote {PLOT_OUT.relative_to(ROOT)}")
    failed = []
    for name, ok, value in checks:
        print(f"  {'OK' if ok else 'WRONG'}  {name}  -> {value}")
        if not ok:
            failed.append(name)
    if failed:
        raise SystemExit(f"checks failed: {failed}")


if __name__ == "__main__":
    build()
