#!/usr/bin/env python3
"""Build a Friday weekly wrap-up from data/weekly/<date>.json plus the daily runs.

    python3 scripts/build_weekly.py 2026-10-02
    python3 scripts/build_weekly.py 2026-10-02 --allow-stale        # build even if that day's daily isn't published
    python3 scripts/build_weekly.py 2026-10-02 --refresh-snapshot   # recompute the frozen chart data (rarely right)

The routine writes the editorial JSON (headline, summary, moves, section notes). This script
computes the key numbers from data/runs.json, stores them back in the JSON, renders
weekly/<date>.html, updates data/weekly/index.json, and exposes weekly_email_html() for Kit.

Key numbers compare published readings only (runs with a report, not marked "comparable": false),
one per date. With no reading 7 or more days back, the comparison is with the first published
reading and is labelled "since <date>", never "this week".

The chart data is frozen: snapshot() stores what each section showed as of the wrap-up date in the
JSON under "snapshot", computed once. The page draws only from that snapshot, so an archived
wrap-up never changes after publication. The standing pages are the live views.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_feed import (CORRECTIONS_SHOWN, FONT, INK, MUTED, RULE, SANS, abs_url, alarm_level_on, as_list,  # noqa: E402
                        changed, claim_date, corrections_box, data_table, delta_amount, delta_cell, email_footer, fmt,
                        gauge_delta, h2, link, nice_date, outlet, p, prob, source_link, th_attr, ul)
from sitekit import SITE, SUBSCRIBE, page  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KEYS = ["A", "B", "C", "D", "Dopen"]
LABELS = {"A": "A: AGI undisclosed", "B": "B: Secret RSI", "C": "C: Covert AGI online",
          "D": "D: Covert govt influence", "Dopen": "D-open: Open govt influence"}
SECTIONS = [("scorecard", "Forecast scorecard", "scorecard.html"),
            ("lag", "Disclosure lag", "disclosure-lag.html"),
            ("claims", "AGI claims ledger", "agi-claims.html"),
            ("calendar", "Coming up", "calendar.html"),
            ("steelman", "Weekly steelman", "steelman.html"),
            ("trends", "Trend watch", "trends.html"),
            ("money", "Follow the money", "money.html")]


def pretty(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%-d %B %Y")


def day_mon(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%-d %b")


def shift(date, days):
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def published_runs(upto):
    """Published, comparable readings dated on or before `upto`, one per date (the last entry wins), oldest first."""
    by_date = {}
    for r in json.loads((ROOT / "data/runs.json").read_text()):
        if r.get("report") and r.get("comparable") is not False and r["date"] <= upto:
            by_date[r["date"]] = r
    return [by_date[d] for d in sorted(by_date)]


def check_fresh(now, date, allow_stale):
    """True when the newest published reading predates the wrap-up; exits unless allow_stale."""
    if now["date"] == date:
        return False
    msg = f"the latest published reading is {now['date']}, not {date}, so the wrap-up's numbers would be stale"
    if not allow_stale:
        sys.exit(f"build_weekly: {msg}. Publish that day's daily first, or pass --allow-stale.")
    print(f"warning: {msg} (--allow-stale).", file=sys.stderr)
    return True


def week_corrections(week):
    """Corrections carried by the week's daily readings, each once, in order."""
    out = []
    for r in week:
        for c in as_list(r.get("corrections")):
            if isinstance(c, dict) and c not in out:
                out.append(c)
    return out


def key_numbers(date, allow_stale=False):
    runs = published_runs(date)
    if not runs:
        sys.exit("No published daily readings on or before " + date)
    now = runs[-1]
    stale = check_fresh(now, date, allow_stale)
    cutoff = shift(date, -7)
    older = [r for r in runs if r["date"] <= cutoff]
    ago = older[-1] if older else runs[0]  # no reading a week back: compare with the first published reading
    first = ago is now  # nothing earlier to compare with at all
    gkeys = [d["key"] for d in json.loads((ROOT / "data/gauges.json").read_text())["gauges"]]
    tw = {"tripped": 0, "watching": 0, "quiet": 0}
    for w in now.get("tripwires", []):
        tw[w["status"]] = tw.get(w["status"], 0) + 1
    week = [r for r in runs if r["date"] > cutoff]
    corrections = week_corrections(week)
    lv = alarm_level_on(now["date"], now)
    return {
        "asOf": now["date"], "weekAgoDate": ago["date"], "sinceFirst": not older, "firstReading": first, "stale": stale,
        "index": now.get("index"), "indexWeekAgo": None if first else ago.get("index"),
        "now": {k: prob(now, k, "now") for k in KEYS},
        "weekAgo": {k: None if first else prob(ago, k, "now") for k in KEYS},
        "y2030": {k: prob(now, k, "y2030") for k in KEYS}, "y2035": {k: prob(now, k, "y2035") for k in KEYS},
        "gauges": {k: (now.get("gauges") or {}).get(k) for k in gkeys},
        "gaugesWeekAgo": {k: None if first else ((ago.get("gauges") or {}).get(k) or {}).get("value") for k in gkeys},
        "tripwires": tw, "dailyRuns": len(week),
        "alarm": {x: lv[x] for x in ("level", "name", "icon", "meaning", "status") if x in lv} if lv else None,
        "corrections": corrections,
    }


def span_label(k):
    """What the change columns compare: 'this week', or 'since 29 Sep' when there's no reading a week back."""
    return "since " + day_mon(k["weekAgoDate"]) if k.get("sinceFirst") and not k.get("firstReading") else "this week"


def wk_delta(cur, prev, span="this week"):
    if cur is None:
        return "–"
    if prev is None:
        return "first reading"
    if not changed(cur, prev):
        return f"no change {span}"
    amt = delta_amount(cur, prev)
    return f'{"▲ +" if float(cur) > float(prev) else "▼ −"}{amt} {"pt" if amt == "1" else "pts"} {span}'


def gauge_change(g, prev_v, span="this week"):
    return gauge_delta((g or {}).get("value"), prev_v, " " + span)


def snapshot(date):
    """What each section shows as of `date`, frozen into the wrap-up's JSON so the archive never changes."""
    soon = shift(date, 45)

    def load(path, what):
        try:
            return json.loads((ROOT / path).read_text())
        except (OSError, ValueError) as e:
            print(f"warning: snapshot: can't read {path} ({e}); the {what} chart will show as unavailable.", file=sys.stderr)
            return None

    snap = {"date": date, "taken": datetime.now().strftime("%Y-%m-%d")}
    runs = load("data/runs.json", "trend") or []
    by_date = {}
    for r in runs:
        if r["date"] <= date:
            by_date[r["date"]] = r  # one point per day: the last entry of the day
    snap["trend"] = [dict({"date": d, "index": by_date[d].get("index")}, **{k: prob(by_date[d], k, "now") for k in "ABCD"})
                     for d in sorted(by_date)]
    fc = load("data/forecasts.json", "scorecard")
    if fc is not None:
        keep = ("id", "question", "p", "market", "made", "deadline", "resolution")
        snap["forecasts"] = sorted(
            (dict({x: f[x] for x in keep if x in f}, outcome=None, resolved=None)
             for f in fc.get("forecasts", [])
             if f.get("made", "") <= date and f.get("outcome") != "void"
             and (f.get("outcome") is None or (f.get("resolved") or "9999-12-31") > date)),
            key=lambda f: f.get("deadline", ""))
    inc = load("data/incidents.json", "disclosure-lag")
    if inc is not None:
        snap["incidents"] = [i for i in inc.get("incidents", []) if i.get("disclosed", "9999") <= date]
    cl = load("data/agi_claims.json", "claims")
    if cl is not None:
        snap["claims"] = [c for c in cl.get("claims", []) if c.get("date", "9999") <= date]
    cal = load("data/calendar.json", "calendar")
    if cal is not None:
        snap["calendar"] = sorted((e for e in cal.get("events", []) if date <= e.get("date", "") <= soon),
                                  key=lambda e: e["date"])
    tr = load("data/trends.json", "METR")
    if tr is not None and tr.get("metr"):
        M = tr["metr"]  # a refit can't be reproduced later, so the current fit is stored as-is
        snap["metr"] = {
            "models": [{x: m.get(x) for x in ("id", "date", "p50", "p50lo", "p50hi", "p80")}
                       for m in M.get("models", []) if m.get("sota") and "2023-01-01" <= m.get("date", "") <= date],
            "p50": {"projection": (M.get("p50") or {}).get("projection")},
            "p80": {"projection": (M.get("p80") or {}).get("projection")},
            "thresholds": M.get("thresholds"),
        }
    mo = load("data/money.json", "money")
    if mo is not None:
        snap["money"] = [row for row in mo.get("spendVsCapability", []) if row.get("end", "9999") <= date]
    return snap


def tile(label, value, sub=""):
    return (f'<div class="tile"><div class="label">{escape(label)}</div><div class="value">{value}</div>'
            f'<div class="delta muted">{sub}</div></div>')


def corrections_html(k):
    """The week's corrections on the wrap-up page. A correction's "date" is when it was made; the claim's
    own date comes from its page path (reports/YYYY-MM-DD.html). Long lists fold after CORRECTIONS_SHOWN."""
    items = []
    for c in k.get("corrections") or []:
        if not c.get("was") or not c.get("now"):
            continue
        said = claim_date(c)
        when = f'On {escape(nice_date(said))} we said' if said else "We said"
        fixed = f' (corrected {escape(nice_date(c["date"]))})' if c.get("date") else ""
        u = abs_url(c.get("url"))
        src = (f' (<a href="{escape(u, quote=True)}" target="_blank" rel="noopener">{escape(c.get("source") or outlet(u))}</a>)'
               if u else "")
        items.append(f'<li>{when} {escape(str(c["was"]).strip().rstrip("."))}. That was wrong{fixed}: '
                     f'{escape(str(c["now"]).strip().rstrip("."))}{src}.</li>')
    if not items:
        return ""
    shown, rest = items[:CORRECTIONS_SHOWN], items[CORRECTIONS_SHOWN:]
    more = (f'<details><summary>{len(rest)} more {"correction" if len(rest) == 1 else "corrections"}</summary>'
            f'<ul class="plain">{"".join(rest)}</ul></details>') if rest else ""
    return (f'\n  <section aria-label="Corrections"><div class="callout" style="border-left-color:var(--ink)">'
            f'<strong>{"Correction" if len(items) == 1 else "Corrections"} this week</strong><ul class="plain">{"".join(shown)}</ul>{more}'
            f'<p class="small muted">Every correction is logged on the <a href="../about.html#corrections">About page</a>.</p></div></section>')


def page_body(w):
    k = w["keyNumbers"]
    span = span_label(k)
    tiles = []
    lv = k.get("alarm")
    if lv:
        tiles.append(tile("Fire alarm", f'<span aria-hidden="true">{lv["icon"]}</span> {escape(lv["name"])}',
                          f'Level {lv["level"]} of 3 · <a href="../alarm.html">criteria</a>'))
    tiles += [tile("Hidden AGI Index", f'{fmt(k["index"])}%', wk_delta(k["index"], k["indexWeekAgo"], span))]
    tiles += [tile(LABELS[h], f'{fmt(k["now"][h])}%', wk_delta(k["now"][h], k["weekAgo"][h], span)) for h in KEYS]
    gdefs = {d["key"]: d for d in json.loads((ROOT / "data/gauges.json").read_text())["gauges"]}
    for gk, g in (k.get("gauges") or {}).items():
        if not g or gk not in gdefs:
            continue
        tiles.append(tile(gdefs[gk]["label"], escape(g.get("display") or fmt(g.get("value"))),
                          gauge_change(g, (k.get("gaugesWeekAgo") or {}).get(gk), span)))
    tiles.append(tile("Tripwires", f'{k["tripwires"]["tripped"]} tripped',
                      f'{k["tripwires"]["watching"]} watching · {k["tripwires"]["quiet"]} quiet'))

    def move_link(m):
        u = abs_url(m.get("url"))
        return (f' (<a href="{escape(u, quote=True)}" target="_blank" rel="noopener">{escape(m.get("source") or outlet(u))}</a>)'
                if u else "")

    moves = "".join(
        f'<li><span class="rdate">{escape(m.get("date", ""))}</span> <strong>{escape(m.get("hyp", ""))}</strong> '
        f'{escape(m["text"])}{move_link(m)}</li>'
        for m in w.get("moves", []))
    notes = w.get("sections", {})
    sec_html = ""
    for key, title, href in SECTIONS:
        chart = {"scorecard": '<div id="fc"></div>', "lag": '<div class="chart-wrap"><div id="lag"></div></div>',
                 "claims": '<div class="chart-wrap"><div id="claims"></div></div>',
                 "calendar": '<ul class="timeline-list" id="cal"></ul>', "steelman": "",
                 "trends": '<div class="chart-wrap"><div id="metr"></div></div>',
                 "money": '<div class="chart-wrap"><div id="money"></div></div>'}[key]
        sec_html += (f'\n  <section id="{key}"><h2>{title}</h2><p>{escape(notes.get(key, ""))}</p>{chart}'
                     f'<p class="small"><a href="../{href}">Full section (live) →</a></p></section>')
    if k.get("firstReading"):
        caption = f'Probability each is true now, as of {pretty(k["asOf"])}. This is our first full reading, so changes appear from the next wrap-up.'
    elif k.get("sinceFirst"):
        caption = f'Probability each is true now, comparing {pretty(k["asOf"])} with {pretty(k["weekAgoDate"])}, our first full reading.'
    else:
        caption = f'Probability each is true now, comparing {pretty(k["asOf"])} with {pretty(k["weekAgoDate"])}.'
    return f"""
  <header class="prose">
    <p class="kicker muted small">Weekly wrap-up · week to {pretty(w["date"])}</p>
    <h1>{escape(w["headline"])}</h1>
    <p class="lede">{escape(w.get("summary", ""))}</p>
  </header>{corrections_html(k)}
  <section aria-label="Key numbers"><div class="tiles">{"".join(tiles)}</div>
  <p class="muted small">{caption} {k["dailyRuns"]} daily reading{"s" if k["dailyRuns"] != 1 else ""} this week. <a href="../start-here.html">How to read these</a>.</p></section>
  <section><h2>This week's moves</h2><ul class="plain">{moves or "<li>A quiet week: nothing moved.</li>"}</ul></section>
  <section><div class="chart-head"><h2>The readings over time</h2></div><div class="chart-wrap"><div id="trend"></div></div></section>{sec_html}
  <p class="muted small">The charts on this page are frozen as of {pretty(w["date"])}, so this wrap-up reads the same later. The linked sections show the live data.</p>
"""


def page_script(w):
    """Draw every chart from the frozen snapshot, inlined in the page: no fetches, and one failed chart can't blank the rest."""
    snap = json.dumps(w.get("snapshot") or {}, ensure_ascii=False).replace("<", "\\u003c")
    return f'<script type="application/json" id="snap">{snap}</script>\n' + """<script type="module">
import * as K from "../assets/charts.js";
const S = JSON.parse(document.getElementById("snap").textContent || "{}");
const h = K.util.h;
const live = K.live || ((host, draw) => draw());
const safeHref = (K.util && K.util.safeHref) || K.safeHref || (u => /^https?:\\/\\//i.test(String(u ?? "").trim()) ? String(u).trim() : null);
const nm = id => String(id).replace(/_inspect$/,"").replace(/_/g," ").replace(/\\b(gpt|o\\d)\\b/gi,s=>s.toUpperCase()).replace(/\\bclaude\\b/i,"Claude").replace(/\\bgemini\\b/i,"Gemini");
const note = (el, text, cls="muted small") => { el.replaceChildren(h("p",{class:cls},text)); };
const chart = (id, draw) => {
  const el = document.getElementById(id); if(!el) return;
  const fail = e => { console.error(id, e); note(el, "Chart unavailable."); };
  const guarded = () => { try { return draw(el); } catch(e) { fail(e); } };
  try { live(el, guarded); } catch(e) { fail(e); }
};
const has = a => Array.isArray(a) && a.length > 0;
chart("trend", el => { if(!has(S.trend)) throw new Error("no readings in snapshot");
  K.lineChart(el, {title:"Probability true now", series:[
    {label:"Hidden AGI Index", short:"Index", color:"--ink", values:S.trend.map(r=>({x:r.date, y:r.index}))},
    ...["A","B","C","D"].map(k=>({label:K.SERIES[k].label, short:k, color:K.SERIES[k].color, values:S.trend.map(r=>({x:r.date, y:r[k]}))}))]}); });
chart("fc", el => { if(!Array.isArray(S.forecasts)) throw new Error("no forecasts in snapshot");
  const open = S.forecasts.filter(f => f.outcome !== "void");
  if(!open.length) return note(el, "No open forecasts as of this week.", "empty");
  K.forecastBars(el, open); });
chart("lag", el => { if(!Array.isArray(S.incidents)) throw new Error("no incidents in snapshot");
  if(!S.incidents.length) return note(el, "No disclosed incidents yet.", "empty");
  K.lagChart(el, S.incidents); });
chart("claims", el => { if(!Array.isArray(S.claims)) throw new Error("no claims in snapshot");
  if(!S.claims.length) return note(el, "No claims logged yet.", "empty");
  K.dotTimeline(el, S.claims, {title:"Public AGI claims"}); });
chart("metr", el => { const M = S.metr; if(!M || !has(M.models)) throw new Error("no METR data in snapshot");
  K.trendChart(el, {title:"METR time horizon", color:"--accent",
    history: M.models.map(m=>({date:m.date, v:m.p50, lo:m.p50lo, hi:m.p50hi, name:nm(m.id)+" · 50%"})), projection: M.p50 && M.p50.projection,
    secondary:{label:"80% horizon", color:"--ink", history: M.models.filter(m=>m.p80).map(m=>({date:m.date, v:m.p80, name:nm(m.id)+" · 80%"})), projection: M.p80 && M.p80.projection},
    thresholds: M.thresholds ? [{v:M.thresholds.workWeek, label:"1 work-week"},{v:M.thresholds.workMonth, label:"1 work-month"}] : []}); });
chart("money", el => { if(!has(S.money)) throw new Error("no money data in snapshot");
  K.lineChart(el, {title:"Spending vs capability, indexed", log:true, yFormat:v=>String(Math.round(v)), series:[
    {label:"Big-4 capex (index)", short:"Spend", color:"--accent", values:S.money.map(t=>({x:t.end, y:t.spend}))},
    {label:"METR-measured frontier horizon (index)", short:"Capability", color:"--ink", values:S.money.map(t=>({x:t.end, y:t.capability}))}]}); });
chart("cal", el => { if(!Array.isArray(S.calendar)) throw new Error("no calendar in snapshot");
  el.replaceChildren();
  S.calendar.forEach(e => { const li = h("li"), what = h("div"), u = safeHref(e.url);
    if(u){ const a = h("a",{href:u, target:"_blank", rel:"noopener"}, e.title); what.append(a); } else what.textContent = e.title;
    li.append(h("div",{class:"when"}, K.util.fmtDate(e.date,{day:"numeric",month:"short"})), what); el.append(li); });
  if(!el.children.length) el.append(h("li",{},"Nothing dated in the six weeks after this wrap-up.")); });
</script>"""


def weekly_email_html(w):
    k = w["keyNumbers"]
    span = span_label(k)
    url = f'{SITE}weekly/{w["date"]}.html'
    lv = k.get("alarm")
    out = [p(f'<span style="color:{MUTED}">Weekly wrap-up · week to {pretty(w["date"])} · {link(url, "Read it on the web, with graphs")}</span>')]
    out.append(corrections_box(k.get("corrections")))
    if (ROOT / f'cards/weekly-{w["date"]}.png').exists():
        alt = f'Week to {pretty(w["date"])}: Hidden AGI Index {fmt(k["index"])}%' + (
            f', fire alarm Level {lv["level"]} ({lv["name"]})' if lv else "")
        out.append(f'<a href="{url}"><img src="{SITE}cards/weekly-{w["date"]}.png" width="580" height="305" alt="{escape(alt, quote=True)}" '
                   f'style="display:block;width:100%;max-width:600px;height:auto;border:0;border-radius:8px;margin:8px 0 14px"></a>')
    if lv:
        out.append(p(f'<strong><span aria-hidden="true">{lv["icon"]}</span> Fire alarm: Level {lv["level"]}, {escape(lv["name"])}.</strong> '
                     f'<span style="color:{MUTED}">{escape(lv.get("meaning", ""))} {link(SITE + "alarm.html", "Criteria")}</span>'))
    out.append(f'<h1 style="{FONT}font-size:24px;color:{INK};margin:6px 0 8px">{escape(w["headline"])}</h1>')
    out.append(p(escape(w.get("summary", ""))))
    th = th_attr()
    td = f'style="{SANS}font-size:14px;color:{INK};padding:6px 8px;border-bottom:1px solid {RULE}"'
    rows = [f"<tr><th {th}>Key number</th><th {th}>Now</th><th {th}>{span[0].upper() + span[1:]}</th><th {th}>By 2030</th></tr>",
            f'<tr><td {td}><strong>Hidden AGI Index</strong></td><td {td}><strong>{fmt(k["index"])}%</strong></td>'
            f'<td {td}>{delta_cell(k["index"], k["indexWeekAgo"])}</td><td {td}><span style="color:{MUTED}">–</span></td></tr>']
    rows += [f'<tr><td {td}>{escape(LABELS[h])}</td><td {td}><strong>{fmt(k["now"][h])}%</strong></td>'
             f'<td {td}>{delta_cell(k["now"][h], k["weekAgo"][h])}</td><td {td}>{fmt(k["y2030"][h])}%</td></tr>' for h in KEYS]
    out.append(data_table(rows))
    if k.get("firstReading"):
        out.append(p(f'<span style="color:{MUTED};font-size:13px">This is our first full reading, so changes appear from the next wrap-up.</span>'))
    elif k.get("sinceFirst"):
        out.append(p(f'<span style="color:{MUTED};font-size:13px">Changes are since {pretty(k["weekAgoDate"])}, our first full reading.</span>'))
    gdefs = {d["key"]: d for d in json.loads((ROOT / "data/gauges.json").read_text())["gauges"]}
    gl = [f'<strong>{escape(gdefs[gk]["label"])}:</strong> {escape(g.get("display") or fmt(g.get("value")))} '
          f'({gauge_change(g, (k.get("gaugesWeekAgo") or {}).get(gk), span)})'
          for gk, g in (k.get("gauges") or {}).items() if g and gk in gdefs]
    if gl:
        out.append(p("<strong>The gauges.</strong> " + " · ".join(gl)))
    tw = k["tripwires"]
    out.append(p(f'<strong>Tripwires:</strong> {tw["tripped"]} tripped, {tw["watching"]} watching, {tw["quiet"]} quiet. '
                 f'{link(SITE + "#tripwires", "See them all")}.'))
    if w.get("moves"):
        out.append(h2("This week's moves"))
        out.append(ul(f'<strong>{escape(m.get("date", ""))}</strong> <strong>{escape(m.get("hyp", ""))}</strong> {escape(m["text"])}'
                      + source_link(m) for m in w["moves"]))
    for key, title, href in SECTIONS:
        note = w.get("sections", {}).get(key)
        if note:
            out.append(h2(title))
            out.append(p(escape(note) + " " + link(SITE + href, "Full section")))
    out.append(p(f'{link(url, "See the full wrap-up with graphs")} · {link(SITE, "Today’s reading")}', "margin-top:22px"))
    out.append(p(f'Forwarded this? {link(SUBSCRIBE, "Subscribe to Hidden AGI watch")}. It\'s free.'))
    out.append(email_footer("weekly"))
    return "".join(out)


def build(date, allow_stale=False, refresh_snapshot=False):
    src = ROOT / f"data/weekly/{date}.json"
    w = json.loads(src.read_text())
    w["date"] = date
    w["keyNumbers"] = key_numbers(date, allow_stale)
    if refresh_snapshot or "snapshot" not in w:
        if "snapshot" in w:
            print(f"note: replacing the frozen snapshot taken {w['snapshot'].get('taken', '?')} (--refresh-snapshot)")
        w["snapshot"] = snapshot(date)
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
    ap = argparse.ArgumentParser(description="Build the Friday wrap-up page, card and key numbers.")
    ap.add_argument("date", help="wrap-up date, YYYY-MM-DD")
    ap.add_argument("--allow-stale", action="store_true", help="build even if no daily reading is published for that date")
    ap.add_argument("--refresh-snapshot", action="store_true",
                    help="recompute the frozen chart snapshot; only to fix a broken snapshot, since it changes a published archive")
    a = ap.parse_args()
    build(a.date, a.allow_stale, a.refresh_snapshot)
