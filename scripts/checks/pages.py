"""Visible-word budgets of the built pages (spec 2.2). WARN only, never an error; run with check_data.py --pages.

Words are counted as a browser shows them with no interaction: closed <details> (except the summary), nav,
footer, subscribe boxes, .sr-only, head and scripts are left out. agi.html is budgeted outside the tracker
(#agi-map) and the tracker on its own.

These counts read the server-rendered HTML only. Text a page's script draws (the scorecard's forecast bars, the
hidden.html gauge tiles, the calendar and claims lists) is not counted, so a JS-drawn page can be over its budget in a
browser while this check is quiet; the rendered count needs a browser (smoke.py runs Chrome). Inside #agi-map the
server HTML is the no-JS static view (spec 6.7: summary, table and eight sections), which agiMap replaces with the
collapsed widget (about 430 words); the static view has its own, larger budget.
"""
from . import visible_words, words

SKIP = ("nav", "footer", ".subscribe", ".share", ".sr-only")
# (page, budget, extra regions left out)
BUDGETS = [
    ("index.html", 500, ()),
    ("agi.html", 800, ("#agi-map",)),
    ("hidden.html", 600, ()),
    ("start-here.html", 1000, ()),
    ("alarm.html", 900, ()),
    ("escape.html", 800, ()),
    ("scorecard.html", 500, ()),
    ("trends.html", 500, ()),
    ("money.html", 450, ()),
    ("disclosure-lag.html", 450, ()),
    ("agi-claims.html", 500, ()),
    ("calendar.html", 700, ()),
    ("steelman.html", 1100, ()),
    ("about.html", 550, ()),
    ("jobs.html", 1200, ("#claims",)),   # the claims' collapsed details are left out, as agi.html's tracker is
]
WIDGET_BUDGET = 1500   # the no-JS static view of #agi-map (spec 6.7); the JS widget collapsed is about 430
WEEKLY_BUDGET = 1200
REPORT_BUDGET = 700
CALENDAR_ITEM = 25


def check(ctx, runs=None):
    """Returns the budget lines to print; over-budget pages and long calendar items are WARNs."""
    f, lines = ctx.f, []

    def note(rel, n, budget, what="words"):
        lines.append("PAGES  %-34s %5d %s (budget %d)%s" % (rel, n, what, budget, "  OVER" if n > budget else ""))
        if n > budget:
            f.warn("%s: %d visible %s, over its budget of %d (spec 2.2)" % (rel, n, what, budget))

    for rel, budget, extra in BUDGETS:
        html = ctx.read(rel)
        if html is None:
            lines.append("PAGES  %-34s not built" % rel)
            continue
        note(rel, visible_words(html, SKIP + extra), budget)
        if "#agi-map" in extra:
            widget = visible_words(html, SKIP) - visible_words(html, SKIP + extra)
            note(rel + " #agi-map", widget, WIDGET_BUDGET, "words, static view")
    # new weekly wrap-ups only (labelSet 2); frozen ones are never rebuilt
    for path in sorted((ctx.root / "data/weekly").glob("*.json")):
        doc = ctx.data.get("data/weekly/" + path.name)
        if not isinstance(doc, dict) or doc.get("labelSet") != 2:
            continue
        rel = "weekly/%s.html" % path.stem
        html = ctx.read(rel)
        if html is not None:
            note(rel, visible_words(html, SKIP), WEEKLY_BUDGET)
    # the wrap-up email's Jobs block, for every imported edition (Jobs plugin spec 8.2)
    claims = ctx.data.get("data/jobs/claims.json")
    for rel in sorted(r for r in ctx.data if r.startswith("data/jobs/") and r != "data/jobs/claims.json"):
        jobs = ctx.data.get(rel)
        if isinstance(jobs, dict) and isinstance(claims, dict):
            import jobs_render
            note("weekly/%s email Jobs block" % rel.rsplit("/", 1)[-1][:-5],
                 visible_words(jobs_render.email_html(jobs, claims), ()), jobs_render.EMAIL_WORDS)
    # the newest format-2 short report (prose outside tables; check_data's report rules hold the 1,000 cap)
    if isinstance(runs, list):
        r = next((x for x in reversed(runs) if isinstance(x, dict) and x.get("report")), None)
        if r and r.get("format") == 2:
            html = ctx.read(r["report"])
            if html is not None:
                note(r["report"], visible_words(html, SKIP + ("table",)), REPORT_BUDGET, "words of prose")
    # calendar items
    cal = ctx.data.get("data/calendar.json")
    for i, ev in enumerate(cal.get("events") or [] if isinstance(cal, dict) else []):
        if isinstance(ev, dict) and words(ev.get("title")) > CALENDAR_ITEM:
            f.warn("calendar.events[%d] (%s) is %d words; calendar items keep to %d" % (
                i, ev.get("date"), words(ev.get("title")), CALENDAR_ITEM))
    return lines
