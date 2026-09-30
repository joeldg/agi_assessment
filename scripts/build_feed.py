#!/usr/bin/env python3
"""Build feed.xml (RSS 2.0, for RSS-to-email via Kit) and sitemap.xml from data/runs.json.

Each run that has a full report becomes one item. The item's content:encoded holds an
email-ready HTML issue with inline styles only, since email clients ignore stylesheets.
Run from the repo root: python3 scripts/build_feed.py
"""
import json
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path

SITE = "https://joeldg.github.io/agi_assessment/"
SUBSCRIBE = "https://hidden-agi.kit.com/f2b4d2f30e"
ROOT = Path(__file__).resolve().parent.parent
SERIES = [
    ("A", "A: AGI exists, undisclosed"),
    ("B", "B: Secret recursive self-improvement"),
    ("C", "C: Covert AGI-level actor online"),
    ("D", "D: AGI covertly influencing government"),
    ("Dopen", "D-open: AGI openly shaping government"),
]
MAX_ITEMS = 30

INK, MUTED, RULE, UP, DOWN, ACCENT = "#1C2733", "#5A6775", "#C9D0D7", "#A33A30", "#2D6A4F", "#B8700C"
FONT = "font-family:Georgia,'Times New Roman',serif;"
SANS = "font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"


def fmt(v):
    if v is None:
        return "–"
    v = float(v)
    if v == 0:
        return "0"
    if v < 10 and v % 1:
        return f"{v:.1f}"
    return str(round(v))


def pretty_date(d):
    t = datetime.strptime(d, "%Y-%m-%d")
    return f"{t.day} {t.strftime('%B %Y')}"


def prob(run, k, h):
    p = (run.get("probs") or {}).get(k)
    return None if p is None else p.get(h)


def delta_cell(cur, prev):
    if cur is None or prev is None:
        return f'<span style="color:{MUTED}">new</span>'
    d = float(cur) - float(prev)
    if abs(d) < 0.05:
        return f'<span style="color:{MUTED}">no change</span>'
    color, arrow = (UP, "▲ +") if d > 0 else (DOWN, "▼ −")
    return f'<span style="color:{color};font-weight:600">{arrow}{fmt(abs(d))}</span>'


def h2(text):
    return (f'<h2 style="{FONT}font-size:20px;color:{INK};margin:28px 0 10px;'
            f'padding-top:10px;border-top:2px solid {INK}">{escape(text)}</h2>')


def p(text, style=""):
    return f'<p style="{SANS}font-size:15px;line-height:1.55;color:{INK};margin:0 0 10px;{style}">{text}</p>'


def ul(items):
    lis = "".join(f'<li style="margin:0 0 8px">{i}</li>' for i in items)
    return f'<ul style="{SANS}font-size:15px;line-height:1.5;color:{INK};padding-left:20px;margin:0 0 10px">{lis}</ul>'


def link(url, text):
    return f'<a href="{escape(url, quote=True)}" style="color:#4A6FA5">{escape(text)}</a>'


def gauges_html(run, prev):
    """Compact gauge table for email: reading, change vs the previous reading, what it measures."""
    defs = json.loads((ROOT / "data/gauges.json").read_text())["gauges"]
    th = f'style="{SANS}font-size:12px;color:{MUTED};text-align:left;padding:5px 8px;border-bottom:1px solid {RULE}"'
    td = f'style="{SANS}font-size:14px;color:{INK};padding:6px 8px;border-bottom:1px solid {RULE};vertical-align:top"'
    rows = [f"<tr><th {th}>Gauge</th><th {th}>Reading</th><th {th}>Change</th></tr>"]
    for d in defs:
        g = run["gauges"].get(d["key"])
        if not g:
            continue
        pg = ((prev or {}).get("gauges") or {}).get(d["key"])
        if pg and pg.get("value") is not None and g.get("value") is not None:
            dv = g["value"] - pg["value"]
            ch = "no change" if abs(dv) < 1e-9 else ("▲ " if dv > 0 else "▼ ") + fmt(abs(dv))
        else:
            ch = "first reading"
        rows.append(f'<tr><td {td}><strong>{escape(d["label"])}</strong><br><span style="color:{MUTED};font-size:12px">'
                    f'{escape(d["question"])}</span></td><td {td}><strong>{escape(g["display"])}</strong></td>'
                    f'<td {td}><span style="color:{MUTED}">{ch}</span></td></tr>')
    return (f'<div style="{SANS}font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:600;margin-top:10px">The four gauges</div>'
            f'<table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;margin:4px 0 12px">{"".join(rows)}</table>')


def issue_html(run, prev):
    report_url = SITE + run["report"]
    out = [p(f'<span style="color:{MUTED}">Daily reading of four hypotheses about hidden advanced AI. '
             f'Probabilities are subjective and sourced in the {link(report_url, "full report")}.</span>')]
    if (ROOT / "cards" / f"{run['date']}.png").exists():
        out.append(f'<a href="{SITE}"><img src="{SITE}cards/{run["date"]}.png" width="600" alt="Hidden AGI Index '
                   f'{fmt(run.get("index"))}% on {pretty_date(run["date"])}" style="display:block;width:100%;max-width:600px;'
                   f'height:auto;border:0;border-radius:8px;margin:8px 0 14px"></a>')
    alarm_path = ROOT / "data/alarm.json"
    if alarm_path.exists():
        a = json.loads(alarm_path.read_text())
        lv = next(l for l in a["levels"] if l["level"] == a["current"]["level"])
        col = {"good": "#2E7D4F", "warn": "#9A6B00", "crit": "#B42318"}[lv["status"]]
        out.append(p(f'<span style="color:{col};font-weight:600">{lv["icon"]} Fire alarm: Level {lv["level"]}, {lv["name"]}.</span> '
                     f'<span style="color:{MUTED}">{escape(lv["meaning"])} {link(SITE + "alarm.html", "How the alarm works")}</span>'))
    if run.get("index") is not None:
        out.append(p(f'<strong>Hidden AGI Index: {fmt(run["index"])}%</strong> '
                     f'{delta_cell(run["index"], prev.get("index") if prev else None)} '
                     f'<span style="color:{MUTED}">· the chance at least one hypothesis is true now. '
                     f'{link(SITE + "start-here.html", "What is this?")}</span>'))
    if run.get("gauges"):
        out.append(gauges_html(run, prev))
    n = run.get("needle")
    if n:
        kicker = "Quiet day" if n.get("quiet") else "What moved the needle"
        src = " " + link(n["url"], "source") if n.get("url") else ""
        out.append(f'<div style="border-left:4px solid {ACCENT};padding:8px 12px;margin:10px 0 16px;background:#F8F9FA">'
                   f'<div style="{SANS}font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:600">{kicker}</div>'
                   f'<div style="{FONT}font-size:18px;font-weight:600;color:{INK};margin:4px 0">{escape(n.get("headline",""))}</div>'
                   f'<div style="{SANS}font-size:14px;line-height:1.5;color:{INK}">{escape(n.get("detail",""))}{src}</div></div>')

    th = f'style="{SANS}font-size:13px;color:{MUTED};text-align:left;padding:6px 8px;border-bottom:1px solid {RULE}"'
    td = f'style="{SANS}font-size:14px;color:{INK};padding:6px 8px;border-bottom:1px solid {RULE};vertical-align:top"'
    rows = [f"<tr><th {th}>Hypothesis</th><th {th}>Now</th><th {th}>2030</th><th {th}>2035</th><th {th}>Change (now)</th></tr>"]
    for k, label in SERIES:
        now = prob(run, k, "now")
        rows.append(
            f"<tr><td {td}>{escape(label)}</td><td {td}><strong>{fmt(now)}%</strong></td>"
            f"<td {td}>{fmt(prob(run, k, 'y2030'))}%</td><td {td}>{fmt(prob(run, k, 'y2035'))}%</td>"
            f"<td {td}>{delta_cell(now, prob(prev, k, 'now') if prev else None)}</td></tr>")
    out.append(f'<table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;margin:6px 0 14px">{"".join(rows)}</table>')

    if run.get("summary"):
        out.append(p(escape(run["summary"])))
    if run.get("tripwires"):
        icon = {"tripped": ("●", "#B42318", "Tripped"), "watching": ("◐", "#9A6B00", "Watching"), "quiet": ("○", "#2E7D4F", "Quiet")}
        live = [w for w in run["tripwires"] if w["status"] != "quiet"]
        quiet = len(run["tripwires"]) - len(live)
        out.append(h2("Tripwires"))
        items = []
        for w in sorted(live, key=lambda w: 0 if w["status"] == "tripped" else 1):
            ic, col, lab = icon[w["status"]]
            items.append(f'<span style="color:{col};font-weight:600">{ic} {lab}</span> · <strong>{escape(w["signal"])}</strong>. '
                         f'<span style="color:{MUTED}">{escape(w.get("note",""))}</span>')
        out.append(ul(items))
        out.append(p(f'<span style="color:{MUTED}">{quiet} more quiet. {link(SITE + "#tripwires", "See all tripwires")}.</span>'))
    if run.get("changes"):
        out.append(h2("What changed"))
        out.append(ul(escape(c) for c in run["changes"]))
    if run.get("timeline"):
        out.append(h2("Timeline reassessment"))
        out.extend(p(escape(par)) for par in run["timeline"].split("\n\n"))
    if run.get("roundup"):
        out.append(h2("What happened"))
        if run.get("roundupWindow"):
            out.append(p(f'<span style="color:{MUTED}">Covering {escape(run["roundupWindow"])}.</span>'))
        for group in run["roundup"]:
            out.append(f'<h3 style="{FONT}font-size:17px;color:{INK};margin:16px 0 6px">{escape(group.get("topic", ""))}</h3>')
            items = []
            for it in group.get("items", []):
                date = f'<strong style="color:{MUTED}">{escape(it["date"])}</strong> ' if it.get("date") else ""
                src = " " + link(it["url"], "source") if str(it.get("url", "")).startswith("http") else ""
                items.append(date + escape(it.get("text", "")) + src)
            out.append(ul(items))
    if run.get("signals"):
        out.append(h2("Signals to watch"))
        out.append(ul(escape(s) for s in run["signals"]))

    out.append(p(f'{link(report_url, "Read the full report")} (definitions, evidence for and against, base rates, '
                 f'probabilities and what would change the estimates) · {link(SITE, "Dashboard and history")}',
                 "margin-top:22px"))
    out.append(p(f'Forwarded this? {link(SUBSCRIBE, "Subscribe to Hidden AGI watch")}. It\'s free.'))
    out.append(p(f'<span style="color:{MUTED};font-size:13px">Researched and drafted daily by a custom AI agent. '
                 f'Methodology and every source are public. Not investment, policy or security advice.</span>'))
    return "".join(out)


def cdata(s):
    return "<![CDATA[" + s.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def write_sitemap(runs):
    dates = {}
    for run in runs:
        if run.get("report"):
            dates[run["report"]] = max(dates.get(run["report"], ""), run["date"])
    latest = max((r["date"] for r in runs), default="")
    weekly_index = ROOT / "data/weekly/index.json"
    wraps = json.loads(weekly_index.read_text())["wrapups"] if weekly_index.exists() else []
    last_week = max((w["date"] for w in wraps), default=latest)
    urls = [(SITE, latest), (SITE + "weekly/", last_week)]
    urls += [(SITE + pg, last_week) for pg in ("start-here.html", "scorecard.html", "disclosure-lag.html",
                                               "agi-claims.html", "calendar.html", "steelman.html", "trends.html", "alarm.html", "style.html")]
    urls += [(SITE + f"weekly/{w['date']}.html", w["date"]) for w in sorted(wraps, key=lambda w: w["date"], reverse=True)]
    urls += sorted(((SITE + path, d) for path, d in dates.items()), key=lambda u: u[1], reverse=True)
    entries = "\n".join(
        f"  <url><loc>{escape(loc)}</loc>" + (f"<lastmod>{d}</lastmod>" if d else "") + "</url>"
        for loc, d in urls)
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n</urlset>\n")
    print(f"sitemap.xml: {len(urls)} URL(s)")


def main():
    runs = json.loads((ROOT / "data/runs.json").read_text())
    write_sitemap(runs)
    items = []
    for i, run in enumerate(runs):
        if not run.get("report"):
            continue  # quick baselines without a full report are not issues
        prev = runs[i - 1] if i > 0 else None
        published = datetime.strptime(run["date"], "%Y-%m-%d").replace(hour=13, tzinfo=timezone.utc)
        headline = " · ".join(f"{k} {fmt(prob(run, k, 'now'))}%" for k in ("A", "B", "C", "D"))
        url = SITE + run["report"]
        items.append((published, f"""    <item>
      <title>{escape(f"Hidden AGI watch, {pretty_date(run['date'])}: {headline}")}</title>
      <link>{escape(url)}</link>
      <guid isPermaLink="true">{escape(url)}</guid>
      <pubDate>{format_datetime(published)}</pubDate>
      <description>{escape(run.get("summary", ""))}</description>
      <content:encoded>{cdata(issue_html(run, prev))}</content:encoded>
    </item>"""))
    items.sort(key=lambda x: x[0], reverse=True)
    items = items[:MAX_ITEMS]
    built = items[0][0] if items else datetime.now(timezone.utc)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Hidden AGI watch</title>
    <link>{SITE}</link>
    <atom:link href="{SITE}feed.xml" rel="self" type="application/rss+xml"/>
    <description>Daily, calibrated probabilities on whether AGI, self-improving AI or covert AI actors already exist in secret. Evidence-rated and fully sourced.</description>
    <language>en</language>
    <image><url>{SITE}assets/brand/avatar.png</url><title>Hidden AGI watch</title><link>{SITE}</link></image>
    <lastBuildDate>{format_datetime(built)}</lastBuildDate>
{chr(10).join(i[1] for i in items)}
  </channel>
</rss>
"""
    (ROOT / "feed.xml").write_text(feed)
    print(f"feed.xml: {len(items)} item(s)")


if __name__ == "__main__":
    main()
