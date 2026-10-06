"""changes.html, "Changes and corrections" (spec 12): one log for the method, the alarm criteria and corrections.

Server-rendered, no JavaScript. #method: data/method.json's changelog, newest first (a definitions entry also shows
its definition text and factors). #criteria: data/alarm.json's changelog, newest first. #corrections:
data/corrections.json, newest first, the 10 newest visible and older ones in <details> by month. This list
replaces the old client-side corrections list on About and Start here (about.html#corrections keeps a stub).
"""
from . import common as C
from .common import as_dict, as_list, e

TITLE = "Changes and corrections · Hidden AGI watch"
DESCRIPTION = ("Every change to our method and to the fire alarm's published criteria, and every correction we have "
               "made, newest first, each with its date and source.")
VISIBLE = 10
FACTOR_LABELS = (("now", "today"), ("y2030", "by end-2030"), ("y2035", "by end-2035"))


def _vkey(v):
    out = []
    for p in str(v or "").split("."):
        out.append(int(p) if p.isdigit() else 0)
    return out


def _newest_first(items):
    items = [(i, x) for i, x in enumerate(as_list(items)) if isinstance(x, dict)]
    items.sort(key=lambda t: (str(t[1].get("date") or ""), _vkey(t[1].get("version")), t[0]), reverse=True)
    return [x for _, x in items]


def _clean(s):
    return str(s or "").strip().rstrip(".")


def method_log(M):
    entries = _newest_first(as_dict(M).get("changelog"))
    if not entries:
        return '<p class="muted">The method log is unavailable.</p>'
    lis = []
    for c in entries:
        extra = ""
        if c.get("definitions"):
            f = as_dict(c.get("factors"))
            fs = " · ".join(f"{C.fmt(f.get(k))} {lab}" for k, lab in FACTOR_LABELS if C.num(f.get(k)) is not None)
            extra = (f'<details><summary>Definitions v{e(c["definitions"])}: the definition'
                     f'{" and the conversion factors" if fs else ""}</summary><div class="body">'
                     + (f'<p class="def">{e(c.get("definitionText"))}</p>' if c.get("definitionText") else "")
                     + (f'<p class="small">Conversion factors (the chance that a system meeting the v1.0 test also meets '
                        f'the rest of the definition): {fs}.</p>' if fs else "")
                     + (f'<p class="small muted">How the next reading converts our numbers: {e(c.get("rule"))}</p>'
                        if c.get("rule") else "")
                     + "</div></details>")
        why = f' <span class="muted">Why: {e(_clean(c["why"]))}.</span>' if c.get("why") else ""
        lis.append(f'<li><strong>v{e(c.get("version"))}</strong> · {e(C.day(c.get("date")))} · {e(c.get("change"))}{why}'
                   f'{extra}</li>')
    return f'<ul class="plain changes-log">{"".join(lis)}</ul>'


def criteria_log(A):
    entries = _newest_first(as_dict(A).get("changelog"))
    if not entries:
        return '<p class="muted">The alarm criteria log is unavailable.</p>'
    lis = "".join(f'<li><strong>v{e(c.get("version"))}</strong> · {e(C.day(c.get("date")))} · {e(c.get("change"))}'
                  + (f' <span class="muted">Why: {e(_clean(c["why"]))}.</span>' if c.get("why") else "") + "</li>"
                  for c in entries)
    return f'<ul class="plain changes-log">{lis}</ul>'


def _correction(c):
    was, now = c.get("was") or c.get("claim"), c.get("now") or c.get("correction")
    out = f'<li><strong>{e(C.day(c.get("date")) or "Undated")}</strong>'
    if c.get("item"):
        out += f" · {e(_clean(c['item']))}."
    if was:
        out += f" We said {e(_clean(was))}."
    if now:
        out += f" {'That was wrong: ' if was else ''}{e(_clean(now))}."
    links = [x for x in (C.link(c.get("page"), "affected page"), C.link(c.get("url"), "source")) if x]
    if links:
        out += " " + " · ".join(links)
    if c.get("emailed"):
        out += f' <span class="muted">Carried in the {e(C.day(c["emailed"]))} email.</span>'
    return out + "</li>"


def corrections_list(cs):
    cs = _newest_first(cs)
    if not cs:
        return '<p class="muted">No corrections so far.</p>'
    head = "".join(_correction(c) for c in cs[:VISIBLE])
    older, months = cs[VISIBLE:], []
    for c in older:
        m = C.month_year(c.get("date")) or "Undated"
        if not months or months[-1][0] != m:
            months.append((m, []))
        months[-1][1].append(c)
    rest = "".join(f'<details><summary>{e(m)}: {len(xs)} more correction{"s" if len(xs) != 1 else ""}</summary>'
                   f'<ul class="plain corrections">{"".join(_correction(c) for c in xs)}</ul></details>' for m, xs in months)
    return f'<ul class="plain corrections">{head}</ul>{rest}'


def glance(M, A, cs):
    bits = []
    defs = [c for c in as_list(as_dict(M).get("changelog")) if isinstance(c, dict) and c.get("definitions")]
    if as_dict(M).get("version"):
        latest_defs = _newest_first(defs)[0] if defs else None
        bits.append(f"Method v{e(M['version'])}" + (f" ({e(C.day(latest_defs.get('date'), False))})"
                                                     if latest_defs and str(latest_defs.get("version")) == str(M["version"]) else ""))
    if as_dict(A).get("version"):
        bits.append(f"alarm criteria v{e(A['version'])}")
    cs = _newest_first(cs)
    if cs:
        bits.append(f"{len(cs)} correction{'s' if len(cs) != 1 else ''}, newest {e(C.day(cs[0].get('date'), False))}")
    return " · ".join(bits)


def render(root_dir=None):
    M = C.load_json("data/method.json", root_dir)
    A = C.load_json("data/alarm.json", root_dir)
    CO = C.load_json("data/corrections.json", root_dir)
    cs = as_list(CO.get("corrections") if isinstance(CO, dict) else CO)
    return f"""  <h1>Changes and corrections</h1>
  <p class="lede">{glance(M, A, cs)}</p>
  <p class="small muted">We log every change to how we work and every error we correct. Readings and forecasts made under earlier definitions keep their meaning and resolve under them. <a href="#method">Method</a> · <a href="#criteria">Alarm criteria</a> · <a href="#corrections">Corrections</a></p>
  <section id="method" aria-labelledby="method-h"><h2 id="method-h">Method</h2>
    <p class="small muted">We change the version for any change to a definition, a gauge, the Index formula or a threshold. How we work: <a href="start-here.html#method">Method</a>.</p>
    {method_log(M)}
  </section>
  <section id="criteria" aria-labelledby="criteria-h"><h2 id="criteria-h">Fire alarm criteria</h2>
    <p class="small muted">The published conditions and levels are on <a href="alarm.html#rules">Fire alarm</a>. Criteria never change while a level change is being considered.</p>
    {criteria_log(A)}
  </section>
  <section id="corrections" aria-labelledby="corr-h"><h2 id="corr-h">Corrections</h2>
    <p class="small muted">Each correction names what we said, what is right, the page that carried it and the source. The affected report gets a dated note, and the next daily email carries the correction.</p>
    {corrections_list(cs)}
  </section>"""


PAGE = dict(title=TITLE, description=DESCRIPTION, body=render, scripts_code="", head_extra="")
