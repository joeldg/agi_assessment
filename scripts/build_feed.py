#!/usr/bin/env python3
"""Build feed.xml (RSS 2.0) from data/runs.json for RSS-to-email services such as Kit.

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
ROOT = Path(__file__).resolve().parent.parent
SERIES = [
    ("A", "A: AGI exists, undisclosed"),
    ("B", "B: Secret recursive self-improvement"),
    ("C", "C: Covert AGI-level actor online"),
    ("D", "D: AGI covertly influencing government"),
    ("Dopen", "D-open: AGI openly shaping government"),
]
MAX_ITEMS = 30

INK, MUTED, RULE, UP, DOWN = "#1C2733", "#5A6775", "#C9D0D7", "#A33A30", "#2D6A4F"
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


def issue_html(run, prev):
    report_url = SITE + run["report"]
    out = [p(f'<span style="color:{MUTED}">Daily reading of four hypotheses about hidden advanced AI. '
             f'Probabilities are subjective and sourced in the {link(report_url, "full report")}.</span>')]

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
    out.append(p(f'<span style="color:{MUTED};font-size:13px">Researched and drafted daily with AI assistance (Claude). '
                 f'Methodology and every source are public. Not investment, policy or security advice.</span>'))
    return "".join(out)


def cdata(s):
    return "<![CDATA[" + s.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def main():
    runs = json.loads((ROOT / "data/runs.json").read_text())
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
