#!/usr/bin/env python3
"""Validate the data and the latest report before anything is published. Read-only.

    python3 scripts/check_data.py [--allow-correction "reason"] [--warn-only]
    python3 scripts/check_data.py --pages      # visible-word budgets of the built pages; warnings only, exit 0

Prints one line per problem, each with a path such as runs[2].tripwires[0].status="Tripped",
and exits 1 if any ERROR remains. Warnings never fail the check.

  --allow-correction "reason"  a deliberate, public correction of published data: immutability
                               errors are listed as warnings instead. Honoured only when
                               data/corrections.json has gained a dated entry since HEAD.
  --warn-only                  report every problem as a warning and exit 0 (diagnosis only).

What it checks:
  (1) every data/*.json and data/weekly/*.json parses (no duplicate keys, no NaN);
  (2) runs.json: dates, unique report paths, probability ranges and coherence, and the shape of
      the latest report run (needle, tripwires, gauges, roundup, alarm);
  (3) alarm.json: level, met list, history, 90-day reviews, rule level, W4 on its 180-day window;
  (4) derived values: the oversight gauge is the incidents median, the money gauge is money.json;
  (5) URLs are http(s) or an existing relative path; denylisted domains;
  (6) the latest report: exists, two subscribe boxes, og:image/og:url/canonical for its date,
      its share card, and evidence tags;
  (7) immutability against git HEAD: past runs, made forecasts, alarm criteria, append-only
      logs, past reports;
  (8) no launch/ path staged or tracked, and no key-like strings in files git would commit;
  (9) redesign v2 (scripts/checks/): data/agi_components.json, the definitions in force and the method-change
      run, data/method.json, the newest format-2 run with its short report, analysis page and build_report
      render. Each rule is a no-op until its input exists.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

sys.dont_write_bytecode = True  # no scripts/__pycache__ for a commit to pick up (the repo has no .gitignore)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from alarm_check import (  # noqa: E402  (shared arithmetic, one implementation)
    exit_rule, id_key, incident_lags, iter_triggers, median, met_flags, parse_date, rule_level, w4_params,
)
import checks  # noqa: E402  (redesign v2 rules)
from checks import components as ck_components, method as ck_method, pages as ck_pages  # noqa: E402
from checks import reports_v2 as ck_reports  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://hiddenagi.com/"
SERIES = ["A", "B", "C", "D", "Dopen"]
HORIZONS = ["now", "y2030", "y2035"]
NEEDS_AGI = ["A", "C", "D", "Dopen"]  # B allows secret RSI short of AGI, so it isn't bounded by agi
STATUSES = {"quiet", "watching", "tripped"}
GAUGE_KINDS = {"measured", "estimated", "assessed"}
DENYLIST = ["shattered.io", "aitoolsreview.co.uk", "geotoolbox.ai", "aistop.watch", "aiweekly.co"]
HEDGES = ["reportedly", "leaked", "draft", "according to", "likely"]
EPS = 1e-9
MISSING = object()
KEY_PATTERNS = [
    ("a Kit API key or secret", re.compile(r"KIT_API_(?:SECRET|KEY)\s*[=:]\s*[\"']?[A-Za-z0-9_\-]{16,}")),
    ("an api_secret value", re.compile(r"api_secret[\"']?\s*[=:]\s*[\"']?[A-Za-z0-9_\-]{20,}", re.I)),
    ("an api_key value", re.compile(r"api_key[\"']?\s*[=:]\s*[\"']?[A-Za-z0-9_\-]{20,}", re.I)),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a GitHub token", re.compile(r"\b(?:gh[pous]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("a secret key", re.compile(r"\bsk[-_](?:live[-_])?[A-Za-z0-9]{24,}")),
    ("an AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".woff", ".woff2", ".ttf", ".otf", ".zip"}


class Findings:
    def __init__(self):
        self.errors, self.warnings, self.frozen = [], [], []

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def freeze(self, msg):
        """An immutability error: --allow-correction can turn it into a warning."""
        self.frozen.append(msg)


def js(value, limit=80):
    s = json.dumps(value, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit - 1] + "…"


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def num(value):
    return "–" if value is None else "%g" % value


def canon(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


# ---------- git ----------

class Git:
    def __init__(self, root, base):
        self.root, self.base = root, base
        self.ok = self._run("rev-parse", "--verify", "--quiet", base + "^{commit}") is not None

    def _run(self, *args):
        try:
            p = subprocess.run(["git", *args], cwd=str(self.root), capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else None

    def show(self, rel):
        """The file's text at the base commit, or None if the base lacks it."""
        return self._run("show", "%s:%s" % (self.base, rel)) if self.ok else None

    def show_json(self, rel):
        text = self.show(rel)
        if text is None:
            return None
        try:
            return json.loads(text)
        except ValueError:
            return None

    def lines(self, *args):
        out = self._run(*args)
        return [line for line in out.splitlines() if line] if out else []


# ---------- (1) syntax ----------

def load_all(root, f):
    """{relative path: parsed JSON or None} for data/*.json and data/weekly/*.json."""
    data = {}
    paths = sorted((root / "data").glob("*.json")) + sorted((root / "data/weekly").glob("*.json"))
    for path in paths:
        rel = path.relative_to(root).as_posix()
        dups, consts = [], []

        def pairs(items, dups=dups):
            seen = set()
            for k, _ in items:
                if k in seen:
                    dups.append(k)
                seen.add(k)
            return dict(items)

        def const(name, consts=consts):
            consts.append(name)
            return None

        try:
            data[rel] = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=const)
        except ValueError as e:
            f.err("%s: invalid JSON: %s" % (rel, e))
            data[rel] = None
            continue
        except OSError as e:
            f.err("%s: can't be read: %s" % (rel, e))
            data[rel] = None
            continue
        for k in sorted(set(dups)):
            f.err("%s: duplicate key %s (the later value silently wins)" % (rel, js(k)))
        for c in sorted(set(consts)):
            f.err("%s: %s is not valid JSON for browsers" % (rel, c))
    return data


# ---------- (2) runs ----------

def check_series(f, path, s):
    if not isinstance(s, dict):
        f.err("%s is missing" % path)
        return {}
    vals = {}
    for h in HORIZONS:
        v = s.get(h, MISSING)
        if not is_num(v):
            f.err("%s.%s=%s is not a number" % (path, h, "missing" if v is MISSING else js(v)))
            continue
        if v < 0 or v > 100:
            f.err("%s.%s=%s is outside 0–100" % (path, h, v))
        vals[h] = v
    if len(vals) == 3 and not (vals["now"] <= vals["y2030"] + EPS and vals["y2030"] <= vals["y2035"] + EPS):
        f.err("%s: now %s ≤ y2030 %s ≤ y2035 %s fails (the horizons are cumulative: 'by 2030')" % (
            path, vals["now"], vals["y2030"], vals["y2035"]))
    return vals


def check_probs(f, p, r, newest):
    probs = r.get("probs")
    if not isinstance(probs, dict):
        f.err("%s.probs is missing" % p)
        return
    v = {k: check_series(f, "%s.probs.%s" % (p, k), probs.get(k)) for k in SERIES}
    agi = r.get("agi")
    if agi is None:
        if r.get("report"):
            f.err("%s.agi is missing" % p)
    else:
        v["agi"] = check_series(f, "%s.agi" % p, agi)
        for k in NEEDS_AGI:
            for h in HORIZONS:
                if h in v[k] and h in v["agi"] and v[k][h] > v["agi"][h] + EPS:
                    f.err("%s.probs.%s.%s=%s is above agi.%s=%s; %s needs an AGI-level system (definitions in "
                          "force: v%s)" % (p, k, h, v[k][h], h, v["agi"][h], k, r.get("defs") or "1.0"))
    nows = [v[k].get("now") for k in "ABCD"]
    idx = r.get("index", MISSING)
    if idx is MISSING or idx is None:
        if r.get("report"):
            f.err("%s.index is missing" % p)
    elif not is_num(idx):
        f.err("%s.index=%s is not a number" % (p, js(idx)))
    elif all(is_num(n) for n in nows):
        lo, hi = max(nows), min(100, sum(nows))
        if idx < lo - EPS or idx > hi + EPS:
            f.err("%s.index=%s is outside [%s, %s]: at least the largest of A–D now, at most their sum" % (
                p, idx, round(lo, 3), round(hi, 3)))
    if r.get("date") == newest and "agi" in v:
        a_now, agi_now, d_now = v["A"].get("now"), v["agi"].get("now"), v["Dopen"].get("now")
        if is_num(a_now) and is_num(agi_now) and is_num(d_now) and d_now > agi_now - a_now + EPS:
            f.warn("%s.probs.Dopen.now=%s is above agi.now − A.now = %s: that needs acknowledged government use "
                   "of a system whose AGI-level capability is undisclosed; the report must say so" % (
                       p, d_now, round(agi_now - a_now, 3)))


def check_latest_shape(f, p, r, gauge_keys, alarm, trigger_ids):
    needle = r.get("needle")
    if not isinstance(needle, dict):
        f.err("%s.needle=%s must be an object" % (p, js(needle)))
    elif not needle.get("quiet") and not isinstance(needle.get("headline"), str):
        f.warn("%s.needle has no headline and isn't marked quiet" % p)

    tws = r.get("tripwires")
    if not isinstance(tws, list):
        f.err("%s.tripwires=%s must be a list" % (p, js(tws)))
        tws = []
    seen = set()
    for j, t in enumerate(tws):
        tp = "%s.tripwires[%d]" % (p, j)
        if not isinstance(t, dict):
            f.err("%s must be an object" % tp)
            continue
        if t.get("status") not in STATUSES:
            f.err("%s.status=%s must be quiet, watching or tripped" % (tp, js(t.get("status"))))
        if not isinstance(t.get("id"), str) or not t.get("id"):
            f.err("%s.id is missing" % tp)
        elif t["id"] in seen:
            f.err("%s.id=%s is a duplicate" % (tp, js(t["id"])))
        seen.add(t.get("id"))
        trig = t.get("trigger")
        if trig is not None and trig not in trigger_ids:
            f.err("%s.trigger=%s is not an alarm trigger id" % (tp, js(trig)))
        if t.get("since") is not None and parse_date(t.get("since")) is None:
            f.err("%s.since=%s is not YYYY-MM-DD" % (tp, js(t.get("since"))))

    gauges = r.get("gauges")
    if not isinstance(gauges, dict):
        f.err("%s.gauges=%s must be an object" % (p, js(gauges)))
        gauges = {}
    for k, g in gauges.items():
        gp = "%s.gauges.%s" % (p, k)
        if gauge_keys is not None and k not in gauge_keys:
            f.err("%s: %s is not a gauge in data/gauges.json" % (gp, js(k)))
        if not isinstance(g, dict):
            f.err("%s must be an object" % gp)
            continue
        if not is_num(g.get("value")):
            f.err("%s.value=%s is not a number" % (gp, js(g.get("value"))))
        if not isinstance(g.get("display"), str):
            f.err("%s.display=%s is not a string" % (gp, js(g.get("display"))))

    for k in ("timeline", "summary"):
        if not isinstance(r.get(k), str):
            f.err("%s.%s=%s must be a string" % (p, k, js(r.get(k))))
    for k in ("changes", "signals"):
        val = r.get(k)
        if not isinstance(val, list):
            f.err("%s.%s=%s must be a list of strings" % (p, k, js(val)))
            continue
        for j, s in enumerate(val):
            if not isinstance(s, str):
                f.err("%s.%s[%d]=%s must be a string" % (p, k, j, js(s)))

    roundup = r.get("roundup")
    if not isinstance(roundup, list):
        f.err("%s.roundup=%s must be a list of {topic, items}" % (p, js(roundup)))
        roundup = []
    for j, sec in enumerate(roundup):
        sp = "%s.roundup[%d]" % (p, j)
        if not isinstance(sec, dict):
            f.err("%s must be an object" % sp)
            continue
        if not isinstance(sec.get("topic"), str):
            f.err("%s.topic=%s must be a string" % (sp, js(sec.get("topic"))))
        items = sec.get("items")
        if not isinstance(items, list):
            f.err("%s.items=%s must be a list" % (sp, js(items)))
            continue
        for m, it in enumerate(items):
            ip = "%s.items[%d]" % (sp, m)
            if not isinstance(it, dict) or not isinstance(it.get("text"), str):
                f.err("%s.text is missing" % ip)
            elif "top" in it and not isinstance(it["top"], bool):
                f.err("%s.top=%s must be true or false" % (ip, js(it["top"])))

    ra = r.get("alarm")
    cur = alarm.get("current") if isinstance(alarm, dict) and isinstance(alarm.get("current"), dict) else None
    if cur is not None:
        want = {"level": cur.get("level"), "met": sorted(cur.get("met") or [], key=id_key)}
        got = None
        if isinstance(ra, dict):
            got = {"level": ra.get("level"), "met": sorted(ra.get("met") or [], key=id_key)}
        if got != want:
            f.err("%s.alarm=%s must equal alarm.json current %s" % (p, js(ra), js(want)))


def check_runs(f, runs, data, today):
    if not isinstance(runs, list):
        f.err("runs.json must be a list of runs")
        return None, None, None
    newest, prev, reports = None, None, {}
    for i, r in enumerate(runs):
        p = "runs[%d]" % i
        if not isinstance(r, dict):
            f.err("%s must be an object" % p)
            continue
        d = parse_date(r.get("date"))
        if d is None:
            f.err("%s.date=%s is not YYYY-MM-DD" % (p, js(r.get("date"))))
        else:
            if prev is not None and d < prev:
                f.err("%s.date=%s is earlier than the run before it (%s); runs must be in date order" % (
                    p, js(r["date"]), prev.isoformat()))
            if d > today:
                f.warn("%s.date=%s is in the future" % (p, js(r["date"])))
            prev = d
            newest = r["date"] if newest is None or r["date"] > newest else newest
        rep = r.get("report")
        if rep is not None:
            if not isinstance(rep, str) or not rep:
                f.err("%s.report=%s must be a path" % (p, js(rep)))
            elif rep in reports:
                f.err("%s.report=%s repeats runs[%d].report: a rerun must replace that day's entry, not append "
                      "(the report path is the feed GUID)" % (p, js(rep), reports[rep]))
            else:
                reports[rep] = i
                if not (ROOT_DIR / rep).is_file():
                    f.err("%s.report=%s does not exist" % (p, js(rep)))
        if "comparable" in r and not isinstance(r["comparable"], bool):
            f.err("%s.comparable=%s must be true or false" % (p, js(r["comparable"])))
    for i, r in enumerate(runs):
        if isinstance(r, dict):
            check_probs(f, "runs[%d]" % i, r, newest)
    latest = None
    for i in range(len(runs) - 1, -1, -1):
        if isinstance(runs[i], dict) and runs[i].get("report"):
            latest = i
            break
    if latest is None:
        f.err("runs.json has no run with a report")
        return newest, None, None
    alarm = data.get("data/alarm.json")
    gdoc = data.get("data/gauges.json")
    gauge_keys = None
    if isinstance(gdoc, dict) and isinstance(gdoc.get("gauges"), list):
        gauge_keys = {g.get("key") for g in gdoc["gauges"] if isinstance(g, dict)}
        for j, g in enumerate(gdoc["gauges"]):
            if isinstance(g, dict) and g.get("kind") not in GAUGE_KINDS:
                f.warn("gauges.gauges[%d].kind=%s is not measured, estimated or assessed" % (j, js(g.get("kind"))))
    trigger_ids = {t.get("id") for _, t in iter_triggers(alarm)} if isinstance(alarm, dict) else set()
    check_latest_shape(f, "runs[%d]" % latest, runs[latest], gauge_keys, alarm, trigger_ids)
    check_moves(f, runs, latest)
    return newest, latest, runs[latest]


def check_moves(f, runs, latest):
    """Warn when a 'now' value moved from the previous comparable reading and no change line names it."""
    prev = None
    for i in range(latest - 1, -1, -1):
        r = runs[i]
        if isinstance(r, dict) and r.get("report") and r.get("comparable") is not False:
            prev = r
            break
    cur = runs[latest]
    if prev is None or not isinstance(prev.get("probs"), dict) or not isinstance(cur.get("probs"), dict):
        return
    text = " ".join(s for s in cur.get("changes") or [] if isinstance(s, str))
    names = {"A": r"\bA\b", "B": r"\bB\b", "C": r"\bC\b", "D": r"\bD\b(?!-open)", "Dopen": r"D-open|Dopen"}
    for k in SERIES:
        a = (prev["probs"].get(k) or {}).get("now")
        b = (cur["probs"].get(k) or {}).get("now")
        if is_num(a) and is_num(b) and a != b and not re.search(names[k], text):
            f.warn("runs[%d].probs.%s.now moved %s → %s but no line in changes mentions %s" % (latest, k, a, b, k))


# ---------- (3) alarm ----------

def check_alarm(f, alarm, latest_run, incidents):
    if not isinstance(alarm, dict):
        return
    levels = {lv.get("level") for lv in alarm.get("levels") or [] if isinstance(lv, dict)}
    cur = alarm.get("current") if isinstance(alarm.get("current"), dict) else {}
    if cur.get("level") not in levels:
        f.err("alarm.current.level=%s is not one of the defined levels %s" % (js(cur.get("level")), sorted(levels)))
    _, _, problem = exit_rule(alarm)
    if problem:
        f.err(problem)
    ids = []
    for gi, g in enumerate(alarm.get("groups") or []):
        if not isinstance(g, dict):
            continue
        for ti, t in enumerate(g.get("triggers") or []):
            if not isinstance(t, dict):
                continue
            tp = "alarm.groups[%d].triggers[%d]" % (gi, ti)
            ids.append(t.get("id"))
            if "met" in t and not isinstance(t["met"], bool):
                f.err("%s.met=%s must be true or false" % (tp, js(t["met"])))
            if t.get("met") is True:
                missing = [k for k in ("since", "evidence", "url") if not t.get(k)]
                if missing:
                    f.err("%s (%s) is met but has no %s" % (tp, t.get("id"), ", ".join(missing)))
            for k in ("since", "watchFrom", "eventDate", "meetsOn", "expires"):
                if t.get(k) is not None and parse_date(t.get(k)) is None:
                    f.err("%s.%s=%s is not YYYY-MM-DD" % (tp, k, js(t.get(k))))
    for tid in sorted({i for i in ids if ids.count(i) > 1}, key=id_key):
        f.err("alarm: trigger id %s appears more than once" % js(tid))
    flags = met_flags(alarm)
    cur_met = cur.get("met") if isinstance(cur.get("met"), list) else None
    if cur_met is None or sorted(cur_met, key=id_key) != flags:
        f.err("alarm.current.met=%s but the triggers marked met are %s" % (js(cur.get("met")), js(flags)))
    history = alarm.get("history")
    if not isinstance(history, list) or not history:
        f.err("alarm.history must be a non-empty list")
    else:
        last = history[-1] if isinstance(history[-1], dict) else {}
        if last.get("to") != cur.get("level"):
            f.err("alarm.history[-1].to=%s but current.level=%s" % (js(last.get("to")), js(cur.get("level"))))
        if last.get("date") != cur.get("since"):
            f.err("alarm.history[-1].date=%s but current.since=%s" % (js(last.get("date")), js(cur.get("since"))))
        prev = None
        for i, h in enumerate(history):
            if not isinstance(h, dict):
                f.err("alarm.history[%d] must be an object" % i)
                continue
            d = parse_date(h.get("date"))
            if d is None:
                f.err("alarm.history[%d].date=%s is not YYYY-MM-DD" % (i, js(h.get("date"))))
                continue
            if prev is not None and d < prev:
                f.err("alarm.history[%d].date=%s is earlier than the entry before it" % (i, js(h["date"])))
            prev = d
            want = (d + timedelta(days=90)).isoformat()
            if h.get("reviewDue") != want:
                f.err("alarm.history[%d].reviewDue=%s must be date + 90 days (%s)" % (i, js(h.get("reviewDue")), want))
    computed = rule_level(alarm)
    level = cur.get("level")
    if is_num(level) and level < computed:
        f.err("alarm.current.level=%s is below the level the met triggers give (%s); a level rises the day its "
              "trigger is met" % (level, computed))
    elif is_num(level) and level > computed:
        f.warn("alarm.current.level=%s is above the rule level %s: allowed only while the 30-day hold-down runs "
               "(see scripts/alarm_check.py)" % (level, computed))
    ref = parse_date(latest_run.get("date")) if isinstance(latest_run, dict) else None
    if isinstance(incidents, dict) and ref is not None:
        window, threshold = w4_params(alarm)
        lags = incident_lags(incidents, ref=ref, window=window)
        med = median(lag for _, lag in lags)
        should = med is not None and med >= threshold
        w4 = next((t for _, t in iter_triggers(alarm) if t.get("id") == "W4"), None)
        if w4 is not None and (w4.get("met") is True) != should:
            f.err("alarm W4.met=%s but the median lag of the %d incidents disclosed in the %d days before %s is %s "
                  "days (threshold %d)" % (js(w4.get("met")), len(lags), window, ref.isoformat(), num(med), threshold))


# ---------- (4) derived values ----------

def check_derived(f, latest, run, data, git):
    if not isinstance(run, dict) or not isinstance(run.get("gauges"), dict):
        return
    p = "runs[%d].gauges" % latest
    run_unchanged = False
    if git.ok:
        head_runs = git.show_json("data/runs.json")
        run_unchanged = isinstance(head_runs, list) and canon(run) in {canon(r) for r in head_runs}

    def report(msg, source):
        # The weekly job refreshes incidents and money after the day's run was published: then the
        # next daily run carries the new number, so a mismatch is only a warning.
        if run_unchanged and git.show(source) != _read(source):
            f.warn(msg + " (%s changed after this run was published; the next run should use the new value)" % source)
        else:
            f.err(msg)

    over = run["gauges"].get("oversight")
    incidents = data.get("data/incidents.json")
    if isinstance(over, dict) and is_num(over.get("value")) and isinstance(incidents, dict):
        lags = incident_lags(incidents, ref=parse_date(run.get("date")))
        med = median(lag for _, lag in lags)
        if med is not None and abs(over["value"] - med) > 1:
            report("%s.oversight.value=%s but the median lag across the %d incidents in data/incidents.json is %s "
                   "days" % (p, over["value"], len(lags), num(med)), "data/incidents.json")
    money = run["gauges"].get("money")
    mdoc = data.get("data/money.json")
    if isinstance(money, dict) and is_num(money.get("value")):
        ttm = (mdoc.get("ttm") or {}).get("usd_b") if isinstance(mdoc, dict) else None
        if not is_num(ttm):
            f.err("%s.money is set but data/money.json has no ttm.usd_b" % p)
        elif abs(money["value"] - ttm) > 0.05:
            report("%s.money.value=%s but data/money.json ttm.usd_b=%s" % (p, money["value"], ttm), "data/money.json")


def _read(rel):
    try:
        return (ROOT_DIR / rel).read_text(encoding="utf-8")
    except OSError:
        return None


# ---------- (5) URLs ----------

def denylisted(host):
    host = (host or "").lower().rstrip(".")
    return next((d for d in DENYLIST if host == d or host.endswith("." + d)), None)


def check_url(f, where, url, strict):
    """strict: a denylisted domain is an error here (alarm, gauge, needle, tripwire, forecast)."""
    if not isinstance(url, str):
        f.err("%s=%s must be a string" % (where, js(url)))
        return
    if not url:
        return
    if url != url.strip():
        f.err("%s=%s has surrounding whitespace" % (where, js(url)))
    s = url.strip()
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.\-]*):", s)
    if m:
        if m.group(1).lower() not in ("http", "https"):
            f.err("%s=%s: only http(s) or a relative path is allowed" % (where, js(url)))
            return
        host = urlsplit(s).hostname
        if not host:
            f.err("%s=%s has no host" % (where, js(url)))
            return
        bad = denylisted(host)
        if bad:
            msg = "%s=%s: %s is a denylisted aggregator; cite the primary source" % (where, js(url), bad)
            (f.err if strict else f.warn)(msg)
        return
    if s.startswith("//"):
        f.err("%s=%s: protocol-relative URLs aren't allowed" % (where, js(url)))
        return
    path = s.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return
    while path.startswith("./"):
        path = path[2:]
    if path.startswith("../"):  # written for a page one folder down (reports/, weekly/)
        path = path[3:]
    target = (ROOT_DIR / path).resolve()
    if ROOT_DIR.resolve() not in target.parents and target != ROOT_DIR.resolve():
        f.err("%s=%s points outside the site" % (where, js(url)))
    elif not target.exists():
        f.err("%s=%s is not http(s) and no such file exists" % (where, js(url)))


URL_KEY = re.compile(r"(?:^|[a-z_])(?:url|href|link)s?$", re.I)
BAD_SCHEME = re.compile(r"^\s*(?:javascript|vbscript|data|file):", re.I)


def walk_urls(f, obj, where, strict_fn):
    if isinstance(obj, dict):
        for k, v in obj.items():
            w = "%s.%s" % (where, k)
            if URL_KEY.search(k) and not isinstance(v, (dict, list)):
                if v is not None:
                    check_url(f, w, v, strict_fn(w))
            elif URL_KEY.search(k) and isinstance(v, list) and all(isinstance(x, str) for x in v):
                for i, x in enumerate(v):
                    check_url(f, "%s[%d]" % (w, i), x, strict_fn(w))
            elif k == "source" and isinstance(v, str) and re.match(r"^[a-z]+:", v, re.I):
                check_url(f, w, v, strict_fn(w))
            else:
                walk_urls(f, v, w, strict_fn)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk_urls(f, v, "%s[%d]" % (where, i), strict_fn)
    elif isinstance(obj, str) and BAD_SCHEME.match(obj):
        f.err("%s=%s: script or data URLs aren't allowed in data" % (where, js(obj)))


def check_data_urls(f, data, runs, newest):
    newest_runs = set()
    if isinstance(runs, list):
        newest_runs = {"runs[%d]" % i for i, r in enumerate(runs) if isinstance(r, dict) and r.get("date") == newest}
    for rel, doc in data.items():
        if doc is None:
            continue
        stem = Path(rel).stem if not rel.startswith("data/weekly/") else "weekly/" + Path(rel).stem

        def strict(w, rel=rel):
            if rel == "data/alarm.json":
                return ".groups[" in w
            if rel in ("data/forecasts.json", "data/gauges.json", "data/agi_components.json"):
                return True
            if rel == "data/runs.json":
                m = re.match(r"runs(\[\d+\])\.(gauges|needle|tripwires)\b", w)
                return bool(m) and "runs" + m.group(1) in newest_runs
            return False

        if rel == "data/runs.json":
            walk_urls(f, doc, "runs", strict)
        else:
            # A top-level "fields" block documents the schema (incidents.json, corrections.json):
            # its values describe fields such as "url" in prose, so they aren't URLs.
            if isinstance(doc, dict) and "fields" in doc:
                doc = {k: v for k, v in doc.items() if k != "fields"}
            walk_urls(f, doc, stem, strict)


class PageScan(HTMLParser):
    """Collects what the report checks need: subscribe boxes, head tags, links, fact-tagged items."""
    BLOCKS = {"li", "td", "dd"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.subscribe, self.meta, self.canonical = 0, {}, None
        self.links, self.stack, self.facts = [], [], []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        cls = a.get("class", "").split()
        if "subscribe" in cls:
            self.subscribe += 1
        if tag == "meta" and (a.get("property") or a.get("name")):
            self.meta[a.get("property") or a.get("name")] = a.get("content")
        if tag == "link" and "canonical" in a.get("rel", "").lower().split():
            self.canonical = a.get("href")
        for k in ("href", "src"):
            if a.get(k):
                self.links.append(a[k])
        if tag in self.BLOCKS:
            self.stack.append({"fact": False, "link": False, "text": []})
        elif self.stack:
            if tag == "span" and "tag" in cls and "fact" in cls:
                self.stack[-1]["fact"] = True
            if tag == "a" and a.get("href"):
                self.stack[-1]["link"] = True

    def handle_endtag(self, tag):
        if tag in self.BLOCKS and self.stack:
            item = self.stack.pop()
            if item["fact"]:
                self.facts.append((" ".join("".join(item["text"]).split()), item["link"]))

    def handle_data(self, data):
        if self.stack:
            self.stack[-1]["text"].append(data)


def scan_page(path):
    scan = PageScan()
    scan.feed(path.read_text(encoding="utf-8"))
    scan.close()
    return scan


def check_page_links(f, root):
    for path in sorted(root.glob("reports/*.html")) + sorted(root.glob("weekly/*.html")):
        rel = path.relative_to(root).as_posix()
        try:
            scan = scan_page(path)
        except (OSError, UnicodeDecodeError) as e:
            f.err("%s can't be read: %s" % (rel, e))
            continue
        for href in sorted(set(scan.links)):
            if re.match(r"^https?:", href, re.I):
                bad = denylisted(urlsplit(href).hostname)
                if bad:
                    f.warn("%s links to %s (%s): cite the primary source, or mark it 'via'" % (rel, bad, js(href)))


# ---------- (6) the latest report ----------

def check_report(f, latest, run):
    if not isinstance(run, dict):
        return
    d, rep = run.get("date"), run.get("report")
    p = "runs[%d]" % latest
    if not isinstance(rep, str):
        return
    if rep != "reports/%s.html" % d:
        f.err("%s.report=%s should be reports/%s.html" % (p, js(rep), d))
    path = ROOT_DIR / rep
    if not path.is_file():
        f.err("%s: the latest report does not exist" % rep)
        return
    scan = scan_page(path)
    if scan.subscribe != 2:
        f.err("%s: %d subscribe boxes; a report needs exactly two (after the header and before the footer)" % (
            rep, scan.subscribe))
    own = "reports/%s.html" % d
    for label, value, suffix in (("og:image", scan.meta.get("og:image"), "cards/%s.png" % d),
                                 ("og:url", scan.meta.get("og:url"), own),
                                 ("canonical", scan.canonical, own)):
        if not value:
            f.err("%s: no %s" % (rep, label))
        elif not value.endswith(suffix):
            f.err("%s: %s=%s should point at %s" % (rep, label, js(value), suffix))
        elif not value.startswith(SITE):
            f.warn("%s: %s=%s is not an absolute %s URL" % (rep, label, js(value), SITE))
    if not (ROOT_DIR / ("cards/%s.png" % d)).is_file():
        f.err("cards/%s.png (the report's share card) does not exist; run scripts/render_card.py" % d)
    for text, linked in scan.facts:
        snippet = js(text, 90)
        if not linked:
            f.warn("%s: fact-tagged item has no link: %s" % (rep, snippet))
        low = text.lower()
        for word in HEDGES:
            if re.search(r"\b%s\b" % re.escape(word), low):
                f.warn("%s: fact-tagged item says %s; tag it report or cite the primary source: %s" % (
                    rep, js(word), snippet))


# ---------- (7) immutability ----------

def entry_changes(he, we):
    """Keys of a frozen entry that changed; adding a key or filling a null one is allowed."""
    if not isinstance(he, dict) or not isinstance(we, dict):
        return ["(whole entry)"] if canon(he) != canon(we) else []
    return [k for k, v in he.items() if v is not None and canon(we.get(k)) != canon(v)]


def append_only(f, label, head, work, key=None):
    if not isinstance(head, list):
        return
    if not isinstance(work, list):
        f.freeze("%s is no longer a list" % label)
        return
    if key and all(isinstance(e, dict) and e.get(key) is not None for e in head) and \
            len({canon(e.get(key)) for e in head}) == len(head):
        wmap = {}
        for i, e in enumerate(work):
            if isinstance(e, dict) and e.get(key) is not None:
                wmap.setdefault(canon(e.get(key)), (i, e))
        for he in head:
            hit = wmap.get(canon(he.get(key)))
            if hit is None:
                f.freeze("%s: entry %s=%s was removed; it is append-only" % (label, key, js(he.get(key))))
                continue
            changed = entry_changes(he, hit[1])
            if changed:
                f.freeze("%s[%d] (%s=%s): %s changed since HEAD; entries are append-only (add fields, never edit)" % (
                    label, hit[0], key, js(he.get(key)), ", ".join(changed)))
        return
    if len(work) < len(head):
        f.freeze("%s: %d entries at HEAD, %d now; it is append-only" % (label, len(head), len(work)))
    for i, he in enumerate(head[:len(work)]):
        changed = entry_changes(he, work[i])
        if changed:
            f.freeze("%s[%d]: %s changed since HEAD; entries are append-only (add fields, never edit)" % (
                label, i, ", ".join(changed)))


def criteria(alarm):
    groups = []
    for g in alarm.get("groups") or []:
        if isinstance(g, dict):
            groups.append({"level": g.get("level"), "rule": g.get("rule"),
                           "triggers": [{k: t.get(k) for k in ("id", "trigger", "threshold", "why")}
                                        for t in g.get("triggers") or [] if isinstance(t, dict)]})
    return {"levels": alarm.get("levels"), "rules": alarm.get("rules"),
            "evidenceStandard": alarm.get("evidenceStandard"), "groups": groups}


def diff_paths(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in list(a) + [k for k in b if k not in a]:
            out += diff_paths(a.get(k, MISSING), b.get(k, MISSING), "%s.%s" % (path, k) if path else k)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_paths(x, y, "%s[%d]" % (path, i))
        return out
    if a is MISSING or b is MISSING or canon(a) != canon(b):
        return [path]
    return []


def check_immutability(f, git, data, runs, newest):
    # runs dated before the newest date
    head_runs = git.show_json("data/runs.json")
    if isinstance(head_runs, list) and isinstance(runs, list) and newest:
        def by_date(rs):
            out = {}
            for i, r in enumerate(rs):
                if isinstance(r, dict) and isinstance(r.get("date"), str) and r["date"] < newest:
                    out.setdefault(r["date"], []).append((i, r))
            return out
        hd, wd = by_date(head_runs), by_date(runs)
        for d in sorted(set(hd) | set(wd)):
            h, w = hd.get(d, []), wd.get(d, [])
            if len(h) != len(w):
                f.freeze("runs dated %s: %d at HEAD, %d now; past runs are frozen (only runs dated %s may change)" % (
                    d, len(h), len(w), newest))
                continue
            for (_, hr), (wi, wr) in zip(h, w):
                keys = [k for k in sorted(set(hr) | set(wr)) if canon(hr.get(k)) != canon(wr.get(k))]
                if keys:
                    f.freeze("runs[%d] (%s): %s changed since HEAD; past runs are frozen" % (wi, d, ", ".join(keys)))
        now_reports = {r.get("report") for r in runs if isinstance(r, dict)}
        for r in head_runs:
            if isinstance(r, dict) and r.get("report") and r["report"] not in now_reports:
                f.freeze("runs: report %s was removed or renamed; a report path is its feed GUID" % js(r["report"]))

    # forecasts
    hf, wf = git.show_json("data/forecasts.json"), data.get("data/forecasts.json")
    if isinstance(hf, dict) and isinstance(wf, dict):
        wmap = {x.get("id"): (i, x) for i, x in enumerate(wf.get("forecasts") or []) if isinstance(x, dict)}
        for h in hf.get("forecasts") or []:
            if not isinstance(h, dict):
                continue
            hit = wmap.get(h.get("id"))
            if hit is None:
                f.freeze("forecasts: %s was removed; withdraw a forecast with outcome \"void\" instead" % (
                    js(h.get("id"))))
                continue
            i, w = hit
            for k in ("id", "made", "question", "p", "deadline", "resolution"):
                if canon(h.get(k)) != canon(w.get(k)):
                    f.freeze("forecasts.forecasts[%d].%s (%s) changed: %s → %s; a made forecast is never edited" % (
                        i, k, h.get("id"), js(h.get(k), 50), js(w.get(k), 50)))
            for k in ("outcome", "resolved"):
                if h.get(k) is not None and canon(h.get(k)) != canon(w.get(k)):
                    f.freeze("forecasts.forecasts[%d].%s (%s) changed: %s → %s; a resolved outcome never reverts" % (
                        i, k, h.get("id"), js(h.get(k)), js(w.get(k))))

    # alarm criteria and history
    ha, wa = git.show_json("data/alarm.json"), data.get("data/alarm.json")
    if isinstance(ha, dict) and isinstance(wa, dict):
        hlog = ha.get("changelog") if isinstance(ha.get("changelog"), list) else []
        wlog = wa.get("changelog") if isinstance(wa.get("changelog"), list) else []
        append_only(f, "alarm.changelog", hlog, wlog)
        append_only(f, "alarm.history", ha.get("history"), wa.get("history"))
        changed = diff_paths(criteria(ha), criteria(wa))
        if changed:
            shown = ", ".join(changed[:6]) + (" …" if len(changed) > 6 else "")
            if len(wlog) > len(hlog):
                f.warn("alarm criteria changed under changelog %s: %s" % (
                    js((wlog[-1] or {}).get("version") if isinstance(wlog[-1], dict) else None), shown))
                if wa.get("version") == ha.get("version"):
                    f.warn("alarm.version is still %s although the changelog grew" % js(wa.get("version")))
            else:
                f.freeze("alarm criteria changed without a changelog entry: %s; criteria change only with a dated, "
                         "versioned changelog entry, never while a level change is considered" % shown)

    # append-only logs
    for rel, field, label, key in (("data/steelman.json", "entries", "steelman.entries", "date"),
                                   ("data/incidents.json", "incidents", "incidents.incidents", "id"),
                                   ("data/corrections.json", "corrections", "corrections.corrections", None)):
        h, w = git.show_json(rel), data.get(rel)
        if isinstance(h, dict) and isinstance(w, dict):
            append_only(f, label, h.get(field), w.get(field), key)

    # past reports
    note = re.compile(r"\b(?:Update[ds]?|Corrections?)\b")
    for rel in git.lines("ls-tree", "--name-only", git.base, "reports/"):
        m = re.search(r"(\d{4}-\d{2}-\d{2})(?:-analysis)?\.html$", rel)
        if not m or not newest or m.group(1) >= newest:
            continue
        w, h = _read(rel), git.show(rel)
        if w is None:
            f.freeze("%s was removed; past reports are frozen (the path is the feed GUID)" % rel)
        elif h is not None and w != h:
            if len(note.findall(w)) > len(note.findall(h)):
                f.warn("%s changed since HEAD and gained an Update/Correction note" % rel)
            else:
                f.freeze("%s changed since HEAD without an \"Update\" or \"Correction\" note; past reports are "
                         "frozen" % rel)


def corrections_gained(git, data):
    """True when data/corrections.json has a dated entry that HEAD doesn't."""
    doc = data.get("data/corrections.json")
    items = doc.get("corrections") if isinstance(doc, dict) else doc if isinstance(doc, list) else None
    if not isinstance(items, list):
        return False
    head = git.show_json("data/corrections.json")
    old = head.get("corrections") if isinstance(head, dict) else head if isinstance(head, list) else []
    old = {canon(x) for x in old or []}
    return any(isinstance(x, dict) and parse_date(x.get("date")) and canon(x) not in old for x in items)


# ---------- (8) git hygiene ----------

def check_git(f, git):
    for rel in git.lines("diff", "--cached", "--name-only"):
        if rel == "launch" or rel.startswith("launch/"):
            f.err("%s is staged: launch/ is private and never committed" % rel)
    for rel in git.lines("ls-files", "--", "launch"):
        f.err("%s is tracked: launch/ is private and never committed" % rel)
    files = set(git.lines("ls-files")) | set(git.lines("ls-files", "--others", "--exclude-standard"))
    for rel in sorted(files):
        if rel.startswith("launch/") or Path(rel).suffix.lower() in BINARY_EXT:
            continue
        path = ROOT_DIR / rel
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:8192] or len(raw) > 20 * 1024 * 1024:
            continue
        text = raw.decode("utf-8", "replace")
        hits = {}
        for label, pat in KEY_PATTERNS:
            for m in pat.finditer(text):
                hits.setdefault(text.count("\n", 0, m.start()) + 1, label)
        for line in sorted(hits):
            f.err("%s:%d looks like %s; never commit keys (value not shown)" % (rel, line, hits[line]))


# ---------- (9) redesign v2: scripts/checks/ ----------

def v2_context(f, data, git, today):
    return checks.Ctx(f=f, root=ROOT_DIR, data=data, git=git, today=today,
                      check_url=check_url, append_only=append_only, js=js, scan_page=scan_page)


def check_v2(ctx, runs, latest):
    ck_method.check(ctx, runs, latest)
    ck_components.check(ctx, runs)
    ck_reports.check(ctx, runs, latest)


def pages_only(f, data, git, today):
    """--pages: the visible-word budgets of the built pages. Never an error; always exit 0."""
    for line in ck_pages.check(v2_context(f, data, git, today), data.get("data/runs.json")):
        print(line)
    for m in f.errors + f.warnings:
        print("WARN   " + m)
    print("check_data --pages: %d warning(s)" % len(f.errors + f.warnings))
    return 0


# ---------- main ----------

ROOT_DIR = ROOT


def main(argv=None):
    global ROOT_DIR
    ap = argparse.ArgumentParser(description="Read-only data and output validator (see the module docstring).")
    ap.add_argument("--allow-correction", metavar="REASON",
                    help="list immutability errors as warnings; needs a new dated entry in data/corrections.json")
    ap.add_argument("--warn-only", action="store_true", help="report everything as warnings and exit 0")
    ap.add_argument("--root", default=str(ROOT), help="repository root (default: this script's repo)")
    ap.add_argument("--base", default="HEAD", help="git revision the immutability checks compare against")
    ap.add_argument("--today", help="treat this date (YYYY-MM-DD) as today")
    ap.add_argument("--pages", action="store_true",
                    help="print the visible-word budgets of the built pages (spec 2.2); warnings only, exit 0")
    args = ap.parse_args(argv)
    ROOT_DIR = Path(args.root).resolve()
    today = parse_date(args.today) if args.today else date.today()
    if today is None:
        ap.error("--today must be YYYY-MM-DD")
    if args.allow_correction is not None and not args.allow_correction.strip():
        ap.error("--allow-correction needs a reason")

    f = Findings()
    data = load_all(ROOT_DIR, f)
    if args.pages:
        return pages_only(f, data, Git(ROOT_DIR, args.base), today)
    runs = data.get("data/runs.json")
    newest, latest, latest_run = check_runs(f, runs, data, today) if runs is not None else (None, None, None)
    check_alarm(f, data.get("data/alarm.json"), latest_run, data.get("data/incidents.json"))
    git = Git(ROOT_DIR, args.base)
    if latest is not None:
        check_derived(f, latest, latest_run, data, git)
    check_data_urls(f, data, runs, newest)
    check_page_links(f, ROOT_DIR)
    if latest is not None:
        check_report(f, latest, latest_run)
    check_v2(v2_context(f, data, git, today), runs, latest)
    if git.ok:
        check_immutability(f, git, data, runs, newest)
        check_git(f, git)
    else:
        f.warn("no git revision %s here: immutability, launch/ and key checks were skipped" % js(args.base))

    if f.frozen:
        if args.allow_correction is not None:
            if corrections_gained(git, data):
                reason = args.allow_correction.strip()
                f.warnings += ["%s (allowed as a correction: %s)" % (m, reason) for m in f.frozen]
            else:
                f.err("--allow-correction needs a new dated entry in data/corrections.json describing the correction")
                f.errors += f.frozen
        else:
            f.errors += f.frozen
    if args.warn_only:
        f.warnings = f.errors + f.warnings
        f.errors = []

    for m in f.errors:
        print("ERROR  " + m)
    for m in f.warnings:
        print("WARN   " + m)
    print("check_data: %d error(s), %d warning(s)" % (len(f.errors), len(f.warnings)))
    return 1 if f.errors else 0


if __name__ == "__main__":
    sys.exit(main())
