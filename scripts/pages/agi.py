"""agi.html, "Is AGI here?" (spec 5, 6): the definition, stated once, and the eight-part tracker.

Server-rendered from data/agi_components.json; the module script then calls charts.js agiMap on #agi-map, which
replaces the static view (6.7) and restores it if it can't draw. The static view's part sections carry the same
ids as the JS deep links (#breadth … #generalization), so agi.html#horizon works without JavaScript.
"""
from . import common as C
from .common import as_dict, as_list, e

TITLE = "Is AGI here? · Hidden AGI watch"
DESCRIPTION = ("What we mean by AGI, and how close each of its eight parts is: the best public result for each part "
               "against its published test, with the evidence, the hard parts and what we watch.")

SCRIPTS_CODE = r"""
// agi.html: draw the eight-part tracker over the server-rendered view (charts.js agiMap restores it on failure).
const host = document.getElementById("agi-map");
if(host){
  Promise.all([
    j("data/agi_components.json"),
    j("data/trends.json").catch(err => { console.error("agi.html: data/trends.json:", err); return null; })
  ]).then(([data, trends]) => { K.agiMap(host, data, {today: {date: host.dataset.today}, trends, root: ""}); })
    .catch(err => console.error("agi.html: couldn't load data/agi_components.json; the plain view stays:", err));
}
"""


def _frameworks(data, root=""):
    rows = []
    for f in as_list(data.get("frameworks")):
        if not isinstance(f, dict):
            continue
        best = e(f.get("best"))
        if f.get("bestUrl"):
            best = C.link(f["bestUrl"], str(f.get("best") or ""), root) or best
        rows.append(f'<tr><td>{e(f.get("name"))}<div class="small muted">{e(f.get("year"))}</div></td>'
                    f'<td data-label="What it requires">{e(f.get("definition"))}</td>'
                    f'<td data-label="Physical work">{e(f.get("physical"))}</td>'
                    f'<td data-label="Versus ours">{e(f.get("vsOurs"))}</td>'
                    f'<td data-label="Best score today">{best} {C.rtag(f)} {C.link(f.get("url"), "source", root)}</td></tr>')
    if not rows:
        return ""
    return ('<div class="table-wrap"><table class="am-fw"><caption class="sr-only">How others define AGI</caption>'
            '<tr><th>Definition</th><th>What it requires</th><th>Physical work</th><th>Versus ours</th>'
            f'<th>Best score today</th></tr>{"".join(rows)}</table></div>')


def _first_research(data):
    ds = sorted(str(h.get("date")) for h in as_list(data.get("history")) if isinstance(h, dict) and h.get("date"))
    return ds[0] if ds else data.get("lastReviewed")


def render(root_dir=None):
    data = C.load_components(root_dir)
    runs = C.load_json("data/runs.json", root_dir)
    trends = C.load_json("data/trends.json", root_dir)
    run = C.newest(runs) or {}
    prev = C.prev_published(runs, run) if run else None
    agi = as_dict(run.get("agi"))
    # V10: on the first reading under new definitions the drop from yesterday is labelled, as on card 1
    mc = (f' <span class="small muted">· <a href="changes.html#method">{e(C.METHOD_CHANGE)}</a></span>'
          if C.is_boundary(run, prev) else "")
    ok = C.ok_view(data)
    chip = C.pending_chip(run, data) if ok else ""
    d = as_dict(data.get("definition")) if ok else {}
    adopted = data.get("adopted") if ok else None
    proposed = ('<p class="small muted am-proposed">Proposed: not yet in effect. The method log will date the change.</p>'
                if ok and not adopted else "")
    ver = e(data.get("definitionsVersion") or "2.0") if ok else "2.0"
    comps = data["components"] if ok else []
    v1 = ", ".join(str(x.get("short") or x["id"]).lower() for x in comps if x.get("v1Test"))
    added = [str(x.get("short") or x["id"]).lower() for x in comps if not x.get("v1Test")]
    n_added = C.NUM_WORDS.get(len(added), str(len(added)))
    until = (f"Through the reading of {C.day(adopted)}" if adopted else f"Until definitions v{ver} take effect")
    wm = C.work_month_text(trends)
    why2030 = ""
    if wm and not chip:   # under the pending chip the figures are v1.0's, so v2.0's added parts don't explain them
        no_trend = [x for x in ("generalization", "learning") if x in added]
        why2030 = (f" Why only {C.fmt(agi.get('y2030'))}% by end-2030 when the time-horizon trend reaches a work-month {wm}: "
                   "that trend covers one test of one part, METR's suite can't yet measure that length"
                   + (f", and {C.NUM_WORDS.get(len(no_trend))} of the parts v{ver} adds ({', '.join(no_trend)}) have no "
                      "trend at all." if no_trend else "."))
    today_attr = f' data-today="{e(run.get("date"))}"' if run.get("date") else ""
    fw_note = e(as_dict(data.get("frameworksSource")).get("statusNote")) if ok else ""
    reviewed = ""
    if ok:
        first = _first_research(data)
        reviewed = (f'<p class="small muted am-reviewed">Each part was researched and adversarially verified on '
                    f'{e(C.day(first))}, and is refreshed every Friday. Reviewed {e(C.day(data.get("lastReviewed")))} · '
                    f'<a href="changes.html">Changes →</a></p>')
    definition = (f'<p class="def">{e(d.get("text"))}</p>' if d.get("text") else f'<p class="def">{e(C.UNAVAILABLE)}</p>')
    figs = f"{C.fmt(agi.get('now'))}% today, {C.fmt(agi.get('y2030'))}% by end-2030"
    if chip:   # ED15: the run's figures are still the v1.0 remote-work test's; say so instead of explaining them by v2.0
        numbers_lead = (f"Until the next reading, AGI anywhere ({figs}){chip} is still our v1.0 figure, for the "
                        "remote-work test; from the next reading it is our probability that some system, public or "
                        "hidden, meets all eight parts at once.")
    else:
        numbers_lead = (f"AGI anywhere ({figs}) is our probability that some system, public or hidden, meets all eight "
                        "parts at once.")
    return f"""  <h1>Is AGI here?</h1>
  <p class="hq-a am-answer">{C.answer_line(data)}</p>
  <p class="hq-line">AGI anywhere, public or hidden: <strong>{C.fmt(agi.get('now'))}%</strong> today · {C.fmt(agi.get('y2030'))}% by end-2030 · {C.fmt(agi.get('y2035'))}% by end-2035{chip}{mc} <a href="#numbers">How we get it →</a></p>
  <div class="am-def" id="definition">
    {definition}
    <p class="small muted">Definitions v{ver}. Physical and embodied work is out of scope. One system must meet all eight parts below at the same time, and the v1.0 remote-work test stays as one of its tests. A part counts as met only when a public system passes its published test. A few tests ask for more than the definition strictly needs (each part's "The full test" says which); our probabilities judge the definition itself. <a href="#v1">How this relates to v1.0</a> · <a href="#others">How others define AGI</a></p>
    {proposed}
  </div>
  <h2 class="am-h2" id="tracker">The eight parts</h2>
  <p class="muted small am-intro">Best public evidence for each part, against its bar. A part's status is the highest of its test's published marks that the evidence reaches. Select a part for the test, the measurements, the hard parts, who is working on it and what we watch.</p>
  <section id="agi-map" aria-label="The eight parts of AGI"{today_attr}>
    {C.static_tracker(data, "", trends)}
  </section>
  <section id="numbers"><h2>From the parts to our number</h2>
    <p class="prose">{numbers_lead} It can be no higher than the chance that its weakest part is met. The tracker shows public systems; the probability adds what could be hidden.{why2030} <a href="start-here.html#pieces">How our numbers fit together →</a></p>
  </section>
  <section id="excludes"><h2>What it leaves out, and why</h2><p class="prose">{e(d.get('excludes'))}</p></section>
  <section id="v1"><h2>How v{ver} relates to v1.0</h2>
    <p class="prose">{e(until)}, our bar was one test: {e(d.get('remoteWorkTest'))} That test still stands inside v{ver}, read through {C.NUM_WORDS.get(len(comps) - len(added), '')} parts ({e(v1)}). v{ver} adds {n_added} parts the old test did not require: {e(', '.join(added))}. So v{ver} is at least as strict on every axis, and re-derived numbers can only hold or fall. Readings and forecasts made under v1.0 keep resolving under v1.0. <a href="changes.html#method">The method change →</a></p>
  </section>
  <section id="others"><h2>How others define AGI</h2>
    {_frameworks(data) if ok else ''}
    <p class="small muted">{fw_note} Lab leaders' "AGI is here" claims are on the <a href="agi-claims.html">AGI claims ledger →</a></p>
  </section>
  {reviewed}"""


PAGE = dict(title=TITLE, description=DESCRIPTION, body=render, scripts_code=SCRIPTS_CODE, head_extra="")
