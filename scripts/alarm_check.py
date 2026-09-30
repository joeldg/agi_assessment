#!/usr/bin/env python3
"""Fire-alarm arithmetic: a read-only report on data/alarm.json. It never writes any file.

    python3 scripts/alarm_check.py [--today YYYY-MM-DD]

The script does the counting and the date arithmetic; the agent still judges the evidence,
decides each trigger's met flag and writes every note.
  (a) The rule level from the met flags: Watch if any two W triggers are met, Warning if any
      X, Alarm if any Y (the counts come from each group's published "any N" rule). Highest wins.
  (b) The 30-day hold-down, rebuilt from runs.json alarm.met (the last entry per date; a run
      without an alarm field is unknown, not unmet). Two readings are shown side by side
      until the owner settles the wording:
        trigger-unmet     the published wording: a level drops only after 30 days with no
                          trigger at that level met;
        rule-unsatisfied  the symmetric reading: a level drops after its rule has gone
                          unsatisfied for 30 consecutive days, to the level the rules then give.
      alarm.json may name the one in force with an optional "exitRule" field, either a mode
      string or {"mode": ..., "days": 30}. Without it, the published wording applies.
  (c) Date crossings: clock triggers reach their threshold on watchFrom + N days (W2, W6;
      an explicit meetsOn wins); window triggers leave their window on eventDate (or since)
      + N days (W3; an explicit expires wins). Anything passed, due today or due within 7
      days is flagged.
  (d) W4: the median disclosure lag of incidents disclosed in the past 180 days, printed
      next to the all-incident median that the oversight gauge uses.
  (e) History entries whose 90-day review is due and still null.

Exit codes:
  0   consistent;
  1   the data disagree with themselves: current.level below the computed level, current.met
      not matching the triggers marked met, a met trigger without since/evidence/url, W4's
      flag disagreeing with the 180-day median, or current not matching history[-1];
  10  a level change is pending: the computed level differs from history[-1].to. Write the
      history entry (with its evidence note), current and today's runs.json alarm field, then
      rerun. Draft the alert (kit_broadcast.py --alarm) only after a clean rerun.
"""
import argparse
import json
import re
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOLD_DAYS = 30
SOON_DAYS = 7
W4_WINDOW, W4_THRESHOLD = 180, 30
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
MODES = {
    "trigger-unmet": "trigger-unmet",
    "published": "trigger-unmet",
    "rule-unsatisfied": "rule-unsatisfied",
    "symmetric": "rule-unsatisfied",
}
MODE_TEXT = {
    "trigger-unmet": "published wording: a level drops only after {d} days with no trigger at that level met",
    "rule-unsatisfied": "symmetric reading: a level drops after its rule has gone unsatisfied for {d} "
                        "consecutive days, to the level the rules then give",
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


def rule_level(alarm, met=None):
    """The highest level whose group rule is satisfied, from the met flags or a given set of ids."""
    best = 0
    for g in alarm.get("groups") or []:
        if not isinstance(g, dict) or not isinstance(g.get("level"), int):
            continue
        triggers = [t for t in g.get("triggers") or [] if isinstance(t, dict)]
        if met is None:
            count = sum(1 for t in triggers if t.get("met") is True)
        else:
            count = sum(1 for t in triggers if t.get("id") in met)
        if count >= group_need(g):
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


def exit_rule(alarm):
    """(mode, days, problem): the hold-down reading in force, from the optional exitRule field."""
    raw = alarm.get("exitRule")
    mode, days, problem = "trigger-unmet", HOLD_DAYS, None
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
        mode = "trigger-unmet"
    return MODES[mode], days, problem


def clock_dates(trigger):
    """(meetsOn, expires) for a trigger, from explicit fields or its threshold text."""
    threshold = str(trigger.get("threshold") or "")
    meets = parse_date(trigger.get("meetsOn"))
    watch_from = parse_date(trigger.get("watchFrom"))
    if meets is None and watch_from is not None:
        days = trigger.get("thresholdDays")
        if not isinstance(days, int) or isinstance(days, bool):
            m = re.search(r"(\d+)\s+days?\s+or\s+more", threshold)
            days = int(m.group(1)) if m else None
        if days:
            meets = watch_from + timedelta(days=days)
    expires = parse_date(trigger.get("expires"))
    if expires is None:
        m = re.search(r"past\s+(\d+)\s+days", threshold)
        start = parse_date(trigger.get("eventDate")) or parse_date(trigger.get("since"))
        if m and start is not None:
            expires = start + timedelta(days=int(m.group(1)))
    return meets, expires


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
    published wording, any trigger at that level was met."""
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

def load(path):
    return json.loads(path.read_text())


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only fire-alarm arithmetic check (see the module docstring).")
    ap.add_argument("--today", help="evaluate as of this date (YYYY-MM-DD); default: today's local date")
    ap.add_argument("--root", default=str(ROOT), help="repository root (default: this script's repo)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    today = parse_date(args.today) if args.today else date.today()
    if today is None:
        ap.error("--today must be YYYY-MM-DD")

    try:
        alarm = load(root / "data/alarm.json")
    except (OSError, ValueError) as e:
        print("ERROR  data/alarm.json can't be read: %s" % e)
        return 1
    try:
        runs = load(root / "data/runs.json")
    except (OSError, ValueError) as e:
        print("WARN   data/runs.json can't be read (%s); the hold-down uses today's flags only" % e)
        runs = []
    try:
        incidents = load(root / "data/incidents.json")
    except (OSError, ValueError) as e:
        print("WARN   data/incidents.json can't be read (%s); W4 is not checked" % e)
        incidents = None

    problems, actions, notes = [], [], []
    names = {lv.get("level"): lv.get("name") for lv in alarm.get("levels") or [] if isinstance(lv, dict)}

    def name(level):
        return "%s %s" % (level, names.get(level, "?"))

    current = alarm.get("current") if isinstance(alarm.get("current"), dict) else {}
    history = [h for h in alarm.get("history") or [] if isinstance(h, dict)]
    last = history[-1] if history else {}
    cur_level = current.get("level")
    in_force = last.get("to") if isinstance(last.get("to"), int) else (cur_level if isinstance(cur_level, int) else 0)
    mode, days, rule_problem = exit_rule(alarm)
    if rule_problem:
        problems.append(rule_problem + "; using the published wording")
    other = "rule-unsatisfied" if mode == "trigger-unmet" else "trigger-unmet"

    # (a) rule level from the flags
    flags = met_flags(alarm)
    r_today = rule_level(alarm)
    print("Fire alarm check · %s · criteria v%s" % (today.isoformat(), alarm.get("version", "?")))
    print("Exit rule in force: %s (%s)" % (
        mode, MODE_TEXT[mode].format(d=days) if alarm.get("exitRule") is not None
        else MODE_TEXT[mode].format(d=days) + "; no exitRule field, so the published wording applies"))
    print()
    print("(a) Rule level from the met flags")
    for g in alarm.get("groups") or []:
        if not isinstance(g, dict):
            continue
        trig = [t for t in g.get("triggers") or [] if isinstance(t, dict)]
        met_here = [t.get("id") for t in trig if t.get("met") is True]
        print("  %s (%s): %d of %d met%s" % (
            names.get(g.get("level"), g.get("level")), g.get("rule"), len(met_here), len(trig),
            (" · " + ", ".join(met_here)) if met_here else ""))
    print("  Rule level today: %s" % name(r_today))
    print("  Level in force: %s since %s (history[-1].to)" % (name(in_force), last.get("date", "?")))

    for g, t in iter_triggers(alarm):
        if "met" in t and not isinstance(t.get("met"), bool):
            problems.append("%s.met=%s must be true or false" % (t.get("id"), json.dumps(t.get("met"))))
        if t.get("met") is True:
            missing = [k for k in ("since", "evidence", "url") if not t.get(k)]
            if missing:
                problems.append("%s is met but has no %s" % (t.get("id"), ", ".join(missing)))
            if t.get("since") and parse_date(t.get("since")) is None:
                problems.append("%s.since=%s is not YYYY-MM-DD" % (t.get("id"), json.dumps(t.get("since"))))

    # (b) hold-down under both readings
    states = day_states(runs, alarm, today)
    proposed = {m: computed_level(states, alarm, today, in_force, m, days) for m in (mode, other)}
    print()
    print("(b) Hold-down (%d days); runs.json alarm.met, last entry per date, plus today's flags" % days)
    published = parse_date(alarm.get("published"))
    start = max(today - timedelta(days=days - 1), published) if published else today - timedelta(days=days - 1)
    unknown = [start + timedelta(days=i) for i in range((today - start).days + 1)
               if states.get(start + timedelta(days=i)) is None]
    if unknown:
        notes.append("%d day(s) since %s have no recorded alarm state (no run, or a run without an alarm "
                     "field); they count as neither held nor unheld." % (len(unknown), start.isoformat()))
    for m in (mode, other):
        tag = "in force" if m == mode else "alternative, for comparison"
        print("  %s (%s): %s" % (m, tag, name(proposed[m])))
        top = max(in_force, r_today)
        for lv in range(top, 0, -1):
            held = last_held(states, alarm, lv, m)
            if held is None:
                print("    %s: never held on a recorded day" % names.get(lv, lv))
                continue
            drop = held + timedelta(days=days)
            if held == today:
                what = ("a trigger at this level is met today" if m == "trigger-unmet"
                        else "its rule holds today")
                print("    %s: %s; if that stops from tomorrow, the earliest drop is %s" % (
                    names.get(lv, lv), what, drop.isoformat()))
            elif (today - held).days < days:
                print("    %s: last held %s; held up until %s (%d day(s) left) unless it holds again" % (
                    names.get(lv, lv), held.isoformat(), drop.isoformat(), (drop - today).days))
            else:
                print("    %s: last held %s; its %d days ran out on %s" % (
                    names.get(lv, lv), held.isoformat(), days, drop.isoformat()))
    if proposed[mode] != proposed[other]:
        notes.append("The two readings disagree today (%s vs %s): the owner's choice of exit rule decides." % (
            name(proposed[mode]), name(proposed[other])))
    computed = proposed[mode]
    print("  Computed level (%s): %s" % (mode, name(computed)))

    # (c) date crossings
    print()
    print("(c) Date crossings (flagged when passed, due today or within %d days)" % SOON_DAYS)
    later = []
    for g, t in iter_triggers(alarm):
        tid, met = t.get("id"), t.get("met") is True
        meets, expires = clock_dates(t)
        if meets is not None and not met:
            delta = (meets - today).days
            if delta < 0:
                actions.append("%s passed its threshold date %s (%d day(s) ago) and is still unmet: evaluate it now. "
                               "If the clock no longer applies (for example an external evaluation happened), say so "
                               "in its evidence and clear watchFrom." % (tid, meets.isoformat(), -delta))
            elif delta == 0:
                actions.append("%s reaches its threshold today (%s): evaluate it now." % (tid, meets.isoformat()))
            elif delta <= SOON_DAYS:
                actions.append("%s reaches its threshold on %s, in %d day(s)." % (tid, meets.isoformat(), delta))
            else:
                later.append("%s reaches its threshold on %s (in %d days) if nothing changes" % (
                    tid, meets.isoformat(), delta))
        if expires is not None and met:
            delta = (expires - today).days
            if delta <= 0:
                actions.append("%s's window ended on %s: mark it unmet unless a newer instance renews it "
                               "(record the new instance in eventDate, evidence and url)." % (tid, expires.isoformat()))
            elif delta <= SOON_DAYS:
                actions.append("%s leaves its window on %s, in %d day(s), unless a newer instance renews it." % (
                    tid, expires.isoformat(), delta))
            else:
                later.append("%s leaves its window on %s (in %d days) unless renewed" % (
                    tid, expires.isoformat(), delta))
    for a in actions:
        print("  ! " + a)
    if not actions:
        print("  Nothing due in the next %d days." % SOON_DAYS)
    for line in later:
        print("  later: " + line)

    # (d) W4
    print()
    print("(d) W4 · oversight gap")
    if incidents is not None:
        window, threshold = w4_params(alarm)
        lags_w = incident_lags(incidents, ref=today, window=window)
        lags_all = incident_lags(incidents, ref=today)
        med_w, med_all = median(lag for _, lag in lags_w), median(lag for _, lag in lags_all)
        w4 = next((t for _, t in iter_triggers(alarm) if t.get("id") == "W4"), None)
        should = med_w is not None and med_w >= threshold
        print("  %d-day median: %s across %d incident(s) disclosed %s to %s → W4 should be %s" % (
            window, "–" if med_w is None else "%g days" % med_w, len(lags_w),
            (today - timedelta(days=window - 1)).isoformat(), today.isoformat(), "met" if should else "unmet"))
        print("  All-incident median (the oversight gauge): %s across %d incident(s)" % (
            "–" if med_all is None else "%g days" % med_all, len(lags_all)))
        runs_list = runs if isinstance(runs, list) else []
        gauge = None
        for r in reversed(runs_list):
            gauges = r.get("gauges") if isinstance(r, dict) else None
            over = gauges.get("oversight") if isinstance(gauges, dict) else None
            if isinstance(over, dict):
                gauge = (r.get("date"), over.get("value"))
                break
        if gauge:
            print("  Latest oversight gauge in runs.json: %s (%s)" % (gauge[1], gauge[0]))
            if isinstance(gauge[1], (int, float)) and med_all is not None and abs(gauge[1] - med_all) > 1:
                notes.append("the latest oversight gauge (%s, %s) differs from the all-incident median (%g): the "
                             "next run should use the recomputed value" % (gauge[1], gauge[0], med_all))
        if med_w != med_all:
            shown = ["–" if v is None else "%g" % v for v in (med_w, med_all)]
            notes.append("W4's %d-day median (%s) and the all-incident gauge median (%s) differ: quote the "
                         "windowed figure in W4's evidence." % (window, shown[0], shown[1]))
        if w4 is None:
            problems.append("no W4 trigger in alarm.json")
        elif (w4.get("met") is True) != should:
            problems.append("W4.met=%s but the %d-day median is %s days (threshold %d): set W4.met to %s" % (
                json.dumps(w4.get("met")), window, "–" if med_w is None else "%g" % med_w, threshold,
                json.dumps(should)))
    else:
        print("  Skipped (no incidents data).")

    # (e) reviews due
    print()
    print("(e) Reviews due")
    due = []
    for i, h in enumerate(history):
        rd = parse_date(h.get("reviewDue"))
        if rd is not None and rd <= today and h.get("review") is None:
            due.append("history[%d] (%s, %s → %s) was due for its 90-day review on %s; publish the review." % (
                i, h.get("date"), "initial" if h.get("from") is None else h.get("from"), h.get("to"), rd.isoformat()))
    for line in due:
        print("  ! " + line)
    if not due:
        nxt = sorted(parse_date(h.get("reviewDue")) for h in history
                     if parse_date(h.get("reviewDue")) and h.get("review") is None)
        print("  None due." + (" Next: %s." % nxt[0].isoformat() if nxt else ""))
    actions.extend(due)

    # consistency and the verdict
    cur_met = current.get("met") if isinstance(current.get("met"), list) else []
    if cur_level not in names:
        problems.append("current.level=%s is not a defined level" % json.dumps(cur_level))
    pending = computed != in_force
    stale = []
    if sorted(cur_met, key=id_key) != flags:
        stale.append("current.met=%s but the triggers marked met are %s" % (json.dumps(cur_met), json.dumps(flags)))
    if cur_level != in_force:
        stale.append("current.level=%s but history[-1].to=%s" % (json.dumps(cur_level), in_force))
    if history and current.get("since") != last.get("date"):
        stale.append("current.since=%s but history[-1].date=%s" % (
            json.dumps(current.get("since")), json.dumps(last.get("date"))))
    if isinstance(cur_level, int) and cur_level < computed and not pending:
        stale.append("current.level=%s is below the computed level %s" % (cur_level, computed))
    runs_list = runs if isinstance(runs, list) else []
    todays = [r for r in runs_list if isinstance(r, dict) and r.get("date") == today.isoformat()]
    if todays:
        ra = todays[-1].get("alarm")
        if not isinstance(ra, dict) or ra.get("level") != cur_level or \
                sorted(ra.get("met") or [], key=id_key) != sorted(cur_met, key=id_key):
            notes.append("today's runs.json entry has alarm=%s; it must equal {level: %s, met: %s} before "
                         "publishing" % (json.dumps(ra), json.dumps(cur_level), json.dumps(cur_met)))

    print()
    for p in problems:
        print("ERROR  " + p)
    if pending:
        direction = "rise" if computed > in_force else "drop"
        print("PENDING  a level %s is due: %s → %s (%s)." % (direction, name(in_force), name(computed), mode))
        print("  Write history[] {date: %s, from: %s, to: %s, triggers: %s, note: <the evidence>, reviewDue: %s, "
              "review: null}; set current {level: %s, since: %s, met: %s, note}; set today's runs.json alarm; "
              "rerun. Draft the alert with kit_broadcast.py --alarm only after a clean rerun." % (
                  today.isoformat(), in_force, computed, json.dumps(flags),
                  (today + timedelta(days=90)).isoformat(), computed, today.isoformat(), json.dumps(flags)))
        for s in stale:
            print("  (to update: %s)" % s)
    else:
        for s in stale:
            print("ERROR  " + s)
    for n in notes:
        print("NOTE   " + n)
    if problems or (stale and not pending):
        print("Result: inconsistent (exit 1)")
        return 1
    if pending:
        print("Result: level change pending (exit 10)")
        return 10
    print("Result: consistent (exit 0)%s" % (" · %d action(s) flagged above" % len(actions) if actions else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
