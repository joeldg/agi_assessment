#!/usr/bin/env python3
"""Fire-alarm arithmetic (criteria v1.1): a read-only report on data/alarm.json. It never writes any file.

    python3 scripts/alarm_check.py [--today YYYY-MM-DD]

The script does the counting and the date arithmetic; the agent still judges the evidence,
decides each trigger's met flag and writes every note.
  (a) The rule level from the met flags: Watch if any two W triggers are met, Warning if any
      X, Alarm if any Y (the counts come from each group's published "any N" rule). Triggers
      that name the same "model" (W2 and W6 on one model) count once. Highest wins.
  (b) The 30-day hold-down under the exit rule in force, rebuilt from runs.json alarm.met (the
      last entry per date; a run without an alarm field is unknown, not unmet). v1.1 publishes
      the symmetric rule, {"mode": "rule-unsatisfied", "days": 30} in alarm.json exitRule: a
      level drops after its rule has gone unsatisfied for 30 consecutive days, to the level the
      rules then give. Criteria older than v1.1 with no exitRule used the "trigger-unmet" wording
      (a level held while any trigger at that level was met).
  (c) Date crossings: clock triggers reach their threshold after N counted days from watchFrom
      (W2; W6 counts only days of internal use, so an entry in its "pauses" list with no "to"
      date suspends it, and a pause marked "voided" counts as use); window triggers leave their
      window on eventDate (or since) + N days (W3, X2). An explicit meetsOn or expires wins.
      Anything passed, due today or due within 7 days is flagged.
  (d) W4: the median disclosure lag of incidents disclosed in the past 180 days, printed next to
      the all-incident median that the oversight gauge uses.
  (e) W5: the rise in a lab's published AI-led share of its AI R&D (data/trends.json
      manual.rdShare*, plus any W5 "readings" not yet recorded there). Met while two readings no
      more than 6 months apart differ by 10 points or more and the later one is from the past 6
      months. A rise within 10% of the threshold is borderline, and counts only when a second
      reading or a second lab confirms it.
  (f) X2: the residual threshold for today (3 residual SDs above the fitted METR trends in
      data/trends.json) and whether any instrument can observe it within METR's reliable range.
  (g) Level 3: the case register (alarm.json "cases"). A met Y trigger needs a case that passed
      the tribunal, and a passed case file must have the structure the Level-3 proof standard
      requires (three lines from different modalities with no shared original source, every
      fact sourced and authenticated, every innocent explanation answered, unanimous judges).
  (h) History entries whose 90-day review is due and still null.

Exit codes:
  0   consistent;
  1   the data disagree with themselves: current.level below the computed level, current.met
      not matching the triggers marked met, a met trigger without since/evidence/url, a met
      trigger marked borderline, W4's or W5's flag disagreeing with the arithmetic, a met Y
      trigger without a passing case, a malformed case register or passed case file, or current
      not matching history[-1];
  10  a level change is pending: the computed level differs from history[-1].to. Write the
      history entry (with its evidence note), current and today's runs.json alarm field, then
      rerun. Draft the alert (kit_broadcast.py --alarm) only after a clean rerun.
"""
import argparse
import calendar
import json
import math
import re
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOLD_DAYS = 30
SOON_DAYS = 7
W4_WINDOW, W4_THRESHOLD = 180, 30
W5_POINTS, W5_MONTHS = 10, 6
X2_SDS, X2_WINDOW, METR_LIMIT = 3, 90, 960   # residual SDs; days a release counts; METR's 16-hour range, in minutes
MARGIN = 0.10                                # the borderline band when a source states no uncertainty
CASE_STATUSES = ("open", "passed", "failed")
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
MODES = {
    "trigger-unmet": "trigger-unmet",
    "published": "trigger-unmet",
    "rule-unsatisfied": "rule-unsatisfied",
    "symmetric": "rule-unsatisfied",
}
MODE_TEXT = {
    "trigger-unmet": "a level drops only after {d} days with no trigger at that level met (the wording before v1.1)",
    "rule-unsatisfied": "a level drops after its rule has gone unsatisfied for {d} consecutive days, "
                        "to the level the rules then give",
}


# ---------- shared helpers (check_data.py imports these) ----------

def parse_date(value):
    """A date from 'YYYY-MM-DD', or None."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def id_key(tid):
    """Natural order for trigger ids: W2 before W10."""
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", str(tid))
    return (m.group(1), int(m.group(2))) if m else (str(tid), 0)


def iter_triggers(alarm):
    """(group, trigger) pairs, skipping anything malformed."""
    for g in alarm.get("groups") or []:
        if not isinstance(g, dict):
            continue
        for t in g.get("triggers") or []:
            if isinstance(t, dict):
                yield g, t


def group_need(group):
    """How many met triggers the group's rule needs: 'any two' -> 2, 'any one, ...' -> 1."""
    m = re.match(r"\s*any\s+(\w+)", str(group.get("rule") or ""), re.I)
    if m:
        word = m.group(1).lower()
        if word.isdigit():
            return int(word)
        if word in NUMBER_WORDS:
            return NUMBER_WORDS[word]
    return 2 if group.get("level") == 1 else 1


def met_flags(alarm):
    """Sorted ids of triggers marked met: true."""
    return sorted({t.get("id") for _, t in iter_triggers(alarm) if t.get("met") is True}, key=id_key)


def count_key(trigger):
    """What a met trigger counts as: triggers naming the same "model" (W2 and W6 on one model) count once."""
    model = trigger.get("model")
    if isinstance(model, str) and model.strip():
        return ("model", model.strip().lower())
    return ("id", trigger.get("id"))


def rule_level(alarm, met=None):
    """The highest level whose group rule is satisfied, from the met flags or a given set of ids."""
    best = 0
    for g in alarm.get("groups") or []:
        if not isinstance(g, dict) or not isinstance(g.get("level"), int):
            continue
        triggers = [t for t in g.get("triggers") or [] if isinstance(t, dict)]
        hit = [t for t in triggers if (t.get("met") is True if met is None else t.get("id") in met)]
        if len({count_key(t) for t in hit}) >= group_need(g):
            best = max(best, g["level"])
    return best


def incident_lags(doc, ref=None, window=None):
    """[(id, lag days)] for incidents with occurred and disclosed dates.

    With ref, incidents disclosed after ref are left out; with window too, only incidents
    disclosed in the `window` days up to ref count (one disclosed exactly `window` days
    before ref has left the window)."""
    out = []
    items = doc.get("incidents") if isinstance(doc, dict) else None
    for it in items or []:
        if not isinstance(it, dict):
            continue
        occurred, disclosed = parse_date(it.get("occurred")), parse_date(it.get("disclosed"))
        if occurred is None or disclosed is None:
            continue
        if ref is not None:
            age = (ref - disclosed).days
            if age < 0 or (window is not None and age >= window):
                continue
        out.append((it.get("id"), (disclosed - occurred).days))
    return out


def median(values):
    values = list(values)
    return statistics.median(values) if values else None


def w4_params(alarm):
    """W4's window and threshold in days, read from its published text when possible."""
    window, threshold = W4_WINDOW, W4_THRESHOLD
    for _, t in iter_triggers(alarm):
        if t.get("id") == "W4":
            m = re.search(r"past\s+(\d+)\s+days", str(t.get("trigger") or ""))
            if m:
                window = int(m.group(1))
            m = re.search(r"(\d+)\s+days?\s+or\s+more", str(t.get("threshold") or ""))
            if m:
                threshold = int(m.group(1))
    return window, threshold


def version_tuple(value):
    """(1, 1) from '1.1', (1, 0, 1) from '1.0.1'; () when there is no version."""
    return tuple(int(p) for p in re.findall(r"\d+", str(value or "")))


def exit_rule(alarm):
    """(mode, days, problem): the hold-down rule in force. alarm.json names it in exitRule (a mode
    string or {"mode": ..., "days": 30}); without one, criteria from v1.1 on use the symmetric
    rule and older criteria the wording they were published with."""
    raw = alarm.get("exitRule")
    default = "trigger-unmet" if version_tuple(alarm.get("version")) < (1, 1) else "rule-unsatisfied"
    mode, days, problem = default, HOLD_DAYS, None
    if isinstance(raw, dict):
        mode = raw.get("mode") or mode
        try:
            days = int(raw.get("days", HOLD_DAYS))
        except (TypeError, ValueError):
            problem = "alarm.exitRule.days is not a whole number of days"
    elif isinstance(raw, str):
        mode = raw
    elif raw is not None:
        problem = "alarm.exitRule must be a mode string or {\"mode\": ..., \"days\": ...}"
    if mode not in MODES:
        problem = "alarm.exitRule mode %r is not one of %s" % (mode, ", ".join(sorted(MODES)))
        mode = default
    return MODES[mode], days, problem


# ---------- clocks and windows ----------

def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def add_months(d, n):
    """The same day n calendar months later (the month's last day when it's shorter)."""
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def threshold_days(trigger):
    """N from an explicit thresholdDays or from 'N days or more' in the threshold text."""
    days = trigger.get("thresholdDays")
    if isinstance(days, int) and not isinstance(days, bool):
        return days
    m = re.search(r"(\d+)\s+days?\s+or\s+more", str(trigger.get("threshold") or ""))
    return int(m.group(1)) if m else None


def pause_spans(trigger):
    """[(from, to or None)] for the trigger's pauses that aren't voided; 'to' is the day use resumed."""
    spans = []
    for p in trigger.get("pauses") or []:
        if isinstance(p, dict) and not p.get("voided") and parse_date(p.get("from")) is not None:
            spans.append((parse_date(p.get("from")), parse_date(p.get("to"))))
    return sorted(spans, key=lambda s: s[0])


def paused_on(day, spans):
    return any(s <= day and (e is None or day < e) for s, e in spans)


def clock_meets(start, need, spans):
    """The day the counted (unpaused) days since start reach need, or None while an open pause
    suspends the clock first. Without pauses that is start + need days."""
    horizon = start + timedelta(days=need + sum((e - s).days for s, e in spans if e is not None) + 1)
    counted, day = 0, start
    while day <= horizon:
        if counted >= need:
            return day
        if any(s <= day and e is None for s, e in spans):
            return None
        counted += 0 if paused_on(day, spans) else 1
        day += timedelta(days=1)
    return None


def clock(trigger, today):
    """A clock trigger's state, or None: {start, need, counted (days counted before today), meets
    (None while an open pause suspends the clock), suspended (the start of an open pause under way)}."""
    start, need = parse_date(trigger.get("watchFrom")), threshold_days(trigger)
    if start is None or not need:
        return None
    spans = pause_spans(trigger)
    counted = sum(1 for i in range(max(0, (today - start).days)) if not paused_on(start + timedelta(days=i), spans))
    explicit = parse_date(trigger.get("meetsOn"))
    suspended = next((s for s, e in spans if e is None and s <= today), None)
    return {"start": start, "need": need, "counted": counted, "meets": explicit or clock_meets(start, need, spans),
            "suspended": None if explicit else suspended}


def window_end(trigger):
    """The day a met window trigger leaves its window: an explicit expires, or eventDate (or
    since) + N from 'past N days' in the threshold text."""
    expires = parse_date(trigger.get("expires"))
    if expires is None:
        m = re.search(r"past\s+(\d+)\s+days", str(trigger.get("threshold") or ""))
        start = parse_date(trigger.get("eventDate")) or parse_date(trigger.get("since"))
        if m and start is not None:
            expires = start + timedelta(days=int(m.group(1)))
    return expires


def trigger_by_id(alarm, tid):
    return next((t for _, t in iter_triggers(alarm) if t.get("id") == tid), None)


# ---------- W5: the rate of the published AI-led R&D share ----------

def reading(p):
    """(date, value, label) from one published reading, or None."""
    if not isinstance(p, dict):
        return None
    d, v = parse_date(p.get("date")), p.get("v")
    if d is None or not is_num(v):
        return None
    return d, float(v), str(p.get("label") or "%g%%" % v)


def rd_readings(alarm, trends):
    """{series: [(date, value, label)]}: each lab's published readings, from data/trends.json
    manual.rdShare* plus W5 "readings" (each may name its "series") that aren't recorded there yet."""
    manual = trends.get("manual") if isinstance(trends, dict) else None
    manual = manual if isinstance(manual, dict) else {}
    found = [(str(k), p) for k, s in manual.items() if str(k).startswith("rdShare") and isinstance(s, dict)
             for p in s.get("points") or []]
    extra = (trigger_by_id(alarm, "W5") or {}).get("readings") or []
    found += [(str(p.get("series") or "rdShare"), p) for p in extra if isinstance(p, dict)]
    out = {}
    for series, p in found:
        r = reading(p)
        if r is not None and r[0] not in {x[0] for x in out.get(series, [])}:
            out.setdefault(series, []).append(r)
    return {k: sorted(v) for k, v in out.items()}


def w5_pairs(readings, day):
    """(rise, series, earlier, later, expires) for every rise of W5_POINTS or more between two
    readings no more than W5_MONTHS apart whose later reading is from the W5_MONTHS before day."""
    pairs = []
    for series, pts in readings.items():
        for i, (da, va, _) in enumerate(pts):
            for db, vb, _ in pts[i + 1:]:
                expires = add_months(db, W5_MONTHS)
                if db <= min(day, add_months(da, W5_MONTHS)) and day < expires and vb - va >= W5_POINTS:
                    pairs.append((vb - va, series, da, db, expires))
    return pairs


def w5_status(readings, day):
    """'met', 'borderline' (within 10% of the threshold, unconfirmed), 'unmet' or 'unknown'."""
    if not readings:
        return "unknown"
    pairs = w5_pairs(readings, day)
    if not pairs:
        return "unmet"
    confirmed = len({(p[1], p[3]) for p in pairs}) >= 2      # a second reading or a second lab
    if max(p[0] for p in pairs) >= W5_POINTS * (1 + MARGIN) or confirmed:
        return "met"
    return "borderline"


# ---------- X2: residual threshold and observability ----------

def metr_trend(fit, day):
    """The fitted trend value on day, from the fit's anchor and doubling time; None if unusable."""
    anchor = fit.get("anchor") if isinstance(fit, dict) else None
    if not isinstance(anchor, dict):
        return None
    a_date, a_val, dd = parse_date(anchor.get("date")), anchor.get("value"), fit.get("doublingDays")
    if a_date is None or not is_num(a_val) or not is_num(dd) or a_val <= 0 or dd <= 0:
        return None
    return a_val * 2 ** ((day - a_date).days / dd)


def x2_params(alarm, trends):
    """(METR fits by key, residual SDs k, METR's reliable range in minutes, X2's window in days)."""
    metr = trends.get("metr") if isinstance(trends, dict) else None
    metr = metr if isinstance(metr, dict) else {}
    x2 = trigger_by_id(alarm, "X2") or {}
    k = x2.get("residualSDs") if is_num(x2.get("residualSDs")) else X2_SDS
    lim = metr.get("x2").get("suiteLimit") if isinstance(metr.get("x2"), dict) else None
    window = re.search(r"past\s+(\d+)\s+days", str(x2.get("threshold") or ""))
    fits = {key: metr[key] for key in ("p50", "p80")
            if isinstance(metr.get(key), dict) and is_num(metr[key].get("residSD")) and metr[key]["residSD"] > 0}
    return fits, k, (lim if is_num(lim) else METR_LIMIT), (int(window.group(1)) if window else X2_WINDOW)


def x2_instruments(alarm, trends, today):
    """[{key, name, sd, k, trend, mult, threshold, limit, observable, months}] for each METR fit."""
    fits, k, limit, _ = x2_params(alarm, trends)
    names = {"p50": "METR 50% time horizon", "p80": "METR 80% time horizon"}
    out = []
    for key, fit in fits.items():
        trend = metr_trend(fit, today)
        if trend is None:
            continue
        mult = 2 ** (k * fit["residSD"])
        out.append({"key": key, "name": names[key], "sd": fit["residSD"], "k": k, "trend": trend, "mult": mult,
                    "threshold": trend * mult, "limit": limit, "observable": trend * mult <= limit,
                    "months": k * fit["residSD"] * fit["doublingDays"] / 30.44})
    return out


def x2_candidates(alarm, trends, today):
    """[(model id, fit key, date, residual in SDs, within range, at or over the threshold)] for
    METR-measured releases in X2's window, on each fit (50% and 80% horizons)."""
    fits, k, limit, window = x2_params(alarm, trends)
    metr = trends.get("metr") if isinstance(trends, dict) else None
    models = [m for m in metr.get("models") or [] if isinstance(m, dict)] if isinstance(metr, dict) else []
    out = []
    for key, fit in fits.items():
        for m in models:
            d, v = parse_date(m.get("date")), m.get(key)
            trend = metr_trend(fit, d) if d is not None and 0 <= (today - d).days < window else None
            if trend and is_num(v) and v > 0:
                resid = math.log2(v / trend) / fit["residSD"]
                out.append((m.get("id"), key, d, resid, v <= limit, resid >= k))
    return out


# ---------- Level 3: the case register and case files ----------

def case_line_problems(lines):
    """What the evidence lines of a case file lack under the proof standard."""
    out = []
    if len(lines) < 3:
        out.append("it has %d evidence line(s); the standard needs at least three" % len(lines))
    mods = [str(x.get("modality") or "").strip().lower() for x in lines]
    if any(not m for m in mods) or len(set(mods)) < len(mods):
        out.append("its lines don't each come from a different modality")
    owner = {}
    for x in lines:
        lid = x.get("id")
        sources = [str(s).strip().lower() for s in x.get("originalSources") or [] if str(s).strip()]
        if not sources:
            out.append("line %s names no original source" % lid)
        out += ["lines %s and %s share an original source (%s)" % (owner[s], lid, s)
                for s in sources if owner.get(s, lid) != lid]
        for s in sources:
            owner.setdefault(s, lid)
        facts = [f for f in x.get("facts") or [] if isinstance(f, dict)]
        if not facts:
            out.append("line %s has no facts" % lid)
        elif any(not f.get("source") or not f.get("authentication") for f in facts):
            out.append("line %s has a fact without its source or authentication" % lid)
    return out


def case_tribunal_problems(trib):
    """What the tribunal record of a case file lacks: a defense, an authenticity check, unanimous judges."""
    trib = trib if isinstance(trib, dict) else {}
    judges = [j for j in trib.get("judges") or [] if isinstance(j, dict)]
    out = []
    if not trib.get("defense"):
        out.append("no defense case is recorded")
    if not trib.get("authenticity"):
        out.append("no authenticity check is recorded")
    if not judges:
        out.append("no judge's verdict is recorded")
    elif trib.get("unanimous") is not True or any(str(j.get("verdict")).strip().lower() != "proven" for j in judges):
        out.append("the judges weren't unanimous that it is proven")
    return out


def case_file_problems(doc):
    """What a passed case file lacks under the published Level-3 proof standard ([] if nothing)."""
    if not isinstance(doc, dict):
        return ["the case file isn't a JSON object"]
    out = [] if str(doc.get("verdict") or "").strip() else ["it has no one-sentence verdict"]
    claim = doc.get("claim")
    if not (isinstance(claim, dict) and claim.get("weClaim") and claim.get("weDoNotClaim")):
        out.append("its claim doesn't say both what we claim and what we don't")
    out += case_line_problems([x for x in doc.get("lines") or [] if isinstance(x, dict)])
    innocent = [x for x in doc.get("innocent") or [] if isinstance(x, dict)]
    if not innocent:
        out.append("it examines no innocent explanation")
    out += ["the innocent explanation %r isn't shown to fail on any evidence" % x.get("explanation")
            for x in innocent if not x.get("failsToExplain")]
    out += ["its %s section is empty" % k for k in ("disproof", "unknowns", "readerActions") if not doc.get(k)]
    out += case_tribunal_problems(doc.get("tribunal"))
    if not str(doc.get("correction") or "").strip():
        out.append("it has no public-correction commitment")
    return out


def case_entry_problems(i, c):
    """Problems with one register entry's own fields (id, status, dates)."""
    cid, status = c.get("id"), c.get("status")
    out = [] if cid else ["alarm.cases[%d] has no id" % i]
    if status not in CASE_STATUSES:
        out.append("case %s: status=%s must be one of %s" % (cid, json.dumps(status), ", ".join(CASE_STATUSES)))
    if parse_date(c.get("opened")) is None:
        out.append("case %s: opened=%s is not YYYY-MM-DD" % (cid, json.dumps(c.get("opened"))))
    if status in ("passed", "failed") and parse_date(c.get("decided")) is None:
        out.append("case %s is %s but decided=%s is not YYYY-MM-DD" % (cid, status, json.dumps(c.get("decided"))))
    return out


def passed_case_problems(c, root):
    """A passed case's file, checked against the proof standard."""
    rel = c.get("file")
    if not isinstance(rel, str) or not rel:
        return ["case %s passed but it names no case file" % c.get("id")]
    try:
        doc = json.loads((root / rel).read_text())
    except (OSError, ValueError) as err:
        return ["case %s passed but its file %s can't be read (%s)" % (c.get("id"), rel, err)]
    return ["case %s passed but %s" % (c.get("id"), x) for x in case_file_problems(doc)]


def check_cases(alarm, root):
    """(problems, lines to print) for the case register and the Y triggers that rest on it."""
    cases = alarm.get("cases")
    if cases is not None and not isinstance(cases, list):
        return ["alarm.cases must be a list"], []
    problems, lines, by_id = [], [], {}
    for i, c in enumerate(cases or []):
        if not isinstance(c, dict):
            problems.append("alarm.cases[%d] must be an object" % i)
            continue
        if c.get("id") in by_id:
            problems.append("alarm.cases: id %s appears more than once" % json.dumps(c.get("id")))
        by_id.setdefault(c.get("id"), c)
        problems += case_entry_problems(i, c)
        if c.get("status") == "open":
            lines.append("under investigation: case %s (%s), opened %s" % (c.get("id"), c.get("trigger"), c.get("opened")))
        elif c.get("status") in ("passed", "failed"):
            lines.append("case %s (%s) %s on %s" % (c.get("id"), c.get("trigger"), c["status"], c.get("decided")))
        if c.get("status") == "passed":
            problems += passed_case_problems(c, root)
    for g, t in iter_triggers(alarm):
        c = by_id.get(t.get("case"))
        if g.get("level") == 3 and t.get("met") is True and (not isinstance(c, dict) or c.get("status") != "passed"):
            problems.append("%s is met but names no case that passed the tribunal (case=%s): Level 3 is set only by a "
                            "passing case file; until then the level holds at Warning at most"
                            % (t.get("id"), json.dumps(t.get("case"))))
    return problems, lines


# ---------- hold-down ----------

def day_states(runs, alarm, today):
    """{date: sorted met ids, or None when unknown}: the last run per date, then today's live flags."""
    states = {}
    for r in runs if isinstance(runs, list) else []:
        if not isinstance(r, dict):
            continue
        d = parse_date(r.get("date"))
        if d is None or d > today:
            continue
        a = r.get("alarm")
        states[d] = sorted(a["met"], key=id_key) if isinstance(a, dict) and isinstance(a.get("met"), list) else None
    states[today] = met_flags(alarm)
    return states


def level_ids(alarm, level):
    return {t.get("id") for g, t in iter_triggers(alarm) if g.get("level") == level}


def last_held(states, alarm, level, mode):
    """The last date the level held: its rule (or a higher one) was satisfied, or, under the
    pre-v1.1 wording, any trigger at that level was met."""
    ids = level_ids(alarm, level)
    best = None
    for d, met in states.items():
        if met is None:
            continue
        held = rule_level(alarm, set(met)) >= level
        if not held and mode == "trigger-unmet":
            held = any(m in ids for m in met)
        if held and (best is None or d > best):
            best = d
    return best


def computed_level(states, alarm, today, in_force, mode, days):
    """The level the rules give today, held up by the hold-down for levels up to the one in force."""
    level = rule_level(alarm, set(states[today]))
    for lv in range(level + 1, in_force + 1):
        held = last_held(states, alarm, lv, mode)
        if held is not None and (today - held).days < days:
            level = lv
    return level


# ---------- report ----------

class Report:
    """The shared state of one check: the inputs, and what was found. problems fail the check
    (exit 1); actions are flagged for the agent; notes are informational."""

    def __init__(self, root, today, inputs):
        alarm, runs, self.incidents, self.trends = inputs
        self.root, self.today, self.alarm, self.runs = root, today, alarm, runs if isinstance(runs, list) else []
        self.problems, self.actions, self.notes = [], [], []
        self.names = {lv.get("level"): lv.get("name") for lv in alarm.get("levels") or [] if isinstance(lv, dict)}
        self.v11 = version_tuple(alarm.get("version")) >= (1, 1)
        self.current = alarm.get("current") if isinstance(alarm.get("current"), dict) else {}
        self.history = [h for h in alarm.get("history") or [] if isinstance(h, dict)]
        self.last = self.history[-1] if self.history else {}
        cur = self.current.get("level")
        self.in_force = self.last.get("to") if isinstance(self.last.get("to"), int) else (cur if isinstance(cur, int) else 0)
        self.mode, self.days, rule_problem = exit_rule(alarm)
        if rule_problem:
            self.problems.append(rule_problem + "; using the default for criteria v%s" % alarm.get("version", "?"))

    def name(self, level):
        return "%s %s" % (level, self.names.get(level, "?"))

    def act(self, line, printed=True):
        self.actions.append(line)
        if printed:
            print("  ! " + line)


def load(path):
    return json.loads(path.read_text())


def load_inputs(root):
    """(alarm, runs, incidents, trends), or (None, message) when alarm.json can't be used."""
    try:
        alarm = load(root / "data/alarm.json")
    except (OSError, ValueError) as e:
        return None, "ERROR  data/alarm.json can't be read: %s" % e
    if not isinstance(alarm, dict):
        return None, "ERROR  data/alarm.json is not an object"
    out = [alarm]
    for rel, default, what in (("data/runs.json", [], "the hold-down uses today's flags only"),
                               ("data/incidents.json", None, "W4 is not checked"),
                               ("data/trends.json", None, "W5 and X2 are not checked")):
        try:
            out.append(load(root / rel))
        except (OSError, ValueError) as e:
            print("WARN   %s can't be read (%s); %s" % (rel, e, what))
            out.append(default)
    return tuple(out), None


def section_rule_level(rep):
    """(a) The rule level from the met flags, and the fields a met trigger must carry."""
    alarm = rep.alarm
    print("Fire alarm check · %s · criteria v%s" % (rep.today.isoformat(), alarm.get("version", "?")))
    print("Exit rule in force: %s: %s%s" % (rep.mode, MODE_TEXT[rep.mode].format(d=rep.days),
                                             "" if alarm.get("exitRule") is not None else " (no exitRule field; the default)"))
    print()
    print("(a) Rule level from the met flags")
    for g in alarm.get("groups") or []:
        if not isinstance(g, dict):
            continue
        trig = [t for t in g.get("triggers") or [] if isinstance(t, dict)]
        met_here = [t for t in trig if t.get("met") is True]
        counted = len({count_key(t) for t in met_here})
        print("  %s · %s: %d of %d met%s%s" % (
            rep.names.get(g.get("level"), g.get("level")), g.get("rule"), len(met_here), len(trig),
            (" · " + ", ".join(str(t.get("id")) for t in met_here)) if met_here else "",
            " · counted as %d (triggers on the same model count once)" % counted if counted < len(met_here) else ""))
    print("  Rule level today: %s" % rep.name(rule_level(alarm)))
    print("  Level in force: %s since %s (history[-1].to)" % (rep.name(rep.in_force), rep.last.get("date", "?")))
    for _, t in iter_triggers(alarm):
        rep.problems += trigger_field_problems(t, rep.v11)


def trigger_field_problems(t, v11):
    """A trigger's own field errors: the met flag, a met trigger's since/evidence/url, borderline, pauses."""
    tid, out = t.get("id"), []
    if "met" in t and not isinstance(t.get("met"), bool):
        out.append("%s.met=%s must be true or false" % (tid, json.dumps(t.get("met"))))
    if t.get("met") is True:
        missing = [k for k in ("since", "evidence", "url") if not t.get(k)]
        if missing:
            out.append("%s is met but has no %s" % (tid, ", ".join(missing)))
        if t.get("since") and parse_date(t.get("since")) is None:
            out.append("%s.since=%s is not YYYY-MM-DD" % (tid, json.dumps(t.get("since"))))
        if v11 and t.get("borderline") is True:
            out.append("%s is met and marked borderline, but borderline doesn't count under v1.1: set met to false "
                       "(it shows as borderline, not counted) until a second reading or source confirms it" % tid)
    for p in t.get("pauses") or []:
        if not isinstance(p, dict) or parse_date(p.get("from")) is None or \
                (p.get("to") is not None and parse_date(p.get("to")) is None):
            out.append("%s.pauses has an entry without a valid from/to date: %s" % (tid, json.dumps(p)))
    return out


def section_hold_down(rep):
    """(b) The hold-down under the rule in force. Returns the computed level."""
    alarm, today, days = rep.alarm, rep.today, rep.days
    states = day_states(rep.runs, alarm, today)
    computed = computed_level(states, alarm, today, rep.in_force, rep.mode, days)
    print()
    print("(b) Hold-down (%d days); runs.json alarm.met, last entry per date, plus today's flags" % days)
    published = parse_date(alarm.get("published"))
    start = max(today - timedelta(days=days - 1), published) if published else today - timedelta(days=days - 1)
    unknown = [d for d in (start + timedelta(days=i) for i in range((today - start).days + 1)) if states.get(d) is None]
    if unknown:
        rep.notes.append("%d day(s) since %s have no recorded alarm state (no run, or a run without an alarm "
                         "field); only recorded days count as held." % (len(unknown), start.isoformat()))
    for lv in range(max(rep.in_force, rule_level(alarm)), 0, -1):
        print("  %s: %s" % (rep.names.get(lv, lv), held_text(last_held(states, alarm, lv, rep.mode), rep)))
    print("  Computed level: %s" % rep.name(computed))
    return computed


def held_text(held, rep):
    """One level's hold-down line: never held, holds today, held up until a date, or run out."""
    if held is None:
        return "never held on a recorded day"
    drop = held + timedelta(days=rep.days)
    if held == rep.today:
        what = "its rule holds today" if rep.mode == "rule-unsatisfied" else "a trigger at this level is met today"
        return "%s; if that stops from tomorrow, the earliest drop is %s" % (what, drop.isoformat())
    if (rep.today - held).days < rep.days:
        return "last held %s; held up until %s (%d day(s) left) unless it holds again" % (
            held.isoformat(), drop.isoformat(), (drop - rep.today).days)
    return "last held %s; its %d days ran out on %s" % (held.isoformat(), rep.days, drop.isoformat())


def clock_lines(t, today):
    """(actions, later) for one unmet clock trigger."""
    ck, tid = clock(t, today), t.get("id")
    if ck is None:
        return [], []
    if ck["suspended"] is not None:
        return [], ["%s's clock is suspended since %s (a pause): %d of %d days counted from %s; it meets this %d "
                     "day(s) after use resumes" % (tid, ck["suspended"].isoformat(), ck["counted"], ck["need"],
                                                    ck["start"].isoformat(), ck["need"] - ck["counted"])]
    if ck["meets"] is None:
        return [], []
    delta = (ck["meets"] - today).days
    if delta < 0:
        return ["%s passed its threshold date %s (%d day(s) ago) and is still unmet: evaluate it now. If the clock no "
                "longer applies (for example an external evaluation happened), say so in its evidence and clear "
                "watchFrom." % (tid, ck["meets"].isoformat(), -delta)], []
    if delta == 0:
        return ["%s reaches its threshold today (%s): evaluate it now." % (tid, ck["meets"].isoformat())], []
    if delta <= SOON_DAYS:
        return ["%s reaches its threshold on %s, in %d day(s)." % (tid, ck["meets"].isoformat(), delta)], []
    return [], ["%s reaches its threshold on %s (in %d days) if nothing changes" % (tid, ck["meets"].isoformat(), delta)]


def window_lines(t, today):
    """(actions, later) for one met window trigger."""
    expires, tid = window_end(t), t.get("id")
    if expires is None:
        return [], []
    delta = (expires - today).days
    if delta <= 0:
        return ["%s's window ended on %s: mark it unmet unless a newer instance renews it (record the new instance "
                "in eventDate, evidence and url)." % (tid, expires.isoformat())], []
    if delta <= SOON_DAYS:
        return ["%s leaves its window on %s, in %d day(s), unless a newer instance renews it." % (
            tid, expires.isoformat(), delta)], []
    return [], ["%s leaves its window on %s (in %d days) unless renewed" % (tid, expires.isoformat(), delta)]


def section_dates(rep):
    """(c) Clock and window crossings."""
    print()
    print("(c) Date crossings (flagged when passed, due today or within %d days)" % SOON_DAYS)
    due, later = [], []
    for _, t in iter_triggers(rep.alarm):
        a, b = window_lines(t, rep.today) if t.get("met") is True else clock_lines(t, rep.today)
        due += a
        later += b
    for line in due:
        rep.act(line)
    if not due:
        print("  Nothing due in the next %d days." % SOON_DAYS)
    for line in later:
        print("  later: " + line)


def section_w4(rep):
    """(d) W4's 180-day median, next to the all-incident gauge median."""
    print()
    print("(d) W4 · oversight gap")
    if rep.incidents is None:
        print("  Skipped (no incidents data).")
        return
    today, (window, threshold) = rep.today, w4_params(rep.alarm)
    lags_w, lags_all = incident_lags(rep.incidents, ref=today, window=window), incident_lags(rep.incidents, ref=today)
    med_w, med_all = median(lag for _, lag in lags_w), median(lag for _, lag in lags_all)
    should = med_w is not None and med_w >= threshold
    print("  %d-day median: %s across %d incident(s) disclosed %s to %s → W4 should be %s" % (
        window, "–" if med_w is None else "%g days" % med_w, len(lags_w),
        (today - timedelta(days=window - 1)).isoformat(), today.isoformat(), "met" if should else "unmet"))
    print("  All-incident median (the oversight gauge): %s across %d incident(s)" % (
        "–" if med_all is None else "%g days" % med_all, len(lags_all)))
    gauge = next(((r.get("date"), r["gauges"]["oversight"].get("value")) for r in reversed(rep.runs)
                  if isinstance(r, dict) and isinstance(r.get("gauges"), dict)
                  and isinstance(r["gauges"].get("oversight"), dict)), None)
    if gauge:
        print("  Latest oversight gauge in runs.json: %s (%s)" % (gauge[1], gauge[0]))
        if is_num(gauge[1]) and med_all is not None and abs(gauge[1] - med_all) > 1:
            rep.notes.append("the latest oversight gauge (%s, %s) differs from the all-incident median (%g): the "
                             "next run should use the recomputed value" % (gauge[1], gauge[0], med_all))
    if med_w != med_all:
        shown = ["–" if v is None else "%g" % v for v in (med_w, med_all)]
        rep.notes.append("W4's %d-day median (%s) and the all-incident gauge median (%s) differ: quote the "
                         "windowed figure in W4's evidence." % (window, shown[0], shown[1]))
    w4 = trigger_by_id(rep.alarm, "W4")
    if w4 is None:
        rep.problems.append("no W4 trigger in alarm.json")
    elif (w4.get("met") is True) != should:
        rep.problems.append("W4.met=%s but the %d-day median is %s days (threshold %d): set W4.met to %s" % (
            json.dumps(w4.get("met")), window, "–" if med_w is None else "%g" % med_w, threshold, json.dumps(should)))


W5_VERDICT = {"met": "met", "unmet": "unmet", "unknown": "left as it is (no readings)",
              "borderline": "unmet (borderline: within %d%% of the threshold and unconfirmed)" % (MARGIN * 100)}


def section_w5(rep):
    """(e) W5's rate from the published readings, checked against its met flag."""
    print()
    print("(e) W5 · rise in the published AI-led share of AI R&D (%d points within %d months)" % (W5_POINTS, W5_MONTHS))
    w5 = trigger_by_id(rep.alarm, "W5")
    if not rep.v11:
        print("  Skipped: W5 is a level (25% or more) before criteria v1.1; the agent reads it from the evidence.")
        return
    if rep.trends is None or w5 is None:
        print("  Skipped (no trends data or no W5 trigger).")
        return
    readings, today = rd_readings(rep.alarm, rep.trends), rep.today
    for series, pts in sorted(readings.items()):
        print("  %s: %s" % (series, "; ".join("%s %s" % (d.isoformat(), label) for d, _, label in pts)))
    status, pairs = w5_status(readings, today), sorted(w5_pairs(readings, today), key=lambda p: (-p[0], p[3]))
    if pairs:
        print("  Largest qualifying rise: +%g points (%s, %s → %s)" % (
            pairs[0][0], pairs[0][1], pairs[0][2].isoformat(), pairs[0][3].isoformat()))
    print("  → W5 should be %s" % W5_VERDICT[status])
    drop = next((d for d in sorted({p[4] for p in pairs}) if w5_status(readings, d) != "met"), None) \
        if status == "met" else None
    if drop is not None:
        line = "W5 stops being met on %s unless a new reading renews it (in %d day(s))" % (
            drop.isoformat(), (drop - today).days)
        if (drop - today).days <= SOON_DAYS:
            rep.act(line + ".")
        else:
            print("  later: " + line)
    if status != "unknown" and (w5.get("met") is True) != (status == "met"):
        rep.problems.append("W5.met=%s but the published readings give %s: set W5.met to %s%s" % (
            json.dumps(w5.get("met")), status, json.dumps(status == "met"),
            " and borderline to true" if status == "borderline" else ""))
    if status == "borderline" and w5.get("borderline") is not True:
        rep.notes.append("W5's rise is borderline (within %d%% of the threshold, unconfirmed): mark it borderline" % (
            MARGIN * 100))


def section_x2(rep):
    """(f) X2's residual threshold today, its observability and any METR-measured release in its window."""
    print()
    print("(f) X2 · far above the trend (residual threshold)")
    x2 = trigger_by_id(rep.alarm, "X2")
    if not rep.v11:
        print("  Skipped: X2 is a 4x ratio before criteria v1.1.")
        return
    if rep.trends is None or x2 is None:
        print("  Skipped (no trends data or no X2 trigger).")
        return
    inst = x2_instruments(rep.alarm, rep.trends, rep.today)
    for i in inst:
        print("  %s: trend %.0f min (%.1f h); %g residual SDs of %.3f log2 = %.2fx → threshold %.0f min (%.1f h), "
              "about %.1f months ahead of the trend; reliable range %g min (%.0f h) → %s" % (
                  i["name"], i["trend"], i["trend"] / 60, i["k"], i["sd"], i["mult"], i["threshold"],
                  i["threshold"] / 60, i["months"], i["limit"], i["limit"] / 60,
                  "observable" if i["observable"] else "can't be observed"))
    cands = x2_candidates(rep.alarm, rep.trends, rep.today)
    for mid, key, d, resid, in_range, _ in cands:
        print("  %s (%s): %+.2f residual SDs on the %s fit%s" % (
            mid, d.isoformat(), resid, key, "" if in_range else " (measured above METR's reliable range)"))
    if not cands:
        print("  No METR-measured frontier release in X2's window.")
    if any(over and in_range for *_, in_range, over in cands) and x2.get("met") is not True:
        rep.act("a METR-measured release is at or above X2's residual threshold within METR's reliable range: "
                "evaluate X2 now.")
    observable = any(i["observable"] for i in inst)
    print("  → X2 %s on the METR fits today" % ("can be observed" if observable else "can't be observed"))
    if inst and observable and x2.get("observable") is False:
        rep.notes.append("X2.observable=false but a METR fit can observe it today: set observable to true and update "
                         "its evidence.")
    elif inst and not observable and x2.get("observable") is not False:
        rep.notes.append("X2.observable=%s but no METR fit can observe it today: set it to false, unless its evidence "
                         "names another instrument (such as an ECI fit) that can." % json.dumps(x2.get("observable")))


def section_cases(rep):
    """(g) The Level-3 case register."""
    print()
    print("(g) Level 3 · case register")
    problems, lines = check_cases(rep.alarm, rep.root)
    rep.problems += problems
    for line in lines:
        print("  " + line)
    if not lines:
        print("  No Level-3 cases opened.")


def section_reviews(rep):
    """(h) 90-day reviews that are due."""
    print()
    print("(h) Reviews due")
    due = ["history[%d] (%s, %s → %s) was due for its 90-day review on %s; publish the review." % (
        i, h.get("date"), "initial" if h.get("from") is None else h.get("from"), h.get("to"),
        parse_date(h.get("reviewDue")).isoformat())
        for i, h in enumerate(rep.history)
        if parse_date(h.get("reviewDue")) is not None and parse_date(h.get("reviewDue")) <= rep.today
        and h.get("review") is None]
    for line in due:
        rep.act(line)
    if not due:
        nxt = sorted(parse_date(h.get("reviewDue")) for h in rep.history
                     if parse_date(h.get("reviewDue")) and h.get("review") is None)
        print("  None due." + (" Next: %s." % nxt[0].isoformat() if nxt else ""))


def stale_state(rep, computed, pending):
    """How current and today's runs.json entry disagree with the flags and the history."""
    cur, flags = rep.current, met_flags(rep.alarm)
    cur_level, cur_met = cur.get("level"), cur.get("met") if isinstance(cur.get("met"), list) else []
    if cur_level not in rep.names:
        rep.problems.append("current.level=%s is not a defined level" % json.dumps(cur_level))
    stale = []
    if sorted(cur_met, key=id_key) != flags:
        stale.append("current.met=%s but the triggers marked met are %s" % (json.dumps(cur_met), json.dumps(flags)))
    if cur_level != rep.in_force:
        stale.append("current.level=%s but history[-1].to=%s" % (json.dumps(cur_level), rep.in_force))
    if rep.history and cur.get("since") != rep.last.get("date"):
        stale.append("current.since=%s but history[-1].date=%s" % (json.dumps(cur.get("since")),
                                                                   json.dumps(rep.last.get("date"))))
    if isinstance(cur_level, int) and cur_level < computed and not pending:
        stale.append("current.level=%s is below the computed level %s" % (cur_level, computed))
    todays = [r for r in rep.runs if isinstance(r, dict) and r.get("date") == rep.today.isoformat()]
    ra = todays[-1].get("alarm") if todays else None
    if todays and (not isinstance(ra, dict) or ra.get("level") != cur_level or
                   sorted(ra.get("met") or [], key=id_key) != sorted(cur_met, key=id_key)):
        rep.notes.append("today's runs.json entry has alarm=%s; it must equal {level: %s, met: %s} before "
                         "publishing" % (json.dumps(ra), json.dumps(cur_level), json.dumps(cur_met)))
    return stale


def verdict(rep, computed):
    """Print the problems, any pending change and the notes; return the exit code."""
    pending = computed != rep.in_force
    stale = stale_state(rep, computed, pending)
    flags, today = met_flags(rep.alarm), rep.today
    print()
    for p in rep.problems:
        print("ERROR  " + p)
    if pending:
        print("PENDING  a level %s is due: %s → %s (%s)." % (
            "rise" if computed > rep.in_force else "drop", rep.name(rep.in_force), rep.name(computed), rep.mode))
        print("  Write history[] {date: %s, from: %s, to: %s, cause, triggers: %s, cleared, note: <the evidence>, "
              "reviewDue: %s, review: null}; set current {level: %s, since: %s, met: %s, note}; set today's runs.json "
              "alarm; rerun. Draft the alert with kit_broadcast.py --alarm only after a clean rerun." % (
                  today.isoformat(), rep.in_force, computed, json.dumps(flags),
                  (today + timedelta(days=90)).isoformat(), computed, today.isoformat(), json.dumps(flags)))
        if computed == 3:
            print("  Level 3 is set only by a case that passed the tribunal; check (g) before writing it.")
        for s in stale:
            print("  (to update: %s)" % s)
    else:
        for s in stale:
            print("ERROR  " + s)
    for n in rep.notes:
        print("NOTE   " + n)
    if rep.problems or (stale and not pending):
        print("Result: inconsistent (exit 1)")
        return 1
    if pending:
        print("Result: level change pending (exit 10)")
        return 10
    print("Result: consistent (exit 0)%s" % (" · %d action(s) flagged above" % len(rep.actions) if rep.actions else ""))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only fire-alarm arithmetic check (see the module docstring).")
    ap.add_argument("--today", help="evaluate as of this date (YYYY-MM-DD); default: today's local date")
    ap.add_argument("--root", default=str(ROOT), help="repository root (default: this script's repo)")
    args = ap.parse_args(argv)
    today = parse_date(args.today) if args.today else date.today()
    if today is None:
        ap.error("--today must be YYYY-MM-DD")
    inputs, error = load_inputs(Path(args.root))
    if inputs is None:
        print(error)
        return 1
    rep = Report(Path(args.root), today, inputs)
    section_rule_level(rep)
    computed = section_hold_down(rep)
    section_dates(rep)
    section_w4(rep)
    section_w5(rep)
    section_x2(rep)
    section_cases(rep)
    section_reviews(rep)
    return verdict(rep, computed)


if __name__ == "__main__":
    sys.exit(main())
