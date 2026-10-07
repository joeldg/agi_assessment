"""jobs.html, "Jobs watch" (the Jobs plugin's spec, 8.3): the standing page of the Jobs tracker, a child of the
"Today" hub. Server-rendered, no JavaScript. Built only when data/jobs/claims.json exists (import_jobs.py writes it);
otherwise render() returns None and build_pages.py skips the page.

The page: a one-line glance, what the tracker is (it never feeds the Index, the odds or the alarm), how to read the
scale, the status board, each claim collapsed under its id (#J0 to #J12) with its wording, marks, indicators and
history, the newest edition's evidence, and the archive of editions with the wrap-ups that carried them.
"""
import re
from pathlib import Path

from . import common as C
from .common import e

TITLE = "Jobs watch · Hidden AGI watch"
DESCRIPTION = ("Jobs watch: thirteen testable claims about the move to a post-AGI economy, from capital already pricing "
               "in labor substitution to the null that this is a normal technology transition, each with its evidence.")
EDITION = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def _editions(root):
    folder = Path(root or C.ROOT) / "data" / "jobs"
    return sorted((m.group(1) for m in (EDITION.match(p.name) for p in folder.glob("*.json")) if m), reverse=True)


def _details(fid, title, body, note=""):
    return (f'<details id="{e(fid)}"><summary><h3 style="display:inline">{title}</h3>{note}</summary>'
            f'<div class="body">{body}</div></details>')


def _claim(c):
    import jobs_render as J
    st = c.get("status")
    pend = c.get("pending") or {}
    note = (f' <span class="st st-{e(st)}">{J.STATUS_LABEL.get(st, e(st))}</span>'
            + (f' <span class="small muted">· {J.STATUS_LABEL.get(pend.get("to"), "")} proposed, under review</span>' if pend else ""))
    marks = "".join(f'<li><strong>{J.STATUS_LABEL[k]}</strong>: {e(c.get("marks", {}).get(k, ""))}</li>'
                    for k in reversed(J.ORDER) if c.get("marks", {}).get(k))
    inds = []
    for i in c.get("indicators") or []:
        conf = "; ".join(e(x) for x in i.get("confounders") or [])
        comp = f' Compared with: {e(i["comparison"])}.' if i.get("comparison") else ""
        inds.append(f'<li><a href="{e(i.get("url", ""))}" target="_blank" rel="noopener">{e(i.get("name", ""))}</a>. '
                    f'{e(i.get("source", ""))} · {e(i.get("cadence", ""))} · {e(i.get("dataKind", ""))} data. '
                    f'<span class="small muted">Confounders: {conf}.{comp}</span></li>')
    hist = "".join(f'<li><span class="rdate">{e(h.get("date", ""))}</span> '
                   f'{J.STATUS_LABEL.get(h.get("from"), "start") if h.get("from") else "Start"} → {J.STATUS_LABEL.get(h.get("to"), "")}'
                   f'{" (the owner)" if h.get("by") == "owner" else ""}: {e(h.get("why", ""))}</li>'
                   for h in reversed(c.get("history") or []))
    body = (f'<p>{e(c.get("wording", ""))}</p><p class="small muted">Why we track it: {e(c.get("why", ""))}</p>'
            f'<h4>Marks</h4><ul class="jobs-items">{marks}</ul>'
            f'<h4>Indicators</h4><ul class="jobs-items">{"".join(inds)}</ul>'
            + (f'<h4>History</h4><ul class="jobs-items">{hist}</ul>' if hist else ""))
    return _details(c.get("id"), f'{e(c.get("id"))} · {e(c.get("label", ""))}', body, note)


def render(root_dir=None):
    import jobs_render as J
    claims = C.load_json("data/jobs/claims.json", root_dir)
    if not isinstance(claims, dict) or not claims.get("claims"):
        return None
    cl = claims["claims"]
    counts = {}
    for c in cl:
        counts[c.get("status")] = counts.get(c.get("status"), 0) + 1
    glance = " · ".join(f'{counts[k]} {J.STATUS_LABEL[k]}' for k in reversed(J.ORDER) if counts.get(k))
    board = J.strip_html({"strip": [{"id": c["id"], "status": c.get("status"), "prev": None,
                                     "pending": {"to": c["pending"]["to"]} if c.get("pending") else None} for c in cl]}, claims, root="")
    scale = "".join(f'<li><strong>{J.STATUS_LABEL[k]}</strong>: {e((claims.get("defaultMarks") or {}).get(k, ""))}</li>'
                    for k in reversed(J.ORDER))
    eds = _editions(root_dir)
    newest = C.load_json(f"data/jobs/{eds[0]}.json", root_dir) if eds else None
    latest = ""
    if isinstance(newest, dict):
        latest = (f'<section id="latest"><h2>This week\'s evidence</h2>'
                  f'<p class="small muted">From the edition of {e(newest.get("date", ""))}, carried in the '
                  f'<a href="weekly/{e(eds[0])}.html">wrap-up of {e(eds[0])}</a>. {e(newest.get("headline", ""))}</p>'
                  f'<ul class="jobs-items">{"".join(J.item_html(i) for i in J.top_items(newest))}</ul></section>')
    archive = "".join(
        f'<li><a href="weekly/{e(d)}.html">{e(d)}</a>: {e((C.load_json(f"data/jobs/{d}.json", root_dir) or {}).get("headline", ""))}</li>'
        for d in eds)
    return f"""  <h1>Jobs watch</h1>
  <p class="lede">Thirteen testable claims about the move to a post-AGI economy, and where the evidence puts each one today. {e(glance)}.</p>
  <section id="about" class="prose"><p>Capital is forward-looking: firms and markets act on what they expect AI to do before it shows in
  employment data, so their positioning is the earliest evidence. Each claim has written marks that decide its status, and
  its status moves at most one step a week; a move to Established or Contradicted is only proposed until the owner confirms it.
  J0 is the null hypothesis, that so far this is a normal technology transition, and every edition reports the strongest
  evidence for it. The thesis's end state, demand that depends on people without wages, is framing here; J9 measures the
  part of it that can be measured now.</p>
  <p class="small muted">{J.DISCLAIMER}</p>
  <h2>How to read a status</h2><ul class="jobs-items">{scale}</ul></section>
  <section id="board" class="jobs"><h2>Where the claims stand</h2>{board}</section>
  <section id="claims"><h2>The claims</h2>{"".join(_claim(c) for c in cl)}</section>
  {latest}
  <section id="editions"><h2>Every edition</h2><ul class="jobs-items">{archive or "<li>No edition yet.</li>"}</ul></section>
  <p class="small muted">Jobs watch is built from the post_agi_work plugin's data (<a href="https://github.com/joeldg/post_agi_work">github.com/joeldg/post_agi_work</a>),
  claims version {e(claims.get("version", ""))}.</p>"""


PAGE = dict(title=TITLE, description=DESCRIPTION, body=render, scripts_code="", head_extra="")
