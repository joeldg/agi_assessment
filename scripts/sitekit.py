"""Shared page shell for generated pages: head, social tags, nav, subscribe box, footer.

Every generated page (the standing sections, weekly wrap-ups, the style guide) goes through
page() so the site stays consistent. SITE and SUBSCRIBE are defined here once; the other
scripts import them from this module.
"""
from html import escape
from urllib.parse import urlsplit

SITE = "https://joeldg.github.io/agi_assessment/"
SUBSCRIBE = "https://hidden-agi.kit.com/f2b4d2f30e"
REPO = "https://github.com/joeldg/agi_assessment"
# The alt text for the default share card (cards/latest.png).
LATEST_CARD_ALT = ("Share card for the latest daily reading: the Hidden AGI Index, "
                   "the A–D probabilities and the fire-alarm level")
NAV = [
    ("", "Hidden AGI watch", "brand"),
    ("escape.html", "Escape watch", "nav-key"),   # hypothesis C's chokepoint indicators, kept prominent
    ("start-here.html", "Start here", ""),
    ("alarm.html", "Fire alarm", ""),
    ("weekly/", "Weekly", ""),
    ("scorecard.html", "Scorecard", ""),
    ("trends.html", "Trends", ""),
    ("money.html", "Money", ""),
    ("disclosure-lag.html", "Disclosure lag", ""),
    ("agi-claims.html", "AGI claims", ""),
    ("calendar.html", "Calendar", ""),
    ("steelman.html", "Steelman", ""),
    ("about.html", "About", ""),
]


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


def subscribe_box():
    return (f'<div class="subscribe">\n  <div><strong>Get Hidden AGI watch by email.</strong> '
            f'<span class="muted">The latest reading, what changed, and the news that matters. Free.</span></div>\n'
            f'  <a class="btn" href="{SUBSCRIBE}" target="_blank" rel="noopener">Subscribe</a>\n</div>\n')


def footer(root, note=""):
    """The site footer. note is optional page-specific HTML shown above the standard lines."""
    extra = f'    <p class="muted small">{note}</p>\n' if note else ""
    return (f"""  <footer>
{extra}    <p>Researched, written and published automatically each day by a custom AI agent built for this project. The site's owner sets the definitions and alarm thresholds and approves every alarm alert. Probabilities are subjective estimates with wide uncertainty; every factual claim links to its source, and secondhand sources are marked. Not investment, policy or security advice.</p>
    <p><a href="{root}about.html">About</a> · <a href="{root}start-here.html#method">Method</a> · <a href="{root}about.html#corrections">Corrections</a> · <a href="{root}style.html">Chart style guide</a> · <a href="{REPO}">Source on GitHub</a> · <a href="{root}feed.xml">RSS</a></p>
  </footer>
""")


def page(*, path, title, description, body, active="", og_image=None, og_w=1200, og_h=630,
         og_type="website", og_image_alt=None, main_class="", footer_note="", scripts=""):
    """path is the published path relative to the site root, e.g. 'scorecard.html' or 'weekly/2026-10-02.html'.
    og_image defaults to the latest share card (with its alt text); og_image_alt adds og:image:alt and
    twitter:image:alt; main_class sets <main class=...>; footer_note is HTML shown above the footer lines."""
    depth = path.count("/")
    root = "../" * depth or "./"
    url = SITE + path.replace("index.html", "")
    img = og_image or SITE + "cards/latest.png"
    if og_image_alt is None and not og_image:
        og_image_alt = LATEST_CARD_ALT
    nav = "\n".join(
        f'    <a{" class=" + chr(34) + cls + chr(34) if cls else ""} href="{root}{href}"'
        f'{" aria-current=" + chr(34) + "page" + chr(34) if href == active else ""}>{escape(label)}</a>'
        for href, label, cls in NAV)
    t, d = escape(title, quote=True), escape(description, quote=True)
    alt = escape(og_image_alt, quote=True) if og_image_alt else ""
    og_alt = f'\n<meta property="og:image:alt" content="{alt}">' if alt else ""
    tw_alt = f'\n<meta name="twitter:image:alt" content="{alt}">' if alt else ""
    main_open = f'<main class="{escape(main_class, quote=True)}">' if main_class else "<main>"
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
<link rel="icon" type="image/png" href="{root}assets/brand/avatar-64.png">
</head>
<body>
{main_open}
  <nav class="site" aria-label="Site">
{nav}
  </nav>
{body}
{subscribe_box()}
{footer(root, footer_note)}</main>
<script type="module">import {{alarmBanner}} from "{root}assets/charts.js"; alarmBanner("{root}");</script>
{scripts}
</body>
</html>
"""
