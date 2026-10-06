"""The newest format-2 run, its short report and its analysis page (spec 8.2, 9.1–9.3, 11).

ERROR: the run's structural fields (analysis path, indexParts on the grid, the components snapshot, the shapes of
tripwireChanges and escape.changes/newEvidence, the needle's brief/rating/url, the top items' short and rating,
verdict/timelineShort/bottomLine); the short report's ids, correction box (at most 5) and 1,000-word prose cap; the
analysis page's subscribe boxes, head tags, required ids in order, markers and full correction list; and, inside
the daily's window only, build_report.render() reproducing the files on disk (the short report byte for byte,
the analysis shell, and the analysis body as build_report cleans it), a render that fails, and a missing
build_report.py.
WARN: field budgets, top items outside 3–6, the components snapshot differing from the live file (a Friday status
change after the morning run is legitimate), prose over 700 words, fact tags without a link or with a hedge word on
the analysis page, and a committed report that no longer matches its render.
"""
import contextlib
import io
import json
import re

from . import (ANALYSIS_IDS, COMPONENT_IDS, MARK_BEGIN, MARK_END, RATINGS, SCALE_KEYS, SHORT_IDS, is_num, outline,
               round_grid, run_defs, visible_words, words)

SITE = "https://hiddenagi.com/"
INDEX_KEYS = ("A", "B", "CD")
CORRECTIONS_SHOWN = 5
PROSE_WARN, PROSE_MAX = 700, 1000
FIELD_BUDGETS = [("verdict", 30), ("needle.brief", 100), ("timelineShort", 40), ("bottomLine", 60)]
HEDGES = ["reportedly", "leaked", "draft", "according to", "likely"]
PROSE_SKIP = ("nav", "footer", "table", ".subscribe", ".sr-only")
# Retired display words (spec 3.1, NAMES) that the agent-written analysis body must not carry on a format-2 reading.
OLD_WORDS = re.compile(r"\bWatching\b|\bTripped\b|\bTripwires\b|Observed · feeds|Feeds hypothesis|\bLevel \d of 5\b|"
                       r"\bstrict AGI\b|\bsecret RSI\b", re.I)


def rating_base(r):
    """The rating word of a rating field, without a qualifier in parentheses: "verified fact (part our inference)"
    -> "verified fact" (build_report.split_rating renders the qualifier after the chip). None when it isn't one of
    the six words."""
    s = str(r or "").strip()
    low = s.lower()
    for base in sorted(RATINGS, key=len, reverse=True):
        if low == base or (low.startswith(base) and re.match(r"^\s*\(.+\)\s*$", s[len(base):])):
            return base
    return None
SNAP_KEYS = ("status", "short", "glance", "basisShort")


def canon(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def get(run, dotted):
    cur = run
    for k in dotted.split("."):
        cur = cur.get(k) if isinstance(cur, dict) else None
    return cur


def top_items(run):
    out = []
    for i, sec in enumerate(run.get("roundup") or []):
        for j, it in enumerate(sec.get("items") or [] if isinstance(sec, dict) else []):
            if isinstance(it, dict) and it.get("top") is True:
                out.append(("roundup[%d].items[%d]" % (i, j), it))
    return out


# ---------- the run ----------

def objects(ctx, where, items, fields):
    """A list of objects that each carry `fields`; ERROR naming the first slip, as build_report.py exits 2 on it."""
    if not isinstance(items, list):
        ctx.f.err("%s must be a list of {%s}" % (where, ", ".join(fields)))
        return []
    for j, x in enumerate(items):
        if not isinstance(x, dict) or not all(k in x for k in fields):
            ctx.f.err("%s[%d]: expected an object with %s; got %s" % (
                where, j, ", ".join(fields), "a string" if isinstance(x, str) else ctx.js(x)))
    return [x for x in items if isinstance(x, dict)]


def check_basics(ctx, p, r):
    f, js, d = ctx.f, ctx.js, r.get("date")
    want = "reports/%s-analysis.html" % d
    if r.get("analysis") != want:
        f.err("%s.analysis=%s should be %s" % (p, js(r.get("analysis")), want))
    elif not (ctx.root / want).is_file():
        f.err("%s.analysis=%s does not exist; run scripts/build_report.py --date %s" % (p, js(want), d))
    for k in ("verdict", "timelineShort", "bottomLine"):
        if not isinstance(r.get(k), str) or not r[k].strip():
            f.err("%s.%s is required on a format-2 run" % (p, k))


def check_index_parts(ctx, p, r):
    f, js, parts = ctx.f, ctx.js, r.get("indexParts")
    if not isinstance(parts, list) or not parts:
        f.err("%s.indexParts must be a list of {key: A|B|CD, v}" % p)
        return
    good = [x for x in parts if isinstance(x, dict) and x.get("key") in INDEX_KEYS and is_num(x.get("v"))]
    for j, x in enumerate(parts):
        if x not in good:
            f.err("%s.indexParts[%d]=%s: expected {key: A|B|CD, v: number}" % (p, j, js(x)))
        elif abs(x["v"] * 20 - round(x["v"] * 20)) > 1e-6:
            f.warn("%s.indexParts[%d].v=%s is not rounded to the nearest 0.05" % (p, j, x["v"]))
    keys = [x["key"] for x in good]
    if len(set(keys)) != len(keys):
        f.err("%s.indexParts repeats a key: %s" % (p, js(keys)))
    total, idx = round(sum(x["v"] for x in good), 6), r.get("index")
    if len(good) == len(parts) and is_num(idx) and abs(round_grid(total) - idx) > 1e-9:
        f.err("%s.indexParts sum to %s, which rounds to %s on our grid, but index=%s" % (
            p, round(total, 4), round_grid(total), idx))


def check_snapshot(ctx, p, r):
    f, js, snap = ctx.f, ctx.js, r.get("components")
    if not isinstance(snap, dict) or sorted(snap) != sorted(COMPONENT_IDS):
        f.err("%s.components must be the snapshot of the 8 parts (%s); run build_report.py --snapshot %s" % (
            p, ", ".join(COMPONENT_IDS), r.get("date")))
        return
    for cid in COMPONENT_IDS:
        s = snap[cid]
        if not isinstance(s, dict) or s.get("status") not in SCALE_KEYS or not all(
                isinstance(s.get(k), str) for k in ("short", "glance")):
            f.err("%s.components.%s=%s: expected {status (far|partial|close|met), short, glance}" % (p, cid, js(s)))
    live = ctx.data.get("data/agi_components.json")
    now = {c.get("id"): c for c in live.get("components") or [] if isinstance(c, dict)} if isinstance(live, dict) \
        else {}
    diff = [cid for cid in COMPONENT_IDS if isinstance(snap.get(cid), dict) and cid in now and any(
        canon(snap[cid][k]) != canon(now[cid].get(k)) for k in SNAP_KEYS if k in snap[cid])]
    if diff:
        f.warn("%s.components snapshot differs from data/agi_components.json for %s (fine after a Friday status "
               "change; the morning's report keeps what readers saw)" % (p, ", ".join(diff)))


def check_changes(ctx, p, r):
    """tripwireChanges and escape.changes/newEvidence: one name and one shape from the decision to the run (M9)."""
    f, js = ctx.f, ctx.js
    if r.get("tripwireChanges") is None:
        f.warn("%s.tripwireChanges is missing (the report leaves the line out)" % p)
    else:
        for j, x in enumerate(objects(ctx, p + ".tripwireChanges", r["tripwireChanges"], ("id", "from", "to", "why"))):
            if words(x.get("why")) > 25:
                f.warn("%s.tripwireChanges[%d].why is %d words (budget 25)" % (p, j, words(x.get("why"))))
    esc = r.get("escape") if isinstance(r.get("escape"), dict) else {}
    if esc.get("changes") is not None:
        objects(ctx, p + ".escape.changes", esc["changes"], ("key", "from", "to", "reason"))
    ne = esc.get("newEvidence")
    if ne is None:
        return
    if not isinstance(ne, list) or not all(isinstance(x, str) for x in ne):
        f.err("%s.escape.newEvidence must be a list of indicator keys" % p)
        return
    edoc = ctx.data.get("data/escape.json")
    keys = {i.get("key") for i in edoc.get("indicators") or [] if isinstance(i, dict)} if isinstance(edoc, dict) \
        else set()
    unknown = [x for x in ne if keys and x not in keys]
    if unknown:
        f.err("%s.escape.newEvidence names %s, which are not Escape watch indicator keys" % (p, js(unknown)))


def check_needle_and_tops(ctx, p, r):
    f, js = ctx.f, ctx.js
    nd = r.get("needle") if isinstance(r.get("needle"), dict) else {}
    for k in ("brief", "url"):
        if not isinstance(nd.get(k), str) or not nd[k].strip():
            f.err("%s.needle.%s is required on a format-2 run" % (p, k))
    if rating_base(nd.get("rating")) is None:
        f.err("%s.needle.rating=%s must be one of: %s (optionally with a short qualifier in parentheses)" % (
            p, js(nd.get("rating")), ", ".join(sorted(RATINGS))))
    if not isinstance(nd.get("source"), str) or not nd["source"].strip():
        f.warn("%s.needle.source is missing (the link is named \"source\")" % p)
    tops = top_items(r)
    if not tops:
        f.err("%s.roundup has no top: true item" % p)
    elif not 3 <= len(tops) <= 6:
        f.warn("%s.roundup has %d top items (3–6; the report shows the first 6)" % (p, len(tops)))
    for ip, it in tops:
        if not isinstance(it.get("short"), str) or not it["short"].strip():
            f.err("%s.%s is a top item without a short" % (p, ip))
        elif words(it["short"]) > 25:
            f.warn("%s.%s.short is %d words (budget 25)" % (p, ip, words(it["short"])))
        if rating_base(it.get("rating")) is None:
            f.err("%s.%s.rating=%s: a top item needs a rating from the six-word set" % (p, ip, js(it.get("rating"))))


def check_budgets(ctx, p, r):
    f = ctx.f
    for k, lim in FIELD_BUDGETS:
        n = words(get(r, k))
        if n > lim:
            f.warn("%s.%s is %d words (budget %d)" % (p, k, n, lim))
    for k, g in (r.get("gauges") or {}).items():
        if isinstance(g, dict) and words(g.get("brief")) > 20:
            f.warn("%s.gauges.%s.brief is %d words (budget 20)" % (p, k, words(g.get("brief"))))
    if re.search(r"\bLevel \d of \d\b", str(get(r, "gauges.delegation.display") or "")):
        f.warn("%s.gauges.delegation.display=%s: delegation is read in rungs (\"rung 3 of 5\"); \"Level\" is the fire "
               "alarm's word" % (p, ctx.js(get(r, "gauges.delegation.display"))))
    if r.get("dates") is None:
        f.warn("%s.dates snapshot is missing (run build_report.py --snapshot %s)" % (p, r.get("date")))
    for j, x in enumerate(r.get("dates") or []):
        if isinstance(x, dict) and words(x.get("short")) > 14:
            f.warn("%s.dates[%d].short is %d words (budget 14)" % (p, j, words(x.get("short"))))


def check_run(ctx, p, r):
    check_basics(ctx, p, r)
    check_index_parts(ctx, p, r)
    check_snapshot(ctx, p, r)
    check_changes(ctx, p, r)
    check_needle_and_tops(ctx, p, r)
    check_budgets(ctx, p, r)


# ---------- the pages ----------

def head_tags(f, js, rel, o, own, card):
    for label, value, suffix in (("og:image", o.meta.get("og:image"), card), ("og:url", o.meta.get("og:url"), own),
                                 ("canonical", o.canonical, own)):
        if not value:
            f.err("%s: no %s" % (rel, label))
        elif not value.endswith(suffix):
            f.err("%s: %s=%s should point at %s" % (rel, label, js(value), suffix))
        elif not value.startswith(SITE):
            f.warn("%s: %s=%s is not an absolute %s URL" % (rel, label, js(value), SITE))


def check_short(ctx, r):
    f, rel = ctx.f, r.get("report")
    html = ctx.read(rel) if isinstance(rel, str) else None
    if html is None:
        return  # check_report says it's missing
    o = outline(html, [".rp-corr"])
    missing = [i for i in SHORT_IDS if i not in o.ids]
    if missing:
        f.err("%s: missing the ids %s (frozen links land on them)" % (rel, ", ".join("#" + i for i in missing)))
    corr = r.get("corrections") or []
    if corr:
        an = "%s-analysis.html#corrections" % r.get("date")
        if ".rp-corr" not in o.li:
            f.err("%s: the run carries %d correction(s) but the page has no correction box (class rp-corr); "
                  "re-run build_report.py --date %s" % (rel, len(corr), r.get("date")))
        elif o.li[".rp-corr"] > CORRECTIONS_SHOWN:
            f.err("%s: the correction box lists %d corrections; it shows at most %d and links the rest" % (
                rel, o.li[".rp-corr"], CORRECTIONS_SHOWN))
        elif len(corr) > o.li[".rp-corr"] and 'href="%s"' % an not in html:
            f.err("%s: the correction box shows %d of the run's %d corrections but doesn't link the rest (%s)" % (
                rel, o.li[".rp-corr"], len(corr), an))
    n = visible_words(html, PROSE_SKIP)
    n_cap = visible_words(html, PROSE_SKIP + (".rp-corr",))   # the correction box counts toward the budget only (m2)
    if n_cap > PROSE_MAX:
        f.err("%s: %d words of prose (outside tables, nav, footer, subscribe boxes and the correction box); the cap is "
              "%d" % (rel, n_cap, PROSE_MAX))
    elif n > PROSE_WARN:
        f.warn("%s: %d words of prose; the budget is %d" % (rel, n, PROSE_WARN))


def check_analysis(ctx, r):
    f, js, d = ctx.f, ctx.js, r.get("date")
    rel = "reports/%s-analysis.html" % d
    html = ctx.read(rel)
    if html is None:
        return  # check_run says it's missing
    o = outline(html, ["#corrections"])
    if o.subscribe != 2:
        f.err("%s: %d subscribe boxes; every report page needs exactly two (after the header and before the "
              "footer)" % (rel, o.subscribe))
    head_tags(f, js, rel, o, rel, "cards/%s.png" % d)
    pos = []
    for i in ANALYSIS_IDS:
        n = o.ids.count(i)
        if n != 1:
            f.err("%s: id %s appears %d times; the analysis needs it exactly once" % (rel, js(i), n))
        else:
            pos.append((o.ids.index(i), i))
    order = [i for _, i in sorted(pos)]
    want = [i for i in ANALYSIS_IDS if i in order]
    if order != want:
        f.err("%s: the sections are out of order (%s); the order is %s" % (rel, " ".join(order), " ".join(want)))
    b, e = MARK_BEGIN[4:-3].strip(), MARK_END[4:-3].strip()
    if o.comments.count(b) != 1 or o.comments.count(e) != 1 or o.comments.index(b) > o.comments.index(e):
        f.err("%s: needs one %s and one %s marker around the body, in that order" % (rel, MARK_BEGIN, MARK_END))
    corr = r.get("corrections") or []
    if corr:
        got = o.li.get("#corrections")
        if got is None:
            f.err("%s: the run carries %d corrections but the page has no #corrections section" % (rel, len(corr)))
        elif got < len(corr):
            f.err("%s: #corrections lists %d of the run's %d corrections; the analysis lists them all" % (
                rel, got, len(corr)))
    body = html.split(MARK_BEGIN, 1)[1].split(MARK_END, 1)[0] if MARK_BEGIN in html and MARK_END in html else ""
    old = sorted(set(m.group(0) for m in OLD_WORDS.finditer(re.sub(r"<[^>]+>", " ", body))))
    if old:
        f.warn("%s: the analysis body uses retired display words %s (signals are Quiet / Open / Confirmed, a "
               "Watch-capped signal is \"Confirmed · counts toward Watch\", delegation is a rung, runs.agi is \"AGI "
               "anywhere\", B is Hidden self-improvement)" % (rel, ", ".join(js(w) for w in old)))
    if ctx.scan_page is not None:
        try:
            scan = ctx.scan_page(ctx.root / rel)
        except (OSError, UnicodeDecodeError):
            return
        for text, linked in scan.facts:
            snippet = js(text, 90)
            if not linked:
                f.warn("%s: fact-tagged item has no link: %s" % (rel, snippet))
            low = text.lower()
            for w in HEDGES:
                if re.search(r"\b%s\b" % re.escape(w), low):
                    f.warn("%s: fact-tagged item says %s; tag it report or cite the primary source: %s" % (
                        rel, js(w), snippet))


# ---------- build_report --check, in process ----------

# The render's own WARN lines that check_data repeats (the others restate this module's field checks).
RENDER_WARNS = ("cards unavailable",)


def load_render():
    """(build_report.render, None), or (None, why). build_report.py ships with format 2, so a missing module or a
    crash while importing it is a finding (one line), never a traceback."""
    try:
        import build_report  # scripts/build_report.py (WP-D); check_data puts scripts/ on sys.path
    except ImportError as e:
        if getattr(e, "name", None) == "build_report":
            return None, "scripts/build_report.py is missing, so the format-2 report can't be re-rendered"
        return None, "%s: %s" % (type(e).__name__, e)
    except Exception as e:  # a syntax error or a crash at import time
        return None, "%s: %s" % (type(e).__name__, e)
    render = getattr(build_report, "render", None)
    if not callable(render):
        return None, "scripts/build_report.py has no render(date, runs_path, body)"
    return render, None


def in_window(ctx, r, rels):
    """True while today's run is being written or fixed: its runs.json entry or one of its report files differs
    from the base commit (uncommitted). Outside it, a Friday weekly or an afternoon Level-3 pass that rewrites
    data files never fails on the report that went out that morning."""
    if not ctx.git.ok:
        return True
    head = ctx.git.show_json("data/runs.json")
    same = [x for x in head if isinstance(x, dict) and x.get("date") == r.get("date")] if isinstance(head, list) else []
    if not same or canon(same[-1]) != canon(r):
        return True
    return any(ctx.git.show(rel) != ctx.read(rel) for rel in rels)


def shell(html):
    """The analysis page without its body: the text before the begin marker and after the end marker."""
    if MARK_BEGIN in html and MARK_END in html:
        return html.split(MARK_BEGIN, 1)[0] + MARK_END + html.split(MARK_END, 1)[1]
    return html


def first_diff(a, b):
    """Where the file on disk first differs from the render: the line, and about 70 characters around the first
    differing column of each, so the difference itself is in the message even on a long line."""
    al, bl = a.splitlines(), b.splitlines()
    for i, (x, y) in enumerate(zip(al, bl)):
        if x != y:
            col = next((j for j, (u, v) in enumerate(zip(x, y)) if u != v), min(len(x), len(y)))
            lo = max(0, col - 30)
            near = [json.dumps(("…" if lo else "") + t[lo:col + 40] + ("…" if len(t) > col + 40 else ""),
                               ensure_ascii=False) for t in (x, y)]
            return "line %d, column %d: %s vs rendered %s" % (i + 1, col + 1, near[0], near[1])
    return "line %d: lengths differ (%d vs rendered %d lines)" % (min(len(al), len(bl)) + 1, len(al), len(bl))


def call_render(render, d, runs_path):
    """((short, analysis), WARN lines, None) or (None, [], one-line failure). Output is captured, never printed."""
    err = io.StringIO()
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            short, analysis = render(d, runs_path)
    except SystemExit as e:
        return None, [], "render(%s) exited %s" % (d, e.code)
    except Exception as e:  # one line, never a traceback
        return None, [], "%s: %s" % (type(e).__name__, str(e).splitlines()[0] if str(e) else "")
    warns = [ln.split("build_report:", 1)[-1].strip() for ln in err.getvalue().splitlines()
             if any(w in ln for w in RENDER_WARNS)]
    return (short, analysis), warns, None


def check_render(ctx, r, render=None):
    """build_report.render() reproduces the newest format-2 report pair (spec 9.3, 11): the short report byte for
    byte, the analysis shell around the markers, and the analysis body as build_report cleans it (a hand edit that
    smuggled in a tag or attribute the fragment validator strips). ERROR inside the daily's window, else WARN."""
    f, d = ctx.f, r.get("date")
    short_rel, an_rel = r.get("report"), "reports/%s-analysis.html" % d
    window = in_window(ctx, r, [short_rel, an_rel])
    say = f.err if window else f.warn
    if render is None:
        render, why = load_render()
        if render is None:
            say("build_report: %s" % why)
            return
    out, warns, why = call_render(render, d, str(ctx.root / "data/runs.json"))
    if why is not None:
        say("build_report: %s%s" % (why, " (inside the daily's window: fix the run or the body it names, then "
                                         "re-run build_report.py --date %s)" % d if window else ""))
        return
    for w in warns:
        f.warn("build_report: %s" % w)
    short, analysis = out
    tail = (": edited by hand, or the run changed after rendering (inside the daily's window: re-run "
            "build_report.py --date %s)" % d if window else
            " (committed earlier, so build_report.py changed since; past reports are frozen, so this is only a "
            "warning)")
    disk = ctx.read(short_rel)
    if disk is not None and disk != short:
        say("%s differs from build_report's render, %s%s" % (short_rel, first_diff(disk, short), tail))
    disk = ctx.read(an_rel)
    if disk is None:
        return
    if shell(disk) != shell(analysis):
        say("%s: the shell around the body differs from build_report's render, %s%s" % (
            an_rel, first_diff(shell(disk), shell(analysis)), tail))
    elif disk != analysis:
        say("%s: the body between the markers isn't what build_report writes (a tag, attribute or comment its "
            "fragment validator strips), %s%s" % (an_rel, first_diff(disk, analysis), tail))


# ---------- the newest v2 wrap-up ----------

def check_weekly(ctx, runs):
    """The newest wrap-up built with v2 labels (snapshot.labelSet 2): its frozen AGI parts are the 8 parts, and
    keyNumbers.methodBoundary says whether the definitions changed between the week-ago and the newest reading."""
    f, js = ctx.f, ctx.js
    docs = sorted(k for k, v in ctx.data.items() if k.startswith("data/weekly/") and isinstance(v, dict)
                  and isinstance(v.get("snapshot"), dict) and v["snapshot"].get("labelSet") == 2)
    if not docs:
        return
    rel, w = docs[-1], ctx.data[docs[-1]]
    agi = w["snapshot"].get("agi")
    if agi is not None:
        parts = agi.get("components") if isinstance(agi, dict) else None
        ids = [c.get("id") for c in parts if isinstance(c, dict)] if isinstance(parts, list) else None
        if ids != COMPONENT_IDS or any(not isinstance(c, dict) or c.get("status") not in SCALE_KEYS for c in parts):
            f.err("%s snapshot.agi.components must be the 8 parts in order, each with a status on the scale "
                  "(got %s)" % (rel, js(ids)))
    k = w.get("keyNumbers") if isinstance(w.get("keyNumbers"), dict) else {}
    by_date = {r["date"]: r for r in runs or [] if isinstance(r, dict) and r.get("report") and r.get("date")}
    now, ago = by_date.get(k.get("asOf")), by_date.get(k.get("weekAgoDate"))
    if "methodBoundary" not in k or now is None or ago is None:
        return
    want = False if k.get("firstReading") else run_defs(now) != run_defs(ago)
    if k["methodBoundary"] is not want:
        f.err("%s keyNumbers.methodBoundary=%s but the readings of %s (definitions %s) and %s (definitions %s) say %s; "
              "a definitions change inside the week prints \"method change\", never a move" % (
                  rel, js(k["methodBoundary"]), k.get("weekAgoDate"), run_defs(ago), k.get("asOf"), run_defs(now),
                  js(want)))


def check(ctx, runs, latest, render=None):
    check_weekly(ctx, runs)
    if not isinstance(runs, list) or latest is None:
        return
    r = runs[latest]
    if not isinstance(r, dict) or r.get("format") != 2:
        return
    p = "runs[%d]" % latest
    check_run(ctx, p, r)
    check_short(ctx, r)
    check_analysis(ctx, r)
    check_render(ctx, r, render)
