"""The Jobs section of the Friday wrap-up, on the page and in the email, and the pieces jobs.html shares (the Jobs
plugin's spec, 8.2 and 8.3).

The data is the week's edition (data/jobs/<FRIDAY>.json, written by import_jobs.py) and the claims
(data/jobs/claims.json). Everything here is display: nothing feeds the Index, the odds or the fire alarm.
"""
from html import escape

STATUS_LABEL = {"contradicted": "Contradicted", "no-clear-sign": "No clear sign", "emerging": "Emerging",
                "supported": "Supported", "established": "Established"}
ORDER = ["contradicted", "no-clear-sign", "emerging", "supported", "established"]
EMAIL_WORDS = 200          # the email block's budget (spec 8.2); check_data.py --pages warns above it
TOP_FALLBACK = 3           # items shown when an edition marks none as top
DISCLAIMER = ("Jobs is a separate tracker of the move to a post-AGI economy. It never feeds the Hidden AGI Index, "
              "the odds or the fire alarm, and it is not investment advice.")


def _arrow(prev, now):
    if prev not in ORDER or now not in ORDER or prev == now:
        return ""
    return " ↑" if ORDER.index(now) > ORDER.index(prev) else " ↓"


def labels(claims):
    return {c.get("id"): c.get("label", "") for c in (claims or {}).get("claims") or []}


def strip_html(ed, claims, root="../"):
    """The thirteen claims with their status words; an arrow when one moved, "under review" for a pending extreme."""
    names = labels(claims)
    rows = []
    for s in ed.get("strip") or []:
        st = s.get("status")
        pend = f' · {STATUS_LABEL.get(s["pending"]["to"], "")} under review' if s.get("pending") else ""
        rows.append(f'<li><span class="cl"><a href="{root}jobs.html#{escape(s["id"])}">{escape(s["id"])}</a> '
                    f'{escape(names.get(s["id"], ""))}</span><span class="st st-{escape(st or "")}">'
                    f'{STATUS_LABEL.get(st, escape(str(st)))}{_arrow(s.get("prev"), st)}{pend}</span></li>')
    return f'<ul class="jobs-strip">{"".join(rows)}</ul>'


def top_items(ed):
    items = [i for i in ed.get("evidence") or [] if i.get("top")]
    return items or (ed.get("evidence") or [])[:TOP_FALLBACK]


def item_html(i):
    import build_report as br
    from build_feed import outlet
    via = f' (via {escape(i["via"])})' if i.get("via") else ""
    return (f'<li><span class="rdate">{escape(str(i.get("eventDate", "")))}</span> {escape(i.get("text", ""))} '
            f'{br.chip(i.get("rating"), i.get("ratingNote"), i.get("ratingQual"))}'
            f'<a href="{escape(i.get("url", ""), quote=True)}" target="_blank" rel="noopener">{escape(outlet(i.get("url", "")))}</a>{via}</li>')


def section_html(ed, claims, root="../"):
    """The wrap-up page's last section, <section id="jobs">."""
    import build_report as br
    from build_feed import outlet
    names = labels(claims)
    base = ed.get("baseline") is True
    out = ['<section id="jobs" class="jobs"><h2>Jobs</h2>',
           f'<p class="kicker muted small">Tracking the move to a post-AGI economy · '
           f'{"baseline, " if base else ""}edition of {br.day(ed["date"])}</p>',
           f'<h3>{escape(ed.get("headline", ""))}</h3>', f'<p class="lede">{escape(ed.get("dek", ""))}</p>',
           f'<h4>{"Starting statuses" if base else "Where the claims stand"}</h4>' + strip_html(ed, claims, root)]
    moves = ed.get("moves") or []
    if moves:
        out.append('<h4>What moved</h4><ul class="jobs-items">' + "".join(
            f'<li><strong>{escape(m["id"])}</strong> {escape(names.get(m["id"], ""))}: '
            f'{STATUS_LABEL.get(m.get("from"), "")} → {STATUS_LABEL.get(m.get("to"), "")}'
            f'{" (confirmed by the owner)" if m.get("by") == "owner" else ""}. {escape(m.get("why", ""))}</li>'
            for m in moves) + "</ul>")
    elif not base:
        out.append('<p>No claim moved this week.</p>')
    if ed.get("pendingOwner"):
        out.append('<h4>Proposed, under review</h4><ul class="jobs-items">' + "".join(
            f'<li><strong>{escape(x["id"])}</strong> {escape(names.get(x["id"], ""))}: {STATUS_LABEL.get(x.get("from"), "")} '
            f'→ {STATUS_LABEL.get(x.get("to"), "")}. {escape(x.get("why", ""))}</li>' for x in ed["pendingOwner"]) + "</ul>")
    out.append('<h4>Evidence to read first</h4><ul class="jobs-items">' + "".join(item_html(i) for i in top_items(ed)) + "</ul>")
    nc = ed.get("nullCase") or {}
    by_id = {i.get("id"): i for i in ed.get("evidence") or []}
    if nc.get("text"):
        refs = ", ".join(f'<a href="{escape(by_id[e]["url"], quote=True)}" target="_blank" rel="noopener">{escape(outlet(by_id[e]["url"]))}</a>'
                         for e in nc.get("evidence") or [] if e in by_id)
        out.append(f'<h4>The case for the null</h4><p>{escape(nc["text"])}' + (f' <span class="small muted">({refs})</span>' if refs else "") + "</p>")
    elif nc.get("none"):
        out.append(f'<h4>The case for the null</h4><p>{escape(nc["none"])}</p>')
    rel = ed.get("releases") or []
    if base:
        out.append(f'<h4>Data</h4><p class="small">{len(rel)} official series loaded for the baseline; from next week this lists that week\'s new releases.</p>')
    elif rel:
        out.append('<h4>New data this week</h4><ul class="small">' + "".join(
            f'<li>{escape(str(r.get("series")))}: {escape(str(r.get("value")))} for {escape(str(r.get("period")))}</li>' for r in rel) + "</ul>")
    out.append(f'<p class="small"><a href="{root}jobs.html">The full tracker: every claim, its marks, indicators and history (live) →</a></p>'
               f'<p class="small muted">{DISCLAIMER}</p></section>')
    return "\n".join(out)


def _first_sentence(text):
    text = str(text or "").strip()
    head = text.split(". ")[0].rstrip(".")
    return head + "." if head else ""


def email_html(ed, claims):
    """The wrap-up email's Jobs block, email-safe (inline styles), at most EMAIL_WORDS words for a normal edition."""
    from build_feed import MUTED, SITE, h2, link, outlet, p, ul
    names = labels(claims)
    out = [h2("Jobs"), p(f'<strong>{escape(ed.get("headline", ""))}</strong>')]
    if ed.get("baseline") is True:
        groups = {}
        for s in ed.get("strip") or []:
            groups.setdefault(s.get("status"), []).append(s["id"] + (f' ({STATUS_LABEL.get(s["pending"]["to"], "")} proposed)' if s.get("pending") else ""))
        parts = [f'{STATUS_LABEL[k]}: {", ".join(groups[k])}' for k in reversed(ORDER) if k in groups and k != "no-clear-sign"]
        if groups.get("no-clear-sign"):
            parts.append(f'No clear sign: the other {len(groups["no-clear-sign"])}')
        out.append(p("Starting statuses. " + ". ".join(parts) + "."))
    elif ed.get("moves"):
        out.append(ul(f'<strong>{escape(m["id"])}</strong> {escape(names.get(m["id"], ""))}: {STATUS_LABEL.get(m.get("from"), "")} → '
                      f'{STATUS_LABEL.get(m.get("to"), "")}{" (confirmed by the owner)" if m.get("by") == "owner" else ""}. '
                      f'{escape(_first_sentence(m.get("why")))}' for m in ed["moves"]))
    else:
        out.append(p("No claim moved this week."))
    for x in ed.get("pendingOwner") or []:
        out.append(p(f'<span style="color:{MUTED}">Proposed, under review:</span> {escape(x["id"])} {escape(names.get(x["id"], ""))} '
                     f'→ {STATUS_LABEL.get(x.get("to"), "")}.'))
    nc = ed.get("nullCase") or {}
    if nc.get("text"):
        out.append(p(f'<span style="color:{MUTED}">The case for the null:</span> {escape(_first_sentence(nc["text"]))}'))
    top = top_items(ed)[:2]
    if top:
        out.append(ul(escape(_first_sentence(i.get("text"))) + " " + link(i.get("url", ""), outlet(i.get("url", ""))) for i in top))
    out.append(p(link(SITE + "jobs.html", "Full tracker →")))
    return "".join(out)
