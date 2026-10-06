"""Shared server-side pieces for redesign v2 (definitions v2.0), spec section 6.9.

One implementation, used by:
  - build_pages.py: the homepage (pages/home.py), agi.html, hidden.html and start-here.html#pieces / #names;
  - build_report.py: the short daily report, which calls the card functions with snapshot(run) only, so the
    report is a pure function of the run and the previous published run (B1);
  - build_weekly.py: new wrap-ups (answer_line and strip, on the wrap-up's frozen copy of the parts).

Pages built every day (homepage, agi.html, hidden.html) pass the live files: data/agi_components.json as the
`view` of card_agi, and {"alarm": alarm.json, "escape": escape.json} as the `view` of card_alarm.

Everything here is deterministic (no clock, no randomness) and escapes every data string. Links from data go
through sitekit.safe_url. When data/agi_components.json is missing or malformed, load_components() prints a WARN
and returns {}, and every function that needs the parts renders a muted "AGI parts are unavailable right now"
block instead (m3), so alarm.html and the rest of the site still build.
"""
import hashlib
import json
import re
import sys
from html import escape, unescape
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from sitekit import (HYP_LABELS, METHOD_CHANGE, method_boundary, pending_defs, run_defs,  # noqa: E402
                     safe_url)

ROOT = _SCRIPTS.parent
IDS = ["breadth", "quality", "reliability", "reasoning", "horizon", "autonomy", "learning", "generalization"]
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
NUM_WORDS = {0: "no", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
             9: "nine", 10: "ten"}

# The status scale as published in data/agi_components.json; used when a view carries none (a run's snapshot).
STATUS_SCALE = [
    {"key": "far", "word": "Far", "pips": 1},
    {"key": "partial", "word": "Partial", "pips": 2},
    {"key": "close", "word": "Close", "pips": 3},
    {"key": "met", "word": "Met", "pips": 4},
]
RATINGS = ["verified fact", "credible report", "expert opinion", "forecast aggregate", "our inference", "speculation"]
RATING_CLS = {"verified fact": "fact", "credible report": "report", "expert opinion": "opinion",
              "forecast aggregate": "agg", "our inference": "ours", "speculation": "spec"}
PART_STATE = {"pass": ("✓", "Passed"), "aggregate": ("≈", "Overall figure only"), "no": ("–", "Not yet"),
              "unmeasured": ("?", "Not measured")}
IX_NAMES = {"A": ("Hidden AGI", "A"), "B": ("Hidden self-improvement only", "B only"),
            "CD": ("Covert actor or government only", "C/D only")}
LEVEL_DEFAULTS = {0: ("○", "good", "Normal"), 1: ("◐", "warn", "Watch"), 2: ("◉", "crit", "Warning"),
                  3: ("●", "crit", "Alarm")}
GROUP_NAMES = {"W": "Watch", "X": "Warning", "Y": "Alarm"}
GAUGE_SENTENCE = ("Context for our odds. The capability gap is the one gauge in a formula (A's), and it sets no alarm "
                  "condition by itself (W1 and X1 need a measured gap). AI-led R&D and the disclosure lag sit next to "
                  "conditions W5/X3 and W4; money and delegation feed none.")
UNAVAILABLE = "AGI parts are unavailable right now."
CHIP_PROPOSED = ("v1.0 bar; definitions v2.0 proposed",
                 "These numbers use the v1.0 bar. Definitions v2.0 are proposed; when they take effect, the next "
                 "reading re-derives the numbers and labels the change a method change, not news.")
CHIP_ADOPTED = ("v1.0 bar until the next reading",
                "Set under the v1.0 bar; the next reading re-derives it under definitions v2.0 and labels the change "
                "a method change, not news.")


# ---------------------------------------------------------------------------------------------------- basics

def warn(msg):
    print(f"WARN pages.common: {msg}", file=sys.stderr)


def e(s):
    return escape("" if s is None else str(s), quote=True)


def day(s, year=True):
    """'2026-10-05' -> 'Oct 5, 2026' (or 'Oct 5'); anything else comes back as given."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    if not m:
        return str(s or "")
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not 1 <= mo <= 12:
        return str(s)
    return f"{MONTHS[mo - 1]} {d}, {y}" if year else f"{MONTHS[mo - 1]} {d}"


def as_of(s):
    """A measurement's free-text "as of": every ISO date in it becomes 'May 8, 2026' and the rest stays
    ('2026-09-17 (last leaderboard update; read Oct 5)' -> 'Sep 17, 2026 (last leaderboard update; read Oct 5)')."""
    return re.sub(r"\b\d{4}-\d{2}-\d{2}\b", lambda m: day(m.group(0)), str(s or ""))


def as_of_html(s):
    """as_of(s) escaped for a table cell, its leading date in a span that keeps it on one line ("–" when empty)."""
    t = as_of(s)
    m = re.match(r"\d{4}-\d{2}-\d{2}\b", str(s or ""))
    if not m:
        return e(t or "–")
    d = day(m.group(0))
    return f'<span class="am-day">{e(d)}</span>{e(t[len(d):])}'


def month_year(s):
    """'2028-07-24' -> 'Jul 2028'."""
    m = re.match(r"(\d{4})-(\d{2})", str(s or ""))
    return f"{MONTHS[int(m.group(2)) - 1]} {m.group(1)}" if m and 1 <= int(m.group(2)) <= 12 else ""


WORD = re.compile(r"[A-Za-z0-9][\w'’.,%-]*")


def words(s):
    return len(WORD.findall(str(s or "")))


def clip_words(s, n):
    """The first n words of s at a word boundary, with an ellipsis when cut."""
    toks = str(s or "").split()
    if len(toks) <= n:
        return " ".join(toks)
    return " ".join(toks[:n]).rstrip(",;:—–-") + "…"


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt(v):
    """A probability or Index figure as published: 0.25, 0.5, 1.5, 2, 45."""
    v = num(v)
    if v is None:
        return "–"
    if v == 0:
        return "0"
    if abs(v) < 1:
        return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v * 10 - round(v * 10)) > 1e-9 else f"{v:.1f}"
    if abs(v) < 10:
        return f"{v:.1f}".rstrip("0").rstrip(".")
    return f"{v:.0f}" if abs(v - round(v)) < 1e-9 else f"{v:.1f}".rstrip("0").rstrip(".")


def fmtp(v):
    """An Index part, rounded to 0.05 and shown with the decimals it needs (1.0, 1.4, 0.55, 0.05)."""
    v = round((num(v) or 0.0) * 20) / 20
    return f"{v:.2f}" if abs(v * 10 - round(v * 10)) > 1e-9 else f"{v:.1f}"


def href(u, root=""):
    """A safe link target from data, with relative site paths resolved against `root` ('' or '../')."""
    h = safe_url(u)
    if not h:
        return None
    if re.match(r"^[a-z][a-z0-9+.-]*:", h, re.I) or h.startswith("#") or h.startswith("/"):
        return h
    return root + h


def link(u, text="source", root="", cls=""):
    """<a> for a data link ('' when the URL isn't http(s) or a site path). New tab only for absolute URLs."""
    h = href(u, root)
    if not h:
        return ""
    ext = ' target="_blank" rel="noopener"' if re.match(r"^https?:", h, re.I) else ""
    c = f' class="{e(cls)}"' if cls else ""
    return f'<a href="{e(h)}"{c}{ext}>{e(text)}</a>'


def split_rating(r):
    """'verified fact (lab's own evaluation)' -> ('verified fact', "lab's own evaluation")."""
    r = str(r or "").strip()
    low = r.lower()
    for base in RATINGS:
        if low.startswith(base):
            rest = re.sub(r"^\((.*)\)$", r"\1", r[len(base):].strip(" .;:,")).strip()
            return base, (rest or None)
    return (low or None), None


def tag(r, note=None, qual=None):
    """A rating chip; a qualified rating shows its short qualifier after the chip and its full note as the title.
    A qualifier written into the rating itself ("verified fact (part our inference)") shows the same way."""
    base, rest = split_rating(r)
    if not base:
        return ""
    qual = qual or rest
    t = f' title="{e(note)}"' if note else ""
    cls = RATING_CLS.get(base, "")
    q = f' <span class="tag-q">({e(qual)})</span>' if qual else ""
    return f'<span class="tag{" " + cls if cls else ""}"{t}>{e(base)}</span>{q}'


def rtag(x):
    x = x if isinstance(x, dict) else {}
    return tag(x.get("rating"), x.get("ratingNote"), x.get("ratingQual"))


def as_list(v):
    return v if isinstance(v, list) else []


def as_dict(v):
    return v if isinstance(v, dict) else {}


def load_json(rel, root=None):
    """data file under `root` (a directory; default the repo), or None when missing or not JSON."""
    p = Path(root or ROOT) / rel
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------------------------------- the parts

def _components_problem(d):
    if not isinstance(d, dict):
        return "not a JSON object"
    comps = d.get("components")
    if not isinstance(comps, list) or not comps:
        return "no components list"
    for i, c in enumerate(comps):
        if not isinstance(c, dict) or not c.get("id") or not c.get("status"):
            return f"components[{i}] has no id or status"
    if not isinstance(d.get("statusScale"), list):
        return "no statusScale"
    return None


def load_components(root=None):
    """data/agi_components.json under `root` (a directory; default the repo). {} with a WARN when the file is
    missing or malformed, so every page still builds (the parts render as 'unavailable')."""
    p = Path(root or ROOT) / "data/agi_components.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        warn("data/agi_components.json is missing; AGI parts render as unavailable")
        return {}
    except (OSError, ValueError, UnicodeDecodeError) as x:
        warn(f"data/agi_components.json can't be read ({x}); AGI parts render as unavailable")
        return {}
    problem = _components_problem(d)
    if problem:
        warn(f"data/agi_components.json is malformed ({problem}); AGI parts render as unavailable")
        return {}
    return d


def ok_view(view):
    """True when `view` (the components file or a run's snapshot) has parts to show."""
    return isinstance(view, dict) and _components_problem(dict(view, statusScale=view.get("statusScale") or [])) is None


def scale(view=None):
    sc = as_list(as_dict(view).get("statusScale")) or STATUS_SCALE
    return {s.get("key"): s for s in sc if isinstance(s, dict)}


def status_counts(data):
    """{"met", "close", "partial", "far"} counts over the parts."""
    c = {"met": 0, "close": 0, "partial": 0, "far": 0}
    for x in as_list(as_dict(data).get("components")):
        if isinstance(x, dict) and x.get("status") in c:
            c[x["status"]] += 1
    return c


def answer_line(view):
    """Card 1's answer, judged on public evidence (4.2): 'Not in public: …', 'Possibly, in public: …' or
    'Yes, in public: …'. Works on the components file, a run's snapshot or a wrap-up's frozen copy."""
    if not ok_view(view):
        return f'<span class="muted">{e(UNAVAILABLE)}</span>'
    c, n, sc = status_counts(view), len(view["components"]), scale(view)
    if isinstance(view.get("publicAgi"), dict) and view["publicAgi"].get("system"):
        return f'<strong>Yes, in public:</strong> {e(view["publicAgi"]["system"])} meets all {n} parts.'
    if c["met"] == n:
        return f'<strong>Possibly, in public:</strong> all {n} parts are met, but not yet by one system.'
    rest = ", ".join(f"{c[k]} {str((sc.get(k) or {}).get('word') or k).lower()}" for k in ("close", "partial", "far")
                     if c[k])
    return f'<strong>Not in public:</strong> {c["met"]} of {n} parts met' + (f" ({e(rest)})." if rest else ".")


def answer_text(view):
    return unescape(re.sub(r"<[^>]+>", "", answer_line(view)))


def _ratio(x):
    h = as_dict(x.get("headline"))
    v, t, lo = num(h.get("value")), num(h.get("target")), num(h.get("min")) or 0.0
    if v is None or t is None or t == lo:
        return None
    return (v - lo) / (t - lo)


def weakest(data, n=3):
    """The Far parts furthest behind their bars, lowest (value-min)/(target-min) first."""
    far = [x for x in as_list(as_dict(data).get("components"))
           if isinstance(x, dict) and x.get("status") == "far" and _ratio(x) is not None]
    far.sort(key=_ratio)
    return far[:n]


def furthest(data):
    """Among the Far parts, the one lowest against its bar on its headline's own scale; None if none."""
    w = weakest(data, 1)
    return w[0] if w else None


def furthest_snapshot(data):
    """The run's `furthest` snapshot (8.2): {id, short, display, targetDisplay}, or None."""
    f = furthest(data)
    if not f:
        return None
    h = as_dict(f.get("headline"))
    return {"id": f["id"], "short": f.get("short"), "display": h.get("display"), "targetDisplay": h.get("targetDisplay")}


def components_snapshot(data):
    """The run's `components` snapshot (8.2): {id: {status, short, glance, basisShort}} for every part."""
    out = {}
    for c in as_list(as_dict(data).get("components")):
        if isinstance(c, dict) and c.get("id"):
            out[c["id"]] = {k: c.get(k) for k in ("status", "short", "glance", "basisShort")}
    return out


def pips(status, data=None, word_cls="am-word"):
    """Ink pips plus the word, always; the screen-reader text reads ', status Far, step 1 of 4'."""
    s = scale(data).get(status) or {"word": str(status or "?").title(), "pips": 0}
    n = int(s.get("pips") or 0)
    spans = "".join(f'<span class="pip{" on" if i < n else ""}"></span>' for i in range(4))
    return (f'<span class="am-status"><span class="am-pips" aria-hidden="true">{spans}</span>'
            f'<span class="{e(word_cls)}" aria-hidden="true">{e(s.get("word"))}</span>'
            f'<span class="sr-only">, status {e(s.get("word"))}, step {n} of 4</span></span>')


def parts_line(component):
    """'1 of 2 parts of the test met' (+ '(1 on the overall figure only, which doesn't count)')."""
    ps = [p for p in as_list(as_dict(component).get("parts")) if isinstance(p, dict)]
    n_pass = sum(1 for p in ps if p.get("state") == "pass")
    agg = sum(1 for p in ps if p.get("state") == "aggregate")
    return f"{n_pass} of {len(ps)} parts of the test met" + (
        f" ({agg} on the overall figure only, which doesn't count)" if agg else "")


def unavailable(cls=""):
    return f'<p class="muted small am-unavailable{" " + e(cls) if cls else ""}">{e(UNAVAILABLE)}</p>'


def strip(data, href=lambda c: "agi.html#" + c["id"]):  # noqa: A002 - the name the spec fixes
    """The eight parts as tiles (ul.ag-strip): short name, pips and the word on every width; the glance is
    screen-reader text; no title attribute."""
    if not ok_view(data):
        return unavailable()
    cells = []
    for c in data["components"]:
        u = href(c)
        cells.append(f'<li><a class="ag-cell" href="{e(u)}"><span class="ag-name">{e(c.get("short") or c.get("name") or c["id"])}'
                     f'</span>{pips(c.get("status"), data, "ag-word")}'
                     f'<span class="sr-only">. {e(c.get("glance"))}</span></a></li>')
    return f'<ul class="ag-strip">{"".join(cells)}</ul>'


def pending_chip(run, data):
    """The chip shown wherever runs.agi or A-D sit next to v2.0 wording, while the run's definitions differ from
    the ones agi.html states (sitekit.pending_defs; never the build clock)."""
    if not data or not pending_defs(run, data):
        return ""
    txt, title = CHIP_ADOPTED if data.get("adopted") else CHIP_PROPOSED
    return f' <a class="chip pend-chip" href="agi.html#v1" title="{e(title)}">{e(txt)}</a>'


# ---------------------------------------------------------------------------------------------------- runs

def published(runs):
    """Published readings in date order: entries with a report, not marked comparable false; when one report
    path appears twice, the later entry wins (the same rule as the site's charts)."""
    by = {}
    for i, r in enumerate(as_list(runs)):
        if isinstance(r, dict) and r.get("report") and r.get("comparable") is not False:
            by.pop(r["report"], None)
            by[r["report"]] = (str(r.get("date") or ""), i, r)
    return [r for _, _, r in sorted(by.values(), key=lambda t: (t[0], t[1]))]


def newest(runs):
    pub = published(runs)
    return pub[-1] if pub else None


def prev_published(runs, run):
    """The published reading `run` is compared with: the latest one dated before it with another report path."""
    best = None
    for r in published(runs):
        if r is run or r.get("report") == (run or {}).get("report"):
            continue
        if str(r.get("date") or "") < str((run or {}).get("date") or ""):
            best = r
    return best


def value(run, key, hz="now"):
    if key == "index":
        return num(as_dict(run).get("index")) if hz == "now" else None
    s = as_dict(run).get("agi") if key == "agi" else as_dict(as_dict(run).get("probs")).get(key)
    return num(as_dict(s).get(hz))


_INDEX_NAME = re.compile(r"\bHidden AGI Index\b|\bthe Index\b")   # never a bare "Index": RLI and AA's index aren't ours
_MOVE = re.compile(r"\d(?:\.\d+)?\s*%?\s*(?:to|→|->)\s*\d|[▲▼]\s*[+−-]?\s*\d|\b(?:up|down|rises?|falls?|rose|fell)\b"
                   r"[^.;]{0,30}?\d", re.I)
_METHOD_LINE = re.compile(r"^\s*method change\b", re.I)


def _news_line(run, key):
    """The first `changes` line (other than a 'Method change' line) that names `key` and states a move."""
    lines = [s for s in as_list(as_dict(run).get("changes")) if isinstance(s, str)]
    try:  # one rule with check_data (checks/method.py), when it is importable
        from checks.method import METHOD_LINE, MOVE, names
        if key == "index":
            return next((s for s in lines if not METHOD_LINE.match(s) and _INDEX_NAME.search(s) and MOVE.search(s)), None)
        return next((s for s in lines if not METHOD_LINE.match(s) and names(key, s) and MOVE.search(s)), None)
    except Exception:  # noqa: BLE001 - same rule, local copy (narrower names)
        pat = {"index": _INDEX_NAME, "agi": re.compile(r"\bAGI anywhere\b")}.get(key) or re.compile(
            rf"(?<![\w&.-]){re.escape('D-open' if key == 'Dopen' else key)}\b(?!-open)")
        return next((s for s in lines if not _METHOD_LINE.match(s) and pat.search(s) and _MOVE.search(s)), None)


def _move_text(delta):
    n = fmt(round(abs(delta), 6))
    return f'{"▲ +" if delta > 0 else "▼ −"}{n} {"pt" if n == "1" else "pts"}'


def _news_amount(line):
    m = re.search(r"(\d+(?:\.\d+)?)\s*%?\s*(?:to|→|->)\s*(\d+(?:\.\d+)?)", line or "")
    if m:
        d = float(m.group(2)) - float(m.group(1))
        if d:
            return _move_text(d)
    m = re.search(r"([▲▼])\s*([+−-]?)\s*(\d+(?:\.\d+)?)", line or "")
    if m:
        d = float(m.group(3)) * (1 if m.group(1) == "▲" else -1)
        return _move_text(d)
    return "moved on"


def delta_text(run, prev, key="index"):
    """'no change', '▲ +0.5 pts', 'first reading' or, on a method boundary, 'method change (definitions v2.0)'
    for agi, A, C, D, D-open and the Index (B keeps its real delta). When a news line also moved one of agi, A, C,
    D or D-open that day, both: '▲ +0.5 pts news; then method change (definitions v2.0)'. The Index always reads
    the method change on the boundary, as build_report.change_cell does: it is re-derived from its parts, whose own
    lines carry any news (M3; one rule on the homepage, hidden.html, the short report and the email)."""
    cur = value(run, key)
    if not prev:
        return "first reading"
    if key == "index" and method_boundary(run, prev):
        return METHOD_CHANGE
    if key != "B" and method_boundary(run, prev):
        line = _news_line(run, key)
        return f"{_news_amount(line)} news; then {METHOD_CHANGE}" if line else METHOD_CHANGE
    old = value(prev, key)
    if cur is None or old is None:
        return "no change"
    if fmt(cur) == fmt(old):
        return "no change"
    return _move_text(cur - old)


def is_boundary(run, prev):
    return bool(as_dict(run).get("methodChange")) or method_boundary(run, prev)


def method_banner(run, prev=None, root=""):
    """The one-line banner on the first reading under new definitions (4.2 b, 9.1 row 6)."""
    if not is_boundary(run, prev):
        return ""
    to = run_defs(run)
    return (f'<p class="callout rp-method"><strong>Method change today:</strong> this is our first reading under definitions v{e(to)}. '
            f'Our numbers were re-derived; this is not news. <a href="{root}changes.html#method">What changed →</a></p>')


def snapshot(run):
    """The run's own copies (8.2) as a view for the card functions: components (a list in part order), furthest,
    alarm, escape and dates. Reports and the v2 email render from this only (B1)."""
    run = as_dict(run)
    comps = as_dict(run.get("components"))
    order = [i for i in IDS if i in comps] + [i for i in comps if i not in IDS]
    lst = [dict(as_dict(comps[i]), id=i) for i in order]
    return {
        "source": "run",
        "definitionsVersion": "2.0",   # the snapshot was copied from the v2.0 parts file
        "adopted": None,
        "statusScale": STATUS_SCALE,
        "components": lst,
        "furthest": run.get("furthest"),
        "alarm": as_dict(run.get("alarm")),
        "escape": as_dict(run.get("escape")),
        "dates": as_list(run.get("dates")),
    }


# ---------------------------------------------------------------------------------------------------- Index bar

def b_only(run):
    for p in as_list(as_dict(run).get("indexParts")):
        if isinstance(p, dict) and p.get("key") == "B":
            return num(p.get("v"))
    return None


def _index_parts(run):
    parts = [p for p in as_list(as_dict(run).get("indexParts"))
             if isinstance(p, dict) and p.get("key") in IX_NAMES and num(p.get("v")) is not None]
    return parts or None


def index_block(run, scale_max=5.0, key=True, uid=None, w=600, h=16):
    """The Hidden AGI Index bar (4.2): a server-rendered SVG on a fixed 0-5% scale, never ''.
    With indexParts: A, B outside A (hypothesis colours), C or D outside A (neutral ink-grey), then a hatched
    ink 'rounding' segment up to the published Index when the parts sum below it. Without (a legacy run): one
    neutral segment for the total, keyed 'breakdown from the next reading'. Every text form adds up to what it
    shows."""
    idx = num(as_dict(run).get("index")) or 0.0
    parts = _index_parts(run)
    if uid is None:
        uid = "ixh" + hashlib.sha1(json.dumps([idx, parts, scale_max], sort_keys=True).encode()).hexdigest()[:8]
    X = lambda v: max(0.0, min(w, v / scale_max * w))  # noqa: E731
    out = [f'<rect class="ix-rest" x="0" y="0" width="{w}" height="{h}" rx="3"></rect>']
    rnd, tot = 0.0, 0.0
    if parts:
        tot = round(sum(round(num(p["v"]) * 20) / 20 for p in parts), 2)
        x = 0.0
        for p in parts:
            v = num(p["v"])
            pw = max(2.0, X(v))
            out.append(f'<rect class="ix-seg-{p["key"]}" x="{x:.1f}" y="0" width="{pw:.1f}" height="{h}">'
                       f'<title>{e(IX_NAMES[p["key"]][0])}: {fmtp(v)} points</title></rect>')
            x += pw
        rnd = round(idx - tot, 2)
        if rnd > 0.001:
            out.append(f'<rect x="{x:.1f}" y="0" width="{X(rnd):.1f}" height="{h}" fill="url(#{uid})" class="ix-round">'
                       f'<title>Rounding: {fmtp(rnd)} points (parts sum to {fmt(tot)}; the Index is rounded to our grid)'
                       f'</title></rect>')
        lab = "; ".join(f"{IX_NAMES[p['key']][0]} {fmtp(p['v'])} points" for p in parts)
        if rnd > 0.001:
            lab += f"; parts sum to {fmt(tot)}, shown as {fmt(idx)} on our rounding grid"
    else:
        out.append(f'<rect class="ix-legacy" x="0" y="0" width="{X(idx):.1f}" height="{h}">'
                   f'<title>Hidden AGI Index {fmt(idx)}%; breakdown from the next reading</title></rect>')
        lab = "total; breakdown from the next reading"
    out.append(f'<rect class="ix-end" x="{w - 3}" y="-2" width="3" height="{h + 4}"></rect>')
    svg = (f'<svg class="ix-bar" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
           f'aria-label="Hidden AGI Index {fmt(idx)}%: {e(lab)}. Scale 0 to {fmt(scale_max)}%.">'
           f'<defs><pattern id="{uid}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
           f'<rect width="6" height="6" class="ix-hatch-bg"></rect><line x1="0" y1="0" x2="0" y2="6" class="ix-hatch">'
           f'</line></pattern></defs>' + "".join(out) + "</svg>")
    sc = f'<div class="ix-scale" aria-hidden="true"><span>0</span><span>{fmt(scale_max)}%</span></div>'
    if not key:
        return f'<div class="ix-wrap">{svg}{sc}</div>'
    if parts:
        ks = "".join(f'<span><span class="swatch ix-sw-{p["key"]}"></span> <span class="l">{e(IX_NAMES[p["key"]][0])}</span>'
                     f'<span class="s">{e(IX_NAMES[p["key"]][1])}</span> {fmtp(p["v"])}</span>' for p in parts)
        if rnd > 0.001:
            ks += (f'<span><span class="swatch ix-sw-round"></span> rounding {fmtp(rnd)}</span>'
                   f'<span class="muted">parts sum to {fmt(tot)}; shown as {fmt(idx)} on our rounding grid</span>')
    else:
        ks = ('<span><span class="swatch ix-sw-legacy"></span> Hidden AGI Index, total</span>'
              '<span class="muted">breakdown from the next reading</span>')
    return f'<div class="ix-wrap">{svg}{sc}</div><div class="ix-key small">{ks}</div>'


def index_parts_text(run, sep=" + ", names=None):
    """'A 1.0 + B-only 1.4 + C/D-only 0.1' (or None for a run without indexParts)."""
    parts = _index_parts(run)
    if not parts:
        return None
    names = names or {"A": "A", "B": "B-only", "CD": "C/D-only"}
    return sep.join(f"{names[p['key']]} {fmtp(p['v'])}" for p in parts)


# ---------------------------------------------------------------------------------------------------- the cards

def _ids(ids, card, q):
    ids = dict(ids or {})
    ids.setdefault("card", card)
    ids.setdefault("q", ids["card"] + "-q")
    return ids


def card_agi(view, run, prev, root="", ids=None, report=False):
    """Card 1 · Is AGI here? `view` is the components file (homepage) or snapshot(run) (report, email).
    The report variant leaves out the horizons, the definition and the furthest/partial lines, and adds the
    pending-check line when the run has componentLeads."""
    ids = _ids(ids, "agi-now", "q1")
    run = as_dict(run)
    agi = as_dict(run.get("agi"))
    ok = ok_view(view)
    later = ""
    if not report:
        later = (f' · {fmt(agi.get("y2030"))}% by end-2030'
                 f'<span class="hq-hide-m"> · {fmt(agi.get("y2035"))}% by end-2035</span>')
    chip = pending_chip(run, view) if ok else ""
    mc = f' <span class="small muted">· {e(METHOD_CHANGE)}</span>' if is_boundary(run, prev) else ""
    agi_link = f"{root}agi.html"
    extra = ""
    if ok and not report:
        d = as_dict(view.get("definition"))
        if d.get("text"):
            dtext = re.sub(r"^\s*AGI\s*:\s*", "", str(d["text"]))
            dtext = dtext[:1].upper() + dtext[1:]
            extra += f'<p class="hq-def hq-hide-m"><span class="muted">What we mean by AGI:</span> {e(dtext)}</p>'
        partial = [x for x in view["components"] if x.get("status") == "partial"]
        if partial:
            extra += ('<p class="hq-line small hq-hide-m">Partial so far: '
                      + "; ".join(f'<a href="{agi_link}#{e(x["id"])}">{e(str(x.get("short") or x["id"]).lower())}</a>'
                                  + (f' ({e(x["basisShort"])})' if x.get("basisShort") else "") for x in partial) + ".</p>")
        f = furthest(view)
        if f:
            hd = as_dict(f.get("headline"))
            extra += (f'<p class="hq-line small hq-hide-m">Furthest behind: <a href="{agi_link}#{e(f["id"])}">'
                      f'{e(str(f.get("short") or f["id"]).lower())}</a>, {e(hd.get("display"))} of '
                      f'{e(hd.get("targetDisplay"))}.</p>')
    if ok and report:
        leads = [x for x in as_list(run.get("componentLeads")) if isinstance(x, dict)]
        if leads:
            names = {c["id"]: c.get("short") or c["id"] for c in view["components"]}
            parts = []
            for x in leads:
                n = str(names.get(x.get("id"), x.get("id") or "")).lower()
                if n and n not in parts:
                    parts.append(n)
            k = len(leads)
            extra += (f'<p class="hq-line small">{k} new result{"s" if k != 1 else ""} pending our weekly check: '
                      f'{e(", ".join(parts))}.</p>')
    body = strip(view, href=lambda c: f"{agi_link}#{c['id']}") if ok else unavailable()
    return f"""<section class="hq" id="{e(ids['card'])}" aria-labelledby="{e(ids['q'])}">
    <h2 class="hq-q" id="{e(ids['q'])}">1 · Is AGI here?</h2>
    <p class="hq-a">{answer_line(view)}</p>
    <p class="hq-line hq-any">AGI anywhere, public or hidden: <strong>{fmt(agi.get('now'))}%</strong> today{later}{chip}{mc}</p>
    {body}
    {extra}
    <p class="hq-more"><a href="{agi_link}#definition">What we mean by AGI →</a><a href="{agi_link}#tracker">All eight parts →</a></p>
  </section>"""


def card_hidden(run, prev, root="", ids=None):
    """Card 2 · Could it be hidden? The Index, its delta, the decomposition bar and the bridge sentence."""
    ids = _ids(ids, "gauges", "q2")
    run = as_dict(run)
    idx, agi_now = num(run.get("index")), value(run, "agi")
    bridge = ""
    if idx is not None and agi_now is not None and idx > agi_now:
        b = b_only(run)
        bridge = (f'<p class="hq-line small">Above AGI anywhere because {fmtp(b)} points are hidden self-improvement (B), '
                  f'which needs no AGI.</p>' if b is not None else
                  '<p class="hq-line small">Above AGI anywhere because part of it is hidden self-improvement (B), '
                  'which needs no AGI.</p>')
    return f"""<section class="hq" id="{e(ids['card'])}" aria-labelledby="{e(ids['q'])}">
    <h2 class="hq-q" id="{e(ids['q'])}">2 · Could it be hidden?</h2>
    <p class="hq-a"><span class="big">{fmt(idx)}%</span> Hidden AGI Index, {e(delta_text(run, prev, 'index'))}</p>
    {index_block(run)}
    {bridge}
    <p class="hq-more"><a href="{root}start-here.html#pieces">How our numbers fit →</a><a href="{root}hidden.html#odds">Our odds to 2035 →</a></p>
  </section>"""


def alarm_state(view, run=None):
    """{level, name, icon, status, since, met} from alarm.json (a view with "alarm": {current, levels}) or from a
    run's alarm snapshot (a view from snapshot(run), or the run itself)."""
    v = as_dict(view)
    a = as_dict(v.get("alarm"))
    if isinstance(a.get("current"), dict):   # live alarm.json
        cur = a["current"]
        lvl = cur.get("level")
        lv = next((x for x in as_list(a.get("levels")) if isinstance(x, dict) and x.get("level") == lvl), {})
        d = LEVEL_DEFAULTS.get(lvl, ("", "", ""))
        return {"level": lvl, "name": lv.get("name") or d[2], "icon": lv.get("icon") or d[0],
                "status": lv.get("status") or d[1], "since": cur.get("since"), "met": as_list(cur.get("met"))}
    a = a or as_dict(as_dict(run).get("alarm"))
    lvl = a.get("level")
    d = LEVEL_DEFAULTS.get(lvl, ("", "", ""))
    return {"level": lvl, "name": a.get("name") or d[2], "icon": a.get("icon") or d[0],
            "status": a.get("status") or d[1], "since": a.get("since"), "met": as_list(a.get("met"))}


def escape_counts(view, run=None):
    """{confirmed, open, quiet, total} for Escape watch: from escape.json's indicators (live) or the run's counts."""
    esc = as_dict(as_dict(view).get("escape"))
    inds = [i for i in as_list(esc.get("indicators")) if isinstance(i, dict)]
    if inds:
        c = {s: sum(1 for i in inds if i.get("status") == s) for s in ("tripped", "watching", "quiet")}
    else:
        esc = esc or as_dict(as_dict(run).get("escape"))
        c = {s: int(num(esc.get(s)) or 0) for s in ("tripped", "watching", "quiet")}
    return {"confirmed": c["tripped"], "open": c["watching"], "quiet": c["quiet"], "total": sum(c.values())}


def signal_counts(run):
    tw = [t for t in as_list(as_dict(run).get("tripwires")) if isinstance(t, dict)]
    return {s: sum(1 for t in tw if t.get("status") == s) for s in ("tripped", "watching", "quiet")}


def met_text(met):
    met = [str(m) for m in met]
    if not met:
        return "none met"
    if len(met) == 1:
        return f"{met[0]} met"
    return ", ".join(met) + " met"


def alarm_line(al):
    return (f'<span class="hq-alarm"><span class="ico ico-{e(al["status"])}" aria-hidden="true">{e(al["icon"])}</span>'
            f'Fire alarm: Level {e(al["level"])} · {e(al["name"])}</span>')


def card_alarm(view, run, root="", ids=None, report=False):
    """Card 3 · Should I worry today? (dashed: set by published rules, never by the odds above).
    view = {"alarm": alarm.json, "escape": escape.json} on the homepage, or snapshot(run) on a report.
    ids: homepage {"card": "alarm", "signals": "tripwires", "escape": "escape"}; report {"card": "alarm"}.
    The report keeps only the alarm line and its links (its needle and signals are sections of their own)."""
    ids = _ids(ids, "alarm", "q3")
    run = as_dict(run)
    al = alarm_state(view, run)
    since = f'since {e(day(al["since"], False))} · ' if al.get("since") else ""
    body = ""
    if report:
        links = (f'<a href="{root}alarm.html#rules">Fire alarm rules →</a>'
                 f'<a href="{root}escape.html">Escape watch →</a>')
    else:
        nd = as_dict(run.get("needle"))
        if nd.get("subject") or nd.get("headline"):
            src = link(nd.get("url"), nd.get("source") or "source", root)
            hl = str(nd.get("headline") or "")
            if run.get("methodChange") and re.search(r"nothing moved", hl, re.I):
                hl = re.sub(r"nothing moved", "no news moved our numbers; the method change re-derived them", hl,
                            flags=re.I)
            head = f'<strong>{e(hl)}</strong> ' if hl else ""
            subj = str(nd.get("subject") or "").rstrip(".")
            body += (f'<p class="hq-line"><span class="hq-show-m">{e(day(run.get("date"), False))} · </span>{head}'
                     f'{e(subj)}{"." if subj else ""} {tag(nd.get("rating"))}{" " if nd.get("rating") and src else ""}{src}</p>')
        sig, es = signal_counts(run), escape_counts(view, run)
        sid = f' id="{e(ids["signals"])}"' if ids.get("signals") else ""
        eid = f' id="{e(ids["escape"])}"' if ids.get("escape") else ""
        body += (f'<p class="hq-line small"{sid}>Signals: {sig["tripped"]} confirmed (count toward Watch) · '
                 f'{sig["watching"]} open · {sig["quiet"]} quiet · <span{eid}>Escape watch: {es["confirmed"]} of '
                 f'{es["total"]} confirmed</span> · <a href="{root}alarm.html#signals">All signals →</a></p>')
        links = ""
        if run.get("report"):
            label = "Today\'s report (2 min) →" if run.get("format") == 2 else "Today\'s report →"
            links += f'<a href="{e(href(run["report"], root) or "")}">{label}</a>'
        if run.get("analysis"):
            links += f'<a href="{e(href(run["analysis"], root) or "")}">Full analysis →</a>'
    return f"""<section class="hq hq-sep" id="{e(ids['card'])}" aria-labelledby="{e(ids['q'])}">
    <h2 class="hq-q" id="{e(ids['q'])}">3 · Should I worry today? <span class="hq-seplabel"><span class="l">Separate: set by published rules, never by the odds above</span><span class="s">Rules, not odds</span></span></h2>
    <p class="hq-a">{alarm_line(al)}
      <span class="small muted">{since}{e(met_text(al['met']))}</span></p>
    {body}
    <p class="hq-more">{links}</p>
  </section>"""


# ---------------------------------------------------------------------------------------------------- numbers diagram

def _crossing(trends, mark="workMonth"):
    cr = as_dict(as_dict(as_dict(as_dict(trends).get("metr")).get("p80")).get("crossings"))
    return as_dict(cr.get(mark))


def work_month_text(trends):
    """'around Jul 2028' from data/trends.json (never copied), or '' when the fit has no date."""
    my = month_year(_crossing(trends).get("mid"))
    return f"around {my}" if my else ""


def _gauge_display(run, key):
    g = as_dict(as_dict(as_dict(run).get("gauges")).get(key))
    d = str(g.get("display") or "")
    return re.sub(r"\bLevel (\d) of (\d)\b", r"rung \1 of \2", d)


def _short_display(run, key):
    """'~106 days' from '~106 days (103–120)'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", _gauge_display(run, key))


def _groups_text(met):
    gs = sorted({GROUP_NAMES.get(str(m)[:1]) for m in met if str(m)[:1] in GROUP_NAMES})
    if len(gs) == 1:
        return f" (all {gs[0]} conditions)" if len(met) > 1 else f" (a {gs[0]} condition)"
    return ""


def _kalshi(external):
    rows = [x for x in as_list(as_dict(external).get("forecasts"))
            if isinstance(x, dict) and str(x.get("who", "")).lower().startswith("kalshi") and x.get("bar") == "announcement"]
    rows.sort(key=lambda x: str(x.get("date") or ""))
    return rows[-1] if rows else None


def _metaculus_weak(data):
    for f in as_list(as_dict(data).get("frameworks")):
        if isinstance(f, dict) and "3479" in str(f.get("name", "")) + str(f.get("url", "")):
            return f
    return None


def outside_rail(data, external, trends):
    """The muted outside view under the diagram (7.2): markets and forecasters, and the trend date."""
    bits = []
    k = _kalshi(external)
    if k and k.get("p") not in (None, ""):
        what = str(k.get("what") or "").strip()
        what = what[:1].lower() + what[1:]
        bits.append(f"Kalshi: {e(k['p'])}% that {e(what)}, {e(day(k.get('asOf'), False))}")
    m = _metaculus_weak(data)
    if m and m.get("best"):
        best = str(m["best"]).rstrip(".")
        bits.append(f"Metaculus &ldquo;weakly general AI&rdquo;: {e(best[:1].lower() + best[1:])}")
    lead = ("Outside view, for comparison only: prediction markets and forecasters mostly settle on a lab <em>announcing</em> "
            "AGI, a looser test than ours")
    s = lead + (f" ({'; '.join(bits)})." if bits else ".")
    wm = work_month_text(trends)
    if wm:
        s += (f" Trend dates are measurements extended, not forecasts: METR's 80% horizon reaches a work-month {wm} "
              "if the trend holds.")
    return s


def fit_diagram(data, run, alarm, escape, *, root="", trends=None, external=None):
    """'How our numbers fit together' (7.1-7.2): the explainer and three lanes (capability, secrecy, rules), each
    box with today's value and 'Reaches the top when…', plus the outside rail. Server-rendered, no JS.
    data = agi_components.json, run = the newest published run, alarm = alarm.json, escape = escape.json;
    trends (data/trends.json) and external (data/external_forecasts.json) add the dates and the outside view."""
    run = as_dict(run)
    agi, pr = as_dict(run.get("agi")), as_dict(run.get("probs"))
    ok = ok_view(data)
    chip = pending_chip(run, data) if ok else ""
    al = alarm_state({"alarm": alarm}, run)
    sig, es = signal_counts(run), escape_counts({"escape": escape}, run)
    wm = work_month_text(trends)

    def box(title, val=None, lines=(), top=None, em=False):
        v = f'<span class="v">{val}</span>' if val else ""
        ls = "".join(f"<span>{x}</span>" for x in lines if x)
        t = f'<span class="top">Reaches the top when {top}.</span>' if top else ""
        return f'<li class="fit-box{" em" if em else ""}"><b>{title}</b>{v}{ls}{t}</li>'

    def hy(k, var):
        v = as_dict(pr.get(k)).get("now")
        return (f'<span class="fit-hy"><i style="background:var({var})"></i><span><strong>{k} {fmt(v)}%</strong> '
                f'{e(HYP_LABELS[k])}</span></span>')

    gap = _gauge_display(run, "gap")
    ev = ["METR time horizons, Remote Labor Index, ARC-AGI, OSWorld, CL-Bench, Epoch's open problems"]
    if gap:
        ev.append(f"capability gap (our gauge, {e(gap)}): how far unreleased models may lead")
    if ok:
        c = status_counts(data)
        parts_box = box("AGI parts", f"{c['met']} of {len(data['components'])} met",
                        [f"{c['partial']} partial, {c['far']} far (definitions v{e(data.get('definitionsVersion') or '2.0')})"]
                        + ([f"{c['close']} close"] if c["close"] else []), "one system meets all eight")
        weak = ", ".join(str(x.get("short") or x["id"]).lower() for x in weakest(data))
    else:
        parts_box = box("AGI parts", None, [e(UNAVAILABLE)])
        weak = ""
    lane1 = (box("Evidence", None, ev) + parts_box
             + box("AGI anywhere, public or hidden", f"{fmt(agi.get('now'))}% today",
                   [f"{fmt(agi.get('y2030'))}% by end-2030 · {fmt(agi.get('y2035'))}% by end-2035{chip}"],
                   "a system meets all eight, public or hidden", True))
    sec = num(run.get("secrecyNow"))
    sec_line = (f"Our judgment of the kept-quiet factor: about {fmt(round(sec, 2))} today." if sec is not None
                else "Our judgment of the kept-quiet factor, from today's derivation of A.")
    parts = _index_parts(run)
    if parts:
        tot = round(sum(round(num(p["v"]) * 20) / 20 for p in parts), 2)
        ixline = " + ".join(f'{ {"A": "A", "B": "B outside A", "CD": "C or D outside A"}[p["key"]]} {fmtp(p["v"])}'
                            for p in parts)
        if abs(tot - (num(run.get("index")) or 0)) > 0.001:
            ixline += f" = {fmt(tot)}, shown as {fmt(run.get('index'))}"
    else:
        ixline = "breakdown from the next reading"
    dopen = as_dict(pr.get("Dopen")).get("now")
    lane2 = (box("AGI anywhere (from 1) × kept quiet 30+ days → A, C, D", None, [sec_line])
             + '<li class="fit-box"><b>Hidden scenarios, today</b>'
             + hy("A", "--sA") + hy("C", "--sC") + hy("D", "--sD")
             + '<span class="fit-bin">B enters on its own: it needs no AGI</span>' + hy("B", "--sB")
             + f'<span class="top">D-open ({fmt(dopen)}%) is open by definition, so it stays out of the Index.</span></li>'
             + box("Hidden AGI Index", f"{fmt(run.get('index'))}% today", [e(ixline)], "one hidden scenario is proven true",
                   True))
    met = al["met"]
    lane3 = (box("Signals", None, [f"Tripwires: {sig['tripped']} confirmed, {sig['watching']} open, {sig['quiet']} quiet",
                                   f"Escape watch: {es['confirmed']} of {es['total']} confirmed"])
             + box("Alarm conditions", f"{len(met)} met", [e(", ".join(map(str, met))) + _groups_text(met) if met else "",
                                                          "Watch: any two W · Warning: any one X · Alarm: any one Y, proven"])
             + box("Fire alarm", f'<span class="ico-{e(al["status"])}">{e(al["icon"])}</span> Level {e(al["level"])} · '
                                 f'{e(al["name"])}', [f"Since {e(day(al['since']))}" if al.get("since") else ""],
                   "a Y condition is proven beyond reasonable doubt (Level 3)", True))

    def lane(q, tagline, items, cls="", note=""):
        return (f'<div class="fit-lane {cls}"><p class="fit-q">{q} <span>{tagline}</span></p>'
                f'<ol class="fit-flow">{items}</ol>' + (f'<p class="fit-note">{note}</p>' if note else "") + "</div>")

    note1 = "AGI anywhere can be no higher than the chance that its weakest part is met."
    if weak:
        note1 += f" Today the furthest behind are {e(weak)}."
    if wm and not chip:
        note1 += (f" Why only {fmt(agi.get('y2030'))}% by end-2030 when the time-horizon trend reaches a work-month {wm}: "
                  "that trend covers one test of one part, METR's suite can't yet measure that length, and generalization "
                  "and learning have no trend.")
    note2 = ("Why the Index can exceed AGI anywhere: B, hidden self-improvement, doesn't need AGI. The hiding-conditions "
             "gauges are " + GAUGE_SENTENCE[0].lower() + GAUGE_SENTENCE[1:])
    return f"""<p class="prose"><strong>Three questions, three kinds of number.</strong> <em>Is AGI here?</em> is a capability question: for each of eight parts we compare the best public result to its bar, and from that we judge the chance that AGI exists anywhere. <em>Could it be hidden?</em> is a secrecy question: A, C and D each mean "AGI exists <em>and</em> was kept quiet" (or acted, or shaped a government decision), so they can never exceed AGI anywhere; B, hidden self-improvement, needs no AGI, which is why the Index can sit above it. <em>Should I worry today?</em> is a rules question: the fire alarm moves only on published conditions, never on our odds.</p>
    <div class="fit-lanes">
      {lane("1 · Is AGI here?", "capability", lane1, note=note1)}
      {lane("2 · Could it be hidden?", "secrecy", lane2, note=note2)}
      {lane("3 · Should I worry today?", "rules, not odds", lane3, "sep", "The alarm never reads the probabilities above. They can move without the alarm, and the alarm can move without them.")}
    </div>
    <p class="fit-note">{outside_rail(data, external, trends)}</p>"""


def names_table(data, run, alarm, *, escape=None, trends=None):
    """'What each number means' (7.3): number · unit · today · reaches the top when. Phones render labelled cards."""
    run = as_dict(run)
    agi, pr = as_dict(run.get("agi")), as_dict(run.get("probs"))
    ok = ok_view(data)
    al = alarm_state({"alarm": alarm}, run)
    sig = signal_counts(run)
    tws = [t for t in as_list(run.get("tripwires")) if isinstance(t, dict)]
    no_cond = sum(1 for t in tws if not t.get("trigger"))
    chip = pending_chip(run, data) if ok else ""
    gauges = " · ".join(x for x in (_gauge_display(run, "gap"), _gauge_display(run, "rd"), _short_display(run, "oversight"),
                                     _gauge_display(run, "money"), _gauge_display(run, "delegation")) if x)
    wm = month_year(_crossing(trends).get("mid"))
    rows = [
        ("AGI parts", "parts met, of 8", str(status_counts(data)["met"]) if ok else "–", "one public system meets all eight"),
        ("AGI anywhere", "probability: today / by end-2030 / by end-2035",
         f"{fmt(agi.get('now'))} / {fmt(agi.get('y2030'))} / {fmt(agi.get('y2035'))}{chip}",
         "a system meets all eight, public or hidden; then it stays at 100"),
        ("A, B, C, D", "probability, today", " / ".join(fmt(as_dict(pr.get(k)).get("now")) for k in ("A", "B", "C", "D")) + chip,
         "proven to the alarm's Level-3 standard (A through Y1, B through Y3, C and D through Y2)"),
        ("D-open", "probability, today", fmt(as_dict(pr.get("Dopen")).get("now")), "open by definition; no alarm condition"),
        ("Hidden AGI Index", "probability that at least one of A–D is true now", fmt(run.get("index")),
         "one hidden scenario is proven"),
        ("Hiding-conditions gauges", "own units", e(gauges) or "–",
         "no top: context for our odds; only the capability gap is in a formula (A's), and none sets an alarm condition "
         "by itself"),
        ("Signals", "Quiet / Open / Confirmed", f"{sig['tripped']} confirmed",
         "goes to a ruling on the alarm condition it names" + (f" ({no_cond} of {len(tws)} tripwires name none)" if no_cond else "")),
        ("Alarm conditions", "met or not met", f"{len(al['met'])} met", "the level's rule is satisfied"),
        ("Fire alarm", "Level 0–3", f"Level {e(al['level'])} · {e(al['name'])}", "Level 3: proof beyond reasonable doubt"),
        ("Trend dates", "a date", f"work-month ~{wm}" if wm else "–", "never: a measured line extended, not a forecast"),
    ]
    body = "".join(f'<tr><td>{n}</td><td data-label="Unit">{u}</td><td data-label="Today">{t}</td>'
                   f'<td data-label="Reaches the top when">{w}</td></tr>' for n, u, t, w in rows)
    return (f'<div class="table-wrap"><table class="am-names"><caption class="sr-only">What each number means</caption>'
            f'<tr><th>Number</th><th>Unit</th><th>Today</th><th>Reaches the top when</th></tr>{body}</table></div>')


# ---------------------------------------------------------------------------------------------------- static tracker

def first_screen(c):
    """One line each for the hardest part, who, and what we watch next (6.4, ED-27)."""
    ups = [u for u in as_list(c.get("upcoming")) if isinstance(u, dict)]
    nxt = ups[0] if ups else None
    wat = [w for w in as_list(c.get("watching")) if isinstance(w, dict)]
    watch = str(wat[0].get("signal") or "") if wat else ""
    who_l = [w for w in as_list(c.get("who")) if isinstance(w, dict)]
    who = ", ".join(str(x.get("name") or "") for x in who_l[:3]) + (f" and {len(who_l) - 3} more" if len(who_l) > 3 else "")
    ch = [x for x in as_list(c.get("challenges")) if isinstance(x, dict)]
    hard = (str(ch[0].get("text") or "").split(". ")[0].rstrip(".") + ".") if ch else ""
    when = (nxt.get("approx") or day(nxt.get("date"))) if nxt else ""
    nx = f" ({when})" if when and when not in watch else ""
    return hard, who, (watch + nx) if watch else ""


def _crossing_text(m):
    def ok(d):
        return bool(re.match(r"\d{4}-\d{2}-\d{2}$", str(d or ""))) and str(d) <= "2030-12-31"
    if not ok(m.get("mid")):
        return "beyond 2030"
    band = (f" (95% band {month_year(m['fast'])} to {month_year(m['slow'])})" if ok(m.get("fast")) and ok(m.get("slow"))
            else " (band beyond 2030)")
    return month_year(m["mid"]) + band


MARK_LABEL = {"workDay": "a workday", "workWeek": "a work-week (40 h)", "workMonth": "a work-month (167 h)"}


def _on_trend(c, trends):
    tr = as_dict(as_dict(c.get("projection")).get("trend"))
    if not tr or not trends:
        return ""
    node = trends
    for k in str(tr.get("path") or "metr.p80.crossings").split("."):
        node = as_dict(node).get(k)
    cr = as_dict(node)
    out = [f"{MARK_LABEL.get(k, k)}: {_crossing_text(as_dict(cr.get(k)))}" for k in as_list(tr.get("marks")) if cr.get(k)]
    return "; ".join(out)


def static_component(c, data=None, root="", trends=None):
    h = as_dict(c.get("headline"))
    cur = "".join(f'<tr><td>{e(x.get("metric"))}</td><td data-label="Result">{e(x.get("value"))}</td>'
                  f'<td data-label="System">{e(x.get("system") or "–")}</td>'
                  f'<td data-label="As of">{as_of_html(x.get("asOf"))}</td>'
                  f'<td data-label="Rating and source">{rtag(x)} {link(x.get("url"), "source", root)}'
                  + (f'<div class="small muted">{e(x["ratingNote"])}</div>' if x.get("ratingNote") else "") + "</td></tr>"
                  for x in as_list(c.get("current")) if isinstance(x, dict))
    kind_chip = {"internal": '<span class="chip">unreleased model</span> ', "yardstick": '<span class="chip">new test</span> '}
    ms = "".join(f'<li><span class="when">{e(day(m.get("date")))}</span><span>{kind_chip.get(m.get("kind"), "")}'
                 f'{e(m.get("text"))} {rtag(m)} {link(m.get("url"), "source", root)}</span></li>'
                 for m in as_list(c.get("milestones")) if isinstance(m, dict))
    ch = "".join(f'<li>{e(x.get("text"))} {rtag(x)} {link(x.get("url"), "source", root)}</li>'
                 for x in as_list(c.get("challenges")) if isinstance(x, dict))
    who = "".join(f'<li><strong>{e(x.get("name"))}</strong>: {e(x.get("what"))} {rtag(x)} {link(x.get("url"), "source", root)}</li>'
                  for x in as_list(c.get("who")) if isinstance(x, dict))
    wat = "".join(f'<li><strong>{e(x.get("signal"))}</strong>. {e(x.get("threshold"))} '
                  f'<span class="muted">Source: {e(x.get("sourceName"))}</span> {link(x.get("url"), "link", root)}'
                  + (f' <span class="muted">Why: {e(x["why"])}</span>' if x.get("why") else "") + "</li>"
                  for x in as_list(c.get("watching")) if isinstance(x, dict))
    parts = "".join(f'<li><span class="mk" aria-hidden="true">{PART_STATE.get(p.get("state"), ("?", "?"))[0]}</span>'
                    f'<strong>{e(PART_STATE.get(p.get("state"), ("?", "Not known"))[1])}:</strong> {e(p.get("name"))}'
                    f' ({e(p.get("value"))})</li>' for p in as_list(c.get("parts")) if isinstance(p, dict))
    ups = "".join(f'<li><span class="when">{e(u.get("approx") or day(u.get("date")))}</span><span>{e(u.get("text"))} '
                  f'{rtag(u)} {link(u.get("url"), "source", root)}</span></li>'
                  for u in as_list(c.get("upcoming")) if isinstance(u, dict))
    proj = as_dict(c.get("projection"))
    trend = _on_trend(c, trends)
    test = as_dict(c.get("test"))
    also = as_dict(c.get("also"))
    hard, who1, nxt = first_screen(c)
    fs = []
    if hard:
        fs.append(f"<strong>Hardest:</strong> {e(hard)}")
    if who1:
        fs.append(f"<strong>Who:</strong> {e(who1)}.")
    if nxt:
        fs.append(f"<strong>Next to watch:</strong> {e(nxt.rstrip('.'))}.")
    v1 = ("Part of the v1.0 remote-work test, kept in v2.0." if c.get("v1Test")
          else "Added in v2.0: the v1.0 test did not require it.")
    return f"""
<section class="am-static" id="{e(c.get('id'))}">
  <h3>{e(c.get('name'))} {pips(c.get('status'), data)}</h3>
  <p>{e(c.get('glance'))}</p>
  <p class="small"><strong>{e(c.get('statusBasis'))}</strong></p>
  <p class="small"><strong>Now:</strong> {e(h.get('display'))} ({e(h.get('label'))}; {e(h.get('system'))}, {e(as_of(h.get('asOf')))}) {rtag(h)} {link(h.get('url'), 'source', root)}.
     <strong>Bar:</strong> {e(c.get('bar'))}</p>
  {('<p class="small am-fs">' + ' '.join(fs) + '</p>') if fs else ''}
  <details><summary>The test, the evidence and who is working on it</summary><div class="body">
    <p><strong>Question.</strong> {e(c.get('question'))}</p>
    <p><strong>Where it stands.</strong> {e(c.get('statusNote'))}</p>
    <p><strong>{e(parts_line(c))}.</strong></p><ul class="plain am-parts">{parts}</ul>
    <p><strong>Measure.</strong> {e(test.get('measure'))}</p>
    <p><strong>Marks.</strong> {e(test.get('threshold'))}</p>
    {f'<p class="small muted"><strong>Details.</strong> {e(test.get("detail"))}</p>' if test.get('detail') else ''}
    {f'<p class="small"><strong>Why this test.</strong> {e(test.get("why"))}</p>' if test.get('why') else ''}
    {f'<p class="small"><strong>Also.</strong> {e(also.get("text"))} {rtag(also)} {link(also.get("url"), "source", root)}</p>' if also.get('text') else ''}
    {f'<p class="small muted">{e(c.get("sharedWith"))}</p>' if c.get('sharedWith') else ''}
    <p class="small muted">{e(v1)} <a href="#v1">How v2.0 relates to v1.0</a></p>
    <h4>Latest measurements ({len(as_list(c.get('current')))})</h4>
    {f'<p class="small">{e(c.get("statusDetail"))}</p>' if c.get('statusDetail') else ''}
    <div class="table-wrap"><table class="am-meas"><tr><th>Measure</th><th>Result</th><th>System</th><th>As of</th><th>Rating and source</th></tr>{cur}</table></div>
    <h4>Timeline ({len(as_list(c.get('milestones')))} milestones) and what lies ahead</h4><ul class="timeline-list">{ms}</ul>
    {f'<p><strong>On-trend dates.</strong> {e(trend)}. <span class="muted">A measured trend extended, not a forecast.</span> {tag("our inference")} {link("trends.html", "Trend watch", root)}</p>' if trend else ''}
    {f'<p><strong>Ahead.</strong> {e(proj.get("text"))} {rtag(proj)} {link(proj.get("url"), "source", root)}</p>' if proj.get('text') else ''}
    {f'<h4>Coming up</h4><ul class="timeline-list">{ups}</ul>' if ups else ''}
    <h4>Hard parts ({len(as_list(c.get('challenges')))})</h4><ul class="plain">{ch}</ul>
    <h4>Who is working on it ({len(as_list(c.get('who')))})</h4><ul class="plain">{who}</ul>
    <h4>What we watch ({len(as_list(c.get('watching')))})</h4><ul class="plain">{wat}</ul>
    <h4>Could it be hidden?</h4><p>{e(c.get('hiddenAngle'))}</p>
    <p class="small muted">{e(str((scale(data).get(c.get('status')) or {}).get('word') or ''))} since {e(day(c.get('since')))} · reviewed {e(day(c.get('lastReviewed')))}.</p>
  </div></details>
</section>"""


def static_tracker(data, root="", trends=None):
    """The no-JS view inside #agi-map (6.7): the summary line, a table, then one section per part (ids equal the
    JS deep links, so agi.html#horizon works without JS). agiMap replaces it when it draws."""
    if not ok_view(data):
        return unavailable()
    c = status_counts(data)
    sc = scale(data)
    rows = "".join(f'<tr><td><a href="#{e(x["id"])}">{e(x.get("name"))}</a></td>'
                   f'<td>{e((sc.get(x.get("status")) or {}).get("word") or x.get("status"))}</td>'
                   f'<td>{e(as_dict(x.get("headline")).get("display"))} ({e(as_dict(x.get("headline")).get("system"))})</td>'
                   f'<td>{e(x.get("bar"))}</td></tr>' for x in data["components"])
    return (f'<p class="am-sum">{c["met"]} of {len(data["components"])} met · {c["close"]} close · {c["partial"]} partial · '
            f'{c["far"]} far</p>'
            f'<div class="table-wrap"><table><caption class="sr-only">The eight parts: status, best public result and bar'
            f'</caption><tr><th>Part</th><th>Status</th><th>Best public result</th><th>Bar</th></tr>{rows}</table></div>'
            + "".join(static_component(x, data, root, trends) for x in data["components"]))
