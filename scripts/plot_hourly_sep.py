import csv
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
W, H = 1000, 560
GREEN, GREY, INK = (46, 125, 50), (68, 68, 68), (40, 40, 40)
GRID, LIGHT = (225, 225, 225), (110, 110, 110)

rows = {r["forecast"]: r for r in csv.DictReader(open("results/hourly_sep.csv"))}
mine = rows["my forecast (H4 mean of last 7 clean days)"]
plan = rows["plant plan"]
for r in (mine, plan):
    assert r["days"] == "30" and r["hours"] == "720" and r["producing_hours"] == "386", r

img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)
f_title = ImageFont.truetype(FONT, 30)
f_sub = ImageFont.truetype(FONT, 15)
f_ax = ImageFont.truetype(FONT, 13)
f_lab = ImageFont.truetype(FONT, 15)
f_val = ImageFont.truetype(FONT, 15)
f_note = ImageFont.truetype(FONT, 13)

d.text((90, 28), "September 2026 — average hourly miss", font=f_title, fill=INK)
d.text((90, 68), "30 days, 720 hours, 386 producing · miss = mean |forecast − real| per hour (kWh/h)",
       font=f_sub, fill=LIGHT)

panels = [
    (90, 130, 400, 310, "Miss, kWh/h", 50, 10, [("My hourly (H4)", float(mine["hourly_miss_kwh"]), GREEN),
                                                ("Plant plan", float(plan["hourly_miss_kwh"]), GREY)], "{:,.3f}"),
    (540, 130, 400, 310, "Producing hours within 10%, %", 75, 25, [("My hourly (H4)", float(mine["within10_pct"]), GREEN),
                                                                   ("Plant plan", float(plan["within10_pct"]), GREY)], "{:.1f}%"),
]
for x0, y0, pw, ph, ytitle, top, step, bars, fmt in panels:
    d.text((x0, y0 - 24), ytitle, font=f_lab, fill=INK)
    ticks = int(top / step)
    for i in range(ticks + 1):
        v = step * i
        y = y0 + ph - ph * i / ticks
        d.line((x0, y, x0 + pw, y), fill=GRID)
        d.text((x0 - 8, y - 7), f"{v:,.0f}", font=f_ax, fill=LIGHT, anchor="ra")
    d.line((x0, y0, x0, y0 + ph), fill=INK)
    d.line((x0, y0 + ph, x0 + pw, y0 + ph), fill=INK)
    bw = pw / (len(bars) * 2.2)
    for i, (label, v, colour) in enumerate(bars):
        cx = x0 + pw * (i + 0.5) / len(bars)
        bh = ph * v / top
        d.rectangle((cx - bw / 2, y0 + ph - bh, cx + bw / 2, y0 + ph), fill=colour)
        d.text((cx, y0 + ph - bh - 10), fmt.format(v), font=f_val, fill=INK, anchor="ms")
        d.text((cx, y0 + ph + 12), label, font=f_lab, fill=INK, anchor="ma")

d.text((90, 512), "Source: results/hourly_sep.csv · green = my forecast (H4 shape on yesterday's daily total), grey = plant plan",
       font=f_note, fill=LIGHT)
d.text((90, 532), f"Within 10%: {mine['within10_hours']} of {mine['producing_hours']} producing hours vs {plan['within10_hours']} of {plan['producing_hours']} for the plan",
       font=f_note, fill=LIGHT)

img.save("results/plot_hourly_sep.png")
print("saved results/plot_hourly_sep.png", img.size)
print("mine", mine["hourly_miss_kwh"], mine["within10_pct"], "plan", plan["hourly_miss_kwh"], plan["within10_pct"])
