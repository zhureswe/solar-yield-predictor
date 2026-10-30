import csv
import json
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HOURLY = DATA / "hourly.csv"
OUT_JSON = DATA / "baselines_summary.json"
OUT_DAILY = DATA / "baselines_daily.csv"
OUT_HOURLY = DATA / "baselines_hourly.csv"
OUT_SUMMARY = DATA / "baselines_summary.csv"

BASELINES = (
    ("yesterday", "Yesterday's output"),
    ("median7", "Median of the last 7 days"),
    ("plan", "Plan the plant sent"),
)


def load_rows():
    with HOURLY.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    daily = []
    hourly = []
    for row in rows:
        ts = datetime.strptime(row["hour"], "%Y-%m-%d %H:%M")
        item = {
            "ts": ts,
            "produced": float(row["kWh produced"]),
            "planned": float(row["kWh planned"]),
        }
        if row["level"] == "daily":
            daily.append(item)
        elif row["level"] == "hourly":
            hourly.append(item)
    if not daily:
        raise RuntimeError("no daily rows")
    if not hourly:
        raise RuntimeError("no hourly rows")
    if len(hourly) % 24:
        raise RuntimeError(f"hourly rows are not whole days: {len(hourly)}")
    daily.sort(key=lambda item: item["ts"])
    hourly.sort(key=lambda item: item["ts"])
    return daily, hourly


def blocks_by_day(hourly):
    blocks = {}
    for item in hourly:
        day = item["ts"].date()
        if item["ts"].hour < 4:
            day -= timedelta(days=1)
        blocks.setdefault(day, []).append(item)
    for day, block in blocks.items():
        block.sort(key=lambda item: item["ts"])
        if len(block) != 24:
            raise RuntimeError(f"{day}: expected 24 hours, got {len(block)}")
    if not blocks:
        raise RuntimeError("no report days")
    return blocks


def summarize(pairs):
    if not pairs:
        return None
    errors = [forecast - actual for forecast, actual in pairs]
    return {
        "n": len(errors),
        "mae": round(sum(abs(value) for value in errors) / len(errors), 3),
        "bias": round(sum(errors) / len(errors), 3),
    }


def yesterday_value(day, daily_map):
    previous = day - timedelta(days=1)
    if previous not in daily_map:
        return None
    return daily_map[previous]["produced"]


def median7_value(day, daily_map):
    previous = [day - timedelta(days=offset) for offset in range(7, 0, -1)]
    if not all(item in daily_map for item in previous):
        return None
    return statistics.median(daily_map[item]["produced"] for item in previous)


def build_daily(daily, blocks):
    daily_map = {item["ts"].date(): item for item in daily}
    for day, block in blocks.items():
        if day in daily_map:
            raise RuntimeError(f"{day}: both daily and hourly totals")
        daily_map[day] = {
            "ts": datetime.combine(day, datetime.min.time()),
            "produced": sum(item["produced"] for item in block),
            "planned": sum(item["planned"] for item in block),
        }
    rows = []
    for day in sorted(daily_map):
        actual = daily_map[day]["produced"]
        plan = daily_map[day]["planned"]
        yesterday = yesterday_value(day, daily_map)
        median7 = median7_value(day, daily_map)
        rows.append(
            {
                "date": day,
                "actual": actual,
                "plan": plan,
                "yesterday": yesterday,
                "median7": median7,
            }
        )
    return rows


def baseline_block(rows, key):
    pairs = [
        (row[key], row["actual"]) for row in rows if row[key] is not None
    ]
    stats = summarize(pairs)
    if stats is None:
        return None
    return {
        "key": key,
        "label": dict(BASELINES)[key],
        "days": len(pairs),
        **stats,
    }


def build_hourly(blocks):
    days = sorted(blocks)
    rows = []
    for day in days:
        previous = day - timedelta(days=1)
        previous_block = blocks.get(previous)
        prior = []
        for offset in range(7, 0, -1):
            block = blocks.get(day - timedelta(days=offset))
            if block is None:
                prior = []
                break
            prior.append(block)
        for index, item in enumerate(blocks[day]):
            yesterday = (
                previous_block[index]["produced"] if previous_block else None
            )
            median7 = (
                statistics.median(block[index]["produced"] for block in prior)
                if prior
                else None
            )
            rows.append(
                {
                    "day": day,
                    "hour": item["ts"],
                    "actual": item["produced"],
                    "plan": item["planned"],
                    "yesterday": yesterday,
                    "median7": median7,
                }
            )
    return rows


def hourly_baseline(rows, key, days):
    selected = [row for row in rows if row["day"] in days]
    pairs = [
        (row[key], row["actual"]) for row in selected if row[key] is not None
    ]
    stats = summarize(pairs)
    if stats is None:
        reasons = {
            "yesterday": "needs a previous report day with 24 hourly rows",
            "median7": "needs 7 prior report days with 24 hourly rows",
            "plan": "no plan values",
        }
        return {
            "key": key,
            "label": dict(BASELINES)[key],
            "available": False,
            "days": 0,
            "hours": 0,
            "reason": reasons[key],
        }
    daily_misses = []
    for day in days:
        block = [row for row in selected if row["day"] == day]
        if not block or any(row[key] is None for row in block):
            continue
        forecast_total = sum(row[key] for row in block)
        actual_total = sum(row["actual"] for row in block)
        daily_misses.append(abs(forecast_total - actual_total))
    if not daily_misses:
        return {
            "key": key,
            "label": dict(BASELINES)[key],
            "available": False,
            "days": 0,
            "hours": 0,
            "reason": "no complete 24-hour days with this forecast",
        }
    return {
        "key": key,
        "label": dict(BASELINES)[key],
        "available": True,
        "days": len(daily_misses),
        "hours": stats["n"],
        "mae": stats["mae"],
        "bias": stats["bias"],
        "daily_miss": round(sum(daily_misses) / len(daily_misses), 3),
    }


def september_rows(daily_rows, hourly_rows, blocks):
    days = [day for day in sorted(blocks) if day.month == 9]
    output = []
    for day in days:
        daily = next(row for row in daily_rows if row["date"] == day)
        hourly = [row for row in hourly_rows if row["day"] == day]
        if len(hourly) != 24:
            raise RuntimeError(f"{day}: expected 24 hourly rows")
        plan_mae = sum(abs(row["plan"] - row["actual"]) for row in hourly) / 24
        plan_daily_miss = abs(daily["plan"] - daily["actual"])
        yesterday = daily["yesterday"]
        yesterday_mae = None
        yesterday_daily_miss = None
        if yesterday is not None:
            yesterday_mae = sum(
                abs(row["yesterday"] - row["actual"]) for row in hourly
            ) / 24
            yesterday_daily_miss = abs(yesterday - daily["actual"])
        median7 = daily["median7"]
        median7_mae = None
        median7_daily_miss = None
        if median7 is not None:
            median7_mae = sum(
                abs(row["median7"] - row["actual"]) for row in hourly
            ) / 24
            median7_daily_miss = abs(median7 - daily["actual"])
        output.append(
            {
                "date": day.isoformat(),
                "actual": round(daily["actual"], 3),
                "plan": round(daily["plan"], 3),
                "plan_miss": round(plan_daily_miss, 3),
                "plan_hourly_mae": round(plan_mae, 3),
                "yesterday": None if yesterday is None else round(yesterday, 3),
                "yesterday_miss": None
                if yesterday_daily_miss is None
                else round(yesterday_daily_miss, 3),
                "yesterday_hourly_mae": None
                if yesterday_mae is None
                else round(yesterday_mae, 3),
                "median7": None if median7 is None else round(median7, 3),
                "median7_miss": None
                if median7_daily_miss is None
                else round(median7_daily_miss, 3),
                "median7_hourly_mae": None
                if median7_mae is None
                else round(median7_mae, 3),
            }
        )
    return output


def write_daily(rows):
    with OUT_DAILY.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "date",
                "actual_kwh",
                "plan_kwh",
                "yesterday_kwh",
                "median7_kwh",
                "plan_abs_miss",
                "yesterday_abs_miss",
                "median7_abs_miss",
            ]
        )
        for row in rows:
            def cell(key):
                value = row[key]
                return "" if value is None else f"{value:.3f}"

            def miss(key):
                value = row[key]
                return (
                    ""
                    if value is None
                    else f"{abs(value - row['actual']):.3f}"
                )

            writer.writerow(
                [
                    row["date"].isoformat(),
                    f"{row['actual']:.3f}",
                    f"{row['plan']:.3f}",
                    cell("yesterday"),
                    cell("median7"),
                    miss("plan"),
                    miss("yesterday"),
                    miss("median7"),
                ]
            )


def write_hourly(rows):
    with OUT_HOURLY.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "report_day",
                "hour",
                "actual_kwh",
                "plan_kwh",
                "yesterday_kwh",
                "median7_kwh",
                "plan_abs_miss",
                "yesterday_abs_miss",
                "median7_abs_miss",
            ]
        )
        for row in rows:
            def cell(key):
                value = row[key]
                return "" if value is None else f"{value:.3f}"

            def miss(key):
                value = row[key]
                return (
                    ""
                    if value is None
                    else f"{abs(value - row['actual']):.3f}"
                )

            writer.writerow(
                [
                    row["day"].isoformat(),
                    row["hour"].strftime("%Y-%m-%d %H:%M"),
                    f"{row['actual']:.3f}",
                    f"{row['plan']:.3f}",
                    cell("yesterday"),
                    cell("median7"),
                    miss("plan"),
                    miss("yesterday"),
                    miss("median7"),
                ]
            )


def pretty(iso):
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%-d %b")


def write_summary(payload):
    daily_common = payload["daily_common"]
    hourly_common = payload["hourly_common"]
    daily_range = payload["daily_all_range"]
    hourly_range = payload["hourly_all_range"]
    with OUT_SUMMARY.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "scope",
                "granularity",
                "forecast",
                "days",
                "hours",
                "mae_kwh",
                "bias_kwh",
                "daily_miss_kwh",
                "note",
            ]
        )
        for baseline in daily_common["baselines"]:
            writer.writerow(
                [
                    f"same {daily_common['days']} days",
                    "daily",
                    baseline["label"],
                    baseline["days"],
                    0,
                    f"{baseline['mae']:.3f}",
                    f"{baseline['bias']:.3f}",
                    "",
                    f"{pretty(daily_common['start'])} - {pretty(daily_common['end'])}",
                ]
            )
        for baseline in hourly_common["baselines"]:
            writer.writerow(
                [
                    f"same {hourly_common['days']} days",
                    "hourly",
                    baseline["label"],
                    baseline["days"],
                    baseline["hours"],
                    f"{baseline['mae']:.3f}" if baseline["available"] else "",
                    f"{baseline['bias']:.3f}" if baseline["available"] else "",
                    f"{baseline['daily_miss']:.3f}"
                    if baseline["available"]
                    else "",
                    f"{pretty(hourly_common['start'])} - {pretty(hourly_common['end'])}"
                    if baseline["available"]
                    else baseline["reason"],
                ]
            )
        for baseline in payload["daily_all"]:
            writer.writerow(
                [
                    "all daily",
                    "daily",
                    baseline["label"],
                    baseline["days"],
                    0,
                    f"{baseline['mae']:.3f}",
                    f"{baseline['bias']:.3f}",
                    "",
                    f"{pretty(daily_range['start'])} - {pretty(daily_range['end'])}",
                ]
            )
        for baseline in payload["hourly_all"]:
            writer.writerow(
                [
                    "all hourly",
                    "hourly",
                    baseline["label"],
                    baseline["days"],
                    baseline["hours"],
                    f"{baseline['mae']:.3f}" if baseline["available"] else "",
                    f"{baseline['bias']:.3f}" if baseline["available"] else "",
                    f"{baseline['daily_miss']:.3f}"
                    if baseline["available"]
                    else "",
                    f"{pretty(hourly_range['start'])} - {pretty(hourly_range['end'])}"
                    if baseline["available"]
                    else baseline["reason"],
                ]
            )


def build():
    daily, hourly = load_rows()
    blocks = blocks_by_day(hourly)
    daily_rows = build_daily(daily, blocks)
    hourly_rows = build_hourly(blocks)

    common_daily = [
        row
        for row in daily_rows
        if row["yesterday"] is not None and row["median7"] is not None
    ]
    if len(common_daily) < 2:
        raise RuntimeError("not enough common daily days")

    hourly_days = sorted(blocks)
    common_hourly_days = [
        day
        for day in hourly_days
        if all(day - timedelta(days=offset) in blocks for offset in range(1, 8))
    ]
    if len(common_hourly_days) < 2:
        raise RuntimeError("not enough common hourly days")

    daily_common = {
        "start": common_daily[0]["date"].isoformat(),
        "end": common_daily[-1]["date"].isoformat(),
        "days": len(common_daily),
        "baselines": [
            baseline_block(common_daily, key) for key, _ in BASELINES
        ],
    }
    daily_all = [baseline_block(daily_rows, key) for key, _ in BASELINES]
    hourly_common = {
        "start": common_hourly_days[0].isoformat(),
        "end": common_hourly_days[-1].isoformat(),
        "days": len(common_hourly_days),
        "baselines": [
            hourly_baseline(hourly_rows, "yesterday", common_hourly_days),
            hourly_baseline(hourly_rows, "median7", common_hourly_days),
            hourly_baseline(hourly_rows, "plan", common_hourly_days),
        ],
    }
    hourly_all = [
        hourly_baseline(hourly_rows, "yesterday", hourly_days),
        hourly_baseline(hourly_rows, "median7", hourly_days),
        hourly_baseline(hourly_rows, "plan", hourly_days),
    ]
    plan_all = hourly_all[2]
    payload = {
        "daily_common": daily_common,
        "daily_all": daily_all,
        "hourly_common": hourly_common,
        "hourly_all": hourly_all,
        "daily_all_range": {
            "start": daily_rows[0]["date"].isoformat(),
            "end": daily_rows[-1]["date"].isoformat(),
        },
        "hourly_all_range": {
            "start": hourly_days[0].isoformat(),
            "end": hourly_days[-1].isoformat(),
        },
        "september_days": september_rows(daily_rows, hourly_rows, blocks),
        "coverage": {
            "daily": {
                "plan": daily_all[2]["days"],
                "yesterday": daily_all[0]["days"],
                "median7": daily_all[1]["days"],
            },
            "hourly": {
                "plan": plan_all["days"],
                "yesterday": hourly_all[0]["days"],
                "median7": hourly_all[1]["days"],
            },
        },
        "notes": [
            f"The daily table uses the {daily_common['days']} days ({pretty(daily_common['start'])} - {pretty(daily_common['end'])}) where yesterday, median-of-7 and the plan are all available.",
            f"The hourly table uses {hourly_common['days']} days ({pretty(hourly_common['start'])} - {pretty(hourly_common['end'])}) where yesterday, median-of-7 at each hour and the plan are all available.",
            "The hourly median-of-7 uses the same hour on the 7 prior report days.",
            f"Plan hourly on all {plan_all['days']} days: {plan_all['mae']:.1f} kWh/h and {plan_all['daily_miss']:,.0f} kWh/day.",
            "Four monthly reports (June-September) give 122 daily totals in data/monthly_daily.csv.",
            "August and September hourly totals match the monthly reports within 1 kWh per day.",
            "Daily total miss uses the 24-hour sums, so hourly misses in opposite directions can cancel.",
            "Bias is the mean signed miss (forecast minus actual); positive means the forecast was too high.",
        ],
    }

    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_daily(daily_rows)
    write_hourly(hourly_rows)
    write_summary(payload)

    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    print(
        f"daily common: {daily_common['days']} days, "
        f"{daily_common['start']} .. {daily_common['end']}"
    )
    for baseline in daily_common["baselines"]:
        print(
            f"  {baseline['label']}: MAE {baseline['mae']:.1f} kWh/day, "
            f"bias {baseline['bias']:+.1f}, {baseline['days']} days"
        )
    print(
        f"hourly common: {hourly_common['days']} days, "
        f"{hourly_common['start']} .. {hourly_common['end']}"
    )
    for baseline in hourly_common["baselines"]:
        if baseline["available"]:
            print(
                f"  {baseline['label']}: MAE {baseline['mae']:.1f} kWh/h, "
                f"bias {baseline['bias']:+.1f}, daily miss {baseline['daily_miss']:.1f}, "
                f"{baseline['days']} days"
            )
        else:
            print(f"  {baseline['label']}: not available hourly ({baseline['reason']})")
    print(
        f"coverage daily: plan {payload['coverage']['daily']['plan']}, "
        f"yesterday {payload['coverage']['daily']['yesterday']}, "
        f"median7 {payload['coverage']['daily']['median7']}"
    )
    print(
        f"coverage hourly: plan {payload['coverage']['hourly']['plan']}, "
        f"yesterday {payload['coverage']['hourly']['yesterday']}, "
        f"median7 {payload['coverage']['hourly']['median7']}"
    )
    print(
        f"wrote {OUT_DAILY.relative_to(ROOT)}, {OUT_HOURLY.relative_to(ROOT)}, "
        f"{OUT_SUMMARY.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    build()
