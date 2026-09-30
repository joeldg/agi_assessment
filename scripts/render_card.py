#!/usr/bin/env python3
"""Render 1200x630 share cards with headless Chrome.

    python3 scripts/render_card.py                  # daily card for the latest run -> cards/<date>.png + cards/latest.png
    python3 scripts/render_card.py --date 2026-09-29
    python3 scripts/render_card.py --weekly 2026-10-02   # weekly card -> cards/weekly-<date>.png

Cards always use the dark palette so they look the same everywhere they're shared.
"""
import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_feed import fmt, prob  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DARK = {"bg": "#141A21", "surface": "#1B232C", "ink": "#E3E8ED", "muted": "#98A5B3", "axis": "#34414E",
        "accent": "#D9A441", "A": "#C4861A", "B": "#139A8C", "C": "#A36ED0", "D": "#DC564A", "Dopen": "#4F82DC"}
LABELS = {"A": "AGI undisclosed", "B": "Secret RSI", "C": "Covert AGI online", "D": "Covert govt influence"}


def dial_svg(value, S=420):
    c, r_out, r_in = S / 2, S * 0.27, S * 0.19
    eye = (f"M {S*.03} {c} C {S*.26} {S*.1}, {S*.74} {S*.1}, {S*.97} {c} "
           f"C {S*.74} {S*.9}, {S*.26} {S*.9}, {S*.03} {c} Z")
    lit = round(min(100, max(0, value)))
    ticks = []
    for i in range(100):
        a = i / 100 * 2 * math.pi - math.pi / 2
        on = i < lit
        ticks.append(f'<line x1="{c+math.cos(a)*r_in:.1f}" y1="{c+math.sin(a)*r_in:.1f}" x2="{c+math.cos(a)*r_out:.1f}" '
                     f'y2="{c+math.sin(a)*r_out:.1f}" stroke="{DARK["accent"] if on else DARK["axis"]}" '
                     f'stroke-width="{S*(.014 if on else .008):.1f}" stroke-linecap="round"/>')
    return (f'<svg width="{S}" height="{S*.66:.0f}" viewBox="0 {S*.17:.0f} {S} {S*.66:.0f}" xmlns="http://www.w3.org/2000/svg">'
            f'<defs><clipPath id="eye"><path d="{eye}"/></clipPath></defs><g clip-path="url(#eye)">{"".join(ticks)}</g>'
            f'<circle cx="{c}" cy="{c}" r="{r_in*.86:.1f}" fill="{DARK["bg"]}"/>'
            f'<path d="{eye}" fill="none" stroke="{DARK["ink"]}" stroke-width="{S*.018:.1f}" stroke-linejoin="round"/>'
            f'<text x="{c}" y="{c+S*.035:.1f}" text-anchor="middle" fill="{DARK["ink"]}" font-family="Public Sans" font-weight="600" font-size="{S*.1:.0f}">{fmt(value)}%</text></svg>')


def card_html(kicker, date_label, index, rows, footer):
    items = "".join(
        f'<div class="row"><span class="dot" style="background:{DARK[k]}"></span><span class="k">{k}</span>'
        f'<span class="lab">{escape(LABELS[k])}</span><span class="v">{escape(v)}</span>'
        f'<span class="d">{escape(d)}</span></div>' for k, v, d in rows)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,600&family=Public+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0}} html,body{{width:1200px;height:630px;overflow:hidden}}
body{{background:{DARK['bg']};color:{DARK['ink']};font-family:"Public Sans",system-ui,sans-serif;display:grid;grid-template-columns:470px 1fr;align-items:center;padding:48px 56px 40px 36px;position:relative}}
.kicker{{font-size:20px;letter-spacing:.14em;text-transform:uppercase;color:{DARK['muted']};font-weight:600}}
h1{{font-family:"Source Serif 4",Georgia,serif;font-size:44px;font-weight:600;margin:6px 0 2px}}
.idx{{font-size:22px;color:{DARK['muted']};margin-bottom:22px}} .idx b{{color:{DARK['ink']};font-size:30px}}
.row{{display:grid;grid-template-columns:18px 26px 1fr auto 120px;align-items:center;gap:10px;padding:9px 0;border-top:1px solid {DARK['axis']};font-size:22px}}
.dot{{width:14px;height:14px;border-radius:50%}} .k{{font-weight:600}} .lab{{color:{DARK['muted']}}}
.v{{font-weight:600;font-size:26px;text-align:right}} .d{{font-size:17px;color:{DARK['muted']};text-align:right}}
.foot{{position:absolute;left:56px;right:56px;bottom:26px;font-size:18px;color:{DARK['muted']};display:flex;justify-content:space-between}}
.foot b{{color:{DARK['ink']}}}
</style></head><body>
<div>{dial_svg(index)}</div>
<div><div class="kicker">{escape(kicker)}</div><h1>{escape(date_label)}</h1>
<div class="idx">Hidden AGI Index <b>{fmt(index)}%</b> · chance at least one is true now</div>{items}</div>
<div class="foot"><span>{escape(footer)}</span><span><b>joeldg.github.io/agi_assessment</b></span></div>
</body></html>"""


def shoot(html, out):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "card.html"
        src.write_text(html)
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1200,630",
                        "--virtual-time-budget=4000", f"--screenshot={out}", src.as_uri()],
                       check=True, capture_output=True)
    print("wrote", out.relative_to(ROOT))


def alarm_label():
    try:
        a = json.loads((ROOT / "data/alarm.json").read_text())
        lv = next(l for l in a["levels"] if l["level"] == a["current"]["level"])
        return f'{lv["icon"]} {lv["name"]}'
    except Exception:
        return None


def delta(cur, prev):
    if cur is None or prev is None:
        return "new"
    d = float(cur) - float(prev)
    return "no change" if abs(d) < 0.05 else ("▲ +" if d > 0 else "▼ −") + fmt(abs(d))


def daily(date=None):
    runs = json.loads((ROOT / "data/runs.json").read_text())
    idx = [i for i, r in enumerate(runs) if r.get("report") and (not date or r["date"] == date)]
    i = idx[-1]
    run, prev = runs[i], (runs[i - 1] if i else None)
    rows = [(k, fmt(prob(run, k, "now")) + "%", delta(prob(run, k, "now"), prob(prev, k, "now") if prev else None)) for k in LABELS]
    n = run.get("needle") or {}
    foot = ("Quiet day: nothing moved." if n.get("quiet") else f"Moved the needle: {n.get('headline','')}")[:92]
    label = datetime.strptime(run["date"], "%Y-%m-%d").strftime("%-d %B %Y")
    out = ROOT / "cards" / f"{run['date']}.png"
    out.parent.mkdir(exist_ok=True)
    lvl = alarm_label()
    shoot(card_html("Daily reading" + (f" · Fire alarm {lvl}" if lvl else " · Hidden AGI watch"), label, run.get("index", prob(run, "A", "now")), rows, foot), out)
    shutil.copyfile(out, ROOT / "cards/latest.png")
    return out


def weekly(date):
    w = json.loads((ROOT / f"data/weekly/{date}.json").read_text())
    k = w["keyNumbers"]
    rows = [(h, fmt(k["now"][h]) + "%", delta(k["now"][h], k["weekAgo"].get(h)) + " wk") for h in LABELS]
    label = "Week to " + datetime.strptime(date, "%Y-%m-%d").strftime("%-d %B %Y")
    out = ROOT / "cards" / f"weekly-{date}.png"
    out.parent.mkdir(exist_ok=True)
    shoot(card_html("Hidden AGI watch · weekly wrap-up", label, k["index"], rows, w.get("headline", "")[:92]), out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--weekly")
    a = ap.parse_args()
    weekly(a.weekly) if a.weekly else daily(a.date)
