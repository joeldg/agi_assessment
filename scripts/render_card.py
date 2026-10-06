#!/usr/bin/env python3
"""Render 1200x630 share cards with headless Chrome.

    python3 scripts/render_card.py                  # daily card for the latest report -> cards/<date>.png + cards/latest.png
    python3 scripts/render_card.py --date 2026-09-29   # re-render one day; latest.png changes only if it's the newest report
    python3 scripts/render_card.py --weekly 2026-10-02   # weekly card -> cards/weekly-<date>.png

Cards always use the dark palette so they look the same everywhere they're shared. Each card shows the
fire-alarm level in force on its own date, with that level's meaning, so a screenshot carries the bottom line,
and, when Escape watch data exists for that date, one muted line with its counts.
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
from build_feed import SITE, alarm_level_on, changed, delta_amount, escape_for_run, fmt, prev_published, prob  # noqa: E402
from sitekit import HYP_LABELS, method_boundary  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DARK = {"bg": "#141A21", "surface": "#1B232C", "ink": "#E3E8ED", "muted": "#98A5B3", "axis": "#34414E",
        "accent": "#D9A441", "A": "#C4861A", "B": "#139A8C", "C": "#A36ED0", "D": "#DC564A", "Dopen": "#4F82DC"}
LABELS = {"A": "AGI undisclosed", "B": "Secret RSI", "C": "Covert AGI online", "D": "Covert govt influence"}
LABELS_V2 = {k: HYP_LABELS[k] for k in LABELS}  # format-2 readings and wrap-ups built with labelSet 2
METHOD_CELL = "method change"  # the card's narrow column; the note line says "definitions v2.0"
SITE_LABEL = SITE.split("://", 1)[-1].rstrip("/")
CHROME_TIMEOUT = 120  # seconds


def pct(v):
    return "–" if v is None else fmt(v) + "%"


def dial_svg(value, S=420):
    c, r_out, r_in = S / 2, S * 0.27, S * 0.19
    eye = (f"M {S*.03} {c} C {S*.26} {S*.1}, {S*.74} {S*.1}, {S*.97} {c} "
           f"C {S*.74} {S*.9}, {S*.26} {S*.9}, {S*.03} {c} Z")
    lit = 0 if value is None else round(min(100, max(0, float(value))))
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
            f'<text x="{c}" y="{c+S*.035:.1f}" text-anchor="middle" fill="{DARK["ink"]}" font-family="Public Sans" font-weight="600" font-size="{S*.1:.0f}">{pct(value)}</text></svg>')


def card_html(kicker, date_label, index, rows, footer, context="", note="", labels=None):
    labels = labels or LABELS
    items = "".join(
        f'<div class="row"><span class="dot" style="background:{DARK[k]}"></span><span class="k">{k}</span>'
        f'<span class="lab">{escape(labels[k])}</span><span class="v">{escape(v)}</span>'
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
.ctx{{border-top:1px solid {DARK['axis']};padding-top:12px;font-size:18px;line-height:1.35;color:{DARK['ink']}}}
.note{{margin-top:8px;font-size:17px;color:{DARK['muted']}}}
</style></head><body>
<div>{dial_svg(index)}</div>
<div><div class="kicker">{escape(kicker)}</div><h1>{escape(date_label)}</h1>
<div class="idx">Hidden AGI Index <b>{pct(index)}</b> · chance at least one is true now</div>{items}{f'<div class="ctx">{escape(context)}</div>' if context else ""}{f'<div class="note">{escape(note)}</div>' if note else ""}</div>
<div class="foot"><span>{escape(footer)}</span><span><b>{escape(SITE_LABEL)}</b></span></div>
</body></html>"""


def shoot(html, out):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "card.html"
        src.write_text(html)
        try:
            subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1200,630",
                            "--virtual-time-budget=4000", f"--screenshot={out}", src.as_uri()],
                           check=True, capture_output=True, timeout=CHROME_TIMEOUT)
        except subprocess.TimeoutExpired:
            sys.exit(f"render_card: headless Chrome timed out after {CHROME_TIMEOUT} s; {out.name} was not written.")
        except FileNotFoundError:
            sys.exit(f"render_card: Chrome not found at {CHROME}; {out.name} was not written.")
        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode(errors="replace").strip()[-600:]
            sys.exit(f"render_card: headless Chrome failed (exit {e.returncode}); {out.name} was not written.\n{err}")
    print("wrote", out.relative_to(ROOT))


def alarm_label(run):
    """(label, meaning) for the fire-alarm level in force on the run's date, or None before the alarm existed."""
    lv = alarm_level_on(run["date"], run)
    if not lv:
        return None
    return f'{lv["icon"]} {lv["name"]}', f'{lv["name"]}: {lv.get("meaning", "")}'.rstrip(": ")


def escape_note(s):
    """'Escape watch: 8 watching · 0 tripped' (quiet only when some are), or '' without Escape watch data."""
    if not s:
        return ""
    c = s["counts"]
    return f'Escape watch: {c["watching"]} watching · {c["tripped"]} tripped' + (f' · {c["quiet"]} quiet' if c["quiet"] else "")


def escape_note_v2(s):
    """'Escape watch: 0 of 8 confirmed · 8 open' (signal words of redesign v2), or '' without Escape watch data."""
    if not s:
        return ""
    c = s["counts"]
    return f'Escape watch: {c["tripped"]} of {s["total"]} confirmed · {c["watching"]} open'


def delta(cur, prev):
    if cur is None:
        return "–"
    if prev is None:
        return "first reading"
    if not changed(cur, prev):
        return "no change"
    return ("▲ +" if float(cur) > float(prev) else "▼ −") + delta_amount(cur, prev)


def v2_card_parts(run, prev):
    """(rows, footer, note) for a format-2 reading: v2 labels, "method change" instead of deltas for A, C and D on
    the boundary run (B keeps its delta), the AGI-parts line from the run's components snapshot and Escape watch
    from the run's own counts."""
    boundary = method_boundary(run, prev)
    rows = []
    for k in LABELS:
        cur = prob(run, k, "now")
        d = METHOD_CELL if boundary and k != "B" else delta(cur, prob(prev, k, "now") if prev else None)
        rows.append((k, pct(cur), d))
    n = run.get("needle") or {}
    sub = str(n.get("subject") or n.get("headline") or "").strip().rstrip(".")
    foot = (("Quiet day: " + sub if sub and not sub.lower().startswith("quiet") else sub or "Quiet day: nothing moved.")
            if n.get("quiet") else f"Moved the needle: {sub}")[:92]
    snap = run.get("components") or {}
    met = sum(1 for c in snap.values() if isinstance(c, dict) and c.get("status") == "met")
    bits = [f"AGI parts: {met} of 8 met"] if snap else []
    es = run.get("escape") if isinstance(run.get("escape"), dict) else {}
    if all(isinstance(es.get(k), (int, float)) for k in ("tripped", "watching", "quiet")):
        bits.append(f'Escape watch: {es["tripped"]} of {es["tripped"] + es["watching"] + es["quiet"]} confirmed')
    if boundary:
        bits.append("Method change: definitions v2.0, numbers re-derived, not news")
    return rows, foot, " · ".join(bits)


def daily(date=None):
    runs = json.loads((ROOT / "data/runs.json").read_text())
    reports = [i for i, r in enumerate(runs) if r.get("report")]
    idx = [i for i in reports if not date or runs[i]["date"] == date]
    if not idx:
        sys.exit(f"render_card: no run with a report for {date or 'any date'} in data/runs.json; nothing rendered.")
    i = idx[-1]
    run, prev = runs[i], prev_published(runs, i)
    if run.get("format") == 2:
        rows, foot, note = v2_card_parts(run, prev)
        label = datetime.strptime(run["date"], "%Y-%m-%d").strftime("%-d %B %Y")
        out = ROOT / "cards" / f"{run['date']}.png"
        out.parent.mkdir(exist_ok=True)
        lvl, meaning = alarm_label(run) or (None, "")
        shoot(card_html("Daily reading" + (f" · Fire alarm {lvl}" if lvl else " · Hidden AGI watch"), label,
                        run.get("index"), rows, foot, meaning, note, LABELS_V2), out)
        if i == reports[-1]:
            shutil.copyfile(out, ROOT / "cards/latest.png")
        else:
            print("note: not the newest report, so cards/latest.png was left unchanged")
        return out
    rows = [(k, pct(prob(run, k, "now")), delta(prob(run, k, "now"), prob(prev, k, "now") if prev else None)) for k in LABELS]
    n = run.get("needle") or {}
    foot = ("Quiet day: nothing moved." if n.get("quiet") else f"Moved the needle: {n.get('headline','')}")[:92]
    label = datetime.strptime(run["date"], "%Y-%m-%d").strftime("%-d %B %Y")
    out = ROOT / "cards" / f"{run['date']}.png"
    out.parent.mkdir(exist_ok=True)
    lvl, meaning = alarm_label(run) or (None, "")
    shoot(card_html("Daily reading" + (f" · Fire alarm {lvl}" if lvl else " · Hidden AGI watch"), label, run.get("index"),
                    rows, foot, meaning, escape_note(escape_for_run(run))), out)
    if i == reports[-1]:  # only the newest report updates the site-wide preview image
        shutil.copyfile(out, ROOT / "cards/latest.png")
    else:
        print("note: not the newest report, so cards/latest.png was left unchanged")
    return out


def weekly(date):
    w = json.loads((ROOT / f"data/weekly/{date}.json").read_text())
    k = w["keyNumbers"]
    since_first = k.get("sinceFirst") and k.get("weekAgo") and k.get("weekAgoDate") != k.get("asOf")

    boundary = weekly_boundary(k)

    def change(h):
        cur, prev = k["now"].get(h), (k.get("weekAgo") or {}).get(h)
        if boundary and h != "B" and cur is not None and prev is not None:
            return METHOD_CELL  # a definitions change inside the week is a method change, never a move (M8)
        d = delta(cur, prev)
        return d + " wk" if cur is not None and prev is not None and not since_first else d

    rows = [(h, pct(k["now"].get(h)), change(h)) for h in LABELS]
    v2 = (w.get("snapshot") or {}).get("labelSet") == 2
    labels = LABELS_V2 if v2 else LABELS
    note = escape_note_v2(k.get("escape")) if v2 else escape_note(k.get("escape"))
    if boundary:
        news = k.get("news") if isinstance(k.get("news"), dict) else {}
        moved = [f'{"D-open" if h == "Dopen" else h} {"▲ +" if v > 0 else "▼ −"}{fmt(abs(v))}'
                 for h, v in news.items() if h in ("A", "C", "D") and isinstance(v, (int, float)) and v]
        note = ("Method change this week: definitions v2.0, numbers re-derived, not news"
                + (f" · news moves: {', '.join(moved)}" if moved else "") + (f" · {note}" if note else ""))
    label = "Week to " + datetime.strptime(date, "%Y-%m-%d").strftime("%-d %B %Y")
    kicker = ("Weekly wrap-up · change since " + datetime.strptime(k["weekAgoDate"], "%Y-%m-%d").strftime("%-d %b")
              if since_first else "Hidden AGI watch · weekly wrap-up")
    lv = k.get("alarm") or alarm_level_on(k.get("asOf") or date)
    meaning = f'{lv["name"]}: {lv.get("meaning", "")}'.rstrip(": ") if lv else ""
    out = ROOT / "cards" / f"weekly-{date}.png"
    out.parent.mkdir(exist_ok=True)
    shoot(card_html(kicker, label, k.get("index"), rows, w.get("headline", "")[:92], meaning, note, labels), out)
    return out


def weekly_boundary(k):
    """True when the definitions changed inside the week: the wrap-up's own flag, else method_boundary of the two
    readings' definitions (missing = "1.0"). Never on a first reading or a wrap-up without a week-ago reading."""
    if k.get("firstReading") or not k.get("weekAgo"):
        return False
    if isinstance(k.get("methodBoundary"), bool):
        return k["methodBoundary"]
    return method_boundary({"defs": k.get("defs")}, {"defs": k.get("defsWeekAgo")})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--weekly")
    a = ap.parse_args()
    weekly(a.weekly) if a.weekly else daily(a.date)
