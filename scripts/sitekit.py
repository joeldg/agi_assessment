"""Shared page shell for generated pages: head, social tags, nav, subscribe box, footer.

Every generated page (the standing weekly sections, weekly wrap-ups, the style guide)
goes through page() so the site stays consistent.
"""
from html import escape

SITE = "https://joeldg.github.io/agi_assessment/"
SUBSCRIBE = "https://hidden-agi.kit.com/f2b4d2f30e"
NAV = [
    ("", "Hidden AGI watch", "brand"),
    ("start-here.html", "Start here", ""),
    ("weekly/", "Weekly wrap-up", ""),
    ("scorecard.html", "Scorecard", ""),
    ("disclosure-lag.html", "Disclosure lag", ""),
    ("agi-claims.html", "AGI claims", ""),
    ("calendar.html", "Calendar", ""),
    ("steelman.html", "Steelman", ""),
    ("trends.html", "Trends", ""),
]


def subscribe_box():
    return (f'<div class="subscribe">\n  <div><strong>Get Hidden AGI watch by email.</strong> '
            f'<span class="muted">The latest reading, what changed, and the news that matters. Free.</span></div>\n'
            f'  <a class="btn" href="{SUBSCRIBE}" target="_blank" rel="noopener">Subscribe</a>\n</div>\n')


def page(*, path, title, description, body, active="", og_image=None, og_w=1200, og_h=630,
         og_type="website", scripts=""):
    """path is the published path relative to the site root, e.g. 'scorecard.html' or 'weekly/2026-10-02.html'."""
    depth = path.count("/")
    root = "../" * depth or "./"
    url = SITE + path.replace("index.html", "")
    img = og_image or SITE + "cards/latest.png"
    nav = "\n".join(
        f'    <a{" class=" + chr(34) + cls + chr(34) if cls else ""} href="{root}{href}"'
        f'{" aria-current=" + chr(34) + "page" + chr(34) if href == active else ""}>{escape(label)}</a>'
        for href, label, cls in NAV)
    t, d = escape(title, quote=True), escape(description, quote=True)
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
<meta property="og:image:height" content="{og_h}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{t}">
<meta name="twitter:description" content="{d}">
<meta name="twitter:image" content="{img}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=Public+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{root}assets/style.css">
<link rel="alternate" type="application/rss+xml" title="Hidden AGI watch" href="{root}feed.xml">
<link rel="icon" type="image/png" href="{root}assets/brand/avatar-64.png">
</head>
<body>
<main>
  <nav class="site" aria-label="Site">
{nav}
  </nav>
{body}
{subscribe_box()}
  <footer>
    Researched and drafted daily by a custom AI agent built for this project. Probabilities are subjective estimates with wide uncertainty, and every factual claim is sourced. Not investment, policy or security advice. <a href="{root}style.html">Chart style guide</a> · <a href="https://github.com/joeldg/agi_assessment">Source on GitHub</a>.
  </footer>
</main>
{scripts}
</body>
</html>
"""
