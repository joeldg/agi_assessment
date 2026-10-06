"""archive.html, "Every reading" (spec 12): one row per reading, newest first. It replaces the old homepage's run
history. Server-rendered, no JavaScript.

Columns: date · definitions (v1.0 / v2.0, from the run's `defs`, missing = v1.0) · Hidden AGI Index · AGI anywhere
today · fire-alarm level · what moved (needle.subject; on a quiet day, "Quiet day" and that day's top story,
never the bare subject) · report · analysis. The first reading under new definitions is marked as a method change;
an entry that is not a published reading (the same-morning chat baseline) is listed as "baseline, not compared".
"""
from . import common as C
from .common import as_dict, as_list, e

TITLE = "Every reading · Hidden AGI watch"
DESCRIPTION = ("Every daily reading, newest first: the definitions it used, the Hidden AGI Index, AGI anywhere, the "
               "fire-alarm level and what moved, with links to each report.")


def _level_names(alarm):
    return {lv.get("level"): lv.get("name") for lv in as_list(as_dict(alarm).get("levels")) if isinstance(lv, dict)}


def moved_cell(subject, quiet=False):
    """The "What moved" cell (HTML). On a quiet day no news moved our numbers, so the needle's subject is only that
    day's most notable story: it is shown muted after "Quiet day", never on its own as if it had moved something."""
    if not quiet:
        return e(subject)
    return "Quiet day" + (f' <span class="small muted">· top story: {e(subject)}</span>' if subject else "")


def rows(runs, alarm):
    runs = [r for r in as_list(runs) if isinstance(r, dict)]
    pub = C.published(runs)
    pub_ids = {id(r) for r in pub}
    others = [r for r in runs if id(r) not in pub_ids and not (r.get("report") and r.get("comparable") is not False)]
    names = _level_names(alarm)
    out = []
    prev = None
    marks = {}
    for r in pub:   # date order: the boundary is between consecutive published readings
        if prev is not None and C.run_defs(r) != C.run_defs(prev):
            marks[id(r)] = f"method change (definitions v{C.run_defs(r)})"
        prev = r
    allr = [(str(r.get("date") or ""), 1, i, r) for i, r in enumerate(pub)] + \
           [(str(r.get("date") or ""), 0, i, r) for i, r in enumerate(others)]
    for _, is_pub, _, r in sorted(allr, key=lambda t: (t[0], t[1], t[2]), reverse=True):
        a = as_dict(r.get("alarm"))
        lvl = a.get("level")
        alarm_t = f"Level {lvl} · {names.get(lvl) or C.LEVEL_DEFAULTS.get(lvl, ('', '', ''))[2]}" if lvl is not None else "–"
        defs = f"v{C.run_defs(r)}"
        if not is_pub:
            defs += ' <span class="small muted">baseline, not compared</span>'
        elif id(r) in marks:
            defs += f' <span class="small muted">{e(marks[id(r)])}</span>'
        nd = as_dict(r.get("needle"))
        subj = nd.get("subject") or ("" if is_pub else r.get("label") or "")
        moved = moved_cell(subj, quiet=nd.get("quiet") is True)
        rep = C.link(r.get("report"), "report") if is_pub else ""
        ana = C.link(r.get("analysis"), "analysis") if is_pub and r.get("analysis") else ""
        out.append(f'<tr><td data-label="Date">{e(C.day(r.get("date")))}</td><td data-label="Definitions">{defs}</td>'
                   f'<td data-label="Hidden AGI Index" class="num">{C.fmt(r.get("index"))}%</td>'
                   f'<td data-label="AGI anywhere" class="num">{C.fmt(C.value(r, "agi"))}%</td>'
                   f'<td data-label="Fire alarm">{e(alarm_t)}</td><td data-label="What moved">{moved}</td>'
                   f'<td data-label="Report">{rep}</td><td data-label="Analysis">{ana}</td></tr>')
    return out


def render(root_dir=None):
    runs = C.load_json("data/runs.json", root_dir)
    alarm = C.load_json("data/alarm.json", root_dir)
    rs = rows(runs, alarm)
    n = len(C.published(runs))
    table = ('<div class="table-wrap"><table class="archive"><caption class="sr-only">Every reading, newest first</caption>'
             '<tr><th>Date</th><th>Definitions</th><th>Hidden AGI Index</th><th>AGI anywhere (v1.0 rows: the strict bar)</th>'
             f'<th>Fire alarm</th><th>What moved</th><th>Report</th><th>Analysis</th></tr>{"".join(rs)}</table></div>'
             if rs else '<p class="muted">No readings yet.</p>')
    return f"""  <h1>Every reading</h1>
  <p class="lede">{n} published reading{'s' if n != 1 else ''}, newest first. Each links to its report, and newer readings also link to their full analysis.</p>
  <p class="small">The week in one page: <a href="weekly/">Friday wrap-ups →</a> · How each number is made: <a href="start-here.html#pieces">How our numbers fit →</a></p>
  {table}
  <p class="small muted">On a quiet day no news moved our numbers; the row names that day's top story instead. Readings under definitions v1.0 used the strict bar (the remote-work test) for AGI anywhere and for A, C and D; they keep that meaning. <a href="changes.html#method">The method log →</a></p>"""


PAGE = dict(title=TITLE, description=DESCRIPTION, body=render, scripts_code="", head_extra="")
