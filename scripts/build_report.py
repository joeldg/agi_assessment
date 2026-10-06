#!/usr/bin/env python3
"""Render the daily report pair for a format-2 reading (spec 9.1–9.3):

    reports/<date>.html            the short report (about 560 words), rendered from the run alone
    reports/<date>-analysis.html   the agent-written analysis body inside a script-rendered shell

    python3 scripts/build_report.py --snapshot DATE              # copy the snapshot fields into DATE's run entry
    python3 scripts/build_report.py --date DATE --body PATH      # render both pages, wrapping the body fragment PATH
    python3 scripts/build_report.py --date DATE                  # re-render, reusing the body already on the page
    python3 scripts/build_report.py --date DATE --check          # compare a fresh render with the files on disk
    python3 scripts/build_report.py --date DATE --runs FIXTURE --body BODY --out DIR   # rehearsal and tests

Both pages are a pure function of the run and the previous published run (B1): everything the short report shows
that lives in a data file the weekly rewrites (part statuses, furthest behind, the alarm's since date, the next
dates) is copied into the run by --snapshot, the only step that reads those files. So a Friday status change never
changes a published report, and --check stays true for it.

Exit codes: 0 done (WARN lines are budget notes); 1 --check found a difference; 2 bad input, naming the failing
field, tag or line (the fixer repairs data, never HTML); 3 a past date without --out (past reports are frozen).
check_data.py imports render() in-process; importing this module has no side effects.
"""
import argparse
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_feed import changed, delta_amount, fmt, outlet, prev_published  # noqa: E402
from sitekit import (HYP_LABELS, METHOD_CHANGE, SIGNAL_STATUS, SITE, method_boundary, round_grid, run_defs,  # noqa: E402
                     safe_url, signal_view, story_date)

ROOT = SCRIPTS.parent
COMPONENT_IDS = ["breadth", "quality", "reliability", "reasoning", "horizon", "autonomy", "learning", "generalization"]
SCALE = {"far": ("Far", 1), "partial": ("Partial", 2), "close": ("Close", 3), "met": ("Met", 4)}
PARTS_DEFS = "2.0"  # the definitions the eight parts belong to (agi_components.json definitionsVersion)
RATINGS = ["verified fact", "credible report", "expert opinion", "forecast aggregate", "our inference", "speculation"]
RATING_CLS = {"verified fact": "fact", "credible report": "report", "expert opinion": "opinion",
              "forecast aggregate": "agg", "our inference": "ours", "speculation": "spec"}
HYP_KEYS = ["A", "B", "C", "D", "Dopen"]
METHOD_KEYS = ["agi", "A", "C", "D", "Dopen"]  # the numbers that need an AGI-level system; B never does
ROWS = [("agi", "AGI anywhere"), ("A", "A · " + HYP_LABELS["A"]), ("B", "B · " + HYP_LABELS["B"]),
        ("C", "C · " + HYP_LABELS["C"]), ("D", "D · " + HYP_LABELS["D"]), ("Dopen", "D-open · " + HYP_LABELS["Dopen"])]
GAUGES = [("gap", "Capability gap"), ("rd", "AI-led R&D"), ("oversight", "Disclosure lag"), ("money", "Big Tech capex"),
          ("delegation", "Delegation")]
FLOOR_GAUGE = "oversight"
FLOOR_CHIP = ('<a href="../disclosure-lag.html#floor"><abbr class="chip" title="Incidents nobody found can\'t be counted, so this '
              'is a minimum">floor</abbr></a>')
INDEX_KEYS = ("A", "B", "CD")
IX_NAMES = {"A": ("Hidden AGI", "A"), "B": ("Hidden self-improvement only", "B only"),
            "CD": ("Covert actor or government only", "C/D only")}
CORRECTIONS_SHOWN = 5  # the email's cap too (build_feed.CORRECTIONS_SHOWN)
TOP_SHOWN = 6
PROSE_WARN, PROSE_MAX = 700, 1000
BUDGETS = [("verdict", 30), ("needle.brief", 100), ("timelineShort", 40), ("bottomLine", 60)]
ANALYSIS_IDS = ["alarm", "index", "gauges", "tripwires", "escape", "agi", "timeline", "roundup",
                "s1", "s2", "s3", "s4", "s5", "s6", "bottom"]
SHELL_IDS = {"corrections"}  # ids the shell owns; the body may not use them
MARK_BEGIN, MARK_END = "<!-- analysis:begin -->", "<!-- analysis:end -->"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
WORD = re.compile(r"[A-Za-z0-9][\w'’.,%-]*")


class ReportError(Exception):
    """Bad input: exit 2 (or 3 for a frozen past date) with one line naming the field, tag or line."""

    def __init__(self, msg, code=2):
        super().__init__(msg)
        self.code = code


# ---------- small helpers ----------

def words(s):
    return len(WORD.findall(s)) if isinstance(s, str) else 0


def e(s):
    return escape(str(s if s is not None else ""), quote=True)


def day(d, year=True):
    """'Oct 6, 2026' or 'Oct 6'."""
    t = datetime.strptime(str(d)[:10], "%Y-%m-%d")
    return f"{MONTHS[t.month - 1]} {t.day}" + (f", {t.year}" if year else "")


def long_day(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%-d %B %Y")


def short_day(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%-d %b %Y")


def get(obj, dotted):
    cur = obj
    for k in dotted.split("."):
        cur = cur.get(k) if isinstance(cur, dict) else None
    return cur


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def href(u, root):
    """A link target from data for a page `root` deep: http(s) as is, a site path made relative, else None."""
    u = safe_url(u)
    if not u:
        return None
    if u.startswith(SITE):
        return root + u[len(SITE):]
    return u if re.match(r"^https?://", u, re.I) or u.startswith("#") else root + u.lstrip("/")


def a(url, text, root):
    h = href(url, root)
    if not h:
        return e(text)
    ext = ' rel="noopener" target="_blank"' if h.startswith("http") else ""
    return f'<a href="{e(h)}"{ext}>{e(text)}</a>'


def split_rating(r):
    """'verified fact (lab's own evaluation)' -> ('verified fact', "lab's own evaluation")."""
    r = str(r or "").strip()
    low = r.lower()
    for base in RATINGS:
        if low.startswith(base):
            rest = re.sub(r"^\((.*)\)$", r"\1", r[len(base):].strip(" .;:,")).strip()
            return base, (rest or None)
    return (low or None), None


def chip(rating, note=None, qual=None):
    base, rest = split_rating(rating)
    if not base:
        return ""
    qual = qual or rest
    t = f' title="{e(note)}"' if note else ""
    q = f' <span class="tag-q">({e(qual)})</span>' if qual else ""
    return f'<span class="tag {RATING_CLS.get(base, "")}"{t}>{e(base)}</span>{q}'


def source_name(item):
    return str(item.get("source") or "").strip() or outlet(item.get("url"))


def fmtp(v):
    """Index parts, rounded to 0.05, with the decimals they need (1.0, 1.4, 0.55, 0.05)."""
    v = round(float(v) * 20) / 20
    return f"{v:.2f}" if abs(v * 10 - round(v * 10)) > 1e-9 else f"{v:.1f}"


def delta_text(cur, prev, unit=" pts"):
    if cur is None:
        return "–"
    if prev is None:
        return "first reading"
    if not changed(cur, prev):
        return "no change"
    return ("▲ +" if float(cur) > float(prev) else "▼ −") + delta_amount(cur, prev) + unit


def series(run, key):
    s = (run or {}).get("agi") if key == "agi" else ((run or {}).get("probs") or {}).get(key)
    return s if isinstance(s, dict) else {}


try:  # one rule for "a news line also moved this number" (WP-E), so the cells and check_data agree
    from checks.method import news_moved, METHOD_LINE  # noqa: E402
except Exception:  # pragma: no cover - only when scripts/checks is missing
    METHOD_LINE = re.compile(r"^\s*method change\b", re.I)

    def news_moved(run, key):
        return False


def news_amount(run, key, prev):
    """The from-to move a news line states for `key` today, as '▲ +0.5 pts', or '' when it can't be read."""
    for line in run.get("changes") or []:
        if not isinstance(line, str) or METHOD_LINE.match(line):
            continue
        m = re.search(r"from\s+(\d+(?:\.\d+)?)\s*%?\s*(?:to|→)\s*(\d+(?:\.\d+)?)", line)
        if m and news_moved({"changes": [line]}, key):
            return delta_text(float(m.group(2)), float(m.group(1)))
    return ""


def change_cell(run, prev, key, horizon="now"):
    """The "Change today" text for agi/A–D-open/index. On a method boundary (the run's definitions differ from the
    previous published run's) the numbers that need an AGI-level system and the Index say METHOD_CHANGE, and a
    number a news line also moved says '▲ +0.5 pts news; then method change (definitions v2.0)'. B keeps its delta."""
    if key == "index":
        cur, old = run.get("index"), (prev or {}).get("index")
    else:
        cur, old = series(run, key).get(horizon), (series(prev, key).get(horizon) if prev else None)
    if method_boundary(run, prev) and key != "B":
        if key != "index" and news_moved(run, key):
            amt = news_amount(run, key, prev)
            return (amt + " news; then " if amt else "news; then ") + METHOD_CHANGE
        return METHOD_CHANGE
    return delta_text(cur, old)


def signal_word(status):
    return SIGNAL_STATUS.get(str(status), (None, None, str(status or "?")))[2]


def signal_counts(run):
    tw = [t for t in run.get("tripwires") or [] if isinstance(t, dict)]
    return {k: sum(1 for t in tw if t.get("status") == k) for k in ("tripped", "watching", "quiet")}


def top_items(run):
    out = []
    for g in run.get("roundup") or []:
        for it in (g.get("items") or []) if isinstance(g, dict) else []:
            if isinstance(it, dict) and it.get("top") is True:
                out.append(it)
    return out


def all_items(run):
    return sum(len(g.get("items") or []) for g in run.get("roundup") or [] if isinstance(g, dict))


def item_short(it):
    s = it.get("short")
    if isinstance(s, str) and s.strip():
        return s.strip()
    w = str(it.get("text") or "").split()
    return " ".join(w[:25]) + ("…" if len(w) > 25 else "")


def item_date(it):
    """The item's date as every surface shows it (sitekit.story_date): background items read "{date} (earlier event)"."""
    return story_date(it)


def status_counts(snap):
    c = {k: 0 for k in SCALE}
    for cid in COMPONENT_IDS:
        st = (snap.get(cid) or {}).get("status")
        if st in c:
            c[st] += 1
    return c


def answer_text(run):
    """'Not in public: 0 of 8 parts met (2 partial, 6 far).' from the run's components snapshot (three states, 4.2).
    "Yes, in public" needs the components file's publicAgi, which the snapshot does not carry: all 8 met reads
    "Possibly, in public"."""
    c, n = status_counts(run.get("components") or {}), len(COMPONENT_IDS)
    if c["met"] == n:
        return "Possibly, in public:", f"all {n} parts are met, but not yet by one system."
    rest = ", ".join(f"{c[k]} {SCALE[k][0].lower()}" for k in ("close", "partial", "far") if c[k])
    return "Not in public:", f"{c['met']} of {n} parts met" + (f" ({rest})." if rest else ".")


def index_parts(run):
    return [p for p in run.get("indexParts") or [] if isinstance(p, dict)]


def index_sum(run):
    return round(sum(round(float(p["v"]) * 20) / 20 for p in index_parts(run)), 2)


def index_parts_text(run):
    """'A 0.55 + B-only 1.7 + C/D 0.05; parts sum to 2.3, shown as 2.5 on our rounding grid' (the last clause only
    when the parts sum below the published Index)."""
    names = {"A": "A", "B": "B-only", "CD": "C/D"}
    parts = index_parts(run)
    if not parts:
        return ""
    s = " + ".join(f"{names[p['key']]} {fmtp(p['v'])}" for p in parts)
    tot = index_sum(run)
    if run.get("index") is not None and float(run["index"]) - tot > 0.001:
        s += f"; parts sum to {fmt(tot)}, shown as {fmt(run['index'])} on our rounding grid"
    return s


def b_only(run):
    return next((p["v"] for p in index_parts(run) if p.get("key") == "B"), None)


def gauge_label(key):
    return dict(GAUGES).get(key, key)


def gauge_display(key, g):
    d = str(g.get("display") or fmt(g.get("value")))
    if key == "delegation":  # "Level" is the fire alarm's word only (3.1)
        d = re.sub(r"^\s*Level\s+(\d)\s+of\s+5", r"rung \1 of 5", d)
    return d


def gauge_keys(run):
    gs = run.get("gauges") or {}
    return [k for k, _ in GAUGES if k in gs] + [k for k in gs if k not in dict(GAUGES)]


def moved_gauges(run, prev):
    out = []
    for k in gauge_keys(run):
        g, pg = (run.get("gauges") or {}).get(k) or {}, ((prev or {}).get("gauges") or {}).get(k) or {}
        if prev is not None and g.get("value") is not None and pg.get("value") is not None \
                and changed(g["value"], pg["value"]):
            out.append(k)
    return out


def escape_line_parts(run):
    """(confirmed, total, open, change text, new-evidence text) from the run's own Escape counts (never escape.json)."""
    es = run.get("escape") if isinstance(run.get("escape"), dict) else {}
    t, w, q = (int(es.get(k) or 0) for k in ("tripped", "watching", "quiet"))
    ch = [c for c in es.get("changes") or [] if isinstance(c, dict)]
    ch_text = "; ".join(f"{c['key']} {signal_word(c['from']).lower()} → {signal_word(c['to']).lower()}" for c in ch) \
        if ch else "no status changed"
    ne = [x for x in es.get("newEvidence") or [] if isinstance(x, str)]
    ne_text = f"new evidence on {len(ne)} ({', '.join(ne)})" if ne else "no new evidence"
    return t, t + w + q, w, ch_text, ne_text


def next_dates(evs, n=3):
    """The next `n` dated events (already sorted by date), always including the next pre-published alarm clock
    (kind "alarm", such as the date W2 is met) in place of the last one when it falls later: the clocks are the
    dates readers can hold us to."""
    nxt = list(evs[:n])
    clock = next((x for x in evs if x.get("kind") == "alarm"), None)
    if clock is not None and clock not in nxt and n > 0:
        nxt = nxt[:n - 1] + [clock]
    return nxt


def calendar_short(ev):
    s = str(ev.get("short") or "").strip()
    if not s:
        s = re.split(r"\s+\(|;\s", str(ev.get("title") or "").strip(), maxsplit=1)[0].strip().rstrip(".")
    w = s.split()
    return " ".join(w[:14]) + ("…" if len(w) > 14 else "")


def event_short(ev, forecasts=None):
    """A date-to-watch line. A deadline for our own forecasts is quoted with our probability, so it never reads as
    news (ED19): 'Our forecast: “OpenAI says it has resumed training its frontier models” (we said 45%)'."""
    if ev.get("kind") == "forecast" and forecasts:
        try:
            from pages.home import _forecast_items
            items = _forecast_items(ev, forecasts)
        except Exception:  # noqa: BLE001 - the plain title is a fine fallback
            items = []
        if len(items) == 1:
            return "Our forecast: " + items[0]
        if items:
            s = f"Deadline for {len(items)} of our forecasts, including {items[0]}"
            return s if words(s) <= 14 else f"Deadline for {len(items)} of our forecasts"
    return calendar_short(ev)


# ---------- loading and validation ----------

def load_runs(runs_path=None):
    p = Path(runs_path) if runs_path else ROOT / "data/runs.json"
    try:
        runs = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as x:
        raise ReportError(f"{p}: {x}")
    if not isinstance(runs, list):
        raise ReportError(f"{p}: expected a list of runs")
    return runs


def root_for(runs_path):
    """The tree a runs file belongs to: <root>/data/runs.json, else this repo (fixtures)."""
    if runs_path:
        p = Path(runs_path).resolve()
        if p.name == "runs.json" and p.parent.name == "data":
            return p.parent.parent
    return ROOT


def find(runs, date):
    idx = [i for i, r in enumerate(runs) if isinstance(r, dict) and r.get("date") == date and r.get("report")]
    if not idx:
        raise ReportError(f"runs.json has no reading with a report dated {date}")
    i = idx[-1]
    return i, runs[i], prev_published(runs, i)


def newest_date(runs):
    return max((r.get("date", "") for r in runs if isinstance(r, dict) and r.get("report")), default="")


def _objects(where, items, fields):
    if items is None:
        return []
    if not isinstance(items, list):
        raise ReportError(f"{where}: expected a list of {{{', '.join(fields)}}}")
    for j, x in enumerate(items):
        if not isinstance(x, dict) or not all(k in x for k in fields):
            got = "a string" if isinstance(x, str) else json.dumps(x, ensure_ascii=False)[:60]
            raise ReportError(f"{where}[{j}]: expected an object with {', '.join(fields)}; got {got}")
    return items


def validate(run):
    """Structural checks first (exit 2, naming the field); returns WARN lines for optional fields and budgets."""
    d = run.get("date")
    warns = []
    if run.get("format") != 2:
        raise ReportError(f"runs[{d}].format is {json.dumps(run.get('format'))}, not 2: only format-2 readings are "
                          "rendered by build_report.py (earlier reports are frozen)")
    if run.get("report") != f"reports/{d}.html":
        raise ReportError(f"report: expected \"reports/{d}.html\", got {json.dumps(run.get('report'))}")
    if run.get("analysis") != f"reports/{d}-analysis.html":
        raise ReportError(f"analysis: expected \"reports/{d}-analysis.html\", got {json.dumps(run.get('analysis'))}")
    for k in ("verdict", "timelineShort", "bottomLine"):
        if not isinstance(run.get(k), str) or not run[k].strip():
            raise ReportError(f"{k}: required on a format-2 reading (a non-empty string)")
    nd = run.get("needle")
    if not isinstance(nd, dict):
        raise ReportError("needle: expected an object with subject, brief, rating, url and source")
    for k in ("brief", "url"):
        if not isinstance(nd.get(k), str) or not nd[k].strip():
            raise ReportError(f"needle.{k}: required on a format-2 reading")
    if not safe_url(nd["url"]):
        raise ReportError(f"needle.url: {json.dumps(nd['url'])} is not an http(s) or site link")
    if split_rating(nd.get("rating"))[0] not in RATINGS:
        raise ReportError(f"needle.rating: {json.dumps(nd.get('rating'))} must be one of: {', '.join(RATINGS)}")
    if not str(nd.get("source") or "").strip():
        warns.append("needle.source is missing; the link is named after its domain")
    if not str(nd.get("subject") or "").strip():
        warns.append("needle.subject is missing; the needle box has no headline")
    for key in ["agi"] + HYP_KEYS:
        s = series(run, key)
        where = "agi" if key == "agi" else f"probs.{key}"
        for h in ("now", "y2030", "y2035"):
            if not is_num(s.get(h)):
                raise ReportError(f"{where}.{h}: expected a number, got {json.dumps(s.get(h))}")
    if not is_num(run.get("index")):
        raise ReportError(f"index: expected a number, got {json.dumps(run.get('index'))}")
    parts = run.get("indexParts")
    if not isinstance(parts, list) or not parts:
        raise ReportError("indexParts: expected a list of {key: A|B|CD, v}")
    seen = set()
    for j, p in enumerate(parts):
        if not isinstance(p, dict) or p.get("key") not in INDEX_KEYS or not is_num(p.get("v")):
            raise ReportError(f"indexParts[{j}]: expected {{key: A|B|CD, v: number}}; got "
                              f"{json.dumps(p, ensure_ascii=False)[:60]}")
        if p["key"] in seen:
            raise ReportError(f"indexParts[{j}]: key {p['key']} appears twice")
        seen.add(p["key"])
        if abs(p["v"] * 20 - round(p["v"] * 20)) > 1e-6:
            warns.append(f"indexParts[{j}].v={p['v']} is not rounded to the nearest 0.05")
    tot = round(sum(p["v"] for p in parts), 6)
    if abs(round_grid(tot) - float(run["index"])) > 1e-9:
        raise ReportError(f"indexParts: the parts sum to {round(tot, 4)}, which rounds to {round_grid(tot)} on our grid, "
                          f"but index={run['index']}")
    snap = run.get("components")
    if not isinstance(snap, dict):
        raise ReportError("components: the snapshot of the 8 parts is missing; run build_report.py --snapshot " + str(d))
    unknown = [k for k in snap if k not in COMPONENT_IDS]
    if unknown:
        raise ReportError(f"components: unknown component id {json.dumps(unknown[0])} (the ids are "
                          f"{', '.join(COMPONENT_IDS)})")
    for cid in COMPONENT_IDS:
        s = snap.get(cid)
        if not isinstance(s, dict) or s.get("status") not in SCALE or not all(
                isinstance(s.get(k), str) for k in ("short", "glance")):
            raise ReportError(f"components.{cid}: expected {{status (far|partial|close|met), short, glance}}; got "
                              f"{json.dumps(s, ensure_ascii=False)[:60]}")
    if run.get("tripwireChanges") is None:
        warns.append("tripwireChanges is missing; the signals section leaves the change line out")
    _objects("tripwireChanges", run.get("tripwireChanges"), ("id", "from", "to", "why"))
    es = run.get("escape")
    if not isinstance(es, dict):
        raise ReportError("escape: expected the run's Escape watch counts {tripped, watching, quiet, changes, newEvidence}")
    for k in ("tripped", "watching", "quiet"):
        if not is_num(es.get(k)):
            raise ReportError(f"escape.{k}: expected a count, got {json.dumps(es.get(k))}")
    _objects("escape.changes", es.get("changes"), ("key", "from", "to", "reason"))
    ne = es.get("newEvidence")
    if ne is None:
        warns.append("escape.newEvidence is missing; the Escape line leaves it out")
    elif not isinstance(ne, list) or not all(isinstance(x, str) for x in ne):
        raise ReportError("escape.newEvidence: expected a list of indicator keys")
    for j, c in enumerate(_objects("componentLeads", run.get("componentLeads"), ("id", "claim", "url", "rating", "why"))):
        if c["id"] not in COMPONENT_IDS:
            raise ReportError(f"componentLeads[{j}].id: unknown component id {json.dumps(c['id'])}")
    mc = run.get("methodChange")
    if mc is not None and (not isinstance(mc, dict) or not all(isinstance(mc.get(k), str) for k in ("from", "to"))):
        raise ReportError("methodChange: expected {from, to, note}")
    al = run.get("alarm")
    if not isinstance(al, dict) or not is_num(al.get("level")) or not isinstance(al.get("met"), list):
        raise ReportError("alarm: expected {level, met, criteria} plus the snapshot (since, icon, status, name)")
    if not all(al.get(k) for k in ("icon", "status", "name")):
        warns.append(f"alarm.icon/status/name snapshot is missing (run build_report.py --snapshot {d}); "
                     "card 3 shows the level number only")
    if run.get("dates") is None:
        warns.append(f"dates snapshot is missing (run build_report.py --snapshot {d}); the dates list is left out")
    elif not isinstance(run["dates"], list):
        raise ReportError("dates: expected a list of {date, short}")
    _objects("dates", run.get("dates"), ("date", "short"))
    if run.get("furthest") is not None and not isinstance(run["furthest"], dict):
        raise ReportError("furthest: expected {id, short, display, targetDisplay} or null")
    for j, c in enumerate(run.get("corrections") or []):
        if not isinstance(c, dict) or not c.get("was") or not c.get("now"):
            raise ReportError(f"corrections[{j}]: expected an object with was and now")
    if not isinstance(run.get("gauges") or {}, dict):
        raise ReportError("gauges: expected an object keyed by gauge")
    if not isinstance(run.get("roundup") or [], list):
        raise ReportError("roundup: expected a list of {topic, items}")
    tops = top_items(run)
    if not tops:
        warns.append("roundup has no top: true item; the top-stories list is empty")
    elif len(tops) > TOP_SHOWN:
        warns.append(f"roundup has {len(tops)} top items; the report shows the first {TOP_SHOWN}")
    elif len(tops) < 3:
        warns.append(f"roundup has {len(tops)} top items (3–6)")
    for j, it in enumerate(tops):
        if not str(it.get("short") or "").strip():
            warns.append(f"top item {j + 1} has no short; its first 25 words are shown")
        elif words(it["short"]) > 25:
            warns.append(f"top item {j + 1}: short is {words(it['short'])} words (budget 25)")
        if split_rating(it.get("rating"))[0] not in RATINGS:
            warns.append(f"top item {j + 1} has no rating from the six-word set; no chip is shown")
    for k, lim in BUDGETS:
        n = words(get(run, k))
        if n > lim:
            warns.append(f"{k} is {n} words (budget {lim})")
    for k, g in (run.get("gauges") or {}).items():
        if isinstance(g, dict) and words(g.get("brief")) > 20:
            warns.append(f"gauges.{k}.brief is {words(g.get('brief'))} words (budget 20)")
    for j, x in enumerate(run.get("dates") or []):
        if words(x.get("short")) > 14:
            warns.append(f"dates[{j}].short is {words(x.get('short'))} words (budget 14)")
    return warns


# ---------- the analysis body fragment (9.2) ----------

ALLOWED_TAGS = {"p", "h2", "h3", "h4", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td", "caption", "div",
                "section", "span", "a", "strong", "em", "b", "i", "small", "aside", "hr", "details", "summary",
                "blockquote", "br", "sup", "abbr", "code", "dl", "dt", "dd"}
ALLOWED_ATTRS = {"id", "class", "href", "title", "colspan", "rowspan", "open", "rel", "target"}
REFUSED_TAGS = {"script", "style", "link", "meta", "iframe", "object", "embed", "form", "input", "nav", "html", "head",
                "body"}
VOID_TAGS = {"br", "hr"}


class _Fragment(HTMLParser):
    """Re-serialises the body: allowed tags and attributes only, all text re-escaped, comments dropped. Refused
    constructs raise ReportError naming the tag and line; anything else unknown is stripped with a WARN."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.warns, self.ids = [], [], []

    def _line(self):
        return self.getpos()[0]

    def _open(self, tag, attrs, close=False):
        line = self._line()
        if tag in REFUSED_TAGS:
            raise ReportError(f"analysis body line {line}: <{tag}> is not allowed (refused: "
                              f"{', '.join(sorted(REFUSED_TAGS))})")
        for k, v in attrs:
            if k.startswith("on"):
                raise ReportError(f"analysis body line {line}: <{tag} {k}=…>: event-handler attributes are not allowed")
            if k == "class" and "subscribe" in (v or "").lower():
                raise ReportError(f"analysis body line {line}: <{tag} class=\"{v}\">: the shell adds the subscribe boxes")
            if k == "href" and not safe_url(v):
                raise ReportError(f"analysis body line {line}: <{tag} href=\"{v}\">: links must be http(s) or relative")
        if tag not in ALLOWED_TAGS:
            self.warns.append(f"analysis body line {line}: <{tag}> stripped (not on the allowed list); its text is kept")
            return
        kept = []
        for k, v in attrs:
            if k not in ALLOWED_ATTRS:
                self.warns.append(f"analysis body line {line}: attribute {k} on <{tag}> stripped")
                continue
            if k == "id" and v in SHELL_IDS:
                self.warns.append(f"analysis body line {line}: id \"{v}\" stripped (the shell renders #{v})")
                continue
            if k == "id":
                self.ids.append((v, line))
            kept.append(f" {k}" if v is None else f' {k}="{escape(v, quote=True)}"')
        self.out.append(f"<{tag}{''.join(kept)}>")
        if close and tag not in VOID_TAGS:
            self.out.append(f"</{tag}>")

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, close=True)

    def handle_endtag(self, tag):
        if tag in REFUSED_TAGS:
            raise ReportError(f"analysis body line {self._line()}: </{tag}> is not allowed")
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        self.out.append(escape(data, quote=False))

    def handle_comment(self, data):
        if data.strip():
            self.warns.append(f"analysis body line {self._line()}: comment dropped")

    def handle_decl(self, decl):
        self.warns.append(f"analysis body line {self._line()}: <!{decl}> dropped")

    def unknown_decl(self, data):
        self.warns.append(f"analysis body line {self._line()}: <![{data[:20]}…]> dropped")

    def handle_pi(self, data):
        self.warns.append(f"analysis body line {self._line()}: processing instruction dropped")


def clean_body(body):
    """(clean fragment, WARN lines). Raises ReportError for refused constructs and for the required ids (each once,
    in order: alarm index gauges tripwires escape agi timeline roundup s1 … s6 bottom)."""
    p = _Fragment()
    p.feed(body or "")
    p.close()
    ids = [i for i, _ in p.ids]
    for i in ANALYSIS_IDS:
        n = ids.count(i)
        if n == 0:
            raise ReportError(f"analysis body: id \"{i}\" is missing (required once each, in this order: "
                              f"{' '.join(ANALYSIS_IDS)})")
        if n > 1:
            lines = [str(ln) for x, ln in p.ids if x == i]
            raise ReportError(f"analysis body: id \"{i}\" appears {n} times (lines {', '.join(lines)}); once only")
    order = [i for i in ids if i in ANALYSIS_IDS]
    if order != ANALYSIS_IDS:
        bad = next(j for j, (x, y) in enumerate(zip(order, ANALYSIS_IDS)) if x != y)
        line = dict(p.ids)[order[bad]]
        raise ReportError(f"analysis body line {line}: id \"{order[bad]}\" is out of order; the order is "
                          f"{' '.join(ANALYSIS_IDS)}")
    return "".join(p.out).strip("\n") + "\n", p.warns


def body_from_page(html):
    """The body between the markers of an existing analysis page, or None."""
    if not html or MARK_BEGIN not in html or MARK_END not in html:
        return None
    return html.split(MARK_BEGIN, 1)[1].split(MARK_END, 1)[0].strip("\n") + "\n"


# ---------- the cards (local renderers, mirroring final_build_prototype.py and pages.common) ----------

def pips(status, word_cls="am-word"):
    word, n = SCALE[status]
    spans = "".join(f'<span class="pip{" on" if i < n else ""}"></span>' for i in range(4))
    return (f'<span class="am-status"><span class="am-pips" aria-hidden="true">{spans}</span>'
            f'<span class="{word_cls}" aria-hidden="true">{e(word)}</span>'
            f'<span class="sr-only">, status {e(word)}, step {n} of 4</span></span>')


def strip_html(run, root):
    snap = run["components"]
    cells = "".join(
        f'<li><a class="ag-cell" href="{root}agi.html#{cid}" data-open="{cid}">'
        f'<span class="ag-name">{e(snap[cid]["short"])}</span>{pips(snap[cid]["status"], "ag-word")}'
        f'<span class="sr-only">. {e(snap[cid]["glance"])}</span></a></li>' for cid in COMPONENT_IDS)
    return f'<ul class="ag-strip">{cells}</ul>'


def pending_chip(run):
    """The run's numbers use different definitions from the parts it shows (definitions v2.0): label them."""
    if run_defs(run) == PARTS_DEFS:
        return ""
    return (' <span class="chip" title="These numbers use the v1.0 bar; the eight parts shown are definitions v2.0\'s.">'
            'v1.0 bar</span>')


def index_block(run):
    """The decomposition bar on a fixed 0–5% scale: A, B outside A, C or D outside A (neutral), then a hatched
    rounding segment up to the published Index when the parts sum below it (ED-03, ED-16, m7, m9)."""
    w, h, scale_max = 600, 16, 5.0
    idx = float(run["index"])
    parts = index_parts(run)
    X = lambda v: max(0.0, min(w, v / scale_max * w))  # noqa: E731
    out = [f'<rect class="ix-rest" x="0" y="0" width="{w}" height="{h}" rx="3"></rect>']
    x = 0.0
    for p in parts:
        pw = max(2.0, X(p["v"]))
        out.append(f'<rect class="ix-seg-{p["key"]}" x="{x:.1f}" y="0" width="{pw:.1f}" height="{h}"><title>'
                   f'{e(IX_NAMES[p["key"]][0])}: {fmtp(p["v"])} points</title></rect>')
        x += pw
    tot = index_sum(run)
    rnd = round(idx - tot, 2)
    lab = "; ".join(f"{IX_NAMES[p['key']][0]} {fmtp(p['v'])} points" for p in parts)
    if rnd > 0.001:
        out.append(f'<rect x="{x:.1f}" y="0" width="{X(rnd):.1f}" height="{h}" fill="url(#ixh-r)" class="ix-round"><title>'
                   f'Rounding: {fmtp(rnd)} points (parts sum to {fmt(tot)}; the Index is rounded to our grid)</title></rect>')
        lab += f"; parts sum to {fmt(tot)}, shown as {fmt(idx)} on our rounding grid"
    out.append(f'<rect class="ix-end" x="{w - 3}" y="-2" width="3" height="{h + 4}"></rect>')
    svg = (f'<svg class="ix-bar" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
           f'aria-label="Hidden AGI Index {fmt(idx)}%: {e(lab)}. Scale 0 to 5%.">'
           f'<defs><pattern id="ixh-r" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
           f'<rect width="6" height="6" class="ix-hatch-bg"></rect><line x1="0" y1="0" x2="0" y2="6" class="ix-hatch">'
           f'</line></pattern></defs>' + "".join(out) + "</svg>")
    sw = {"A": "ix-sw-A", "B": "ix-sw-B", "CD": "ix-sw-CD"}
    ks = "".join(f'<span><span class="swatch {sw[p["key"]]}"></span> <span class="l">{e(IX_NAMES[p["key"]][0])}</span>'
                 f'<span class="s">{e(IX_NAMES[p["key"]][1])}</span> {fmtp(p["v"])}</span>' for p in parts)
    if rnd > 0.001:
        ks += (f'<span><span class="swatch ix-sw-round"></span> rounding {fmtp(rnd)}</span>'
               f'<span class="muted">parts sum to {fmt(tot)}; shown as {fmt(idx)} on our rounding grid</span>')
    return (f'<div class="ix-wrap">{svg}<div class="ix-scale" aria-hidden="true"><span>0</span><span>5%</span></div></div>'
            f'<div class="ix-key small">{ks}</div>')


def card_agi(run, prev, root, an):
    head, rest = answer_text(run)
    leads = [c for c in run.get("componentLeads") or [] if isinstance(c, dict)]
    lead = ""
    if leads:
        names = []
        for c in leads:
            n = run["components"][c["id"]]["short"]
            if n not in names:
                names.append(n)
        lead = (f'<p class="hq-line small">{len(leads)} new result{"s" if len(leads) != 1 else ""} pending our weekly '
                f'check: {e(", ".join(names))}. <a href="{an}#agi">Details →</a></p>')
    mc = ' <span class="small muted">· method change (definitions v2.0)</span>' if method_boundary(run, prev) else ""
    return f"""<section class="hq" id="agi" aria-labelledby="q1">
    <h2 class="hq-q" id="q1">1 · Is AGI here?</h2>
    <p class="hq-a"><strong>{e(head)}</strong> {e(rest)}</p>
    <p class="hq-line hq-any">AGI anywhere, public or hidden: <strong>{fmt(run['agi']['now'])}%</strong> today{pending_chip(run)}{mc}</p>
    {strip_html(run, root)}
    {lead}<p class="hq-more"><a href="{root}agi.html#definition">What we mean by AGI →</a><a href="{root}agi.html">All eight parts →</a></p>
  </section>"""


def card_hidden(run, prev, root, an):
    b = b_only(run)
    bridge = ""
    if float(run["index"]) > float(run["agi"]["now"]) and b is not None:
        bridge = (f'<p class="hq-line small">Above AGI anywhere because {fmtp(b)} points are hidden self-improvement (B), '
                  'which needs no AGI.</p>')
    return f"""<section class="hq" id="index" aria-labelledby="q2">
    <h2 class="hq-q" id="q2">2 · Could it be hidden?</h2>
    <p class="hq-a"><span class="big">{fmt(run['index'])}%</span> Hidden AGI Index, {e(change_cell(run, prev, 'index'))}</p>
    {index_block(run)}
    {bridge}<p class="hq-more"><a href="{root}start-here.html#pieces">How our numbers fit →</a><a href="{an}#index">How we derived it →</a></p>
  </section>"""


def card_alarm(run, root):
    al = run["alarm"]
    icon = (f'<span class="ico ico-{e(al["status"])}" aria-hidden="true">{e(al["icon"])}</span>'
            if al.get("icon") and al.get("status") else "")
    name = f' · {e(al["name"])}' if al.get("name") else ""
    since = f'since {day(al["since"], False)} · ' if al.get("since") else ""
    met = ", ".join(str(m) for m in al.get("met") or [])
    met = f"{e(met)} met" if met else "no condition met"
    return f"""<section class="hq hq-sep" id="alarm" aria-labelledby="q3">
    <h2 class="hq-q" id="q3">3 · Should I worry today? <span class="hq-seplabel"><span class="l">Separate: set by published rules, never by the odds above</span><span class="s">Rules, not odds</span></span></h2>
    <p class="hq-a"><span class="hq-alarm">{icon}Fire alarm: Level {int(al['level'])}{name}</span>
      <span class="small muted">{since}{met}</span></p>
    <p class="hq-more"><a href="{root}alarm.html">Fire alarm rules →</a><a href="{root}escape.html">Escape watch →</a></p>
  </section>"""


def cards(run, prev, root, an, warns=None):
    """The three answer cards, from pages.common (one implementation with the homepage) called with snapshot(run)
    only (B1). The local renderers above stand in only if pages.common is missing or fails, with a WARN, so a slip
    in shared page code never costs the issue."""
    try:
        from pages import common
        view = common.snapshot(run)
        html = (common.card_agi(view, run, prev, root, {"card": "agi", "q": "q1"}, report=True) + "\n  "
                + common.card_hidden(run, prev, root, {"card": "index", "q": "q2"}) + "\n  "
                + common.card_alarm(view, run, root, {"card": "alarm", "q": "q3"}, report=True))
    except Exception as x:  # noqa: BLE001 - any failure falls back to the local cards
        if warns is not None:
            warns.append(f"pages.common cards unavailable ({type(x).__name__}: {x}); rendered with the local cards")
        html = f"{card_agi(run, prev, root, an)}\n  {card_hidden(run, prev, root, an)}\n  {card_alarm(run, root)}"
    return f'<div class="rp-cards">{html}</div>'


# ---------- the short report (9.1) ----------

def correction_li(c, root):
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(c.get("page") or ""))
    said = f"On {long_day(m.group(0))} we said" if m else "We said"
    fixed = f" (corrected {long_day(c['date'])})" if re.match(r"^\d{4}-\d{2}-\d{2}$", str(c.get("date") or "")) else ""
    src = f" ({a(c.get('url'), source_name(c), root)})" if safe_url(c.get("url")) else ""
    return (f'<li>{said} {e(str(c["was"]).strip().rstrip("."))}. That was wrong{fixed}: '
            f'{e(str(c["now"]).strip().rstrip("."))}{src}.</li>')


def newest_first(cs):
    """Corrections by correction date, newest first; entries of one date keep their order."""
    return [c for _, c in sorted(enumerate(cs), key=lambda t: (str(t[1].get("date") or ""), -t[0]), reverse=True)]


def corrections_box(run, root, an):
    cs = [c for c in run.get("corrections") or [] if isinstance(c, dict)]
    if not cs:
        return ""
    shown = newest_first(cs)[:CORRECTIONS_SHOWN]
    more = len(cs) - len(shown)
    tail = (f'<p class="small"><a href="{an}#corrections">{more} more correction{"s" if more != 1 else ""} →</a></p>'
            if more else "")
    head = "Correction" if len(cs) == 1 else "Corrections"
    return (f'<aside class="callout rp-corr" aria-label="{head}"><strong>{head}</strong>'
            f'<ul class="plain">{"".join(correction_li(c, root) for c in shown)}</ul>{tail}</aside>')


def method_banner(run, prev, root):
    if not run.get("methodChange") and not method_boundary(run, prev):
        return ""
    to = (run.get("methodChange") or {}).get("to") or run_defs(run)
    return (f'<p class="callout rp-method"><strong>Method change today:</strong> this is our first reading under definitions v{e(to)}. Our '
            f'numbers were re-derived; this is not news. <a href="{root}changes.html#method">What changed →</a></p>')


def needle_html(run, root):
    nd = run["needle"]
    q = " quiet" if nd.get("quiet") else ""
    head = f'<p class="headline">{e(nd["subject"])}</p>' if str(nd.get("subject") or "").strip() else ""
    kicker = "Quiet day" if nd.get("quiet") else "What moved the needle"   # the email's kicker too (build_feed)
    return (f'<section id="needle" class="needle{q}"><p class="kicker">{kicker}</p>{head}\n'
            f'    <p>{e(nd["brief"])} {chip(nd.get("rating"))}{a(nd.get("url"), source_name(nd), root)}</p></section>')


def prob_table(run, prev):
    rows = []
    for key, label in ROWS:
        s = series(run, key)
        rows.append(f'<tr><td>{e(label)}</td><td class="num" data-label="Today">{fmt(s["now"])}%</td>'
                    f'<td class="num" data-label="By end-2030">{fmt(s["y2030"])}%</td>'
                    f'<td class="num" data-label="By end-2035">{fmt(s["y2035"])}%</td>'
                    f'<td class="muted" data-label="Change today">{e(change_cell(run, prev, key))}</td>'
                    f'<td data-label="Confidence">{e(s.get("conf") or "")}</td></tr>')
    return ('<div class="table-wrap"><table class="rp-prob"><tr><th>Hypothesis</th><th class="num">Today</th>'
            '<th class="num">By end-2030</th><th class="num">By end-2035</th><th>Change today</th><th>Confidence</th></tr>'
            + "".join(rows) + "</table></div>")


def signals_html(run, prev, root):
    c = signal_counts(run)
    by_id = {t.get("id"): t for t in run.get("tripwires") or [] if isinstance(t, dict)}
    ch = [x for x in run.get("tripwireChanges") or [] if isinstance(x, dict)]
    if ch:
        lis = []
        for x in ch[:3]:
            trig = (by_id.get(x["id"]) or {}).get("trigger")
            icon, tok, word = signal_view(x["to"], trig) if str(x["to"]) in SIGNAL_STATUS else ("", "", signal_word(x["to"]))
            name = (by_id.get(x["id"]) or {}).get("signal") or x["id"]
            ico = f'<span class="ico ico-{tok}" aria-hidden="true">{icon}</span> ' if icon else ""
            lis.append(f'<li>{ico}{e(name)}: {e(signal_word(x["from"]))} → {e(word)}. {e(x["why"])}</li>')
        more = f'<p class="small muted">{len(ch) - 3} more changed; see the analysis.</p>' if len(ch) > 3 else ""
        changes = f'<ul class="plain">{"".join(lis)}</ul>{more}'
        lead = ""
    else:
        changes = ""
        lead = " No signal changed today." if run.get("tripwireChanges") is not None else ""
    t, total, w, ch_text, ne_text = escape_line_parts(run)
    es_more = f"; {ne_text}" if (run.get("escape") or {}).get("newEvidence") is not None else ""
    gl = []
    mv = moved_gauges(run, prev)
    for k in gauge_keys(run):
        g = run["gauges"][k] or {}
        floor = f" {FLOOR_CHIP}" if k == FLOOR_GAUGE else ""
        gl.append(f"{e(gauge_label(k))} {e(gauge_display(k, g))}{floor}")
    briefs = []
    for k in mv:
        g = run["gauges"][k] or {}
        pg = ((prev or {}).get("gauges") or {}).get(k) or {}
        b = str(g.get("brief") or "").strip()
        briefs.append(f'{e(gauge_label(k))}: {e(gauge_display(k, pg))} → {e(gauge_display(k, g))}' + (f". {e(b)}" if b else ""))
    gtail = (" " + " ".join(f"{x}." if not x.endswith(".") else x for x in briefs)) if briefs else \
        (" No gauge moved." if prev is not None else "")
    return f"""<section id="tripwires"><h2 class="rp-h2">Signals</h2>
    <p>{c['tripped']} confirmed (count toward Watch) · {c['watching']} open · {c['quiet']} quiet.{lead} <a href="{root}alarm.html#signals">All signals →</a></p>
    {changes}<p id="escape">Escape watch: {t} of {total} confirmed · {w} open · {e(ch_text)}{e(es_more)}. <a href="{root}escape.html">Escape watch →</a></p>
    <p id="gauges" class="small">{' · '.join(gl)}.{gtail}</p></section>"""


def tops_html(run, root, an):
    tops = top_items(run)[:TOP_SHOWN]
    lis = "".join(
        f'<li><span class="rdate">{e(item_date(it))}</span> {e(item_short(it))} {chip(it.get("rating"))}'
        f'{a(it.get("url"), source_name(it), root) if safe_url(it.get("url")) else ""} · <a href="{an}#roundup">more →</a></li>'
        for it in tops)
    n = all_items(run)
    return (f'<section id="roundup"><h2 class="rp-h2">Top stories</h2><ul class="plain hq-tops">{lis}</ul>'
            f'<p class="small"><a href="{an}#roundup">All {n} {"story" if n == 1 else "stories"}, with sources →</a></p></section>')


def dates_html(run, an):
    lis = "".join(f'<li><span class="when">{day(x["date"], False)}</span><span>{e(x["short"])}</span></li>'
                  for x in run.get("dates") or [] if re.match(r"^\d{4}-\d{2}-\d{2}", str(x.get("date") or "")))
    lst = f'<ul class="timeline-list">{lis}</ul>' if lis else ""
    return (f'<section id="s6"><h2 class="rp-h2">Dates to watch</h2>{lst}'
            f'<p class="small"><a href="{an}#s6">What would change our mind →</a></p></section>')


def short_html(run, prev, path, warns=None):
    from sitekit import page, subscribe_box
    d = run["date"]
    root = "../"
    an = f"{d}-analysis.html"
    al = run["alarm"]
    lvl = f'Level {int(al["level"])}' + (f' ({al["name"]})' if al.get("name") else "")
    mc_note = ""
    if method_boundary(run, prev):
        mc_note = (f'\n    <p class="small muted">Method change (definitions v{e(run_defs(run))}): the numbers that need an '
                   f'AGI-level system were re-derived; B doesn\'t need one. <a href="{root}changes.html#method">What changed →</a></p>')
    body = f"""<header class="rp-head"><p class="kicker muted small">Daily reading · {long_day(d)}</p>
  <h1 class="rp-h1">{e(run['verdict'])}</h1></header>
{subscribe_box()}{corrections_box(run, root, an)}
{method_banner(run, prev, root)}
{cards(run, prev, root, an, warns)}
{needle_html(run, root)}
<section id="s5"><h2 class="rp-h2">Probabilities</h2>
    {prob_table(run, prev)}{mc_note}
    <p class="small muted">How the "today" numbers are derived: <a href="{an}#s5">analysis, Step 5 →</a></p></section>
{signals_html(run, prev, root)}
<section id="timeline"><h2 class="rp-h2">Is AGI here, today?</h2><p>{e(run['timelineShort'])} <a href="{an}#timeline">Full reasoning →</a></p></section>
{tops_html(run, root, an)}
{dates_html(run, an)}
<section id="bottom"><p class="bottomline">{e(run['bottomLine'])}</p>
    <p><strong><a href="{an}">Full analysis: evidence, reasoning and every source →</a></strong></p></section>"""
    top = (f'<a href="{an}">Full analysis →</a><a href="#s5">Probabilities</a><a href="#tripwires">Signals</a>'
           f'<a href="#timeline">AGI</a><a href="#roundup">Top stories</a><a href="#s6">Dates</a>')
    return page(path=path, title=f"Hidden AGI watch · {short_day(d)}",
                description=f"Daily reading for {long_day(d)}: {run['verdict']}", body=body, og_type="article",
                og_image=f"{SITE}cards/{d}.png", og_image_alt=card_alt(run, lvl), main_class="report", nav_top=top)


def card_alt(run, lvl):
    return (f"Share card for {short_day(run['date'])}: Hidden AGI Index {fmt(run['index'])}% with the A–D probabilities, "
            f"the AGI parts and fire-alarm {lvl}")


# ---------- the analysis page (9.2) ----------

def analysis_html(run, body, path):
    from sitekit import page, subscribe_box
    d = run["date"]
    root = "../"
    al = run["alarm"]
    lvl = f'Level {int(al["level"])}' + (f' ({al["name"]})' if al.get("name") else "")
    cs = [c for c in run.get("corrections") or [] if isinstance(c, dict)]
    corr = ""
    if cs:
        corr = (f'\n<section id="corrections"><h2>{"Correction" if len(cs) == 1 else "Corrections"} in this reading</h2>'
                f'<ul class="plain">{"".join(correction_li(c, root) for c in newest_first(cs))}</ul>'
                f'<p class="small"><a href="{root}changes.html#corrections">The full corrections log →</a></p></section>')
    head = f"""<header class="rp-head"><p class="kicker muted small">Daily reading · {long_day(d)} · analysis</p>
  <h1 class="rp-h1">Analysis for {day(d)}</h1>
  <p class="small"><a href="{d}.html">← Today's report</a> · <a href="{root}start-here.html#method">How we rate evidence →</a></p></header>
{subscribe_box()}"""
    # .rp-body: on phones a wide table in the agent-written body scrolls inside itself, never the page (V3)
    page_body = f'{head}\n<div class="rp-body">\n{MARK_BEGIN}\n{body}{MARK_END}\n</div>{corr}'
    top = ('<a href="#alarm">Fire alarm</a><a href="#index">Index</a><a href="#gauges">Gauges</a>'
           '<a href="#tripwires">Signals</a><a href="#escape">Escape watch</a><a href="#agi">AGI parts</a>'
           '<a href="#timeline">Timeline</a><a href="#roundup">News</a><a href="#s1">Steps 1–6</a>'
           '<a href="#bottom">Bottom line</a>')
    return page(path=path, title=f"Hidden AGI watch · Analysis · {short_day(d)}",
                description=f"Analysis for {long_day(d)}: the evidence, reasoning and every source behind the daily "
                            f"reading. {run['verdict']}",
                body=page_body, og_type="article", og_image=f"{SITE}cards/{d}.png", og_image_alt=card_alt(run, lvl),
                main_class="report", nav_top=top)


# ---------- public API ----------

def _prose_words(html, extra=()):
    try:
        from checks import visible_words
    except Exception:  # pragma: no cover
        return None
    return visible_words(html, ("nav", "footer", "table", ".subscribe", ".sr-only") + tuple(extra))


_HREF = re.compile(r'href="([^"]*)"')


def _local_target(u, root, base):
    """(site-relative path, Path) for a link into the site, or None for an external, mailto or same-page link.
    `base` is the folder the link is written in, relative to the site root ('reports/' for the analysis body,
    '' for a site path in the data)."""
    u = (u or "").strip()
    if u.startswith(SITE):
        u, base = u[len(SITE):], ""
    if not u or u.startswith("#") or re.match(r"^[a-z][a-z0-9+.-]*:", u, re.I):
        return None
    if u.startswith("/"):   # a site-absolute path
        u, base = u.lstrip("/"), ""
    path = u.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return None
    from urllib.parse import unquote
    p = (Path(root) / base / unquote(path)).resolve()
    try:
        rel = p.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return ("../" + path, None)
    if p.is_dir():
        p, rel = p / "index.html", (rel + "/index.html").lstrip("/")
    return rel, p


def link_problems(run, body, root):
    """Relative links in the analysis body (written from reports/) and site links in the run's data whose file does
    not exist (M2): the dead-link class behind the two broken links in the frozen 2026-10-01 report. Only checked in
    a built site tree (one with index.html); the fragment is the smoke check's job (smoke.py --anchors-only)."""
    root = Path(root)
    if not (root / "index.html").is_file():
        return []
    own = {run.get("report"), run.get("analysis")}
    probs = []
    for u in sorted(set(unescape(m.group(1)) for m in _HREF.finditer(body or ""))):
        hit = _local_target(u, root, "reports/")
        if hit and hit[0] not in own and (hit[1] is None or not hit[1].exists()):
            probs.append(f'analysis body: href "{u}" points at {hit[0]}, which does not exist (the page lives in reports/: '
                         'link site pages as ../agi.html, other readings as 2026-10-05.html)')
    nd = run.get("needle") if isinstance(run.get("needle"), dict) else {}
    data = [("needle.url", nd.get("url"))] + [(f"roundup item {k + 1}.url", it.get("url")) for k, it in enumerate(top_items(run))]
    data += [(f"corrections[{k}].url", c.get("url")) for k, c in enumerate(run.get("corrections") or []) if isinstance(c, dict)]
    data += [(f"componentLeads[{k}].url", c.get("url")) for k, c in enumerate(run.get("componentLeads") or [])
             if isinstance(c, dict)]
    for where, u in data:
        hit = _local_target(safe_url(u) or "", root, "")
        if hit and hit[0] not in own and (hit[1] is None or not hit[1].exists()):
            probs.append(f'{where}: "{u}" points at {hit[0]}, which does not exist (site links in the data are written '
                         'from the site root, e.g. agi.html#breadth)')
    return probs


def _render(date, runs, body, root):
    """(short_html, analysis_html, warns). Reads only the run and the previous published run, plus the analysis
    body (given, or the one already between the markers of <root>/reports/<date>-analysis.html)."""
    i, run, prev = find(runs, date)
    warns = validate(run)
    if body is None:
        try:
            body = body_from_page((Path(root) / run["analysis"]).read_text(encoding="utf-8"))
        except OSError:
            body = None
        if body is None:
            raise ReportError(f"no analysis body: pass --body PATH (no {run['analysis']} with the analysis markers "
                              "to reuse)")
    clean, bw = clean_body(body)
    warns += bw
    bad = link_problems(run, clean, root)
    if bad:
        raise ReportError(bad[0] + (f" (and {len(bad) - 1} more)" if len(bad) > 1 else ""))
    short = short_html(run, prev, run["report"], warns)
    analysis = analysis_html(run, clean, run["analysis"])
    # The cap counts what the writer controls; the correction box (at most 5 entries, their text fixed by
    # data/corrections.json) counts toward the 700-word budget only, so a day of long corrections never exits 2 (m2).
    n = _prose_words(short)
    n_cap = _prose_words(short, (".rp-corr",))
    if n_cap is not None and n_cap > PROSE_MAX:
        raise ReportError(f"short report: {n_cap} words of prose outside the correction box (cap {PROSE_MAX}): shorten "
                          "verdict, needle.brief, timelineShort, bottomLine or the top-item shorts")
    if n is not None and n > PROSE_WARN:
        warns.append(f"short report: {n} words of prose (budget {PROSE_WARN})")
    return short, analysis, warns


def render(date, runs_path=None, body=None):
    """(short_html, analysis_html) for the reading dated `date` in runs_path (default data/runs.json). Writes nothing;
    WARN lines go to stderr; bad input raises ReportError (one line, naming the field, tag or line)."""
    runs = load_runs(runs_path)
    short, analysis, warns = _render(date, runs, body, root_for(runs_path))
    for w in warns:
        print("WARN  build_report: " + w, file=sys.stderr)
    return short, analysis


def furthest_part(doc):
    """Among Far parts, the lowest best-result-to-bar ratio on the headline's own scale (pages.common.furthest)."""
    try:
        from pages import common
        if callable(getattr(common, "furthest", None)):
            return common.furthest(doc)
    except Exception:
        pass
    far = [c for c in doc.get("components") or [] if isinstance(c, dict) and c.get("status") == "far"]

    def ratio(c):
        h = c.get("headline") or {}
        lo = float(h.get("min") or 0)
        return (float(h["value"]) - lo) / (float(h["target"]) - lo)
    far = [c for c in far if is_num((c.get("headline") or {}).get("value")) and is_num((c.get("headline") or {}).get("target"))]
    return min(far, key=ratio) if far else None


def snapshot(date, runs_path=None):
    """The 8.2 snapshot fields for the reading dated `date`, from the live files of the runs file's tree:
    components {id: {status, short, glance, basisShort}}, furthest, dates (next 3 dated events after the date) and
    alarm.{since, icon, status, name}. Writes nothing."""
    root = root_for(runs_path)
    runs = load_runs(runs_path)
    _, run, _ = find(runs, date)

    def load(rel):
        try:
            return json.loads((root / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as x:
            raise ReportError(f"{rel}: {x}")
    comp = load("data/agi_components.json")
    by_id = {c.get("id"): c for c in comp.get("components") or [] if isinstance(c, dict)}
    missing = [cid for cid in COMPONENT_IDS if cid not in by_id]
    if missing:
        raise ReportError(f"data/agi_components.json: no component {', '.join(missing)}")
    components = {cid: {k: by_id[cid].get(k) for k in ("status", "short", "glance", "basisShort")} for cid in COMPONENT_IDS}
    f = furthest_part(comp)
    furthest = None
    if f:
        h = f.get("headline") or {}
        furthest = {"id": f["id"], "short": f.get("short"), "display": h.get("display"),
                    "targetDisplay": h.get("targetDisplay")}
    cal = load("data/calendar.json")
    evs = sorted((x for x in cal.get("events") or [] if isinstance(x, dict)
                  and re.match(r"^\d{4}-\d{2}-\d{2}$", str(x.get("date") or "")) and x["date"] > date),
                 key=lambda x: x["date"])
    try:
        fcs = json.loads((root / "data/forecasts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fcs = None
    dates = [{"date": x["date"], "short": event_short(x, fcs)} for x in next_dates(evs)]
    al = load("data/alarm.json")
    run_alarm = run.get("alarm") if isinstance(run.get("alarm"), dict) else {}
    lvl = run_alarm.get("level", (al.get("current") or {}).get("level"))
    ldef = next((x for x in al.get("levels") or [] if x.get("level") == lvl), None)
    if ldef is None:
        raise ReportError(f"alarm.level {json.dumps(lvl)}: no such level in data/alarm.json")
    cur = al.get("current") or {}
    since = cur.get("since") if cur.get("level") == lvl else None
    if since is None:
        past = [h for h in al.get("history") or [] if h.get("to") == lvl and str(h.get("date", "")) <= date]
        since = past[-1]["date"] if past else None
    alarm = {"since": since, "icon": ldef.get("icon"), "status": ldef.get("status"), "name": ldef.get("name")}
    return {"components": components, "furthest": furthest, "dates": dates, "alarm": alarm}


def write_snapshot(date, runs_path=None):
    """Write the snapshot fields into the reading's runs.json entry; nothing else in the file changes."""
    p = Path(runs_path) if runs_path else ROOT / "data/runs.json"
    text = p.read_text(encoding="utf-8")
    runs = json.loads(text)
    snap = snapshot(date, str(p))
    i, run, _ = find(runs, date)
    canonical = json.dumps(runs, indent=1, ensure_ascii=False) + "\n" == text
    run["components"], run["furthest"], run["dates"] = snap["components"], snap["furthest"], snap["dates"]
    if not isinstance(run.get("alarm"), dict):
        run["alarm"] = {}
    run["alarm"].update(snap["alarm"])
    atomic_write(p, json.dumps(runs, indent=1, ensure_ascii=False) + "\n")
    warns = [] if canonical else [f"{p.name} was not in its usual layout (indent 1); it was rewritten in it"]
    return snap, warns


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def shell(html):
    if MARK_BEGIN in html and MARK_END in html:
        return html.split(MARK_BEGIN, 1)[0] + MARK_END + html.split(MARK_END, 1)[1]
    return html


def first_diff(disk, new):
    al, bl = disk.splitlines(), new.splitlines()
    for j, (x, y) in enumerate(zip(al, bl)):
        if x != y:
            return f"line {j + 1}:\n  on disk:  {x[:160]}\n  rendered: {y[:160]}"
    return f"line {min(len(al), len(bl)) + 1}: lengths differ ({len(al)} lines on disk, {len(bl)} rendered)"


# ---------- CLI ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Render reports/<date>.html and reports/<date>-analysis.html from a "
                                             "format-2 reading.")
    ap.add_argument("--date", help="the reading's date (YYYY-MM-DD); the newest reading unless --out is given")
    ap.add_argument("--body", help="the analysis body fragment to wrap (absolute or relative path)")
    ap.add_argument("--check", action="store_true", help="render in memory and compare with the files on disk")
    ap.add_argument("--out", help="write under DIR/reports/ instead of the repo (rehearsal, tests)")
    ap.add_argument("--runs", help="read the runs from PATH instead of data/runs.json")
    ap.add_argument("--snapshot", metavar="DATE", help="copy the snapshot fields from the live files into DATE's entry")
    args = ap.parse_args(argv)
    try:
        if args.snapshot:
            snap, warns = write_snapshot(args.snapshot, args.runs)
            for w in warns:
                print("WARN  " + w)
            print(f"snapshot for {args.snapshot}: components (" + ", ".join(
                f"{k} {v['status']}" for k, v in snap["components"].items()) + f"); furthest "
                f"{(snap['furthest'] or {}).get('id')}; {len(snap['dates'])} dates; alarm since {snap['alarm']['since']}")
            if not args.date:
                return 0
        if not args.date:
            ap.error("--date is required (or --snapshot)")
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            raise ReportError(f"--date {args.date!r}: expected YYYY-MM-DD")
        runs = load_runs(args.runs)
        if args.date != newest_date(runs) and not args.out and not args.check:
            raise ReportError(f"{args.date} is not the newest reading ({newest_date(runs)}): past reports are frozen "
                              "(use --out DIR to render a copy elsewhere)", code=3)
        body = None
        if args.body:
            try:
                body = Path(args.body).read_text(encoding="utf-8")
            except OSError as x:
                raise ReportError(f"--body {args.body}: {x}")
        out_root = Path(args.out) if args.out else root_for(args.runs)
        _, run, _ = find(runs, args.date)
        if body is None and args.out:  # reuse the body from the copy under --out first, then the tree's
            try:
                body = body_from_page((out_root / run.get("analysis", "")).read_text(encoding="utf-8"))
            except OSError:
                body = None
        short, analysis, warns = _render(args.date, runs, body, root_for(args.runs))
        for w in warns:
            print("WARN  " + w)
        sp, apath = out_root / run["report"], out_root / run["analysis"]
        if args.check:
            bad = []
            try:
                disk = sp.read_text(encoding="utf-8")
                if disk != short:
                    bad.append(f"{run['report']} differs from its render, {first_diff(disk, short)}")
            except OSError:
                bad.append(f"{run['report']} does not exist")
            try:
                disk = apath.read_text(encoding="utf-8")
                if shell(disk) != shell(analysis):
                    bad.append(f"{run['analysis']}: the shell around the body differs, "
                               f"{first_diff(shell(disk), shell(analysis))}")
            except OSError:
                bad.append(f"{run['analysis']} does not exist")
            if bad:
                for b in bad:
                    print("ERROR " + b)
                print("Edited by hand, or the run changed after rendering: re-run build_report.py --date " + args.date)
                return 1
            print(f"check: {run['report']} and {run['analysis']} match their render")
            return 0
        atomic_write(sp, short)
        atomic_write(apath, analysis)
        print(f"wrote {sp if args.out else run['report']} and {apath if args.out else run['analysis']}")
        return 0
    except ReportError as x:
        print(f"ERROR build_report: {x}", file=sys.stderr)
        return x.code


if __name__ == "__main__":
    sys.exit(main())
