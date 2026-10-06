#!/usr/bin/env python3
"""Build feed.xml (RSS 2.0) and sitemap.xml from data/runs.json, and define the daily email body
that scripts/kit_broadcast.py sends through the Kit API (Kit's RSS-to-email is a paid feature and
is not used; the feed is for feed readers).

Each run that has a full report becomes one feed item. A rerun or correction that repeats a report
path replaces the earlier entry. The item's content:encoded holds the email-ready HTML issue, with
inline styles only, since email clients ignore stylesheets. The helpers here (fmt, changed,
prev_published, alarm_level_on, source_link, email_footer, escape_for_run, ...) are shared with render_card.py,
build_weekly.py and kit_broadcast.py.
Run from the repo root: python3 scripts/build_feed.py
"""
import json
import re
import sys
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from email.utils import format_datetime
from html import escape
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sitekit import SITE, SUBSCRIBE  # noqa: E402  (one source of truth for both URLs)

ROOT = Path(__file__).resolve().parent.parent
# Feed item identity. Never change it, even if the site moves: GUIDs stay FEED_GUID_BASE + report path.
FEED_GUID_BASE = "https://joeldg.github.io/agi_assessment/"
ISSUES = "https://github.com/joeldg/agi_assessment/issues"
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
# What each gauge measures, for the email's one-line gauge strip (the site's pages carry the full questions).
GAUGE_GLOSS = {"gap": "Capability gap, unreleased over public models", "rd": "A lab's AI-led share of its AI R&D",
               "oversight": "Disclosure lag, incident to public", "money": "Big Tech capex, all property and equipment",
               "delegation": "Government delegation to AI"}


def _q(v, places):
    return Decimal(str(v)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def fmt(v):
    """Display precision, rounded half-up: 2 decimals below 1, 1 decimal below 10, whole numbers above.
    Values that round up to the next band roll over (0.996 -> '1', 9.96 -> '10'). assets/charts.js fmtNum mirrors this."""
    if v is None:
        return "–"
    v = float(v)
    if v == 0:
        return "0"
    a = abs(v)
    places = 2 if a < 1 else 1 if a < 10 else 0
    q = _q(a, places)
    while places and q >= (1 if places == 2 else 10):
        places -= 1
        q = _q(a, places)
    s = format(q.normalize(), "f")
    return s if v > 0 or s == "0" else "-" + s


def changed(cur, prev):
    """A move counts only if the two displayed numbers differ, so the figures and the delta always agree."""
    return fmt(cur) != fmt(prev)


def delta_amount(cur, prev):
    return fmt(round(abs(float(cur) - float(prev)), 6))


def pretty_date(d):
    t = datetime.strptime(d, "%Y-%m-%d")
    return f"{t.day} {t.strftime('%B %Y')}"


def nice_date(d):
    try:
        return pretty_date(str(d))
    except ValueError:
        return str(d or "")


def prob(run, k, h):
    p = ((run or {}).get("probs") or {}).get(k)
    return None if p is None else p.get(h)


def as_list(x):
    """A list field the routine might have written as a single string."""
    if not x:
        return []
    return [x] if isinstance(x, str) else list(x)


def prev_published(runs, i):
    """The reading that runs[i] is compared with: the latest earlier entry that has a report, isn't marked
    "comparable": false (e.g. the 29 Sep chat baseline), and isn't an earlier copy of the same report
    (a rerun or correction). None means runs[i] is the first published reading."""
    rep = runs[i].get("report")
    for j in range(i - 1, -1, -1):
        r = runs[j]
        if r.get("report") and r.get("comparable") is not False and r["report"] != rep:
            return r
    return None


def alarm_level_on(date, run=None):
    """The fire-alarm level definition in force on `date` (a dict from alarm.json levels), taken from the
    run's own recorded level, else from the latest public-history entry dated on or before `date`.
    Never falls back to the current level, so past issues keep the level they had. None when the
    date predates the alarm or alarm.json is absent."""
    ap = ROOT / "data/alarm.json"
    if not ap.exists():
        return None
    a = json.loads(ap.read_text())
    lvl = ((run or {}).get("alarm") or {}).get("level")
    if lvl is None:
        past = sorted((h for h in a.get("history", []) if h.get("date", "") <= date and h.get("to") is not None),
                      key=lambda h: h["date"])  # stable: the last entry of a day wins
        lvl = past[-1]["to"] if past else None
    if lvl is None:
        return None
    return next((l for l in a.get("levels", []) if l.get("level") == lvl), None)


# Status marks for tripwires and Escape watch, the only places (with the alarm) that use status colours,
# always with the icon and the label: (icon, colour, label).
STATUS = {"tripped": ("●", "#B42318", "Tripped"), "watching": ("◐", "#9A6B00", "Watching"), "quiet": ("○", "#2E7D4F", "Quiet")}
STATUS_ORDER = {"tripped": 0, "watching": 1, "quiet": 2}


def trigger_level(trigger):
    """The alarm level (1 Watch, 2 Warning, 3 Alarm) of an alarm trigger id such as 'W3' or 'X6', from the
    groups in data/alarm.json, else from its letter (W, X, Y). None for no trigger or an unknown id."""
    tid = str(trigger or "").strip().upper()
    if not tid:
        return None
    try:
        for g in json.loads((ROOT / "data/alarm.json").read_text()).get("groups", []):
            if any(str(t.get("id", "")).upper() == tid for t in g.get("triggers", [])):
                return g.get("level")
    except (OSError, ValueError):
        pass
    return {"W": 1, "X": 2, "Y": 3}.get(tid[:1])


def tripwire_mark(w):
    """(icon, colour, label) for a tripwire. The colour is capped at the level of the alarm trigger it feeds:
    a tripped wire shows red only when it feeds a Warning or Alarm trigger (X or Y); one that feeds a Watch
    trigger (W), or no trigger, stays amber, so the board never looks louder than the alarm it feeds."""
    icon, col, lab = STATUS[w["status"]]
    if w["status"] == "tripped" and (trigger_level(w.get("trigger")) or 0) < 2:
        col = STATUS["watching"][1]
    return icon, col, lab


ESCAPE_SINCE = "2026-09-30"  # the first daily issue to carry Escape watch; earlier issues never gain it


def escape_summary(doc):
    """What the emails and cards show of Escape watch, from data/escape.json or a frozen copy of it:
    {updated, overall, counts {tripped, watching, quiet}, total, live [{key, name, status}]}, where live
    lists the indicators that aren't quiet, tripped first. None when there are no indicators."""
    if not isinstance(doc, dict):
        return None
    inds = [i for i in as_list(doc.get("indicators")) if isinstance(i, dict) and i.get("name")]
    if not inds:
        return None
    counts = {k: 0 for k in STATUS}
    live = []
    for i in inds:
        st = str(i.get("status") or "").strip().lower()
        if st not in STATUS:
            print(f"warning: escape watch: indicator {i.get('key') or i['name']!r} has unknown status {i.get('status')!r}; "
                  "left out of the counts.", file=sys.stderr)
            continue
        counts[st] += 1
        if st != "quiet":
            live.append({"key": i.get("key"), "name": i["name"], "status": st})
    live.sort(key=lambda i: STATUS_ORDER[i["status"]])  # stable: data order within a status
    return {"updated": doc.get("updated"), "overall": str(doc.get("overall") or "").strip(), "counts": counts,
            "total": sum(counts.values()), "live": live}


def escape_counts_text(s, sep=", "):
    """'0 tripped, 8 watching, 0 quiet' (tripped first, since that is the number that matters)."""
    return sep.join(f'{s["counts"][k]} {k}' for k in ("tripped", "watching", "quiet"))


def escape_for_run(run):
    """Escape watch as it stood on the run's date, or None. A run that recorded its own copy ("escape",
    shaped like data/escape.json) uses that. Otherwise data/escape.json is used only for the newest
    published run, dated on or after ESCAPE_SINCE, when the file's "updated" date isn't later than the run:
    the file holds today's statuses only, so an older issue (a past feed item) never shows later ones."""
    if isinstance(run.get("escape"), dict):
        return escape_summary(run["escape"])
    if run.get("date", "") < ESCAPE_SINCE:
        return None
    try:
        runs = json.loads((ROOT / "data/runs.json").read_text())
        doc = json.loads((ROOT / "data/escape.json").read_text())
    except (OSError, ValueError):
        return None
    newest = max((r.get("date", "") for r in runs if r.get("report")), default="")
    if run.get("date") != newest or str(doc.get("updated") or "") > run["date"]:
        return None
    return escape_summary(doc)


def delta_cell(cur, prev):
    if cur is None:
        return f'<span style="color:{MUTED}">–</span>'
    if prev is None:
        return f'<span style="color:{MUTED}">first reading</span>'
    if not changed(cur, prev):
        return f'<span style="color:{MUTED}">no change</span>'
    color, arrow = (UP, "▲ +") if float(cur) > float(prev) else (DOWN, "▼ −")
    return f'<span style="color:{color};font-weight:600">{arrow}{delta_amount(cur, prev)}</span>'


def h2(text):
    return (f'<h2 style="{FONT}font-size:20px;color:{INK};margin:28px 0 10px;'
            f'padding-top:10px;border-top:2px solid {INK}">{escape(text)}</h2>')


def p(text, style=""):
    return f'<p style="{SANS}font-size:15px;line-height:1.55;color:{INK};margin:0 0 10px;{style}">{text}</p>'


def ul(items):
    lis = "".join(f'<li style="margin:0 0 8px">{i}</li>' for i in items)
    return f'<ul style="{SANS}font-size:15px;line-height:1.5;color:{INK};padding-left:20px;margin:0 0 10px">{lis}</ul>'


def link(url, text):
    if urlparse(str(url)).scheme not in ("http", "https"):
        return escape(text)  # never emit javascript:, data: or other schemes from data files
    return f'<a href="{escape(url, quote=True)}" style="color:#4A6FA5">{escape(text)}</a>'


# Link text for sources: the outlet's name, so readers can judge a source at a glance.
# Hosts not listed show as the bare domain, never as a vague word like "source".
OUTLETS = {
    "hiddenagi.com": "Hidden AGI watch", "joeldg.github.io": "Hidden AGI watch",
    "techcrunch.com": "TechCrunch", "fortune.com": "Fortune", "nbcnews.com": "NBC News", "reuters.com": "Reuters",
    "apnews.com": "AP", "axios.com": "Axios", "bloomberg.com": "Bloomberg", "ft.com": "Financial Times",
    "nytimes.com": "The New York Times", "wsj.com": "The Wall Street Journal", "washingtonpost.com": "The Washington Post",
    "theguardian.com": "The Guardian", "bbc.com": "BBC", "bbc.co.uk": "BBC", "cnn.com": "CNN", "cnbc.com": "CNBC",
    "abc.net.au": "ABC News (Australia)", "aljazeera.com": "Al Jazeera", "euronews.com": "Euronews",
    "japantimes.co.jp": "The Japan Times", "politico.com": "Politico", "semafor.com": "Semafor", "time.com": "TIME",
    "economist.com": "The Economist", "forbes.com": "Forbes", "businessinsider.com": "Business Insider",
    "businesstoday.in": "Business Today", "theverge.com": "The Verge", "wired.com": "WIRED", "arstechnica.com": "Ars Technica",
    "engadget.com": "Engadget", "techradar.com": "TechRadar", "thenextweb.com": "The Next Web", "venturebeat.com": "VentureBeat",
    "theinformation.com": "The Information", "theregister.com": "The Register", "zdnet.com": "ZDNET", "404media.co": "404 Media",
    "the-decoder.com": "The Decoder", "sherwood.news": "Sherwood News", "pymnts.com": "PYMNTS", "coindesk.com": "CoinDesk",
    "9to5google.com": "9to5Google", "quantamagazine.org": "Quanta", "nature.com": "Nature", "science.org": "Science",
    "bleepingcomputer.com": "BleepingComputer", "securityweek.com": "SecurityWeek", "helpnetsecurity.com": "Help Net Security",
    "cybersecuritydive.com": "Cybersecurity Dive", "defensescoop.com": "DefenseScoop", "defenseone.com": "Defense One",
    "nextgov.com": "Nextgov", "lawfaremedia.org": "Lawfare", "finance.yahoo.com": "Yahoo Finance", "investing.com": "Investing.com",
    "tradingview.com": "TradingView", "kalshi.com": "Kalshi", "polymarket.com": "Polymarket", "metaculus.com": "Metaculus",
    "metr.org": "METR", "aisi.gov.uk": "UK AISI", "epoch.ai": "Epoch AI", "transluce.org": "Transluce", "arxiv.org": "arXiv",
    "anthropic.com": "Anthropic", "openai.com": "OpenAI", "deepmind.google": "Google DeepMind", "blog.google": "Google",
    "x.ai": "xAI", "blog.aifutures.org": "AI Futures Project", "thezvi.substack.com": "Zvi Mowshowitz",
    "casp.ac": "CASP", "claymath.org": "Clay Mathematics Institute", "sec.gov": "SEC EDGAR", "news.un.org": "UN News",
    "whitehouse.gov": "The White House", "gov.ca.gov": "Office of the California Governor", "gov.uk": "UK government",
    "dwt.com": "Davis Wright Tremaine", "en.wikipedia.org": "Wikipedia", "github.com": "GitHub",
}


def outlet(url):
    """Display name for a link's publisher: the OUTLETS entry for its host (or a parent domain), else the bare domain."""
    host = (urlparse(str(url)).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    for k in range(len(parts) - 1):
        name = OUTLETS.get(".".join(parts[k:]))
        if name:
            return name
    return host or "link"


def abs_url(u):
    """Absolute URL for a link taken from the data: relative site paths resolve against SITE.
    Returns None for an empty value or any scheme other than http(s)."""
    u = str(u or "").strip()
    if not u:
        return None
    full = urljoin(SITE, u)
    return full if urlparse(full).scheme in ("http", "https") else None


def source_link(item):
    """' (Outlet)' linked to item['url']; item['source'] overrides the outlet name. '' when there's no usable URL."""
    u = abs_url((item or {}).get("url"))
    if not u:
        return ""
    return f' ({link(u, str(item.get("source") or "").strip() or outlet(u))})'


def email_footer(kind):
    """Shared email footer. kind is 'daily', 'weekly' or 'alarm'."""
    made = {"daily": "Researched, written and sent automatically each morning",
            "weekly": "Researched, written and sent automatically each Friday",
            "alarm": "Researched and written"}[kind]
    review = ("A person reviewed and approved this alert before it was sent." if kind == "alarm"
              else "Fire-alarm alerts are always approved by a person before sending.")
    return p(f'<span style="color:{MUTED};font-size:13px">{made} by a custom AI agent built for this project. {review} '
             f'Methodology and every source are public. Spot an error? Reply or open an issue at '
             f'{link(ISSUES, "github.com/joeldg/agi_assessment/issues")}; corrections are logged publicly. '
             f'Not investment, policy or security advice.</span>')


CORRECTIONS_LOG = SITE + "about.html#corrections"
CORRECTIONS_SHOWN = 5  # the rest are summarised with a link to the log, so the reading stays near the top


def claim_date(c):
    """The date a corrected claim was published: from its page path (reports/YYYY-MM-DD.html), else None.
    A correction's own "date" is when the correction was made, never when the claim was."""
    m = re.search(r"\d{4}-\d{2}-\d{2}", str((c or {}).get("page") or ""))
    return m.group(0) if m else None


def correction_text(c):
    """'On 29 September 2026 we said X. That was wrong (corrected 30 September 2026): Y (Source).', escaped."""
    said = claim_date(c)
    when = f"On {escape(nice_date(said))} we said" if said else "We said"
    fixed = f" (corrected {escape(nice_date(c['date']))})" if c.get("date") else ""
    return (f'{when} {escape(str(c["was"]).strip().rstrip("."))}. That was wrong{fixed}: '
            f'{escape(str(c["now"]).strip().rstrip("."))}{source_link(c)}.')


def corrections_box(corrections, title=None, cap=CORRECTIONS_SHOWN, more_url=None):
    """A neutral box listing corrections ({date, page, was, now, url, source}); '' when there are none.
    Shows at most `cap` items, then how many more there are, linked to the public log (or to `more_url`,
    the analysis page's #corrections on a format-2 issue)."""
    items, seen = [], set()
    for c in as_list(corrections):
        if not isinstance(c, dict) or not c.get("was") or not c.get("now"):
            continue
        key = (str(c["was"]).strip(), str(c["now"]).strip())
        if key in seen:
            continue
        seen.add(key)
        items.append(correction_text(c))
    if not items:
        return ""
    more = len(items) - cap if cap and len(items) > cap else 0
    lis = "".join(f'<li style="margin:0 0 6px">{i}</li>' for i in (items[:cap] if more else items))
    if more:
        if more_url:
            label = f'{more} more {"correction" if more == 1 else "corrections"} →'
            lis += f'<li style="margin:0 0 6px;list-style:none">{link(more_url, label)}</li>'
        else:
            lis += (f'<li style="margin:0 0 6px;list-style:none">{more} more {"correction" if more == 1 else "corrections"}: '
                    f'{link(CORRECTIONS_LOG, "see the corrections log")}.</li>')
    head = title or ("Correction" if len(items) == 1 else "Corrections")
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin:6px 0 14px"><tr>'
            f'<td bgcolor="#F8F9FA" style="background-color:#F8F9FA;border-left:4px solid {INK};padding:8px 12px">'
            f'<div style="{SANS}font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:600;padding:0">'
            f'{escape(head)}</div>'
            f'<ul style="{SANS}font-size:14px;line-height:1.5;color:{INK};padding-left:18px;margin:6px 0 0">{lis}</ul>'
            f'</td></tr></table>')


def th_attr(size=13):
    return f'scope="col" style="{SANS}font-size:{size}px;color:{MUTED};text-align:left;padding:6px 8px;border-bottom:1px solid {RULE}"'


def data_table(rows, margin="6px 0 14px"):
    """A data table (not role=presentation, so screen readers keep the header relationships)."""
    return f'<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;margin:{margin}">{"".join(rows)}</table>'


NUMBER_WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


def gauge_delta(value, prev_value, suffix=""):
    """Change in a gauge reading as HTML: the arrow is hidden from screen readers and the sign carries the direction."""
    if value is None or prev_value is None:
        return "first reading"
    if not changed(value, prev_value):
        return "no change" + suffix
    up = float(value) > float(prev_value)
    return f'<span aria-hidden="true">{"▲" if up else "▼"}</span> {"+" if up else "−"}{delta_amount(value, prev_value)}{suffix}'


def gauges_html(run, prev):
    """Compact gauge table for email: reading, change vs the previous published reading, what it measures."""
    defs = json.loads((ROOT / "data/gauges.json").read_text())["gauges"]
    th = th_attr(12)
    td = f'style="{SANS}font-size:14px;color:{INK};padding:6px 8px;border-bottom:1px solid {RULE};vertical-align:top"'
    rows = [f"<tr><th {th}>Gauge</th><th {th}>Reading</th><th {th}>Change</th></tr>"]
    for d in defs:
        g = (run.get("gauges") or {}).get(d["key"])
        if not g:
            continue
        pg = ((prev or {}).get("gauges") or {}).get(d["key"]) or {}
        rows.append(f'<tr><td {td}><strong>{escape(d["label"])}</strong><br><span style="color:{MUTED};font-size:12px">'
                    f'{escape(d["question"])}</span></td><td {td}><strong>{escape(g.get("display") or fmt(g.get("value")))}</strong></td>'
                    f'<td {td}><span style="color:{MUTED}">{gauge_delta(g.get("value"), pg.get("value"))}</span></td></tr>')
    n = len(rows) - 1
    title = "The gauge" if n == 1 else f"The {NUMBER_WORDS[n] if n < len(NUMBER_WORDS) else n} gauges"
    return (f'<div style="{SANS}font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:600;margin-top:10px">{title}</div>'
            + data_table(rows, "4px 0 12px"))


def escape_html(run):
    """Compact Escape watch block for the daily email (after the gauges): the overall line, the status counts,
    one line per indicator that isn't quiet, and a link to escape.html. '' when escape_for_run has nothing."""
    s = escape_for_run(run)
    if not s:
        return ""
    lines = []
    for i in s["live"]:
        ic, col, lab = STATUS[i["status"]]
        lines.append(f'<span style="color:{col};font-weight:600"><span aria-hidden="true">{ic}</span> {lab}</span> · {escape(i["name"])}')
    lis = "".join(f'<li style="margin:0 0 3px">{x}</li>' for x in lines)
    return (f'<div style="{SANS}font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:600;margin-top:10px">Escape watch</div>'
            + p(f'<strong>{s["total"]} indicators: {escape_counts_text(s)}.</strong> '
                f'<span style="color:{MUTED}">{escape(s["overall"])}</span>', "font-size:14px;margin:4px 0 6px")
            + (f'<ul style="{SANS}font-size:14px;line-height:1.45;color:{INK};padding-left:20px;margin:0 0 6px">{lis}</ul>' if lis else "")
            + p(f'<span style="color:{MUTED};font-size:13px">Tracks hypothesis C at the chokepoints an AI system running on its own would still need: '
                f'weights, compute, money and accounts. {link(SITE + "escape.html", "See the indicators and evidence")}</span>',
                "margin:0 0 12px"))


def needle_hook(run):
    """One line for the day: the needle's subject (or headline), or a quiet-day line. Used in the feed item title."""
    n = run.get("needle") or {}
    hook = str(n.get("subject") or n.get("headline") or "").strip().rstrip(".")
    if n.get("quiet") and not hook.lower().startswith("quiet day"):
        hook = "Quiet day" + (f": {hook}" if hook else "")
    return hook or "Today's reading"


def roundup_selection(roundup):
    """What the email shows of the roundup: the items flagged top:true; else everything if 10 or fewer;
    else the first 2 per group. Returns ([(topic, items)], number of stories left out)."""
    groups = [(g.get("topic", ""), [it for it in as_list(g.get("items")) if isinstance(it, dict)])
              for g in as_list(roundup) if isinstance(g, dict)]
    total = sum(len(items) for _, items in groups)
    if any(it.get("top") for _, items in groups for it in items):
        shown = [(t, [it for it in items if it.get("top")]) for t, items in groups]
    elif total <= 10:
        shown = groups
    else:
        shown = [(t, items[:2]) for t, items in groups]
    shown = [(t, items) for t, items in shown if items]
    return shown, total - sum(len(items) for _, items in shown)


# ---- daily email sections: each returns a list of HTML blocks (empty when the section has nothing to say) ----

def _alarm_line(run):
    lv = alarm_level_on(run["date"], run)
    if not lv:
        return []
    col = {"good": "#2E7D4F", "warn": "#9A6B00", "crit": "#B42318"}.get(lv.get("status"), INK)
    return [p(f'<span style="color:{col};font-weight:600"><span aria-hidden="true">{lv["icon"]}</span> Fire alarm: Level {lv["level"]}, {escape(lv["name"])}.</span> '
              f'<span style="color:{MUTED}">{escape(lv.get("meaning", ""))} {link(SITE + "alarm.html", "How the alarm works")}</span>')]


def _index_line(run, prev):
    if run.get("index") is None:
        return []
    return [p(f'<strong>Hidden AGI Index: {fmt(run["index"])}%</strong> '
              f'{delta_cell(run["index"], prev.get("index") if prev else None)} '
              f'<span style="color:{MUTED}">· the chance at least one hypothesis is true now. '
              f'{link(SITE + "start-here.html", "What is this?")}</span>')]


def _needle_box(n):
    if not n:
        return []
    kicker = "Quiet day" if n.get("quiet") else "What moved the needle"
    # A one-cell table, not a div: Outlook only pads table cells. padding:0 on the inner divs beats Kit's template CSS.
    return [f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin:10px 0 16px"><tr>'
            f'<td bgcolor="#F8F9FA" style="background-color:#F8F9FA;border-left:4px solid {ACCENT};padding:8px 12px">'
            f'<div style="{SANS}font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:600;padding:0">{kicker}</div>'
            f'<div style="{FONT}font-size:18px;font-weight:600;color:{INK};margin:4px 0;padding:0">{escape(n.get("headline", ""))}</div>'
            f'<div style="{SANS}font-size:14px;line-height:1.5;color:{INK};padding:0">{escape(n.get("detail", ""))}{source_link(n)}</div>'
            f'</td></tr></table>']


def _prob_table(run, prev):
    th = th_attr()
    td = f'style="{SANS}font-size:14px;color:{INK};padding:6px 8px;border-bottom:1px solid {RULE};vertical-align:top"'
    rows = [f"<tr><th {th}>Hypothesis</th><th {th}>Now</th><th {th}>2030</th><th {th}>2035</th><th {th}>Change (now)</th></tr>"]
    for k, label in SERIES:
        now = prob(run, k, "now")
        rows.append(
            f"<tr><td {td}>{escape(label)}</td><td {td}><strong>{fmt(now)}%</strong></td>"
            f"<td {td}>{fmt(prob(run, k, 'y2030'))}%</td><td {td}>{fmt(prob(run, k, 'y2035'))}%</td>"
            f"<td {td}>{delta_cell(now, prob(prev, k, 'now') if prev else None)}</td></tr>")
    return [data_table(rows)]


def _tripwires(run):
    if not run.get("tripwires"):
        return []
    live = [w for w in run["tripwires"] if w["status"] != "quiet"]
    quiet = len(run["tripwires"]) - len(live)
    items = []
    for w in sorted(live, key=lambda w: 0 if w["status"] == "tripped" else 1):
        ic, col, lab = tripwire_mark(w)
        tid = str(w.get("trigger") or "").strip()
        feeds = (f' <span style="color:{MUTED}">· feeds {link(SITE + "alarm.html#" + quote(tid), "alarm trigger " + tid)}</span>'
                 if tid else "")
        items.append(f'<span style="color:{col};font-weight:600"><span aria-hidden="true">{ic}</span> {lab}</span>{feeds} · <strong>{escape(w["signal"])}</strong>. '
                     f'<span style="color:{MUTED}">{escape(w.get("note", ""))}</span>{source_link(w)}')
    return [h2("Tripwires"), ul(items),
            p(f'<span style="color:{MUTED}">{quiet} more quiet. {link(SITE + "#tripwires", "See all tripwires")}.</span>')]


def _what_changed(run, report_url):
    """At most 5 bullets, without the one the needle box already tells."""
    changes = as_list(run.get("changes"))
    n = run.get("needle") or {}
    if not n.get("quiet") and n.get("hypothesis") and n.get("from") is not None and n.get("to") is not None:
        hyp = "D-open" if n["hypothesis"] == "Dopen" else n["hypothesis"]
        key = f"from {fmt(n['from'])} to {fmt(n['to'])}"
        changes = [c for c in changes if not (str(c).startswith(hyp + " ") and key in str(c))]
    if not changes:
        return []
    out = [h2("What changed"), ul(escape(str(c)) for c in changes[:5])]
    if len(changes) > 5:
        more = len(changes) - 5
        out.append(p(f'<span style="color:{MUTED}">{more} more change{"s" if more != 1 else ""} in the '
                     f'{link(report_url + "#s5", "full report")}.</span>'))
    return out


def _timeline(run, prev, report_url):
    """The full reasoning only when the strict-AGI timeline moved (or on a first reading); otherwise one line."""
    if not run.get("timeline"):
        return []
    a, pa = run.get("agi") or {}, (prev or {}).get("agi") or {}
    same = (prev is not None and a.get("y2030") is not None and a.get("y2035") is not None
            and not changed(a["y2030"], pa.get("y2030")) and not changed(a["y2035"], pa.get("y2035")))
    if same:
        return [h2("Timeline reassessment"),
                p(f'Timeline unchanged: strict AGI {fmt(a["y2030"])}% by end-2030, {fmt(a["y2035"])}% by end-2035. '
                  f'{link(report_url + "#timeline", "Full reasoning")}')]
    tl = run["timeline"]
    paras = tl.split("\n\n") if isinstance(tl, str) else as_list(tl)
    return [h2("Timeline reassessment")] + [p(escape(str(par))) for par in paras if str(par).strip()]


def _roundup(run, report_url):
    if not run.get("roundup"):
        return []
    shown, hidden = roundup_selection(run["roundup"])
    out = [h2("What happened")]
    if run.get("roundupWindow"):
        out.append(p(f'<span style="color:{MUTED}">Covering {escape(run["roundupWindow"])}.</span>'))
    for topic, group in shown:
        out.append(f'<h3 style="{FONT}font-size:17px;color:{INK};margin:16px 0 6px">{escape(topic)}</h3>')
        out.append(ul((f'<strong style="color:{MUTED}">{escape(it["date"])}</strong> ' if it.get("date") else "")
                      + escape(it.get("text", "")) + source_link(it) for it in group))
    if hidden:
        out.append(p(f'{hidden} more stor{"y" if hidden == 1 else "ies"} in the {link(report_url + "#roundup", "full report")}.'))
    return out


def _signals(run, prev, report_url):
    """All signals on a first reading; afterwards only new or reworded ones, or a one-line 'unchanged'."""
    signals = as_list(run.get("signals"))
    if not signals:
        return []
    norm = lambda s: " ".join(str(s).lower().split())  # noqa: E731
    old = {norm(s) for s in as_list((prev or {}).get("signals"))}
    new = [s for s in signals if norm(s) not in old]
    if prev is None or len(new) == len(signals):
        return [h2("Signals to watch"), ul(escape(str(s)) for s in signals)]
    if new:
        return [h2("Signals to watch"), ul(escape(str(s)) for s in new),
                p(f'<span style="color:{MUTED}">New or reworded since the last reading. The other {len(signals) - len(new)} are unchanged: '
                  f'{link(report_url + "#s6", "full list")}.</span>')]
    return [p(f'<strong>Signals to watch:</strong> unchanged since the last reading. {link(report_url + "#s6", "Full list")}.',
              "margin-top:18px")]


def _closing(run, report_url):
    out = []
    if (ROOT / "cards" / f"{run['date']}.png").exists():
        idx = f'Hidden AGI Index {fmt(run.get("index"))}%' if run.get("index") is not None else "Hidden AGI watch"
        out.append(f'<a href="{report_url}"><img src="{SITE}cards/{run["date"]}.png" width="580" height="305" '
                   f'alt="{escape(idx, quote=True)} on {pretty_date(run["date"])}" style="display:block;width:100%;max-width:600px;'
                   f'height:auto;border:0;border-radius:8px;margin:22px 0 8px"></a>')
    out.append(p(f'{link(report_url, "Read the full report")} (definitions, evidence for and against, base rates, '
                 f'probabilities and what would change the estimates) · {link(SITE, "Dashboard and history")}',
                 "margin-top:14px"))
    out.append(p(f'Forwarded this? {link(SUBSCRIBE, "Subscribe to Hidden AGI watch")}. It\'s free.'))
    out.append(p(f'<span style="color:{MUTED};font-size:13px">A daily reading of four hypotheses about hidden advanced AI. '
                 f'Probabilities are subjective and sourced in the {link(report_url, "full report")}.</span>', "margin:18px 0 4px"))
    out.append(email_footer("daily"))
    return out


def issue_html(run, prev, later=None):
    """The daily email (also each feed item's content). prev is prev_published(runs, i), or None.
    later: corrections logged since this issue went out whose page is this issue's report (the feed item
    shows them; the email that carries them is the next day's, through run["corrections"]).
    Order: dated masthead, corrections, alarm, index, needle, gauges, Escape watch, probabilities, summary, tripwires,
    what changed, timeline, roundup, signals, then the share card next to the report link and the footer."""
    if run.get("format") == 2:
        return issue_html_v2(run, prev, later)
    report_url = SITE + run["report"]
    t = datetime.strptime(run["date"], "%Y-%m-%d")
    out = [p(f'<span style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:600">'
             f'Hidden AGI watch · {t.strftime("%a")} {pretty_date(run["date"])}</span>', "margin-bottom:12px"),
           corrections_box(later, title="Corrected since this issue was published"),
           corrections_box(run.get("corrections"))]
    out += _alarm_line(run) + _index_line(run, prev) + _needle_box(run.get("needle"))
    if run.get("gauges"):
        out.append(gauges_html(run, prev))
    out.append(escape_html(run))
    out += _prob_table(run, prev)
    if run.get("summary"):
        out.append(p(escape(run["summary"])))
    out += _tripwires(run) + _what_changed(run, report_url) + _timeline(run, prev, report_url)
    out += _roundup(run, report_url) + _signals(run, prev, report_url) + _closing(run, report_url)
    return "".join(out)


# ---- format-2 issue (spec 9.4): a pure function of the run and the previous published run (B1) ----
# It reads the run's own snapshots (components, furthest, alarm, escape counts, dates), never the live data files,
# so every past v2 item rebuilds byte-identically. The legacy path above is untouched.

def _chip(rating):
    """An evidence-rating chip with inline styles (email clients ignore stylesheets)."""
    import build_report as br
    base, qual = br.split_rating(rating)
    if not base:
        return ""
    q = f' <span style="color:{MUTED};font-size:11px">({escape(qual)})</span>' if qual else ""
    return (f' <span style="{SANS}font-size:11px;text-transform:uppercase;letter-spacing:.02em;border:1px solid {RULE};'
            f'border-radius:3px;padding:0 4px;color:{MUTED};white-space:nowrap">{escape(base)}</span>{q}')


def _small(text):
    return f'<span style="color:{MUTED};font-size:13px">{text}</span>'


def _kicker(text, margin="18px 0 4px"):
    return (f'<div style="{SANS}font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};'
            f'font-weight:600;margin:{margin}">{escape(text)}</div>')


def _cell_text(text):
    """A Change-today cell: arrows coloured, method change muted."""
    if text.startswith("▲"):
        return f'<span style="color:{UP};font-weight:600">{escape(text)}</span>'
    if text.startswith("▼"):
        return f'<span style="color:{DOWN};font-weight:600">{escape(text)}</span>'
    return f'<span style="color:{MUTED}">{escape(text)}</span>'


def issue_html_v2(run, prev, later=None):
    """The daily email for a format-2 reading. Order: masthead, corrections (at most 5, then a link to the analysis),
    method banner (boundary run only), alarm line, the answers line, the Index line, needle box, probability table,
    signals, gauges, "Is AGI here, today?", top stories, dates to watch, bottom line, closing."""
    import build_report as br
    from sitekit import SIGNAL_STATUS, condition_name, method_boundary, run_defs, signal_view
    d = run["date"]
    report_url, an_url = SITE + run["report"], SITE + (run.get("analysis") or run["report"])
    t = datetime.strptime(d, "%Y-%m-%d")
    out = [p(f'<span style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:600">'
             f'Hidden AGI watch · {t.strftime("%a")} {pretty_date(d)}</span>', "margin-bottom:12px")]
    if str(run.get("verdict") or "").strip():   # the day in one line (the short report's H1), before anything static
        out.append(p(escape(str(run["verdict"]).strip()), f"{FONT}font-size:17px"))
    out += [corrections_box(later, title="Corrected since this issue was published"),
            corrections_box(br.newest_first([c for c in as_list(run.get("corrections")) if isinstance(c, dict)]),
                            more_url=an_url + "#corrections")]
    boundary = method_boundary(run, prev)
    if run.get("methodChange") or boundary:
        to = (run.get("methodChange") or {}).get("to") or run_defs(run)
        out.append(p(f'<strong>Method change today:</strong> this is our first reading under definitions v{escape(to)}. Our numbers were '
                     f're-derived; this is not news. {link(SITE + "changes.html#method", "What changed →")}',
                     f"background:#F8F9FA;border-left:4px solid {INK};padding:8px 12px"))
    al = run.get("alarm") or {}
    if al.get("icon") and al.get("name"):
        col = {"good": "#2E7D4F", "warn": "#9A6B00", "crit": "#B42318"}.get(al.get("status"), INK)
        since = f'since {br.day(al["since"], False)} · ' if al.get("since") else ""
        met = "; ".join(condition_name(m) for m in al.get("met") or [])
        met = f"met: {met}" if met else "no condition met"
        out.append(p(f'<span style="color:{col};font-weight:600"><span aria-hidden="true">{escape(al["icon"])}</span> '
                     f'Fire alarm: Level {int(al["level"])}, {escape(al["name"])}.</span> '
                     f'<span style="color:{MUTED}">{escape(since)}{escape(met)}. Set by published rules, not our odds. '
                     f'{link(SITE + "alarm.html", "How the alarm works")}</span>'))
    else:
        out += _alarm_line(run)
    head, rest = br.answer_text(run)
    agi = run.get("agi") or {}
    mc_agi = ""
    if boundary and prev:
        mc_agi = f' (method change, from {fmt((prev.get("agi") or {}).get("now"))}%)'
    out.append(p(f'<strong>Is AGI here?</strong> {escape(head)} {escape(rest)} AGI anywhere, public or hidden: '
                 f'<strong>{fmt(agi.get("now"))}%</strong> today{escape(mc_agi)}. '
                 f'{link(SITE + "agi.html#definition", "What we mean by AGI →")}'))
    f = run.get("furthest")
    if isinstance(f, dict) and f.get("short"):
        out.append(p(_small(f'Furthest behind: {escape(str(f["short"]).lower())}, {escape(f.get("display") or "")} of '
                            f'{escape(f.get("targetDisplay") or "")}.'), "margin-top:-4px"))
    # The parts (A + B-only + C/D) and the rounding note stay on the report's card 2 and the analysis #index; the
    # email says how the Index sits against AGI anywhere, the question readers ask.
    ix_delta = br.change_cell(run, prev, "index")
    if boundary and prev and fmt(prev.get("index")) == fmt(run.get("index")):
        ix_delta += ", unchanged after rounding"
    b = br.b_only(run)
    bridge = ""
    if run.get("index") is not None and agi.get("now") is not None and float(run["index"]) > float(agi["now"]) \
            and b is not None:
        bridge = (f" Higher than AGI anywhere ({fmt(agi.get('now'))}%) because {br.fmtp(b)} points are hidden "
                  "self-improvement (B), which needs no AGI.")
    out.append(p(f'<strong>Hidden AGI Index: {fmt(run.get("index"))}%</strong> · {_cell_text(ix_delta)} '
                 f'<span style="color:{MUTED}">· the chance at least one hidden scenario is true now.{escape(bridge)} '
                 f'{link(SITE + "start-here.html#pieces", "How our numbers fit →")}</span>'))
    nd = run.get("needle") or {}
    kicker = "Quiet day · the day's story" if nd.get("quiet") else "What moved the needle"
    src = br.source_name(nd)
    out.append(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin:10px 0 16px"><tr>'
               f'<td bgcolor="#F8F9FA" style="background-color:#F8F9FA;border-left:4px solid {ACCENT};padding:8px 12px">'
               f'<div style="{SANS}font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:600;padding:0">{escape(kicker)}</div>'
               f'<div style="{FONT}font-size:18px;font-weight:600;color:{INK};margin:4px 0;padding:0">{escape(nd.get("subject") or nd.get("headline") or "")}</div>'
               f'<div style="{SANS}font-size:14px;line-height:1.5;color:{INK};padding:0">{escape(nd.get("brief") or "")}'
               f'{_chip(nd.get("rating"))} {link(abs_url(nd.get("url")) or "", src) if abs_url(nd.get("url")) else ""}</div>'
               f'</td></tr></table>')
    th = th_attr()
    td = f'style="{SANS}font-size:14px;color:{INK};padding:6px 8px;border-bottom:1px solid {RULE};vertical-align:top"'
    # The Change column appears only on a day a displayed number moved (a ▲/▼ cell); on a quiet day the table is
    # four columns that fit a phone, and one line under it says so. On the method boundary that line names the
    # from→to of every re-derived number (the short report keeps its full table: checks/method.py reads its cells).
    cells = {key: br.change_cell(run, prev, key) for key, _ in br.ROWS}
    moved = any(str(c).startswith(("▲", "▼")) for c in cells.values())
    # A by-end-2030 or by-end-2035 number that moved on a day no today number did (M2): the four-column table has no
    # Change column, so the line under it names those moves instead of saying nothing moved.
    h_moved = [(k, h) for k, _ in br.ROWS for h in ("y2030", "y2035")
               if str(br.change_cell(run, prev, k, h)).startswith(("▲", "▼"))]
    rows = [f"<tr><th {th}>Hypothesis</th><th {th}>Today</th><th {th}>By end-2030</th><th {th}>By end-2035</th>"
            + (f"<th {th}>Change today</th>" if moved else "") + "</tr>"]
    for key, label in br.ROWS:
        s = br.series(run, key)
        rows.append(f"<tr><td {td}>{escape(label)}</td><td {td}><strong>{fmt(s.get('now'))}%</strong></td>"
                    f"<td {td}>{fmt(s.get('y2030'))}%</td><td {td}>{fmt(s.get('y2035'))}%</td>"
                    + (f"<td {td}>{_cell_text(cells[key])}</td>" if moved else "") + "</tr>")
    out.append(data_table(rows))
    step5 = link(an_url + "#s5", "analysis, Step 5 →")
    if moved:
        note = f"What changed and why: {step5}"
    elif boundary and prev:
        mv = "; ".join(f"{lab} {fmt(br.series(prev, k).get('now'))}→{fmt(br.series(run, k).get('now'))}%"
                       for k, lab in (("agi", "AGI anywhere"), ("A", "A"), ("C", "C"), ("D", "D"), ("Dopen", "D-open"))
                       if fmt(br.series(prev, k).get("now")) != fmt(br.series(run, k).get("now")))
        note = (f"Method change (definitions v{escape(run_defs(run))}): {escape(mv) or 'no displayed number moved'}; "
                f"B unchanged, it needs no AGI. {step5}")
    elif prev is not None and h_moved:
        short = {"agi": "AGI anywhere", "A": "A", "B": "B", "C": "C", "D": "D", "Dopen": "D-open"}
        horizon = {"y2030": "by end-2030", "y2035": "by end-2035"}
        hv = "; ".join(f"{short[k]} {horizon[h]} {fmt(br.series(prev, k).get(h))}→{fmt(br.series(run, k).get(h))}%"
                       for k, h in h_moved)
        note = f"No today number moved; by end-2030 / end-2035 changed: {escape(hv)}. {step5}"
    elif prev is not None:
        note = f"No number moved today. {step5}"
    else:
        note = f"First reading. {step5}"
    out.append(p(_small(note), "margin-top:-6px"))
    c = br.signal_counts(run)
    by_id = {w.get("id"): w for w in as_list(run.get("tripwires")) if isinstance(w, dict)}
    ch = [x for x in as_list(run.get("tripwireChanges")) if isinstance(x, dict)]
    lead = "No signal changed today · " if (run.get("tripwireChanges") is not None and not ch) else ""
    out.append(_kicker("Signals"))
    out.append(p(f'{lead}{c["tripped"]} confirmed (count toward Watch) · {c["watching"]} open · {c["quiet"]} quiet. '
                 f'{link(SITE + "alarm.html#signals", "All signals →")}', "margin:4px 0 6px"))
    if ch:
        items = []
        for x in ch[:3]:
            # the display cap of sitekit.signal_view, from the condition letter the run's tripwire names (B1: the
            # email is a pure function of the run): amber "Confirmed · counts toward Watch" unless X/Y-linked
            trig = (by_id.get(x.get("id")) or {}).get("trigger")
            icon, tok, word = signal_view(x.get("to"), trig) if str(x.get("to")) in SIGNAL_STATUS else (
                "", "", str(x.get("to")))
            col = {"good": "#2E7D4F", "warn": "#9A6B00", "crit": "#B42318"}.get(tok, INK)
            name = (by_id.get(x.get("id")) or {}).get("signal") or x.get("id")
            items.append(f'<span style="color:{col};font-weight:600"><span aria-hidden="true">{icon}</span> {escape(word)}</span>'
                         f' · <strong>{escape(str(name))}</strong> (was {escape(br.signal_word(x.get("from")).lower())}). '
                         f'<span style="color:{MUTED}">{escape(str(x.get("why") or ""))}</span>')
        out.append(ul(items))
    tt, total, w, ch_text, _ = br.escape_line_parts(run)
    es = run.get("escape") if isinstance(run.get("escape"), dict) else {}
    n_new = sum(1 for x in as_list(es.get("newEvidence")) if isinstance(x, str))
    ne = "" if es.get("newEvidence") is None else (f"; new evidence on {n_new} of {total} indicators" if n_new
                                                   else "; no new evidence")
    out.append(p(f'Escape watch: {tt} of {total} confirmed · {w} open · {escape(ch_text)}{escape(ne)}. '
                 f'{link(SITE + "escape.html", "Escape watch →")}', "font-size:14px"))
    gl = []
    for k in br.gauge_keys(run):
        g = (run.get("gauges") or {}).get(k) or {}
        fl = ", a floor" if k == br.FLOOR_GAUGE else ""
        gl.append(f"{escape(GAUGE_GLOSS.get(k) or br.gauge_label(k))} <strong>{escape(br.gauge_display(k, g))}</strong>{fl}")
    if gl:
        out.append(_kicker("Gauges", "12px 0 4px"))
        out.append(p(" · ".join(gl) + ".", "font-size:14px;margin:4px 0 6px"))
        for k in br.moved_gauges(run, prev):
            g, pg = run["gauges"][k] or {}, ((prev or {}).get("gauges") or {}).get(k) or {}
            b = str(g.get("brief") or "").strip()
            out.append(p(_small(f'{escape(br.gauge_label(k))}: {escape(br.gauge_display(k, pg))} → '
                                f'{escape(br.gauge_display(k, g))}' + (f". {escape(b)}" if b else "")), "margin:0 0 6px"))
    out.append(_kicker("AGI parts", "12px 0 4px"))
    out.append(p(f'{escape(run.get("timelineShort") or "")} {link(an_url + "#timeline", "More →")}',
                 "font-size:14px;margin:4px 0 6px"))
    nurl = abs_url(nd.get("url")) or ""   # the needle box already tells this story
    tops = [it for it in br.top_items(run) if not (nurl and abs_url(it.get("url")) == nurl)][:br.TOP_SHOWN]
    if tops:
        out.append(h2("Top stories"))
        out.append(ul((f'<strong style="color:{MUTED}">{escape(br.item_date(it))}</strong> ' if it.get("date") else "")
                      + escape(br.item_short(it)) + _chip(it.get("rating")) + source_link(it) for it in tops))
        n = br.all_items(run)
        out.append(p(link(an_url + "#roundup", f'All {n} {"story" if n == 1 else "stories"}, with sources →')))
    dates = [x for x in as_list(run.get("dates")) if isinstance(x, dict) and x.get("date")]
    out.append(h2("Dates to watch"))
    if dates:
        out.append(ul(f'<strong>{escape(br.day(x["date"], False))}</strong> · {escape(str(x.get("short") or ""))}'
                      for x in dates))
    out.append(p(link(an_url + "#s6", "What would change our mind →")))
    out.append(h2("Bottom line"))
    out.append(p(escape(run.get("bottomLine") or ""), f"{FONT}font-size:17px"))
    if (ROOT / "cards" / f"{d}.png").exists():
        alt = escape(f'Hidden AGI Index {fmt(run.get("index"))}% on {pretty_date(d)}', quote=True)
        out.append(f'<a href="{report_url}"><img src="{SITE}cards/{d}.png" width="580" height="305" alt="{alt}" '
                   f'style="display:block;width:100%;max-width:600px;height:auto;border:0;border-radius:8px;margin:22px 0 8px"></a>')
    today = link(report_url, "Today's report")
    out.append(p(f'{today} · {link(an_url, "Full analysis")} (evidence, reasoning and every source) · '
                 f'{link(SITE, "Dashboard")}', "margin-top:14px"))
    out.append(p(f'Forwarded this? {link(SUBSCRIBE, "Subscribe to Hidden AGI watch")}. It\'s free.'))
    out.append(p(_small(f'A daily reading of four hidden-AI scenarios. Probabilities are subjective and sourced in the '
                        f'{link(an_url, "full analysis")}.'), "margin:18px 0 4px"))
    out.append(email_footer("daily"))
    return "".join(out)


def cdata(s):
    return "<![CDATA[" + s.replace("]]>", "]]]]><![CDATA[>") + "]]>"


STANDING_PAGES = ("start-here.html", "about.html", "scorecard.html", "disclosure-lag.html", "agi-claims.html",
                  "calendar.html", "steelman.html", "trends.html", "money.html", "alarm.html", "style.html",
                  "escape.html", "agi.html", "hidden.html", "changes.html", "archive.html")


def write_sitemap(runs):
    """List only pages that exist on disk, so a partial commit or a missing report never feeds 404s to Search Console."""
    dates = {}
    for run in runs:
        for path in (run.get("report"), run.get("analysis")):
            if path and (ROOT / path).exists():
                dates[path] = max(dates.get(path, ""), run["date"])
    latest = max((r["date"] for r in runs), default="")
    weekly_index = ROOT / "data/weekly/index.json"
    wraps = json.loads(weekly_index.read_text())["wrapups"] if weekly_index.exists() else []
    last_week = max((w["date"] for w in wraps), default=latest)
    urls = [(SITE, latest)]
    if (ROOT / "weekly/index.html").exists():
        urls.append((SITE + "weekly/", last_week))
    urls += [(SITE + pg, last_week) for pg in STANDING_PAGES if (ROOT / pg).exists()]
    urls += [(SITE + f"weekly/{w['date']}.html", w["date"]) for w in sorted(wraps, key=lambda w: w["date"], reverse=True)
             if (ROOT / f"weekly/{w['date']}.html").exists()]
    urls += sorted(((SITE + path, d) for path, d in dates.items()), key=lambda u: u[1], reverse=True)
    entries = "\n".join(
        f"  <url><loc>{escape(loc)}</loc>" + (f"<lastmod>{d}</lastmod>" if d else "") + "</url>"
        for loc, d in urls)
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n</urlset>\n")
    print(f"sitemap.xml: {len(urls)} URL(s)")


def feed_items(runs):
    """Indices of the runs that become feed items: one per report path, the latest entry winning."""
    reported = [i for i, r in enumerate(runs) if r.get("report")]
    latest = {}
    for i in reported:
        latest[runs[i]["report"]] = i
    if len(latest) < len(reported):
        dups = sorted({runs[i]["report"] for i in reported if latest[runs[i]["report"]] != i})
        print(f"warning: runs.json repeats report path(s) {', '.join(dups)}; the latest entry of each is used. "
              "A rerun or correction should replace the day's entry, not append one.", file=sys.stderr)
    keep = []
    for i in sorted(latest.values()):
        if (ROOT / runs[i]["report"]).exists():
            keep.append(i)
        else:
            print(f"warning: {runs[i]['report']} does not exist; left out of the feed.", file=sys.stderr)
    return keep


def corrections_log():
    """The entries of data/corrections.json, or [] when it's missing or unreadable."""
    try:
        doc = json.loads((ROOT / "data/corrections.json").read_text())
    except (OSError, ValueError):
        return []
    items = doc.get("corrections") if isinstance(doc, dict) else doc
    return [c for c in items or [] if isinstance(c, dict)]


def main():
    runs = json.loads((ROOT / "data/runs.json").read_text())
    write_sitemap(runs)
    log = corrections_log()
    items = []
    for i in feed_items(runs):
        run = runs[i]
        prev = prev_published(runs, i)
        later = [c for c in log if c.get("page") == run["report"]
                 or (run.get("format") == 2 and run.get("analysis") and c.get("page") == run["analysis"])]
        published = datetime.strptime(run["date"], "%Y-%m-%d").replace(hour=13, tzinfo=timezone.utc)
        idx = run.get("index")
        title = (f"Hidden AGI Index {fmt(idx)}% · " if idx is not None else "Hidden AGI watch · ") + needle_hook(run)
        url = SITE + run["report"]
        guid = FEED_GUID_BASE + run["report"]
        # Entity-escape twice: RSS description is HTML carried as text, so "R&D" must reach the reader as "R&amp;D".
        text = (run.get("verdict") or run.get("summary", "")) if run.get("format") == 2 else run.get("summary", "")
        desc = escape(escape(text, quote=False), quote=False)
        items.append((published, f"""    <item>
      <title>{escape(title)}</title>
      <link>{escape(url)}</link>
      <guid isPermaLink="{"true" if SITE == FEED_GUID_BASE else "false"}">{escape(guid)}</guid>
      <pubDate>{format_datetime(published)}</pubDate>
      <description>{desc}</description>
      <content:encoded>{cdata(issue_html(run, prev, later))}</content:encoded>
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
    <description>Daily, sourced probabilities on whether AGI, self-improving AI or covert AI actors already exist in secret, with forecasts scored in public.</description>
    <language>en</language>
    <image><url>{SITE}assets/brand/avatar.png</url><title>Hidden AGI watch</title><link>{SITE}</link></image>
    <lastBuildDate>{format_datetime(built)}</lastBuildDate>
{chr(10).join(i[1] for i in items)}
  </channel>
</rss>
"""
    (ROOT / "feed.xml").write_text(feed)
    print(f"feed.xml: {len(items)} item(s)")


def preview(date, runs_path=None):
    """Print the email (issue_html) for the reading dated `date`; writes nothing (rehearsal)."""
    runs = json.loads(Path(runs_path).read_text() if runs_path else (ROOT / "data/runs.json").read_text())
    idx = [i for i, r in enumerate(runs) if r.get("report") and r.get("date") == date]
    if not idx:
        sys.exit(f"build_feed --preview: no reading with a report dated {date}")
    i = idx[-1]
    sys.stdout.write(issue_html(runs[i], prev_published(runs, i), []) + "\n")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Build feed.xml and sitemap.xml, or preview one issue's email.")
    ap.add_argument("--preview", metavar="DATE", help="print the email for DATE's reading to stdout; write nothing")
    ap.add_argument("--runs", help="with --preview: read the runs from PATH (a fixture) instead of data/runs.json")
    a = ap.parse_args()
    if a.preview:
        preview(a.preview, a.runs)
    elif a.runs:
        ap.error("--runs only works with --preview")
    else:
        main()
