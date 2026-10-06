"""Shared page shell for generated pages: head, social tags, nav, breadcrumb, subscribe box, footer,
plus the small shared rules every builder needs to agree on (labels, signal words, the rounding grid,
which definitions are in force, and when a reading sits on a method boundary).

Every generated page (the hubs, the standing sections, the daily report pair, weekly wrap-ups, the style
guide) goes through page() so the site stays consistent. SITE and SUBSCRIBE are defined here once; the
other scripts import them from this module.

Frozen pages (past daily reports, weekly/2026-10-02.html) were written with the old `nav.site` markup and
never read this module again; nothing here changes how they look. Redesign v2 pages use `nav.site2`
(six hubs plus the Escape watch pill; short labels on phones; no JS).
"""
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from html import escape
from urllib.parse import urlsplit

SITE = "https://hiddenagi.com/"
SUBSCRIBE = "https://hidden-agi.kit.com/f2b4d2f30e"
REPO = "https://github.com/joeldg/agi_assessment"
# The alt text for the default share card (cards/latest.png).
LATEST_CARD_ALT = ("Share card for the latest daily reading: the Hidden AGI Index, "
                   "the A–D probabilities and the fire-alarm level")

NAV = [  # (hub path, long label, short label, children: paths or path prefixes that light this hub)
    ("index.html",       "Today",               "Today",  ("archive.html", "reports/", "weekly/")),
    ("agi.html",         "Is AGI here?",        "AGI",    ("trends.html", "agi-claims.html")),
    ("hidden.html",      "Could it be hidden?", "Hidden", ("disclosure-lag.html", "money.html")),
    ("alarm.html",       "Fire alarm",          "Alarm",  ("escape.html",)),
    ("scorecard.html",   "Track record",        "Record", ("calendar.html", "steelman.html", "changes.html")),
    ("start-here.html",  "How it works",        "Method", ("about.html", "style.html")),
]
NAV_KEY = ("escape.html", "Escape watch")   # the owner's one emphasised entry, kept as a pill

# The short title a child page shows in its breadcrumb ("Fire alarm › Escape watch"). Reports and wrap-ups
# are matched by pattern in crumb_for(); every other child is listed here.
CRUMB_TITLES = {
    "archive.html": "Archive",
    "weekly/index.html": "Weekly wrap-ups",
    "trends.html": "Trend watch",
    "agi-claims.html": "AGI claims ledger",
    "disclosure-lag.html": "Disclosure lag",
    "money.html": "Follow the money",
    "escape.html": "Escape watch",
    "calendar.html": "Coming up",
    "steelman.html": "Weekly steelman",
    "changes.html": "Changes and corrections",
    "about.html": "About",
    "style.html": "Chart style guide",
}
_REPORT = re.compile(r"^reports/(\d{4}-\d{2}-\d{2})(-analysis)?\.html$")
_WEEKLY = re.compile(r"^weekly/(\d{4}-\d{2}-\d{2})\.html$")

# Display names for the hypotheses under definitions v2.0 (section 3.1). Data keys never change.
HYP_LABELS = {"A": "Hidden AGI", "B": "Hidden self-improvement", "C": "Covert AGI actor",
              "D": "Covert government influence", "Dopen": "Open government influence"}
# Signal words for tripwires and Escape watch indicators, keyed by the stored status value.
# Tuples are ordered (icon, token, word); the token names the CSS colour variable (--good, --warn, --crit).
SIGNAL_STATUS = {"quiet": ("○", "good", "Quiet"), "watching": ("◔", "warn", "Open"), "tripped": ("●", "crit", "Confirmed")}
# One-line names of the alarm conditions (the `short` of each trigger in data/alarm.json, criteria 1.2), for the
# email's "met" list. A constant rather than a read of alarm.json, so the email stays a pure function of the run
# (B1); test_condition_short_matches_alarm_json keeps it equal to the file.
CONDITION_SHORT = {
    "W1": "Capability gap of 3+ months, measured or credibly reported",
    "W2": "Unreleased frontier model with no outside evaluation for 60+ days",
    "W3": "Evaluator access restricted by a lab or government (past 90 days)",
    "W4": "Median disclosure lag of 30+ days (incidents disclosed in past 180 days)",
    "W5": "A lab's AI-led R&D share up 10+ points in 6 months",
    "W6": "Exclusive internal use of an unreleased model for 90+ days",
    "X1": "Measured or leaked capability gap of 6+ months",
    "X2": "A new model 3+ residual SDs above the capability trend",
    "X3": "AI-driven self-improvement: over 10% autonomous AI R&D, or 3x+ speed-up",
    "X4": "Unexplained compute at 2x+ the trend for the largest AI data center",
    "X5": "Insider evidence",
    "X6": "Covert autonomous operation (30+ days) or weight exfiltration",
    "Y1": "Undisclosed system meets AGI (definitions v2.0)",
    "Y2": "AGI-level system acting covertly, or covertly shaping a government decision",
    "Y3": "Undisclosed recursive self-improvement",
}


def condition_name(cid):
    """'W3, evaluator access restricted by a lab or government (past 90 days)' for the email; the bare id when unknown."""
    s = CONDITION_SHORT.get(str(cid or "").strip().upper())
    if not s:
        return str(cid)
    if len(s) > 1 and not s[1].isupper():   # "AI-driven…" keeps its capital; "Evaluator…" reads on mid-sentence
        s = s[0].lower() + s[1:]
    return f"{str(cid).strip().upper()}, {s}"
# What builders print instead of ▲▼ deltas for agi, A, C, D, D-open and the Index on a method boundary.
METHOD_CHANGE = "method change (definitions v2.0)"
_LEVEL_BY_LETTER = {"W": 1, "X": 2, "Y": 3}
_LEVEL_NAMES = {0: "Normal", 1: "Watch", 2: "Warning", 3: "Alarm"}


def safe_url(u):
    """A link target from data: an http(s) URL or a relative site path, else None.
    Never javascript:, data: or other schemes, and no protocol-relative //host links."""
    u = str(u or "").strip()
    if not u:
        return None
    parts = urlsplit(u)
    if parts.scheme:
        return u if parts.scheme.lower() in ("http", "https") and parts.netloc else None
    return None if u.startswith("//") or u.startswith("\\") else u


# ---- shared rules ---------------------------------------------------------------------------------------------

def trigger_level(trigger, alarm=None):
    """The alarm level an alarm condition belongs to (1 Watch, 2 Warning, 3 Alarm): from alarm.json's groups when
    given, else from the id's letter (W, X, Y). None for no condition or one we can't place (charts.js triggerLevel)."""
    tid = str(trigger or "").strip()
    if not tid:
        return None
    for g in (alarm or {}).get("groups") or []:
        if isinstance(g, dict) and any(isinstance(x, dict) and x.get("id") == tid for x in g.get("triggers") or []):
            try:
                return int(g.get("level"))
            except (TypeError, ValueError):
                break
    return _LEVEL_BY_LETTER.get(tid[0].upper())


def signal_view(status, trigger=None, alarm=None):
    """(icon, token, word) for a signal (a tripwire), with the display cap of charts.js statusView: a confirmed
    signal is red only when the condition it feeds is Warning- or Alarm-level (X, Y). One that feeds a Watch-level
    condition (W), or none, shows amber: "Confirmed · counts toward Watch" (or "· no alarm condition"). The stored
    status is never changed, only how it is shown. `alarm` (alarm.json) is optional: without it the condition's letter
    decides, so reports and emails stay a pure function of the run."""
    key = str(status or "").strip().lower()
    if key not in SIGNAL_STATUS:
        return ("?", "muted", f"Unknown status: {status}" if status else "Unknown status")
    icon, tok, word = SIGNAL_STATUS[key]
    if key == "tripped":
        lv = trigger_level(trigger, alarm)
        if lv is None or lv < 2:
            name = next((x.get("name") for x in (alarm or {}).get("levels") or []
                         if isinstance(x, dict) and x.get("level") == 1), None) or _LEVEL_NAMES[1]
            return (icon, "warn", f"Confirmed · counts toward {name}" if lv == 1 else "Confirmed · no alarm condition")
    return (icon, tok, word)


_DISPLAY_WORDS = [  # (pattern, replacement): stored statuses and field names never change, only what readers see
    (re.compile(r'Observed · feeds Watch'), "Confirmed · counts toward Watch"),
    (re.compile(r"a tripwire's colour is capped at its trigger's level"), "a signal's colour is capped at its condition's level"),
    (re.compile(r"\bNEAR-TRIP\b"), "NEAR-CONFIRMATION"),
    (re.compile(r"\bWATCHING\b"), "OPEN"),
    (re.compile(r"\bTRIPPED\b"), "CONFIRMED"),
    (re.compile(r"'watching'"), "'open'"),
    (re.compile(r"'tripped'"), "'confirmed'"),
    (re.compile(r"\b([Ss]tatus (?:is |to )?|current |stays |is high in )watching\b"), r"\1open"),
    (re.compile(r"\bWatching is\b"), "Open is"),
    (re.compile(r"\btrip rule\b"), "confirm rule"),
    (re.compile(r"\bsecret RSI\b"), "hidden self-improvement"),
    (re.compile(r"\bstrict AGI\b"), "AGI under the v1.0 bar"),
]


def display_words(s):
    """Reader copy from data with the retired display words of spec 3.1 replaced (Quiet / Open / Confirmed, confirm
    rule, "Confirmed · counts toward Watch"). Data values, field names and ids are untouched."""
    s = str(s or "")
    for pat, rep in _DISPLAY_WORDS:
        s = pat.sub(rep, s)
    return s


_BACKGROUND = re.compile(r"\(\s*(?:[^()]*?[;,]\s*)?background\b[^()]*\)", re.I)


def story_date(item):
    """The date shown for a roundup item, one rule for the homepage, the short report and the email. The writer
    dates an item by when the event happened and marks one older than the reading's window "(background)", or sets
    background: true. That shows as "{date} (earlier event)": the event predates today's window, which is true of
    every background item (some were first reported in an earlier reading, so "first reported" would not be). A
    parenthesis that only repeats the item's own attribution ("Oct 5 (Quartz, citing the WSJ)") is dropped."""
    d = str((item or {}).get("date") or "").strip()
    bg = (item or {}).get("background") is True or bool(_BACKGROUND.search(d))
    d = _BACKGROUND.sub(" ", d)
    text = " ".join(str((item or {}).get(k) or "") for k in ("short", "text")).lower()
    for m in list(re.finditer(r"\s*\(([^()]+)\)", d)):
        inner = m.group(1).strip().lower()
        if inner and inner in text:
            d = d.replace(m.group(0), " ")
    d = " ".join(d.split())
    return f"{d} (earlier event)" if bg and d else d


def round_grid(v):
    """Our published rounding grid, half up with decimal arithmetic: 0.1 steps below 1, 0.5 steps from 1 to 10,
    whole points above 10. So 0.25 × 0.6 = 0.15 → 0.2, 2.27 → 2.5, 44.5 → 45. None stays None."""
    if v is None:
        return None
    d = Decimal(repr(float(v)))  # repr is the shortest round-trip form, so 0.25 * 0.6 reads as 0.15
    step = Decimal("0.1") if abs(d) < 1 else Decimal("0.5") if abs(d) <= 10 else Decimal(1)
    return float((d / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step)


def run_defs(run):
    """The definitions a run was made under; runs from before definitions v2.0 carry no `defs` and mean 1.0."""
    return str((run or {}).get("defs") or "1.0")


def defs_in_force(method, date):
    """Definitions in force for a run dated `date` (YYYY-MM-DD): the `definitions` value of the last changelog
    entry (in list order) that has one and is dated strictly before `date`; "1.0" if none. So the morning run
    on a method entry's own date stays on the old definitions and the next day's run is the first new reading."""
    out = "1.0"
    for c in ((method or {}).get("changelog") or []):
        if isinstance(c, dict) and c.get("definitions") and str(c.get("date") or "") < str(date):
            out = str(c["definitions"])
    return out


def method_boundary(run, prev):
    """True when `run` was made under different definitions from `prev`, the previous published run (missing
    defs = "1.0"). Then agi, A, C, D, D-open and the Index show METHOD_CHANGE instead of ▲▼ deltas; B keeps its
    real delta. No previous run means no boundary."""
    if not prev:
        return False
    return run_defs(run) != run_defs(prev)


def pending_defs(run, components):
    """True when the run's numbers use different definitions from the ones agi.html states
    (agi_components.json `definitionsVersion`); the pages then show the pending chip next to runs.agi and A–D.
    Never reads the build clock."""
    want = (components or {}).get("definitionsVersion")
    return bool(want) and run_defs(run) != str(want)


# ---- navigation -----------------------------------------------------------------------------------------------

def _root(path):
    return "../" * path.count("/") or "./"


def _hub_href(root, hub):
    return root if hub == "index.html" else root + hub


def _match(path, pattern):
    return path.startswith(pattern) if pattern.endswith("/") else path == pattern


def hub_for(path):
    """(hub path, relation) for a page: relation "page" on the hub itself, "true" on one of its children;
    (None, None) for a page outside the six hubs."""
    for hub, _, _, _ in NAV:
        if path == hub:
            return hub, "page"
    for hub, _, _, children in NAV:
        if any(_match(path, c) for c in children):
            return hub, "true"
    return None, None


def crumb_for(path):
    """The breadcrumb line for a child page; '' for a hub or a page outside the hubs.
    Reports read "Today › Daily report", analysis pages "Today › Daily report › Analysis"."""
    hub, rel = hub_for(path)
    if rel != "true":
        return ""
    root = _root(path)
    long = next(l for h, l, _, _ in NAV if h == hub)
    head = f'<a href="{_hub_href(root, hub)}">{escape(long)}</a>'
    m = _REPORT.match(path)
    if m and m.group(2):
        tail = f'<a href="{root}reports/{m.group(1)}.html">Daily report</a> › Analysis'
    elif m or path.startswith("reports/"):
        tail = "Daily report"
    elif _WEEKLY.match(path):
        tail = "Weekly wrap-up"
    elif path in CRUMB_TITLES:
        tail = escape(CRUMB_TITLES[path])
    elif path.startswith("weekly/"):
        tail = "Weekly wrap-ups"
    else:
        return ""
    return f'<p class="crumb">{head} › {tail}</p>'


def nav_html(path, active=""):
    """The site nav (nav.site2): the brand, six hubs (long labels on desktop, short ones on phones) and the
    Escape watch pill. The hub gets aria-current="page" on itself and "true" on its children; `active` (a hub
    path) is used only for a page outside the hubs."""
    root = _root(path)
    hub, rel = hub_for(path)
    if hub is None and active:
        hub, rel = next(((h, "true") for h, _, _, _ in NAV if h == active), (None, None))
    links = "".join(
        f'<a href="{_hub_href(root, h)}"{f" aria-current={chr(34)}{rel}{chr(34)}" if h == hub else ""}>'
        f'<span class="l">{escape(l)}</span><span class="s">{escape(s)}</span></a>'
        for h, l, s, _ in NAV)
    key_href, key_label = NAV_KEY
    key_cur = ' aria-current="page"' if path == key_href else ""
    return (f'  <nav class="site2" aria-label="Site">\n'
            f'    <a class="brand" href="{root}">Hidden AGI watch</a>\n'
            f'    <span class="nav-links">{links}</span>\n'
            f'    <a class="nav-key" href="{root}{key_href}"{key_cur}>{escape(key_label)}</a>\n'
            f'  </nav>\n')


# ---- boxes and footer -----------------------------------------------------------------------------------------

def subscribe_box():
    return (f'<div class="subscribe">\n  <div><strong>Get Hidden AGI watch by email.</strong> '
            f'<span class="muted">The latest reading, what changed, and the news that matters. Free.</span></div>\n'
            f'  <a class="btn" href="{SUBSCRIBE}" target="_blank" rel="noopener">Subscribe</a>\n</div>\n')


def footer(root, note="", date=None):
    """The site footer. note is optional page-specific HTML shown above the standard lines; date (YYYY-MM-DD)
    gives the dated variant the daily report pages carry."""
    extra = f'    <p class="muted small">{note}</p>\n' if note else ""
    if date:
        made = ("Researched, written and published automatically by a custom AI agent built for this project, "
                f'{datetime.strptime(date, "%Y-%m-%d").strftime("%-d %b %Y")}.')
    else:
        made = "Researched, written and published each day by a custom AI agent."
    return (f"""  <footer>
{extra}    <p>{made} The owner sets the definitions and alarm thresholds and approves every alarm alert. Probabilities are subjective; every factual claim links to its source, and the claims in our readings carry an evidence rating (see Method). Not advice.</p>
    <p><a href="{root}about.html">About</a> · <a href="{root}start-here.html#method">Method</a> · <a href="{root}changes.html">Changes and corrections</a> · <a href="{root}style.html">Chart style guide</a> · <a href="{REPO}">Source on GitHub</a> · <a href="{root}feed.xml">RSS</a></p>
  </footer>
""")


def page(*, path, title, description, body, active="", og_image=None, og_w=1200, og_h=630, og_type="website",
         og_image_alt=None, main_class="", footer_note="", scripts="", head_extra="", nav_top="", subscribe=True):
    """One generated page.

    path: the published path relative to the site root, e.g. 'scorecard.html', 'weekly/2026-10-09.html' or
      'reports/2026-10-06-analysis.html'. It sets the relative root, the canonical URL, the lit hub, the
      breadcrumb and (for daily report pages) the dated footer.
    active: a hub path; used only to light a hub for a page outside NAV (otherwise the path decides).
    og_image defaults to the latest share card (with its alt text); og_image_alt adds og:image:alt and
      twitter:image:alt; main_class sets <main class=...>; footer_note is HTML shown above the footer lines.
    head_extra: raw HTML placed at the end of <head> (the homepage's site-verification meta and JSON-LD).
    nav_top: the in-page nav under the breadcrumb: a whole <nav ...> element, or just its links, which are
      wrapped in <nav class="top" aria-label="On this page">.
    subscribe: False leaves out the subscribe box page() appends before the footer."""
    root = _root(path)
    url = SITE + path.replace("index.html", "")
    img = og_image or SITE + "cards/latest.png"
    if og_image_alt is None and not og_image:
        og_image_alt = LATEST_CARD_ALT
    t, d = escape(title, quote=True), escape(description, quote=True)
    alt = escape(og_image_alt, quote=True) if og_image_alt else ""
    og_alt = f'\n<meta property="og:image:alt" content="{alt}">' if alt else ""
    tw_alt = f'\n<meta name="twitter:image:alt" content="{alt}">' if alt else ""
    main_open = f'<main class="{escape(main_class, quote=True)}">' if main_class else "<main>"
    head_more = f"\n{head_extra.strip()}" if head_extra and head_extra.strip() else ""
    crumb = crumb_for(path)
    crumb = f"  {crumb}\n" if crumb else ""
    top = (nav_top or "").strip()
    if top and not top.startswith("<nav"):
        # rp-top: the new pages' in-page nav wraps on phones instead of scrolling under a fade (frozen reports keep
        # their own nav.top markup and never read this module)
        top = f'<nav class="top rp-top" aria-label="On this page">{top}</nav>'
    top = f"  {top}\n" if top else ""
    m = _REPORT.match(path)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{escape(title)}</title>
<meta name="description" content="{d}">
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="Hidden AGI watch">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{d}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{img}">
<meta property="og:image:width" content="{og_w}">
<meta property="og:image:height" content="{og_h}">{og_alt}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{t}">
<meta name="twitter:description" content="{d}">
<meta name="twitter:image" content="{img}">{tw_alt}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=Public+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{root}assets/style.css">
<link rel="canonical" href="{url}">
<link rel="alternate" type="application/rss+xml" title="Hidden AGI watch" href="{root}feed.xml">
<link rel="icon" type="image/png" href="{root}assets/brand/avatar-64.png">{head_more}
</head>
<body>
<a class="skip-link sr-only" href="#content">Skip to content</a>
{main_open}
{nav_html(path, active)}{crumb}{top}<div id="content" tabindex="-1"></div>{body}
{subscribe_box() if subscribe else ""}
{footer(root, footer_note, m.group(1) if m else None)}</main>
<script type="module">import {{alarmBanner}} from "{root}assets/charts.js"; alarmBanner("{root}");</script>
{scripts}
</body>
</html>
"""
