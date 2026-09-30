#!/usr/bin/env python3
"""Build feed.xml (RSS 2.0) and sitemap.xml from data/runs.json, and define the daily email body
that scripts/kit_broadcast.py sends through the Kit API (Kit's RSS-to-email is a paid feature and
is not used; the feed is for feed readers).

Each run that has a full report becomes one feed item. A rerun or correction that repeats a report
path replaces the earlier entry. The item's content:encoded holds the email-ready HTML issue, with
inline styles only, since email clients ignore stylesheets. The helpers here (fmt, changed,
prev_published, alarm_level_on, source_link, email_footer, ...) are shared with render_card.py,
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
from urllib.parse import urljoin, urlparse

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


def _q(v, places):
    return Decimal(str(v)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def fmt(v):
    """Display precision, rounded half-up: 2 decimals below 1, 1 decimal below 10, whole numbers above.
    Values that round up to the next band roll over (0.996 -> '1', 9.96 -> '10'). assets/app.js mirrors this."""
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
    "joeldg.github.io": "Hidden AGI watch",
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


def corrections_box(corrections, title=None, cap=CORRECTIONS_SHOWN):
    """A neutral box listing corrections ({date, page, was, now, url, source}); '' when there are none.
    Shows at most `cap` items, then how many more there are, linked to the public log."""
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
    icon = {"tripped": ("●", "#B42318", "Tripped"), "watching": ("◐", "#9A6B00", "Watching"), "quiet": ("○", "#2E7D4F", "Quiet")}
    live = [w for w in run["tripwires"] if w["status"] != "quiet"]
    quiet = len(run["tripwires"]) - len(live)
    items = []
    for w in sorted(live, key=lambda w: 0 if w["status"] == "tripped" else 1):
        ic, col, lab = icon[w["status"]]
        items.append(f'<span style="color:{col};font-weight:600"><span aria-hidden="true">{ic}</span> {lab}</span> · <strong>{escape(w["signal"])}</strong>. '
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
    Order: dated masthead, corrections, alarm, index, needle, gauges, probabilities, summary, tripwires,
    what changed, timeline, roundup, signals, then the share card next to the report link and the footer."""
    report_url = SITE + run["report"]
    t = datetime.strptime(run["date"], "%Y-%m-%d")
    out = [p(f'<span style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:600">'
             f'Hidden AGI watch · {t.strftime("%a")} {pretty_date(run["date"])}</span>', "margin-bottom:12px"),
           corrections_box(later, title="Corrected since this issue was published"),
           corrections_box(run.get("corrections"))]
    out += _alarm_line(run) + _index_line(run, prev) + _needle_box(run.get("needle"))
    if run.get("gauges"):
        out.append(gauges_html(run, prev))
    out += _prob_table(run, prev)
    if run.get("summary"):
        out.append(p(escape(run["summary"])))
    out += _tripwires(run) + _what_changed(run, report_url) + _timeline(run, prev, report_url)
    out += _roundup(run, report_url) + _signals(run, prev, report_url) + _closing(run, report_url)
    return "".join(out)


def cdata(s):
    return "<![CDATA[" + s.replace("]]>", "]]]]><![CDATA[>") + "]]>"


STANDING_PAGES = ("start-here.html", "about.html", "scorecard.html", "disclosure-lag.html", "agi-claims.html",
                  "calendar.html", "steelman.html", "trends.html", "money.html", "alarm.html", "style.html")


def write_sitemap(runs):
    """List only pages that exist on disk, so a partial commit or a missing report never feeds 404s to Search Console."""
    dates = {}
    for run in runs:
        if run.get("report") and (ROOT / run["report"]).exists():
            dates[run["report"]] = max(dates.get(run["report"], ""), run["date"])
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
        later = [c for c in log if c.get("page") == run["report"]]
        published = datetime.strptime(run["date"], "%Y-%m-%d").replace(hour=13, tzinfo=timezone.utc)
        idx = run.get("index")
        title = (f"Hidden AGI Index {fmt(idx)}% · " if idx is not None else "Hidden AGI watch · ") + needle_hook(run)
        url = SITE + run["report"]
        guid = FEED_GUID_BASE + run["report"]
        # Entity-escape twice: RSS description is HTML carried as text, so "R&D" must reach the reader as "R&amp;D".
        desc = escape(escape(run.get("summary", ""), quote=False), quote=False)
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


if __name__ == "__main__":
    main()
