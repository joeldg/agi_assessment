"""Definitions in force, the method-change boundary and data/method.json (spec 8.3, 9.4, 10.1, 11).

ERROR rules:
  - a run with `defs` or `format` has defs == defs_in_force(method, run.date);
  - every run dated after a definitions entry has `defs` and `format: 2`;
  - `methodChange` sits on exactly the runs whose definitions in force differ from the previous published
    run's `defs` (missing = "1.0"), with matching from/to; same-day entries collapse to the last (defs_in_force);
  - on such a run, a "Method change" line in `changes` names every moved number among agi, A, C, D, D-open;
  - on the newest such run, each "Change today" cell of the short report's #s5 table agrees with the changes
    lines: "method change" for a number the definition moved, "news; then method change" when a news line also
    moved it, never "method change" for B (B needs no AGI);
  - method.json: changelog append-only vs HEAD; top-level version = the highest entry version; a definitions
    entry has a string `definitions`, `definitionText` equal to agi_components.definition.text and factors in (0, 1].

news_moved(run, key) and METHOD_LINE are the one rule for "a news line also moved this number"; build_report.py
and build_feed.py may import them so the cells and this check never disagree.
"""
import re
from html import unescape

from . import (HYP_KEYS, definitions_entries, defs_in_force, is_num, iso, outline, prev_published, run_defs,
               version_tuple)

HORIZONS = ["now", "y2030", "y2035"]
METHOD_KEYS = ["agi", "A", "C", "D", "Dopen"]  # the numbers that need an AGI-level system
METHOD_LINE = re.compile(r"^\s*method change\b", re.I)
# How a changes line names each number: the letter used as a name (not the article "A", not the D in "R&D"),
# the v2 display name, or the field name.
_AS_NAME = r"(?=\s*(?:\([^)]*\)\s*)?(?:[:=,/;.)▲▼]|\d|$|\b(?:and|or|go|goes|went|rise|rises|rose|fall|falls|fell|" \
           r"move|moves|moved|is|was|are|stay|stays|stayed|hold|holds|held|from|now|today|up|down|at)\b))"
NAMES = {
    "agi": r"\bAGI anywhere\b|\bAGI exists\b|\bstrict AGI\b|\bagi\b",
    "A": r"(?<![\w&.-])A\b" + _AS_NAME + r"|\bHidden AGI\b(?! Index| watch)",
    "B": r"(?<![\w&.-])B\b" + _AS_NAME + r"|\bHidden self-improvement\b",
    "C": r"(?<![\w&.-])C\b" + _AS_NAME + r"|\bCovert AGI actor\b",
    "D": r"(?<![\w&.-])D\b(?!-open)" + _AS_NAME + r"|\bCovert government influence\b",
    "Dopen": r"\bD-open\b|\bDopen\b|\bOpen government influence\b",
}
# A news line "moves" a number when it gives a from-to pair: "from 1% to 1.5%", "1% → 1.5%", "▲ +0.5".
MOVE = re.compile(r"\d(?:\.\d+)?\s*%?\s*(?:to|→|->)\s*\d|[▲▼]\s*[+−-]?\s*\d|\b(?:up|down|rises?|falls?|rose|fell)\b"
                  r"[^.;]{0,30}?\d", re.I)
ROW_LABELS = [("Dopen", r"^\s*D-open\b|^\s*Open government influence"), ("agi", r"^\s*AGI anywhere"),
              ("A", r"^\s*A\b"), ("B", r"^\s*B\b"), ("C", r"^\s*C\b"), ("D", r"^\s*D\b")]


def names(key, text):
    return bool(re.search(NAMES[key], text or ""))


def change_lines(run):
    return [s for s in run.get("changes") or [] if isinstance(s, str)]


def news_moved(run, key):
    """True when a changes line that isn't a "Method change" line names `key` and states a move."""
    for line in change_lines(run):
        if not METHOD_LINE.match(line) and names(key, line) and MOVE.search(line):
            return True
    return False


def method_named(run, key):
    return any(METHOD_LINE.match(line) and names(key, line) for line in change_lines(run))


def series(run, key):
    s = run.get("agi") if key == "agi" else (run.get("probs") or {}).get(key)
    return s if isinstance(s, dict) else {}


def moved(run, prev, key):
    a, b = series(prev, key), series(run, key)
    return any(is_num(a.get(h)) and is_num(b.get(h)) and a[h] != b[h] for h in HORIZONS)


def label(k):
    return "D-open" if k == "Dopen" else k


# ---------- runs ----------

def check_run_defs(ctx, p, r, want, first):
    """defs is the definitions in force; every run after a definitions entry is format 2 with defs."""
    f, js, d = ctx.f, ctx.js, r["date"]
    if "defs" in r or "format" in r:
        if run_defs(r) != want or not isinstance(r.get("defs"), str):
            f.err("%s.defs=%s but the definitions in force on %s are %s (data/method.json: the last definitions "
                  "entry dated before the run)" % (p, js(r.get("defs")), d, js(want)))
        if "format" in r and r.get("format") != 2:
            f.err("%s.format=%s: the only format is 2 (rendered by build_report.py)" % (p, js(r.get("format"))))
    if first and d > first and r.get("report") and (r.get("format") != 2 or "defs" not in r):
        f.err("%s (%s) is dated after the definitions entry of %s, so it needs defs and format 2 (it has defs=%s, "
              "format=%s)" % (p, d, first, js(r.get("defs")), js(r.get("format"))))


def check_method_change(ctx, p, r, want, prev):
    """methodChange sits on exactly the first reading under new definitions, and its moved numbers say so."""
    f, js, d = ctx.f, ctx.js, r["date"]
    before = run_defs(prev) if prev else "1.0"
    mc = r.get("methodChange")
    if want == before:
        if mc is not None:
            f.err("%s.methodChange is set but the definitions in force (%s) equal the previous published run's (%s); "
                  "only the first reading after a definitions entry carries it" % (p, want, before))
        return
    if not isinstance(mc, dict):
        f.err("%s (%s) is the first reading under definitions %s (the previous published run used %s) and needs "
              "methodChange {from: %s, to: %s, note}" % (p, d, want, before, js(before), js(want)))
    elif str(mc.get("from")) != before or str(mc.get("to")) != want:
        f.err("%s.methodChange=%s should say from %s to %s" % (
            p, js({k: mc.get(k) for k in ("from", "to")}), js(before), js(want)))
    elif not isinstance(mc.get("note"), str) or not mc["note"].strip():
        f.err("%s.methodChange.note is missing" % p)
    for k in METHOD_KEYS if prev else []:
        if moved(r, prev, k) and not method_named(r, k):
            f.err("%s (%s): %s moved from the %s reading but no changes line starting \"Method change "
                  "(definitions v%s):\" names it; a number moved by the definition is a method change, never news" % (
                      p, d, label(k), prev.get("date"), want))


def check_runs(ctx, runs, method):
    entries = definitions_entries(method)
    first = min((e["date"] for e in entries if isinstance(e.get("date"), str)), default=None)
    for i, r in enumerate(runs):
        if not isinstance(r, dict) or not isinstance(r.get("date"), str):
            continue
        p, want = "runs[%d]" % i, defs_in_force(method, r["date"])
        check_run_defs(ctx, p, r, want, first)
        if r.get("report"):
            check_method_change(ctx, p, r, want, prev_published(runs, i))


def check_cells(ctx, runs, latest):
    """The newest boundary run's short report: each "Change today" cell agrees with the changes lines (ED-23)."""
    f = ctx.f
    if latest is None:
        return
    r = runs[latest]
    if not isinstance(r, dict) or r.get("format") != 2 or not isinstance(r.get("methodChange"), dict):
        return
    rel = r.get("report")
    html = ctx.read(rel) if isinstance(rel, str) else None
    if html is None:
        return  # reports_v2 / check_report say the report is missing
    rows = outline(html, ["#s5"]).rows.get("#s5") or []
    header = next((row for row in rows if any("change today" in c.lower() for c in row)), None)
    if header is None:
        f.err("%s: the #s5 table has no \"Change today\" column" % rel)
        return
    col = next(j for j, c in enumerate(header) if "change today" in c.lower())
    prev = prev_published(runs, latest)
    seen = set()
    for row in rows:
        if row is header or len(row) <= col:
            continue
        key = next((k for k, pat in ROW_LABELS if re.search(pat, row[0])), None)
        if key is None or key in seen:
            continue
        seen.add(key)
        cell = row[col].lower()
        has_method, has_news = "method change" in cell, "news" in cell
        where = "%s #s5 %s \"Change today\"=%s" % (rel, label(key), ctx.js(row[col]))
        if key == "B":
            if has_method:
                f.err("%s: B needs no AGI-level system, so a definitions change never moves it" % where)
            continue
        news = news_moved(r, key)
        if prev is not None and moved(r, prev, key) and not has_method:
            f.err("%s: the number moved on the method-change day, so the cell must say \"method change\"" % where)
        if news and not (has_news and has_method and cell.index("news") < cell.index("method change")):
            f.err("%s: a news line also moves %s, so the cell must read \"… news; then method change\"" % (
                where, label(key)))
        if has_news and not news:
            f.err("%s: the cell credits news but no changes line (other than \"Method change\" lines) moves %s" % (
                where, label(key)))
    missing = [label(k) for k in ["agi"] + HYP_KEYS if k not in seen]
    if missing:
        f.err("%s: the #s5 table has no row for %s" % (rel, ", ".join(missing)))
    # The Index (card 2, "Hidden AGI Index, {delta}") is re-derived from its parts on the boundary run, so it reads
    # "method change" whatever the changes lines say: one rule with build_report.change_cell and
    # pages.common.delta_text, so a line about another index (the Remote Labor Index) can't turn it into news (M3).
    m = re.search(r'id="index"[^>]*>.*?<p class="hq-a">(.*?)</p>', html, re.S)
    if m:
        cell = " ".join(unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split())
        if "method change" not in cell.lower() or "news" in cell.lower():
            f.err("%s card \"Could it be hidden?\" reads %s: on the first reading under new definitions the Hidden AGI "
                  "Index shows \"method change\", never a news move" % (rel, ctx.js(cell)))


# ---------- method.json ----------

def check_versions(ctx, method, log):
    f, js = ctx.f, ctx.js
    if ctx.git.ok:
        head = ctx.git.show_json("data/method.json")
        if isinstance(head, dict) and isinstance(head.get("changelog"), list):
            ctx.append_only(f, "method.changelog", head["changelog"], log)
    versions = [version_tuple(e.get("version")) for e in log if isinstance(e, dict)]
    if any(v is None for v in versions):
        f.err("method.changelog: every entry needs a numeric version such as \"2.0\"")
    versions = [v for v in versions if v is not None]
    if versions and version_tuple(method.get("version")) != max(versions):
        f.err("method.version=%s but the highest changelog version is %s" % (
            js(method.get("version")), ".".join(map(str, max(versions)))))
    prev = None
    for i, e in enumerate(log):
        d = iso(e.get("date")) if isinstance(e, dict) else None
        if d is None:
            f.err("method.changelog[%d].date=%s is not YYYY-MM-DD" % (
                i, js(e.get("date") if isinstance(e, dict) else e)))
        elif prev and d < prev:
            f.warn("method.changelog[%d].date=%s is earlier than the entry before it; definitions in force follow "
                   "list order" % (i, js(e.get("date"))))
        prev = d or prev


def check_definitions_entry(ctx, p, e, components):
    """A definitions entry states the definition word for word (as agi_components.json does) and its factors."""
    f, js = ctx.f, ctx.js
    if not isinstance(e.get("definitions"), str) or version_tuple(e["definitions"]) is None:
        f.err("%s.definitions=%s must be a version string such as \"2.0\"" % (p, js(e.get("definitions"))))
    if e.get("definitions") == "1.0":
        return  # a withdrawal back to v1.0 carries no new text or factors
    text = e.get("definitionText")
    cur = components.get("definition") if isinstance(components, dict) else None
    if not isinstance(text, str) or not text.strip():
        f.err("%s (definitions %s) has no definitionText" % (p, js(e.get("definitions"))))
    elif isinstance(cur, dict) and e.get("definitions") == components.get("definitionsVersion") \
            and text != cur.get("text"):
        f.err("%s.definitionText differs from agi_components.definition.text; the definition is stated once, word "
              "for word" % p)
    fac = e.get("factors")
    if not isinstance(fac, dict):
        f.err("%s.factors must be {now, y2030, y2035}" % p)
        return
    for h in HORIZONS:
        if not is_num(fac.get(h)) or not 0 < fac[h] <= 1:
            f.err("%s.factors.%s=%s must be a number in (0, 1]" % (p, h, js(fac.get(h))))


def check_method_file(ctx, method, components):
    if not isinstance(method, dict):
        return
    log = method.get("changelog")
    if not isinstance(log, list):
        ctx.f.err("method.changelog must be a list")
        return
    check_versions(ctx, method, log)
    for i, e in enumerate(log):
        if isinstance(e, dict) and "definitions" in e:
            check_definitions_entry(ctx, "method.changelog[%d]" % i, e, components)


def check(ctx, runs, latest):
    method = ctx.data.get("data/method.json")
    components = ctx.data.get("data/agi_components.json")
    check_method_file(ctx, method, components)
    if isinstance(runs, list):
        check_runs(ctx, runs, method if isinstance(method, dict) else {})
        check_cells(ctx, runs, latest)
