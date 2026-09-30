#!/usr/bin/env python3
"""Build a Friday weekly wrap-up from data/weekly/<date>.json plus the daily runs.

    python3 scripts/build_weekly.py 2026-10-02

The routine writes the editorial JSON (headline, summary, moves, section notes). This script
computes the key numbers from data/runs.json, stores them back in the JSON, renders
weekly/<date>.html, updates data/weekly/index.json, and exposes weekly_email_html() for Kit.
"""
import json
import sys
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_feed import (ACCENT, FONT, INK, MUTED, RULE, SANS, delta_cell, fmt, h2, link, p,  # noqa: E402
                        prob, ul)
from sitekit import SITE, page  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KEYS = ["A", "B", "C", "D", "Dopen"]
LABELS = {"A": "A: AGI undisclosed", "B": "B: Secret RSI", "C": "C: Covert AGI online",
          "D": "D: Covert govt influence", "Dopen": "D-open: Open govt influence"}
SECTIONS = [("scorecard", "Forecast scorecard", "scorecard.html"),
            ("lag", "Disclosure lag", "disclosure-lag.html"),
            ("claims", "AGI claims ledger", "agi-claims.html"),
            ("calendar", "Coming up", "calendar.html"),
            ("steelman", "Weekly steelman", "steelman.html"),
            ("trends", "Trend watch", "trends.html")]


def pretty(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%-d %B %Y")


def key_numbers(date):
    runs = [r for r in json.loads((ROOT / "data/runs.json").read_text()) if r["date"] <= date]
    if not runs:
        sys.exit("No daily runs on or before " + date)
    now = runs[-1]
    cutoff = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    older = [r for r in runs if r["date"] <= cutoff]
    ago = older[-1] if older else runs[0]
    tw = {"tripped": 0, "watching": 0, "quiet": 0}
    for w in now.get("tripwires", []):
        tw[w["status"]] += 1
    return {
        "asOf": now["date"], "weekAgoDate": ago["date"],
        "index": now.get("index"), "indexWeekAgo": ago.get("index"),
        "now": {k: prob(now, k, "now") for k in KEYS}, "weekAgo": {k: prob(ago, k, "now") for k in KEYS},
        "y2030": {k: prob(now, k, "y2030") for k in KEYS}, "y2035": {k: prob(now, k, "y2035") for k in KEYS},
        "tripwires": tw, "dailyRuns": len({r["date"] for r in runs if r["date"] > cutoff}),
    }


def tile(label, value, sub=""):
    return (f'<div class="tile"><div class="label">{escape(label)}</div><div class="value">{value}</div>'
            f'<div class="delta muted">{sub}</div></div>')


def wk_delta(cur, prev):
    if cur is None or prev is None:
        return "new this week"
    d = cur - prev
    return "no change this week" if abs(d) < 0.05 else f'{"▲ +" if d > 0 else "▼ −"}{fmt(abs(d))} pts this week'


def page_body(w):
    k = w["keyNumbers"]
    tiles = [tile("Hidden AGI Index", f'{fmt(k["index"])}%', wk_delta(k["index"], k["indexWeekAgo"]))]
    tiles += [tile(LABELS[h], f'{fmt(k["now"][h])}%', wk_delta(k["now"][h], k["weekAgo"][h])) for h in KEYS]
    tiles.append(tile("Tripwires", f'{k["tripwires"]["tripped"]} tripped',
                      f'{k["tripwires"]["watching"]} watching · {k["tripwires"]["quiet"]} quiet'))
    moves = "".join(
        f'<li><span class="rdate">{escape(m.get("date",""))}</span> <strong>{escape(m.get("hyp",""))}</strong> '
        f'{escape(m["text"])}{" <a href=" + chr(34) + escape(m["url"], quote=True) + chr(34) + " target=_blank rel=noopener>source</a>" if m.get("url") else ""}</li>'
        for m in w.get("moves", []))
    notes = w.get("sections", {})
    sec_html = ""
    for key, title, href in SECTIONS:
        chart = {"scorecard": '<div id="fc"></div>', "lag": '<div class="chart-wrap"><div id="lag"></div></div>',
                 "claims": '<div class="chart-wrap"><div id="claims"></div></div>',
                 "calendar": '<ul class="timeline-list" id="cal"></ul>', "steelman": "",
                 "trends": '<div class="chart-wrap"><div id="metr"></div></div>'}[key]
        sec_html += (f'\n  <section id="{key}"><h2>{title}</h2><p>{escape(notes.get(key, ""))}</p>{chart}'
                     f'<p class="small"><a href="../{href}">Full section →</a></p></section>')
    return f"""
  <header class="prose">
    <p class="kicker muted small">Weekly wrap-up · week to {pretty(w["date"])}</p>
    <h1>{escape(w["headline"])}</h1>
    <p class="lede">{escape(w.get("summary", ""))}</p>
  </header>
  <section aria-label="Key numbers"><div class="tiles">{"".join(tiles)}</div>
  <p class="muted small">Probability each is true now, comparing {pretty(k["asOf"])} with {pretty(k["weekAgoDate"])}. {k["dailyRuns"]} daily reading{"s" if k["dailyRuns"] != 1 else ""} this week. <a href="../start-here.html">How to read these</a>.</p></section>
  <section><h2>This week's moves</h2><ul class="plain">{moves or "<li>A quiet week: nothing moved.</li>"}</ul></section>
  <section><div class="chart-head"><h2>The readings over time</h2></div><div class="chart-wrap"><div id="trend"></div></div></section>{sec_html}
"""


def page_script(w):
    return """<script type="module">
import * as K from "../assets/charts.js";
const j = p => fetch(p,{cache:"no-cache"}).then(r=>r.json());
const [runs, fc, inc, cl, cal, tr] = await Promise.all(["../data/runs.json","../data/forecasts.json","../data/incidents.json","../data/agi_claims.json","../data/calendar.json","../data/trends.json"].map(j));
const M = tr.metr, fr = M.models.filter(m=>m.sota && m.date>="2023-01-01");
K.trendChart(document.getElementById("metr"), {title:"METR time horizon", color:"--accent", history: fr.map(m=>({date:m.date, v:m.p50, name:m.id+" · 50%"})), projection: M.p50.projection,
  secondary:{label:"80% horizon", color:"--ink", history: fr.filter(m=>m.p80).map(m=>({date:m.date, v:m.p80, name:m.id+" · 80%"})), projection: M.p80.projection},
  thresholds:[{v:M.thresholds.workWeek, label:"1 work-week"},{v:M.thresholds.workMonth, label:"1 work-month"}]});
const days = [...new Map(runs.filter(r=>r.date<=%(date)s).map(r=>[r.date,r])).values()];
K.lineChart(document.getElementById("trend"), {title:"Probability true now", series:[
  {label:"Hidden AGI Index", short:"Index", color:"--ink", values:days.map(r=>({x:r.date,y:r.index}))},
  ...["A","B","C","D"].map(k=>({label:K.SERIES[k].label, short:k, color:K.SERIES[k].color, values:days.map(r=>({x:r.date,y:r.probs?.[k]?.now}))}))]});
K.forecastBars(document.getElementById("fc"), fc.forecasts.filter(f=>f.outcome==null).sort((a,b)=>a.deadline.localeCompare(b.deadline)));
K.lagChart(document.getElementById("lag"), inc.incidents);
K.dotTimeline(document.getElementById("claims"), cl.claims, {title:"Public AGI claims"});
const h = K.util.h, list = document.getElementById("cal"), soon = new Date(%(date)s+"T12:00:00"); soon.setDate(soon.getDate()+45);
cal.events.filter(e=>e.date>=%(date)s && new Date(e.date+"T12:00:00")<=soon).forEach(e=>{ const li=h("li"); li.append(h("div",{class:"when"},K.util.fmtDate(e.date,{day:"numeric",month:"short"})), h("div",{},e.title)); list.append(li); });
if(!list.children.length) list.append(h("li",{},"Nothing dated in the next six weeks."));
</script>""".replace("%(date)s", json.dumps(w["date"]))


def weekly_email_html(w):
    k = w["keyNumbers"]
    url = f'{SITE}weekly/{w["date"]}.html'
    out = [p(f'<span style="color:{MUTED}">Weekly wrap-up · week to {pretty(w["date"])} · {link(url, "Read it on the web, with graphs")}</span>')]
    if (ROOT / f'cards/weekly-{w["date"]}.png').exists():
        out.append(f'<a href="{url}"><img src="{SITE}cards/weekly-{w["date"]}.png" width="600" alt="Weekly key numbers" '
                   f'style="display:block;width:100%;max-width:600px;height:auto;border:0;border-radius:8px;margin:8px 0 14px"></a>')
    out.append(f'<h1 style="{FONT}font-size:24px;color:{INK};margin:6px 0 8px">{escape(w["headline"])}</h1>')
    out.append(p(escape(w.get("summary", ""))))
    th = f'style="{SANS}font-size:13px;color:{MUTED};text-align:left;padding:6px 8px;border-bottom:1px solid {RULE}"'
    td = f'style="{SANS}font-size:14px;color:{INK};padding:6px 8px;border-bottom:1px solid {RULE}"'
    rows = [f"<tr><th {th}>Key number</th><th {th}>Now</th><th {th}>This week</th><th {th}>By 2030</th></tr>",
            f'<tr><td {td}><strong>Hidden AGI Index</strong></td><td {td}><strong>{fmt(k["index"])}%</strong></td>'
            f'<td {td}>{delta_cell(k["index"], k["indexWeekAgo"])}</td><td {td}>–</td></tr>']
    rows += [f'<tr><td {td}>{escape(LABELS[h])}</td><td {td}><strong>{fmt(k["now"][h])}%</strong></td>'
             f'<td {td}>{delta_cell(k["now"][h], k["weekAgo"][h])}</td><td {td}>{fmt(k["y2030"][h])}%</td></tr>' for h in KEYS]
    out.append(f'<table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;margin:6px 0 14px">{"".join(rows)}</table>')
    tw = k["tripwires"]
    out.append(p(f'<strong>Tripwires:</strong> {tw["tripped"]} tripped, {tw["watching"]} watching, {tw["quiet"]} quiet. '
                 f'{link(SITE + "#tripwires", "See them all")}.'))
    if w.get("moves"):
        out.append(h2("This week's moves"))
        out.append(ul(f'<strong>{escape(m.get("date",""))}</strong> {escape(m["text"])}'
                      + (" " + link(m["url"], "source") if m.get("url") else "") for m in w["moves"]))
    for key, title, href in SECTIONS:
        note = w.get("sections", {}).get(key)
        if note:
            out.append(h2(title))
            out.append(p(escape(note) + " " + link(SITE + href, "Full section")))
    out.append(p(f'{link(url, "See the full wrap-up with graphs")} · {link(SITE, "Today’s reading")}', "margin-top:22px"))
    out.append(p(f'Forwarded this? {link("https://hidden-agi.kit.com/f2b4d2f30e", "Subscribe to Hidden AGI watch")}. It\'s free.'))
    out.append(p(f'<span style="color:{MUTED};font-size:13px">Researched and drafted with AI assistance (Claude). '
                 f'Methodology and every source are public. Not investment, policy or security advice.</span>'))
    return "".join(out)


def build(date):
    src = ROOT / f"data/weekly/{date}.json"
    w = json.loads(src.read_text())
    w["date"] = date
    w["keyNumbers"] = key_numbers(date)
    src.write_text(json.dumps(w, indent=1, ensure_ascii=False) + "\n")
    import render_card
    render_card.weekly(date)
    card = f"{SITE}cards/weekly-{date}.png" if (ROOT / f"cards/weekly-{date}.png").exists() else None
    html = page(path=f"weekly/{date}.html", title=f"{w['headline']} · Weekly wrap-up · Hidden AGI watch",
                description=w.get("summary", "")[:200], body=page_body(w), active="weekly/",
                og_image=card, og_type="article", scripts=page_script(w))
    (ROOT / "weekly").mkdir(exist_ok=True)
    (ROOT / f"weekly/{date}.html").write_text(html)
    idx_path = ROOT / "data/weekly/index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else {"wrapups": []}
    idx["wrapups"] = [x for x in idx["wrapups"] if x["date"] != date] + [{"date": date, "headline": w["headline"]}]
    idx_path.write_text(json.dumps(idx, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote weekly/{date}.html")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: build_weekly.py YYYY-MM-DD")
    build(sys.argv[1])
