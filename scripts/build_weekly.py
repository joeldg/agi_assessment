#!/usr/bin/env python3
"""Build a Friday weekly wrap-up from data/weekly/<date>.json plus the daily runs.

    python3 scripts/build_weekly.py 2026-10-09
    python3 scripts/build_weekly.py 2026-10-09 --allow-stale        # build even if that day's daily isn't published
    python3 scripts/build_weekly.py 2026-10-09 --refresh-snapshot   # recompute the frozen chart data (rarely right)

The routine writes the editorial JSON (headline, summary, moves, section notes). This script
computes the key numbers from data/runs.json, stores them back in the JSON, renders
weekly/<date>.html, updates data/weekly/index.json, and exposes weekly_email_html() for Kit.

Key numbers compare published readings only (runs with a report, not marked "comparable": false),
one per date. With no reading 7 or more days back, the comparison is with the first published
reading and is labelled "since <date>", never "this week". They run in chain order: AGI parts,
AGI anywhere, the Hidden AGI Index, the fire alarm, then the hypotheses, gauges and signals.

Method changes: when the definitions in force changed inside the week (sitekit.method_boundary between
the reading a week ago and today's), AGI anywhere, A, C, D, D-open and the Index print "method change
(definitions v2.0)" instead of a ▲▼ delta, and any move on news on the other days of the week is shown
next to it, never hidden behind the label. B keeps its real delta: it doesn't depend on the AGI bar.

The chart data is frozen: snapshot() stores what each section showed as of the wrap-up date in the
JSON under "snapshot", computed once. The page draws only from that snapshot, so an archived
wrap-up never changes after publication. The standing pages are the live views. Escape watch's
statuses and the eight AGI parts (status, short name and glance) are frozen the same way.

Wrap-ups from before redesign v2 (their snapshot has no labelSet 2; today only 2026-10-02) are frozen
pages: this script refuses to rebuild them, and weekly_email_html() keeps their original email.

The plan-usage line ("This week's readings used X% of a Claude Max 20x plan's weekly allowance")
stays hidden until data/usage.json holds a full completed week of daily readings (see usage_week).
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_feed import (DOWN, FONT, INK, MUTED, RULE, SANS, UP, abs_url, alarm_level_on,  # noqa: E402
                        as_list, changed, claim_date, corrections_box, data_table, delta_amount, delta_cell,
                        email_footer, escape_counts_text, escape_summary, fmt, gauge_delta, h2, link, nice_date, outlet,
                        p, prob, source_link, th_attr, ul)
from sitekit import (HYP_LABELS, METHOD_CHANGE, SIGNAL_STATUS, SITE, SUBSCRIBE, method_boundary, page,  # noqa: E402
                     pending_defs, run_defs)

ROOT = Path(__file__).resolve().parent.parent
KEYS = ["A", "B", "C", "D", "Dopen"]
# Numbers that need an AGI-level system, so a change of definitions moves them (B doesn't).
DEFS_BOUND = ("agi", "index", "A", "C", "D", "Dopen")
# The labels wrap-ups used before redesign v2; kept only for the frozen wrap-ups' email.
LABELS_V1 = {"A": "A: AGI undisclosed", "B": "B: Secret RSI", "C": "C: Covert AGI online",
             "D": "D: Covert govt influence", "Dopen": "D-open: Open govt influence"}
LABEL_SET = 2  # snapshot marker: wrap-ups built with the v2 labels and layout
SECTIONS = [("agi", "AGI parts", "agi.html"),
            ("scorecard", "Forecast scorecard", "scorecard.html"),
            ("lag", "Disclosure lag", "disclosure-lag.html"),
            ("claims", "AGI claims ledger", "agi-claims.html"),
            ("calendar", "Coming up", "calendar.html"),
            ("steelman", "Weekly steelman", "steelman.html"),
            ("trends", "Trend watch", "trends.html"),
            ("money", "Follow the money", "money.html"),
            ("escape", "Escape watch", "escape.html")]
DEK_WORDS = 60          # the summary under the headline (the dek): WARN above this
TITLES_SHOWN = 10       # correction titles listed before "and N more"
# The owner-approved wording for the plan-usage line. It appears only once data/usage.json holds a full week.
USAGE_LINE = "This week's readings used {pct}% of a Claude Max 20x plan's weekly allowance"
USAGE_MIN_READINGS = 7
_UNSET = object()  # page_body/weekly_email_html_v2 load the Jobs section from disk unless told otherwise


def load_jobs(date):
    """The week's Jobs section data, {"edition", "claims"}, from data/jobs/ (written by import_jobs.py), or None when
    the wrap-up has no Jobs edition: then the page and email are exactly as they were before Jobs existed."""
    ed, cl = ROOT / f"data/jobs/{date}.json", ROOT / "data/jobs/claims.json"
    if not ed.exists() or not cl.exists():
        return None
    return {"edition": json.loads(ed.read_text(encoding="utf-8")), "claims": json.loads(cl.read_text(encoding="utf-8"))}


def label(k):
    """'A · Hidden AGI', 'D-open · Open government influence'."""
    return f'{"D-open" if k == "Dopen" else k} · {HYP_LABELS[k]}'


def pretty(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%-d %B %Y")


def day_mon(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%-d %b")


def shift(date, days):
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def published_runs(upto):
    """Published, comparable readings dated on or before `upto`, one per date (the last entry wins), oldest first."""
    by_date = {}
    for r in json.loads((ROOT / "data/runs.json").read_text()):
        if r.get("report") and r.get("comparable") is not False and r["date"] <= upto:
            by_date[r["date"]] = r
    return [by_date[d] for d in sorted(by_date)]


def check_fresh(now, date, allow_stale):
    """True when the newest published reading predates the wrap-up; exits unless allow_stale."""
    if now["date"] == date:
        return False
    msg = f"the latest published reading is {now['date']}, not {date}, so the wrap-up's numbers would be stale"
    if not allow_stale:
        sys.exit(f"build_weekly: {msg}. Publish that day's daily first, or pass --allow-stale.")
    print(f"warning: {msg} (--allow-stale).", file=sys.stderr)
    return True


def week_corrections(week):
    """Corrections carried by the week's daily readings, each once, in order."""
    out = []
    for r in week:
        for c in as_list(r.get("corrections")):
            if isinstance(c, dict) and c not in out:
                out.append(c)
    return out


def _usage_find(obj, words, path=""):
    """(path, value) pairs for the leaves of a usage reading whose key contains one of `words`."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += _usage_find(v, words, f"{path}.{k}".lower())
    elif path and any(w in path.rsplit(".", 1)[-1] for w in words):
        out.append((path, obj))
    return out


def _usage_reading(r):
    """(date, stamp, percent, reset) from one usage.json reading, or None when it lacks a date or a percentage.
    Tolerant of the exact field names: the percentage is the numeric field whose key says 'percent' or 'pct'
    (one under a 'week' key preferred, then 'all' models), the reset is any field whose key says 'reset'."""
    if not isinstance(r, dict):
        return None
    stamp = next((str(r[k]) for k in ("at", "time", "takenAt", "recordedAt", "timestamp", "date") if r.get(k)), "")
    day = str(r.get("date") or stamp)[:10]
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return None
    nums = [(p, v) for p, v in _usage_find(r, ("percent", "pct"))
            if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1000]
    if not nums:
        return None
    nums.sort(key=lambda pv: ("week" not in pv[0], "all" not in pv[0]))
    resets = [str(v) for p, v in _usage_find(r, ("reset",)) if v]
    return day, stamp, float(nums[0][1]), (resets[0] if resets else None)


def usage_week(date):
    """The plan-usage figure for the last completed usage week, or None until there is a full one.
    data/usage.json (written by the daily run each morning; absent until then) holds one reading per day:
    a list, or {"readings": [...]}, each with a date and the "Weekly · all models" percent used. The week
    resets on Fridays at about 11:00 PT, after the morning reading, so the last completed week for a wrap-up
    is the seven days ending on the latest Friday on or before it. Readings that name a reset time are
    grouped by it, and a week whose reset is still in the future isn't complete. The figure is the week's
    last reading, shown only when the week has USAGE_MIN_READINGS daily readings or more.
    Returns {"weekEnd", "readings", "percent"}."""
    try:
        doc = json.loads((ROOT / "data/usage.json").read_text())
    except (OSError, ValueError):
        return None
    rows = doc if isinstance(doc, list) else (doc.get("readings") or doc.get("entries") or []) if isinstance(doc, dict) else []
    d = datetime.strptime(date, "%Y-%m-%d")
    end = (d - timedelta(days=(d.weekday() - 4) % 7)).strftime("%Y-%m-%d")  # Friday is weekday 4
    start = shift(end, -6)
    week = [x for x in (_usage_reading(r) for r in as_list(rows)) if x and start <= x[0] <= end]
    if not week:
        return None
    week.sort(key=lambda x: (x[0], x[1]))

    def reset_time(r):
        try:
            t = datetime.fromisoformat(r.replace("Z", "+00:00"))
            return t if t.tzinfo else None
        except ValueError:
            return None

    resets = {x[3] for x in week if x[3]}
    if resets:
        # a reading taken after the reset belongs to the next week; a reset still in the future means not complete
        done = [r for r in resets if reset_time(r) is None or reset_time(r) <= datetime.now(reset_time(r).tzinfo)]
        if not done:
            return None
        reset = max(done, key=lambda r: (reset_time(r) is not None, reset_time(r).timestamp() if reset_time(r) else 0, r))
        week = [x for x in week if x[3] in (reset, None)]
    days = len({x[0] for x in week})
    if days < USAGE_MIN_READINGS:
        return None
    return {"weekEnd": end, "readings": days, "percent": week[-1][2]}


def usage_text(k):
    """The usage line, or '' while there is no complete week of readings."""
    u = (k or {}).get("usage")
    return USAGE_LINE.format(pct=fmt(u["percent"])) + "." if u and u.get("percent") is not None else ""


def value_of(run, key):
    """A run's 'today' figure for a key-number row: agi (AGI anywhere), index, or a hypothesis."""
    if key == "agi":
        return ((run or {}).get("agi") or {}).get("now")
    if key == "index":
        return (run or {}).get("index")
    return prob(run, key, "now")


def news_moves(seq, keys):
    """For readings `seq` (oldest first, from the week-ago reading to today's), the move on news in each key:
    the sum of the day-to-day changes, leaving out every step that crosses a method boundary (that step is the
    change of definitions, reported as a method change). Only keys with a displayed move are returned."""
    out = {}
    for key in keys:
        tot, seen = 0.0, False
        for prev, cur in zip(seq, seq[1:]):
            a, b = value_of(prev, key), value_of(cur, key)
            if method_boundary(cur, prev) or a is None or b is None:
                continue
            tot += float(b) - float(a)
            seen = True
        tot = round(tot, 6)
        if seen and changed(tot, 0):
            out[key] = tot
    return out


def key_numbers(date, allow_stale=False):
    runs = published_runs(date)
    if not runs:
        sys.exit("No published daily readings on or before " + date)
    now = runs[-1]
    stale = check_fresh(now, date, allow_stale)
    cutoff = shift(date, -7)
    older = [r for r in runs if r["date"] <= cutoff]
    ago = older[-1] if older else runs[0]  # no reading a week back: compare with the first published reading
    first = ago is now  # nothing earlier to compare with at all
    gkeys = [d["key"] for d in json.loads((ROOT / "data/gauges.json").read_text())["gauges"]]
    tw = {"tripped": 0, "watching": 0, "quiet": 0}
    for w in now.get("tripwires", []):
        tw[w["status"]] = tw.get(w["status"], 0) + 1
    week = [r for r in runs if r["date"] > cutoff]
    corrections = week_corrections(week)
    lv = alarm_level_on(now["date"], now)
    boundary = not first and method_boundary(now, ago)
    seq = [r for r in runs if ago["date"] <= r["date"] <= now["date"]]
    crossed = next((cur["date"] for prev, cur in zip(seq, seq[1:]) if method_boundary(cur, prev)), None)
    agi_now, agi_ago = now.get("agi") or {}, ({} if first else ago.get("agi") or {})
    return {
        "asOf": now["date"], "weekAgoDate": ago["date"], "sinceFirst": not older, "firstReading": first, "stale": stale,
        "defs": run_defs(now), "defsWeekAgo": None if first else run_defs(ago),
        "methodBoundary": boundary, "methodChangeDate": crossed if boundary else None,
        "news": news_moves(seq, DEFS_BOUND) if boundary else {},
        "agi": {h: agi_now.get(h) for h in ("now", "y2030", "y2035")},
        "agiWeekAgo": None if first else agi_ago.get("now"),
        "index": now.get("index"), "indexWeekAgo": None if first else ago.get("index"),
        "now": {k: prob(now, k, "now") for k in KEYS},
        "weekAgo": {k: None if first else prob(ago, k, "now") for k in KEYS},
        "y2030": {k: prob(now, k, "y2030") for k in KEYS}, "y2035": {k: prob(now, k, "y2035") for k in KEYS},
        "gauges": {k: (now.get("gauges") or {}).get(k) for k in gkeys},
        "gaugesWeekAgo": {k: None if first else ((ago.get("gauges") or {}).get(k) or {}).get("value") for k in gkeys},
        "tripwires": tw, "dailyRuns": len(week),
        "alarm": {x: lv[x] for x in ("level", "name", "icon", "meaning", "status") if x in lv} if lv else None,
        "corrections": corrections,
    }


def span_label(k):
    """What the change columns compare: 'this week', or 'since 29 Sep' when there's no reading a week back."""
    return "since " + day_mon(k["weekAgoDate"]) if k.get("sinceFirst") and not k.get("firstReading") else "this week"


def _move(amount):
    """'▲ +0.5 pts' for a signed move."""
    amt = delta_amount(amount, 0)
    return f'{"▲ +" if float(amount) > 0 else "▼ −"}{amt} {"pt" if amt == "1" else "pts"}'


def wk_delta(cur, prev, span="this week", key=None, k=None):
    """The change text for a key number. On a method boundary inside the week, a number that needs an
    AGI-level system shows the method-change label (with any move on news on the other days first)."""
    if cur is None:
        return "–"
    if k and k.get("methodBoundary") and key in DEFS_BOUND:
        news = (k.get("news") or {}).get(key)
        return f"{_move(news)} news {span}; {METHOD_CHANGE}" if news is not None else METHOD_CHANGE
    if prev is None:
        return "first reading"
    if not changed(cur, prev):
        return f"no change {span}"
    return f"{_move(float(cur) - float(prev))} {span}"


def gauge_change(g, prev_v, span="this week"):
    return gauge_delta((g or {}).get("value"), prev_v, " " + span)


def status_counts(agi):
    """{met, close, partial, far} from the frozen AGI parts."""
    c = {"met": 0, "close": 0, "partial": 0, "far": 0}
    for x in (agi or {}).get("components") or []:
        if x.get("status") in c:
            c[x["status"]] += 1
    return c


def agi_snapshot(date, load):
    """The eight AGI parts as of `date` (status, names, glance, why), frozen like the charts, plus what the strip
    needs to draw them (the status scale) and the definitions the AGI page stated. None when unavailable."""
    if not (ROOT / "data/agi_components.json").exists():
        print("warning: snapshot: data/agi_components.json is missing; the AGI parts are left out.", file=sys.stderr)
        return None
    comp = load("data/agi_components.json", "AGI parts")
    if not isinstance(comp, dict):
        return None
    if str(comp.get("lastReviewed") or "") > date:
        print(f"warning: snapshot: data/agi_components.json was reviewed {comp.get('lastReviewed')}, after {date}; "
              "the AGI parts are left out rather than showing later statuses.", file=sys.stderr)
        return None
    parts = [{x: c.get(x) for x in ("id", "name", "short", "status", "glance", "basisShort")}
             for c in as_list(comp.get("components")) if isinstance(c, dict) and c.get("id")]
    if not parts:
        return None
    out = {"definitionsVersion": comp.get("definitionsVersion"), "adopted": comp.get("adopted"),
           "lastReviewed": comp.get("lastReviewed"),
           "statusScale": [{x: s.get(x) for x in ("key", "word", "pips", "meaning")} for s in as_list(comp.get("statusScale"))
                           if isinstance(s, dict)],
           "components": parts}
    if comp.get("publicAgi"):
        out["publicAgi"] = comp["publicAgi"]
    return out


def snapshot(date):
    """What each section shows as of `date`, frozen into the wrap-up's JSON so the archive never changes."""
    soon = shift(date, 45)

    def load(path, what):
        try:
            return json.loads((ROOT / path).read_text())
        except (OSError, ValueError) as e:
            print(f"warning: snapshot: can't read {path} ({e}); the {what} chart will show as unavailable.", file=sys.stderr)
            return None

    snap = {"date": date, "taken": datetime.now().strftime("%Y-%m-%d"), "labelSet": LABEL_SET}
    runs = load("data/runs.json", "trend") or []
    by_date = {}
    for r in runs:
        if r["date"] <= date:
            by_date[r["date"]] = r  # one point per day: the last entry of the day
    snap["trend"] = [dict({"date": d, "index": by_date[d].get("index"), "agi": (by_date[d].get("agi") or {}).get("now"),
                           "defs": run_defs(by_date[d])}, **{k: prob(by_date[d], k, "now") for k in "ABCD"})
                     for d in sorted(by_date)]
    # a dashed hairline where the definitions changed; lineChart doesn't join a series across it
    snap["breaks"] = [{"x": cur["date"], "label": f'Definitions v{cur["defs"]}'}
                      for prev, cur in zip(snap["trend"], snap["trend"][1:]) if cur["defs"] != prev["defs"]]
    agi = agi_snapshot(date, load)
    if agi is not None:
        snap["agi"] = agi
    fc = load("data/forecasts.json", "scorecard")
    if fc is not None:
        keep = ("id", "question", "p", "market", "made", "deadline", "resolution")
        snap["forecasts"] = sorted(
            (dict({x: f[x] for x in keep if x in f}, outcome=None, resolved=None)
             for f in fc.get("forecasts", [])
             if f.get("made", "") <= date and f.get("outcome") != "void"
             and (f.get("outcome") is None or (f.get("resolved") or "9999-12-31") > date)),
            key=lambda f: f.get("deadline", ""))
    inc = load("data/incidents.json", "disclosure-lag")
    if inc is not None:
        snap["incidents"] = [i for i in inc.get("incidents", []) if i.get("disclosed", "9999") <= date]
    cl = load("data/agi_claims.json", "claims")
    if cl is not None:
        snap["claims"] = [c for c in cl.get("claims", []) if c.get("date", "9999") <= date]
    cal = load("data/calendar.json", "calendar")
    if cal is not None:
        snap["calendar"] = sorted((e for e in cal.get("events", []) if date <= e.get("date", "") <= soon),
                                  key=lambda e: e["date"])
    tr = load("data/trends.json", "METR")
    if tr is not None and tr.get("metr"):
        M = tr["metr"]  # a refit can't be reproduced later, so the current fit is stored as-is
        snap["metr"] = {
            "models": [{x: m.get(x) for x in ("id", "date", "p50", "p50lo", "p50hi", "p80")}
                       for m in M.get("models", []) if m.get("sota") and "2023-01-01" <= m.get("date", "") <= date],
            "p50": {"projection": (M.get("p50") or {}).get("projection")},
            "p80": {"projection": (M.get("p80") or {}).get("projection")},
            "thresholds": M.get("thresholds"),
        }
    mo = load("data/money.json", "money")
    if mo is not None:
        snap["money"] = [row for row in mo.get("spendVsCapability", []) if row.get("end", "9999") <= date]
    esc = load("data/escape.json", "Escape watch") if (ROOT / "data/escape.json").exists() else None
    if esc is not None:
        if str(esc.get("updated") or "") > date:
            print(f"warning: snapshot: data/escape.json was updated {esc.get('updated')}, after {date}; "
                  "Escape watch is left out rather than showing later statuses.", file=sys.stderr)
        else:  # the statuses as of the wrap-up, frozen like the charts
            snap["escape"] = {"updated": esc.get("updated"), "overall": esc.get("overall"),
                              "indicators": [{x: i.get(x) for x in ("key", "name", "status")}
                                             for i in as_list(esc.get("indicators")) if isinstance(i, dict)]}
    return snap


# ---- the wrap-up page --------------------------------------------------------------------------------------------

def tile(label_text, value, sub=""):
    return (f'<div class="tile"><div class="label">{escape(label_text)}</div><div class="value">{value}</div>'
            f'<div class="delta muted">{sub}</div></div>')


def pending_chip(k, agi):
    """The chip next to AGI anywhere and A–D while today's numbers use a different bar from the one agi.html
    states (sitekit.pending_defs, from the frozen parts; never the build clock)."""
    if not agi or not pending_defs({"defs": k.get("defs")}, agi):
        return ""
    if agi.get("adopted"):
        return (' <span class="chip" title="Set under the v1.0 bar; the next reading re-derives it under definitions v2.0 '
                'and labels the change a method change, not news.">v1.0 bar until the next reading</span>')
    return (' <span class="chip" title="These numbers use the v1.0 bar. Definitions v2.0 are proposed; when they take '
            'effect, the next reading re-derives the numbers and labels the change a method change, not news.">'
            'v1.0 bar; definitions v2.0 proposed</span>')


def _scale(agi):
    return {s.get("key"): s for s in (agi or {}).get("statusScale") or []}


def answer_text(agi):
    """'Not in public: 0 of 8 parts met (2 partial, 6 far).' and its two other states, as HTML."""
    try:
        from pages import common  # the shared server-side pieces (WP-C2), when present
        return common.answer_line(agi)
    except Exception:  # noqa: BLE001 - fall back to the same wording, built here
        pass
    c, n, sc = status_counts(agi), len(agi["components"]), _scale(agi)
    if agi.get("publicAgi"):
        return f'<strong>Yes, in public:</strong> {escape(str(agi["publicAgi"].get("system", "")))} meets all {n} parts.'
    if c["met"] == n:
        return f'<strong>Possibly, in public:</strong> all {n} parts are met, but not yet by one system.'
    rest = ", ".join(f'{c[s]} {str((sc.get(s) or {}).get("word") or s).lower()}' for s in ("close", "partial", "far") if c[s])
    return f'<strong>Not in public:</strong> {c["met"]} of {n} parts met' + (f" ({rest})." if rest else ".")


def strip_html(agi):
    """The eight parts as a strip of tiles (ink pips plus the word), each linking to its part on agi.html."""
    href = lambda c: f'../agi.html#{c["id"]}'  # noqa: E731
    try:
        from pages import common  # one implementation when it exists (WP-C2)
        return common.strip(agi, href=href)
    except Exception:  # noqa: BLE001 - same markup and classes, built here
        pass
    sc = _scale(agi)
    cells = []
    for c in agi["components"]:
        s = sc.get(c.get("status")) or {"word": str(c.get("status") or "?").title(), "pips": 0}
        n = int(s.get("pips") or 0)
        pips = "".join(f'<span class="pip{" on" if i < n else ""}"></span>' for i in range(4))
        cells.append(f'<li><a class="ag-cell" href="{escape(href(c), quote=True)}">'
                     f'<span class="ag-name">{escape(str(c.get("short") or c.get("name") or c["id"]))}</span>'
                     f'<span class="am-status"><span class="am-pips" aria-hidden="true">{pips}</span>'
                     f'<span class="ag-word" aria-hidden="true">{escape(str(s.get("word")))}</span>'
                     f'<span class="sr-only">, status {escape(str(s.get("word")))}, step {n} of 4</span></span>'
                     f'<span class="sr-only">. {escape(str(c.get("glance") or ""))}</span></a></li>')
    return f'<ul class="ag-strip">{"".join(cells)}</ul>'


def agi_section_html(agi):
    if not agi:
        return '<p class="muted small">The AGI parts were not recorded in this wrap-up\'s snapshot.</p>'
    return f'<p>{answer_text(agi)}</p>{strip_html(agi)}'


def correction_title(c):
    t = str(c.get("item") or "").strip()
    if not t:
        words = str(c.get("now") or c.get("was") or "").split()
        t = " ".join(words[:12]) + ("…" if len(words) > 12 else "")
    return t.rstrip(".")


def corrections_html(k):
    """The week's corrections on the wrap-up page: how many, and their titles, linking the one corrections log."""
    cs = [c for c in k.get("corrections") or [] if c.get("was") and c.get("now")]
    if not cs:
        return ""
    items = []
    for c in cs[:TITLES_SHOWN]:
        said = claim_date(c)
        when = f' <span class="muted small">(we said it {escape(nice_date(said))})</span>' if said else ""
        items.append(f'<li><a href="../changes.html#corrections">{escape(correction_title(c))}</a>{when}</li>')
    more = len(cs) - TITLES_SHOWN
    if more > 0:
        items.append(f'<li class="muted">and {more} more</li>')
    n = len(cs)
    return (f'\n  <section aria-label="Corrections"><div class="callout" style="border-left-color:var(--ink)">'
            f'<strong>{n} {"correction" if n == 1 else "corrections"} this week</strong><ul class="plain">{"".join(items)}</ul>'
            f'<p class="small muted">What we said and what is right, for each one: '
            f'<a href="../changes.html#corrections">the corrections log →</a></p></div></section>')


def signal_counts_text(c, sep=", "):
    """'2 confirmed, 6 open, 3 quiet' from {tripped, watching, quiet} counts."""
    return sep.join(f'{c.get(s, 0)} {SIGNAL_STATUS[s][2].lower()}' for s in ("tripped", "watching", "quiet"))


def escape_list_html(esc):
    """Escape watch on the wrap-up page: the counts, the overall line and each indicator that isn't quiet with
    its status (status colour, always with the icon and the word), from the frozen snapshot."""
    if not esc:
        return '<p class="muted small">Escape watch was not recorded in this wrap-up\'s snapshot.</p>'
    rows = "".join(
        f'<li><span style="color:var(--{SIGNAL_STATUS[i["status"]][1]});font-weight:600">'
        f'<span aria-hidden="true">{SIGNAL_STATUS[i["status"]][0]}</span> {SIGNAL_STATUS[i["status"]][2]}</span>'
        f' · {escape(i["name"])}</li>'
        for i in esc["live"])
    quiet = esc["counts"]["quiet"]
    more = f'<li class="muted">{quiet} {"indicator" if quiet == 1 else "indicators"} quiet.</li>' if quiet else ""
    return (f'<p><strong>{esc["total"]} indicators: {signal_counts_text(esc["counts"])}.</strong> '
            f'{escape(esc.get("overall") or "")}</p><ul class="plain">{rows}{more}</ul>')


def page_body(w, jobs=_UNSET):
    if jobs is _UNSET:
        jobs = load_jobs(w["date"])
    k = w["keyNumbers"]
    span = span_label(k)
    agi = (w.get("snapshot") or {}).get("agi")
    chip = pending_chip(k, agi)
    tiles = []
    parts = k.get("agiParts")
    if parts and agi:
        n = len(agi["components"])
        rest = "".join(f' · {parts[s]} {s}' for s in ("close", "partial", "far") if parts.get(s))
        tiles.append(tile("AGI parts", f'{parts["met"]} of {n}', f'met{rest} · <a href="../agi.html">the parts</a>'))
    a = k.get("agi") or {}
    if a.get("now") is not None:
        later = f' · {fmt(a["y2030"])}% by end-2030' if a.get("y2030") is not None else ""
        tiles.append(tile("AGI anywhere", f'{fmt(a["now"])}%',
                          escape(wk_delta(a["now"], k.get("agiWeekAgo"), span, "agi", k)) + later + chip))
    tiles.append(tile("Hidden AGI Index", f'{fmt(k["index"])}%',
                      escape(wk_delta(k["index"], k["indexWeekAgo"], span, "index", k))))
    lv = k.get("alarm")
    if lv:
        cls = f' class="ico-{lv["status"]}"' if lv.get("status") in ("good", "warn", "crit") else ""
        tiles.append(tile("Fire alarm", f'<span aria-hidden="true"{cls}>{lv["icon"]}</span> Level {lv["level"]} · {escape(lv["name"])}',
                          'Set by published rules, not our odds · <a href="../alarm.html">the rules</a>'))
    tiles += [tile(label(h), f'{fmt(k["now"][h])}%', escape(wk_delta(k["now"][h], k["weekAgo"][h], span, h, k))) for h in KEYS]
    gdefs = {d["key"]: d for d in json.loads((ROOT / "data/gauges.json").read_text())["gauges"]}
    for gk, g in (k.get("gauges") or {}).items():
        if not g or gk not in gdefs:
            continue
        tiles.append(tile(gdefs[gk]["label"], escape(g.get("display") or fmt(g.get("value"))),
                          gauge_change(g, (k.get("gaugesWeekAgo") or {}).get(gk), span)))
    tw = k["tripwires"]
    tiles.append(tile("Tripwire signals", f'{tw["tripped"]} confirmed',
                      f'{tw["watching"]} open · {tw["quiet"]} quiet · <a href="../alarm.html#signals">all signals</a>'))
    esc = k.get("escape")
    if esc:
        tiles.append(tile("Escape watch", f'{esc["counts"]["tripped"]} of {esc["total"]} confirmed',
                          f'{esc["counts"]["watching"]} open · {esc["counts"]["quiet"]} quiet'))

    def move_link(m):
        u = abs_url(m.get("url"))
        return (f' (<a href="{escape(u, quote=True)}" target="_blank" rel="noopener">{escape(m.get("source") or outlet(u))}</a>)'
                if u else "")

    moves = "".join(
        f'<li><span class="rdate">{escape(m.get("date", ""))}</span> <strong>{escape(m.get("hyp", ""))}</strong> '
        f'{escape(m["text"])}{move_link(m)}</li>'
        for m in w.get("moves", []))
    notes = w.get("sections", {})
    sec_html = ""
    for key, title, href in SECTIONS:
        chart = {"agi": agi_section_html(agi), "scorecard": '<div id="fc"></div>',
                 "lag": '<div class="chart-wrap"><div id="lag"></div></div>',
                 "claims": '<div class="chart-wrap"><div id="claims"></div></div>',
                 "calendar": '<ul class="timeline-list" id="cal"></ul>', "steelman": "",
                 "trends": '<div class="chart-wrap"><div id="metr"></div></div>',
                 "money": '<div class="chart-wrap"><div id="money"></div></div>',
                 "escape": escape_list_html(k.get("escape"))}[key]
        note = f'<p>{escape(notes[key])}</p>' if notes.get(key) else ""
        sec_html += (f'\n  <section id="{key}"><h2>{title}</h2>{note}{chart}'
                     f'<p class="small"><a href="../{href}">Full section (live) →</a></p></section>')
    if jobs:  # the Jobs plugin's section, last (plugin spec 8.2)
        import jobs_render
        sec_html += "\n  " + jobs_render.section_html(jobs["edition"], jobs["claims"])
    usage = f'\n  <p class="muted small">{escape(usage_text(k))}</p>' if usage_text(k) else ""
    if k.get("firstReading"):
        caption = f'Probabilities are for today, as of {pretty(k["asOf"])}. This is our first full reading, so changes appear from the next wrap-up.'
    elif k.get("sinceFirst"):
        caption = f'Probabilities are for today, comparing {pretty(k["asOf"])} with {pretty(k["weekAgoDate"])}, our first full reading.'
    else:
        caption = f'Probabilities are for today, comparing {pretty(k["asOf"])} with {pretty(k["weekAgoDate"])}.'
    if k.get("methodBoundary"):
        when = f' from the reading of {pretty(k["methodChangeDate"])}' if k.get("methodChangeDate") else " this week"
        caption += (f' Our readings use definitions v2.0{when}: AGI anywhere, A, C, D, D-open and the Index were re-derived '
                    f'under the new definition, so their change reads "{METHOD_CHANGE}", not news; '
                    f'B doesn\'t depend on the definition. <a href="../changes.html#method">What changed</a>.')
    return f"""
  <header class="prose">
    <p class="kicker muted small">Weekly wrap-up · week to {pretty(w["date"])}</p>
    <h1>{escape(w["headline"])}</h1>
    <p class="lede">{escape(w.get("summary", ""))}</p>
  </header>{corrections_html(k)}
  <section aria-label="Key numbers"><div class="tiles">{"".join(tiles)}</div>
  <p class="muted small">{caption} {k["dailyRuns"]} daily reading{"s" if k["dailyRuns"] != 1 else ""} this week. <a href="../start-here.html#names">How to read these</a>.</p></section>
  <section><h2>This week's moves</h2><ul class="plain">{moves or "<li>A quiet week: nothing moved.</li>"}</ul></section>
  <section><div class="chart-head"><h2>The readings over time</h2></div><div class="chart-wrap"><div id="trend"></div></div></section>{sec_html}
  <p class="muted small">The charts and the AGI parts on this page are frozen as of {pretty(w["date"])}, so this wrap-up reads the same later. The linked sections show the live data.</p>{usage}
"""


def page_script(w):
    """Draw every chart from the frozen snapshot, inlined in the page: no fetches, and one failed chart can't blank the rest."""
    snap = json.dumps(w.get("snapshot") or {}, ensure_ascii=False).replace("<", "\\u003c")
    return f'<script type="application/json" id="snap">{snap}</script>\n' + """<script type="module">
import * as K from "../assets/charts.js";
const S = JSON.parse(document.getElementById("snap").textContent || "{}");
const h = K.util.h;
const live = K.live || ((host, draw) => draw());
const safeHref = (K.util && K.util.safeHref) || K.safeHref || (u => /^https?:\\/\\//i.test(String(u ?? "").trim()) ? String(u).trim() : null);
const nm = id => String(id).replace(/_inspect$/,"").replace(/_/g," ").replace(/\\b(gpt|o\\d)\\b/gi,s=>s.toUpperCase()).replace(/\\bclaude\\b/i,"Claude").replace(/\\bgemini\\b/i,"Gemini");
const sname = k => (S.labelSet === 2 && K.SERIES[k].name) ? K.SERIES[k].name : K.SERIES[k].label;
const note = (el, text, cls="muted small") => { el.replaceChildren(h("p",{class:cls},text)); };
const chart = (id, draw) => {
  const el = document.getElementById(id); if(!el) return;
  const fail = e => { console.error(id, e); note(el, "Chart unavailable."); };
  const guarded = () => { try { return draw(el); } catch(e) { fail(e); } };
  try { live(el, guarded); } catch(e) { fail(e); }
};
const has = a => Array.isArray(a) && a.length > 0;
chart("trend", el => { if(!has(S.trend)) throw new Error("no readings in snapshot");
  K.lineChart(el, {title:"Probability true today", breaks: Array.isArray(S.breaks) ? S.breaks : [], series:[
    {label:"Hidden AGI Index", short:"Index", color:"--ink", values:S.trend.map(r=>({x:r.date, y:r.index}))},
    ...["A","B","C","D"].map(k=>({label:sname(k), short:k, color:K.SERIES[k].color, values:S.trend.map(r=>({x:r.date, y:r[k]}))}))]}); });
chart("fc", el => { if(!Array.isArray(S.forecasts)) throw new Error("no forecasts in snapshot");
  const open = S.forecasts.filter(f => f.outcome !== "void");
  if(!open.length) return note(el, "No open forecasts as of this week.", "empty");
  K.forecastBars(el, open); });
chart("lag", el => { if(!Array.isArray(S.incidents)) throw new Error("no incidents in snapshot");
  if(!S.incidents.length) return note(el, "No disclosed incidents yet.", "empty");
  K.lagChart(el, S.incidents); });
chart("claims", el => { if(!Array.isArray(S.claims)) throw new Error("no claims in snapshot");
  if(!S.claims.length) return note(el, "No claims logged yet.", "empty");
  K.dotTimeline(el, S.claims, {title:"Public AGI claims"}); });
chart("metr", el => { const M = S.metr; if(!M || !has(M.models)) throw new Error("no METR data in snapshot");
  K.trendChart(el, {title:"METR time horizon", color:"--accent",
    history: M.models.map(m=>({date:m.date, v:m.p50, lo:m.p50lo, hi:m.p50hi, name:nm(m.id)+" · 50%"})), projection: M.p50 && M.p50.projection,
    secondary:{label:"80% horizon", color:"--ink", history: M.models.filter(m=>m.p80).map(m=>({date:m.date, v:m.p80, name:nm(m.id)+" · 80%"})), projection: M.p80 && M.p80.projection},
    thresholds: M.thresholds ? [{v:M.thresholds.workWeek, label:"1 work-week"},{v:M.thresholds.workMonth, label:"1 work-month"}] : []}); });
chart("money", el => { if(!has(S.money)) throw new Error("no money data in snapshot");
  K.lineChart(el, {title:"Spending vs capability, indexed", log:true, yFormat:v=>String(Math.round(v)), series:[
    {label:"Big-4 capex (index)", short:"Spend", color:"--accent", values:S.money.map(t=>({x:t.end, y:t.spend}))},
    {label:"METR-measured frontier horizon (index)", short:"Capability", color:"--ink", values:S.money.map(t=>({x:t.end, y:t.capability}))}]}); });
chart("cal", el => { if(!Array.isArray(S.calendar)) throw new Error("no calendar in snapshot");
  el.replaceChildren();
  S.calendar.forEach(e => { const li = h("li"), what = h("div"), u = safeHref(e.url);
    if(u){ const a = h("a",{href:u, target:"_blank", rel:"noopener"}, e.title); what.append(a); } else what.textContent = e.title;
    li.append(h("div",{class:"when"}, K.util.fmtDate(e.date,{day:"numeric",month:"short"})), what); el.append(li); });
  if(!el.children.length) el.append(h("li",{},"Nothing dated in the six weeks after this wrap-up.")); });
</script>"""


# ---- the email ---------------------------------------------------------------------------------------------------

def is_v2(w):
    return (w.get("snapshot") or {}).get("labelSet") == LABEL_SET


def weekly_email_html(w):
    """The wrap-up email. Wrap-ups from before redesign v2 keep their original email, byte for byte."""
    return weekly_email_html_v2(w) if is_v2(w) else weekly_email_html_v1(w)


def email_delta(cur, prev, key, k):
    """A change cell for the email's key-number table: the method-change label on a boundary week (with any
    move on news first), else the usual arrow cell."""
    if cur is not None and k.get("methodBoundary") and key in DEFS_BOUND:
        news = (k.get("news") or {}).get(key)
        lab = f'<span style="color:{MUTED}">{escape(METHOD_CHANGE)}</span>'
        if news is None:
            return lab
        color = UP if news > 0 else DOWN
        return f'<span style="color:{color};font-weight:600">{escape(_move(news))} news</span>; {lab}'
    return delta_cell(cur, prev)


def email_corrections(k):
    cs = [c for c in k.get("corrections") or [] if c.get("was") and c.get("now")]
    if not cs:
        return ""
    n = len(cs)
    items = [escape(correction_title(c)) for c in cs[:TITLES_SHOWN]]
    if n > TITLES_SHOWN:
        items.append(f"and {n - TITLES_SHOWN} more")
    lis = "".join(f'<li style="margin:0 0 4px">{i}</li>' for i in items)
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin:6px 0 14px"><tr>'
            f'<td bgcolor="#F8F9FA" style="background-color:#F8F9FA;border-left:4px solid {INK};padding:8px 12px">'
            f'<div style="{SANS}font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:600;padding:0">'
            f'{n} {"correction" if n == 1 else "corrections"} this week</div>'
            f'<ul style="{SANS}font-size:14px;line-height:1.5;color:{INK};padding-left:18px;margin:6px 0 4px">{lis}</ul>'
            f'<div style="{SANS}font-size:14px;color:{INK}">{link(SITE + "changes.html#corrections", "What we said and what is right, for each one")}</div>'
            f'</td></tr></table>')


def weekly_email_html_v2(w, jobs=_UNSET):
    if jobs is _UNSET:
        jobs = load_jobs(w["date"])
    k = w["keyNumbers"]
    span = span_label(k)
    url = f'{SITE}weekly/{w["date"]}.html'
    lv = k.get("alarm")
    agi = (w.get("snapshot") or {}).get("agi")
    out = [p(f'<span style="color:{MUTED}">Weekly wrap-up · week to {pretty(w["date"])} · {link(url, "Read it on the web, with graphs")}</span>')]
    out.append(email_corrections(k))
    if (ROOT / f'cards/weekly-{w["date"]}.png').exists():
        alt = f'Week to {pretty(w["date"])}: Hidden AGI Index {fmt(k["index"])}%' + (
            f', fire alarm Level {lv["level"]} ({lv["name"]})' if lv else "")
        out.append(f'<a href="{url}"><img src="{SITE}cards/weekly-{w["date"]}.png" width="580" height="305" alt="{escape(alt, quote=True)}" '
                   f'style="display:block;width:100%;max-width:600px;height:auto;border:0;border-radius:8px;margin:8px 0 14px"></a>')
    if lv:
        out.append(p(f'<strong><span aria-hidden="true">{lv["icon"]}</span> Fire alarm: Level {lv["level"]} · {escape(lv["name"])}.</strong> '
                     f'<span style="color:{MUTED}">{escape(lv.get("meaning", ""))} {link(SITE + "alarm.html", "The rules")}</span>'))
    out.append(f'<h1 style="{FONT}font-size:24px;color:{INK};margin:6px 0 8px">{escape(w["headline"])}</h1>')
    out.append(p(escape(w.get("summary", ""))))
    if k.get("methodBoundary"):
        when = f' on {pretty(k["methodChangeDate"])}' if k.get("methodChangeDate") else " this week"
        out.append(p(f'<strong>Method change{escape(when)}:</strong> our first reading under definitions v2.0, so AGI anywhere, A, C, D, '
                     f'D-open and the Index were re-derived under the new definition. Those changes are not news. '
                     f'{link(SITE + "changes.html#method", "What changed")}'))
    th = th_attr()
    td = f'style="{SANS}font-size:14px;color:{INK};padding:6px 8px;border-bottom:1px solid {RULE}"'
    dash = f'<span style="color:{MUTED}">–</span>'
    rows = [f"<tr><th {th}>Key number</th><th {th}>Today</th><th {th}>{span[0].upper() + span[1:]}</th><th {th}>By end-2030</th></tr>"]
    parts = k.get("agiParts")
    if parts and agi:
        n = len(agi["components"])
        rest = ", ".join(f'{parts[s]} {s}' for s in ("close", "partial", "far") if parts.get(s))
        rows.append(f'<tr><td {td}>{link(SITE + "agi.html", "AGI parts")}</td><td {td}><strong>{parts["met"]} of {n} met</strong></td>'
                    f'<td {td}><span style="color:{MUTED}">{escape(rest)}</span></td><td {td}>{dash}</td></tr>')
    a = k.get("agi") or {}
    if a.get("now") is not None:
        rows.append(f'<tr><td {td}>AGI anywhere, public or hidden</td><td {td}><strong>{fmt(a["now"])}%</strong></td>'
                    f'<td {td}>{email_delta(a["now"], k.get("agiWeekAgo"), "agi", k)}</td>'
                    f'<td {td}>{fmt(a["y2030"]) + "%" if a.get("y2030") is not None else dash}</td></tr>')
    rows.append(f'<tr><td {td}><strong>Hidden AGI Index</strong></td><td {td}><strong>{fmt(k["index"])}%</strong></td>'
                f'<td {td}>{email_delta(k["index"], k["indexWeekAgo"], "index", k)}</td><td {td}>{dash}</td></tr>')
    rows += [f'<tr><td {td}>{escape(label(h))}</td><td {td}><strong>{fmt(k["now"][h])}%</strong></td>'
             f'<td {td}>{email_delta(k["now"][h], k["weekAgo"][h], h, k)}</td><td {td}>{fmt(k["y2030"][h])}%</td></tr>' for h in KEYS]
    out.append(data_table(rows))
    if agi and pending_defs({"defs": k.get("defs")}, agi):
        txt = ("Set under the v1.0 bar; the next reading re-derives these numbers under definitions v2.0."
               if agi.get("adopted") else "These numbers use the v1.0 bar; definitions v2.0 are proposed.")
        out.append(p(f'<span style="color:{MUTED};font-size:13px">{escape(txt)}</span>'))
    if k.get("firstReading"):
        out.append(p(f'<span style="color:{MUTED};font-size:13px">This is our first full reading, so changes appear from the next wrap-up.</span>'))
    elif k.get("sinceFirst"):
        out.append(p(f'<span style="color:{MUTED};font-size:13px">Changes are since {pretty(k["weekAgoDate"])}, our first full reading.</span>'))
    gdefs = {d["key"]: d for d in json.loads((ROOT / "data/gauges.json").read_text())["gauges"]}
    gl = [f'<strong>{escape(gdefs[gk]["label"])}:</strong> {escape(g.get("display") or fmt(g.get("value")))} '
          f'({gauge_change(g, (k.get("gaugesWeekAgo") or {}).get(gk), span)})'
          for gk, g in (k.get("gauges") or {}).items() if g and gk in gdefs]
    if gl:
        out.append(p("<strong>Hiding-conditions gauges.</strong> " + " · ".join(gl)))
    tw = k["tripwires"]
    out.append(p(f'<strong>Tripwire signals:</strong> {signal_counts_text(tw)}. '
                 f'{link(SITE + "alarm.html#signals", "See them all")}.'))
    esc = k.get("escape")
    if esc:
        out.append(p(f'<strong>Escape watch:</strong> {esc["counts"]["tripped"]} of {esc["total"]} confirmed, '
                     f'{esc["counts"]["watching"]} open, {esc["counts"]["quiet"]} quiet. '
                     f'{link(SITE + "escape.html", "See the indicators")}.'))
    if w.get("moves"):
        out.append(h2("This week's moves"))
        out.append(ul(f'<strong>{escape(m.get("date", ""))}</strong> <strong>{escape(m.get("hyp", ""))}</strong> {escape(m["text"])}'
                      + source_link(m) for m in w["moves"]))
    for key, title, href in SECTIONS:
        note = w.get("sections", {}).get(key)
        if note:
            out.append(h2(title))
            out.append(p(escape(note) + " " + link(SITE + href, "Full section")))
    if jobs:  # the Jobs plugin's block, after the sections and before the closing links (plugin spec 8.2)
        import jobs_render
        out.append(jobs_render.email_html(jobs["edition"], jobs["claims"]))
    out.append(p(f'{link(url, "See the full wrap-up with graphs")} · {link(SITE, "Today’s reading")}', "margin-top:22px"))
    if usage_text(k):
        out.append(p(f'<span style="color:{MUTED};font-size:13px">{escape(usage_text(k))}</span>'))
    out.append(p(f'Forwarded this? {link(SUBSCRIBE, "Subscribe to Hidden AGI watch")}. It\'s free.'))
    out.append(email_footer("weekly"))
    return "".join(out)


def weekly_email_html_v1(w):
    """The email of a wrap-up built before redesign v2, unchanged (old labels and links)."""
    k = w["keyNumbers"]
    span = span_label(k)
    url = f'{SITE}weekly/{w["date"]}.html'
    lv = k.get("alarm")
    out = [p(f'<span style="color:{MUTED}">Weekly wrap-up · week to {pretty(w["date"])} · {link(url, "Read it on the web, with graphs")}</span>')]
    out.append(corrections_box(k.get("corrections")))
    if (ROOT / f'cards/weekly-{w["date"]}.png').exists():
        alt = f'Week to {pretty(w["date"])}: Hidden AGI Index {fmt(k["index"])}%' + (
            f', fire alarm Level {lv["level"]} ({lv["name"]})' if lv else "")
        out.append(f'<a href="{url}"><img src="{SITE}cards/weekly-{w["date"]}.png" width="580" height="305" alt="{escape(alt, quote=True)}" '
                   f'style="display:block;width:100%;max-width:600px;height:auto;border:0;border-radius:8px;margin:8px 0 14px"></a>')
    if lv:
        out.append(p(f'<strong><span aria-hidden="true">{lv["icon"]}</span> Fire alarm: Level {lv["level"]}, {escape(lv["name"])}.</strong> '
                     f'<span style="color:{MUTED}">{escape(lv.get("meaning", ""))} {link(SITE + "alarm.html", "Criteria")}</span>'))
    out.append(f'<h1 style="{FONT}font-size:24px;color:{INK};margin:6px 0 8px">{escape(w["headline"])}</h1>')
    out.append(p(escape(w.get("summary", ""))))
    th = th_attr()
    td = f'style="{SANS}font-size:14px;color:{INK};padding:6px 8px;border-bottom:1px solid {RULE}"'
    rows = [f"<tr><th {th}>Key number</th><th {th}>Now</th><th {th}>{span[0].upper() + span[1:]}</th><th {th}>By 2030</th></tr>",
            f'<tr><td {td}><strong>Hidden AGI Index</strong></td><td {td}><strong>{fmt(k["index"])}%</strong></td>'
            f'<td {td}>{delta_cell(k["index"], k["indexWeekAgo"])}</td><td {td}><span style="color:{MUTED}">–</span></td></tr>']
    rows += [f'<tr><td {td}>{escape(LABELS_V1[h])}</td><td {td}><strong>{fmt(k["now"][h])}%</strong></td>'
             f'<td {td}>{delta_cell(k["now"][h], k["weekAgo"][h])}</td><td {td}>{fmt(k["y2030"][h])}%</td></tr>' for h in KEYS]
    out.append(data_table(rows))
    if k.get("firstReading"):
        out.append(p(f'<span style="color:{MUTED};font-size:13px">This is our first full reading, so changes appear from the next wrap-up.</span>'))
    elif k.get("sinceFirst"):
        out.append(p(f'<span style="color:{MUTED};font-size:13px">Changes are since {pretty(k["weekAgoDate"])}, our first full reading.</span>'))
    gdefs = {d["key"]: d for d in json.loads((ROOT / "data/gauges.json").read_text())["gauges"]}
    gl = [f'<strong>{escape(gdefs[gk]["label"])}:</strong> {escape(g.get("display") or fmt(g.get("value")))} '
          f'({gauge_change(g, (k.get("gaugesWeekAgo") or {}).get(gk), span)})'
          for gk, g in (k.get("gauges") or {}).items() if g and gk in gdefs]
    if gl:
        out.append(p("<strong>The gauges.</strong> " + " · ".join(gl)))
    tw = k["tripwires"]
    out.append(p(f'<strong>Tripwires:</strong> {tw["tripped"]} tripped, {tw["watching"]} watching, {tw["quiet"]} quiet. '
                 f'{link(SITE + "#tripwires", "See them all")}.'))
    esc = k.get("escape")
    if esc:
        out.append(p(f'<strong>Escape watch:</strong> {escape_counts_text(esc)}. '
                     f'{link(SITE + "escape.html", "See the indicators")}.'))
    if w.get("moves"):
        out.append(h2("This week's moves"))
        out.append(ul(f'<strong>{escape(m.get("date", ""))}</strong> <strong>{escape(m.get("hyp", ""))}</strong> {escape(m["text"])}'
                      + source_link(m) for m in w["moves"]))
    for key, title, href in SECTIONS:
        if key == "agi":  # added in redesign v2; a frozen wrap-up has no such note
            continue
        note = w.get("sections", {}).get(key)
        if note:
            out.append(h2(title))
            out.append(p(escape(note) + " " + link(SITE + href, "Full section")))
    out.append(p(f'{link(url, "See the full wrap-up with graphs")} · {link(SITE, "Today’s reading")}', "margin-top:22px"))
    if usage_text(k):
        out.append(p(f'<span style="color:{MUTED};font-size:13px">{escape(usage_text(k))}</span>'))
    out.append(p(f'Forwarded this? {link(SUBSCRIBE, "Subscribe to Hidden AGI watch")}. It\'s free.'))
    out.append(email_footer("weekly"))
    return "".join(out)


# ---- build ---------------------------------------------------------------------------------------------------------

def build(date, allow_stale=False, refresh_snapshot=False):
    src = ROOT / f"data/weekly/{date}.json"
    w = json.loads(src.read_text())
    if "snapshot" in w and not is_v2(w) and not refresh_snapshot:
        sys.exit(f"build_weekly: weekly/{date}.html is a frozen wrap-up from before redesign v2; "
                 "past wrap-ups are not rebuilt.")
    w["date"] = date
    words = len(str(w.get("summary") or "").split())
    if words > DEK_WORDS:
        print(f"warning: the summary (the dek under the headline) is {words} words; keep it to {DEK_WORDS}.", file=sys.stderr)
    w["keyNumbers"] = key_numbers(date, allow_stale)
    if refresh_snapshot or "snapshot" not in w:
        if "snapshot" in w:
            print(f"note: replacing the frozen snapshot taken {w['snapshot'].get('taken', '?')} (--refresh-snapshot)")
        w["snapshot"] = snapshot(date)
    esc = escape_summary(w["snapshot"].get("escape"))  # from the frozen snapshot, so the tile never drifts
    if esc:
        w["keyNumbers"]["escape"] = esc
    if w["snapshot"].get("agi"):  # from the frozen parts, so the tile never drifts either
        w["keyNumbers"]["agiParts"] = status_counts(w["snapshot"]["agi"])
    usage = usage_week(date)
    if usage:
        w["keyNumbers"]["usage"] = usage
    src.write_text(json.dumps(w, indent=1, ensure_ascii=False) + "\n")
    import render_card
    render_card.weekly(date)
    card = f"{SITE}cards/weekly-{date}.png" if (ROOT / f"cards/weekly-{date}.png").exists() else None
    html = page(path=f"weekly/{date}.html", title=f"{w['headline']} · Weekly wrap-up · Hidden AGI watch",
                description=w.get("summary", "")[:200], body=page_body(w),
                og_image=card, og_type="article", scripts=page_script(w))
    (ROOT / "weekly").mkdir(exist_ok=True)
    (ROOT / f"weekly/{date}.html").write_text(html)
    idx_path = ROOT / "data/weekly/index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else {"wrapups": []}
    idx["wrapups"] = [x for x in idx["wrapups"] if x["date"] != date] + [{"date": date, "headline": w["headline"]}]
    idx_path.write_text(json.dumps(idx, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote weekly/{date}.html")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the Friday wrap-up page, card and key numbers.")
    ap.add_argument("date", help="wrap-up date, YYYY-MM-DD")
    ap.add_argument("--allow-stale", action="store_true", help="build even if no daily reading is published for that date")
    ap.add_argument("--refresh-snapshot", action="store_true",
                    help="recompute the frozen chart snapshot; only to fix a broken snapshot, since it changes a published archive")
    a = ap.parse_args()
    build(a.date, a.allow_stale, a.refresh_snapshot)
