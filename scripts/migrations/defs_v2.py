#!/usr/bin/env python3
"""The definitions v2.0 method change: one migration, applied once at go-live (FINAL_SPEC 8.3-8.5, 16).

    python3 scripts/migrations/defs_v2.py --date YYYY-MM-DD [--dry-run]       # default: print every edit, write nothing
    python3 scripts/migrations/defs_v2.py --date YYYY-MM-DD --apply           # write the edits
    python3 scripts/migrations/defs_v2.py --date YYYY-MM-DD --display-only    # only the escape.json display wording
    options: --root DIR (repository root; default this script's repo), --full (print edits untruncated)

What --apply writes, all from scripts/migrations/defs_v2.json (the staged text):
  data/method.json             appends the v2.0 changelog entry dated --date (definitions, definitionText, factors,
                               rule, change, why) and sets the top-level version to "2.0";
  data/alarm.json              Y1's trigger restated on definitions v2.0, version "1.2", a changelog entry dated
                               --date that records the same-day re-evaluation (the real level and met conditions),
                               and a display-only `short` label on all 15 conditions;
  data/agi_claims.json         definitions.v2 and meets.v2 = "no" on every claim;
  data/external_forecasts.json bar/gap copied to barV1/gapV1, then bar/gap set against v2.0; note likewise;
  data/gauges.json             the delegation gauge's unit and how-text say "rung", not "level";
  data/escape.json             the three "Watching, ..." leads open "Open, ..."; the status legend in
                               Quiet / Open / Confirmed words (display only; also what --display-only writes);
  data/agi_components.json     adopted = --date;
  data/calendar.json           a display-only `short` on the 2026-11-07 alarm clock (the date W2 is met), so the
                               report's and the email's dates line reads whole (the title cuts at its parenthesis).

It is idempotent: an edit that is already in place is reported as done and skipped, so a second --apply
writes nothing. It refuses (exit 2, nothing written) when the data disagree with the staged text: a v2.0
entry with another date, Y1 edited since staging, an alarm level change pending or a case open, a run dated
after --date, or a newest reading whose v1.0 numbers differ from the ones the method entry quotes.

Exit codes: 0 done (or nothing to do), 2 refused. Stdlib only.
"""
import argparse
import copy
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent.parent
STAGED = HERE / "defs_v2.json"
FILES = ("method", "alarm", "agi_claims", "external_forecasts", "gauges", "escape", "agi_components", "calendar", "runs")
CLOSED_CASE = {"closed", "refuted", "retracted", "dismissed", "rejected", "failed", "not met", "withdrawn"}


class Refuse(Exception):
    pass


def vtuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def load(path):
    text = path.read_text(encoding="utf-8")
    return json.loads(text), text.endswith("\n")


def dump(doc, newline):
    return json.dumps(doc, ensure_ascii=False, indent=1) + ("\n" if newline else "")


def short(v, full):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if full or len(s) <= 160 else s[:157] + "..."


def level_name(alarm, level):
    for lv in alarm.get("levels") or []:
        if isinstance(lv, dict) and lv.get("level") == level:
            return lv.get("name")
    return None


def and_list(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def triggers(alarm):
    for g in alarm.get("groups") or []:
        for t in (g.get("triggers") or []) if isinstance(g, dict) else []:
            if isinstance(t, dict):
                yield t


class Migration:
    def __init__(self, root, day, full=False):
        self.root, self.day, self.full = root, day, full
        self.staged = json.loads(STAGED.read_text(encoding="utf-8"))
        self.docs, self.newline, self.before = {}, {}, {}
        for name in FILES:
            p = root / "data" / (name + ".json")
            if not p.exists():
                raise Refuse("data/%s.json is missing" % name)
            self.docs[name], self.newline[name] = load(p)
            self.before[name] = copy.deepcopy(self.docs[name])
        self.edits, self.done, self.notes = [], [], []

    # ---- bookkeeping
    def edit(self, name, where, old, new):
        self.edits.append((name, where, old, new))

    def already(self, name, what):
        self.done.append("data/%s.json: %s" % (name, what))

    # ---- preflight (only what the definitions change needs; --display-only skips it)
    def preflight(self):
        runs = self.docs["runs"]
        later = sorted({r.get("date") for r in runs if isinstance(r, dict) and str(r.get("date")) > self.day})
        if later:
            raise Refuse("runs.json has readings dated after %s (%s): the method entry must be dated on or after the "
                         "newest reading" % (self.day, ", ".join(later)))
        comp = self.docs["agi_components"]
        if comp.get("definitionsVersion") != self.staged["method"]["definitions"]:
            raise Refuse("agi_components.json definitionsVersion is %r, not %r"
                         % (comp.get("definitionsVersion"), self.staged["method"]["definitions"]))
        if (comp.get("definition") or {}).get("text") != self.staged["method"]["definitionText"]:
            raise Refuse("agi_components.json definition.text differs from the staged method entry's definitionText")
        if len(comp.get("components") or []) != 8:
            raise Refuse("agi_components.json does not list the eight parts")
        if self.method_state() == "todo":
            self.check_v1_numbers()
        if self.alarm_state() == "todo":
            self.check_alarm_quiet()

    def check_v1_numbers(self):
        pub = [r for r in self.docs["runs"] if isinstance(r, dict) and r.get("report") and r.get("comparable") is not False
               and str(r.get("date")) <= self.day]
        if not pub:
            raise Refuse("no published reading on or before %s" % self.day)
        r, want = pub[-1], self.staged["v1Numbers"]
        got = {"agi": {k: (r.get("agi") or {}).get(k) for k in ("now", "y2030", "y2035")},
               "probs": {h: {k: ((r.get("probs") or {}).get(h) or {}).get(k) for k in ("now", "y2030", "y2035")}
                         for h in want["probs"]},
               "index": r.get("index")}
        bad = []
        if got["agi"] != want["agi"]:
            bad.append("agi %s" % got["agi"])
        for h, v in want["probs"].items():
            if got["probs"][h] != v:
                bad.append("%s %s" % (h, got["probs"][h]))
        if got["index"] != want["index"]:
            bad.append("index %s" % got["index"])
        if bad:
            raise Refuse("the newest reading (%s) is not the one the method entry's worked numbers quote (%s): %s. "
                         "Recompute the change text from that reading with the same factors (FINAL_SPEC 8.3) and update "
                         "scripts/migrations/defs_v2.json first" % (r.get("date"), self.staged["numbersAsOf"], "; ".join(bad)))
        if r.get("defs") not in (None, "1.0"):
            raise Refuse("the newest reading (%s) already carries defs %r" % (r.get("date"), r.get("defs")))

    def check_alarm_quiet(self):
        a = self.docs["alarm"]
        if any(isinstance(h, dict) and h.get("date") == self.day for h in a.get("history") or []):
            raise Refuse("alarm.json has a level change dated %s: criteria never change on a day a level changes" % self.day)
        open_cases = [c for c in a.get("cases") or []
                      if not isinstance(c, dict) or str(c.get("status", "open")).lower() not in CLOSED_CASE]
        if open_cases:
            raise Refuse("alarm.json lists a case that is not closed: criteria never change while one is open")
        met_y = [t["id"] for t in triggers(a) if str(t.get("id", "")).startswith("Y") and t.get("met") is True]
        if met_y:
            raise Refuse("alarm condition %s is met: criteria never change while a Level-3 case stands" % ", ".join(met_y))
        script = self.root / "scripts" / "alarm_check.py"
        if script.exists():
            try:
                p = subprocess.run([sys.executable, str(script), "--today", self.day], cwd=str(self.root),
                                   capture_output=True, text=True, timeout=120)
            except (OSError, subprocess.SubprocessError) as exc:
                raise Refuse("could not run scripts/alarm_check.py: %s" % exc)
            if p.returncode == 10:
                raise Refuse("scripts/alarm_check.py reports a pending alarm level change (exit 10): criteria never "
                             "change while a level change is being considered")
            if p.returncode != 0:
                raise Refuse("scripts/alarm_check.py exits %d: fix alarm.json first\n%s" % (p.returncode, p.stdout[-1500:]))
            self.notes.append("alarm_check.py --today %s: exit 0" % self.day)
        else:
            self.notes.append("scripts/alarm_check.py not found under --root; level-change check skipped")

    # ---- states
    def method_state(self):
        m = self.docs["method"]
        hits = [e for e in m.get("changelog") or [] if isinstance(e, dict) and e.get("definitions") == "2.0"]
        if not hits:
            if vtuple(m.get("version")) >= vtuple(self.staged["method"]["version"]):
                raise Refuse("method.json version is %s but has no definitions 2.0 entry" % m.get("version"))
            return "todo"
        want = dict(self.staged["method"], date=self.day)
        if len(hits) == 1 and hits[0] == want:
            return "done"
        raise Refuse("method.json already has a definitions 2.0 entry (dated %s) that differs from the staged one for "
                     "--date %s; a changelog is append-only, so fix this by hand" % (hits[0].get("date"), self.day))

    def alarm_state(self):
        a, s = self.docs["alarm"], self.staged["alarm"]
        y1 = next((t for t in triggers(a) if t.get("id") == "Y1"), None)
        if y1 is None:
            raise Refuse("alarm.json has no Y1")
        logged = [e for e in a.get("changelog") or [] if isinstance(e, dict) and e.get("version") == s["version"]]
        if a.get("version") == s["version"] and logged and y1.get("trigger") == s["conditions"]["Y1"]["trigger"]:
            if len(logged) != 1 or logged[0].get("date") != self.day:
                raise Refuse("alarm.json criteria %s are logged under another date (%s)" % (s["version"], logged[0].get("date")))
            return "done"
        if a.get("version") != s["fromVersion"] or logged:
            raise Refuse("alarm.json is at criteria %s with %d changelog entr(ies) for %s; expected %s before the migration"
                         % (a.get("version"), len(logged), s["version"], s["fromVersion"]))
        if y1.get("trigger") != s["conditions"]["Y1"]["triggerFrom"]:
            raise Refuse("Y1's trigger text changed since the migration was staged; update defs_v2.json first")
        return "todo"

    # ---- edits
    def do_method(self):
        if self.method_state() == "done":
            self.already("method", "definitions 2.0 entry dated %s" % self.day)
        else:
            m = self.docs["method"]
            entry = dict(self.staged["method"], date=self.day)
            m["changelog"].append(entry)
            self.edit("method", "changelog[+]", None, entry)
        m = self.docs["method"]
        top = max((e.get("version") for e in m["changelog"] if isinstance(e, dict)), key=vtuple)
        if m.get("version") != top:
            self.edit("method", "version", m.get("version"), top)
            m["version"] = top

    def reevaluated(self):
        a = self.docs["alarm"]
        cur = a.get("current") or {}
        lv = cur.get("level")
        name = level_name(a, lv)
        met = list(cur.get("met") or [])
        level = "Level %s · %s" % (lv, name) if name else "Level %s" % lv
        on = ("on %s" % and_list(met)) if met else "with no condition met"
        return "the level stays %s %s; no Y condition is met and no case is open." % (level, on)

    def do_alarm(self):
        a, s = self.docs["alarm"], self.staged["alarm"]
        if self.alarm_state() == "done":
            self.already("alarm", "criteria %s (Y1 restated, changelog dated %s)" % (s["version"], self.day))
        else:
            y1 = next(t for t in triggers(a) if t.get("id") == "Y1")
            self.edit("alarm", "groups[Y1].trigger", y1["trigger"], s["conditions"]["Y1"]["trigger"])
            y1["trigger"] = s["conditions"]["Y1"]["trigger"]
            self.edit("alarm", "version", a.get("version"), s["version"])
            a["version"] = s["version"]
            log = dict(s["changelog"], date=self.day)
            log["change"] = log["change"].format(reevaluated=self.reevaluated())
            a["changelog"].append(log)
            self.edit("alarm", "changelog[+]", None, log)
        relabelled = 0
        for t in triggers(a):
            want = s["short"].get(t.get("id"))
            if want is None:
                self.notes.append("alarm condition %s has no staged short label" % t.get("id"))
            elif t.get("short") != want:
                self.edit("alarm", "groups[%s].short" % t["id"], t.get("short"), want)
                t["short"] = want
                relabelled += 1
        if not relabelled:
            self.already("alarm", "short labels")

    def do_claims(self):
        c, s = self.docs["agi_claims"], self.staged["agiClaims"]
        defs = c.setdefault("definitions", {})
        if defs.get("v2") != s["definitionV2"]:
            self.edit("agi_claims", "definitions.v2", defs.get("v2"), s["definitionV2"])
            defs["v2"] = s["definitionV2"]
        n = 0
        for i, cl in enumerate(c.get("claims") or []):
            meets = cl.setdefault("meets", {})
            if "v2" not in meets:
                meets["v2"] = s["meetsV2"]
                n += 1
                self.edit("agi_claims", "claims[%d].meets.v2 (%s, %s)" % (i, cl.get("who"), cl.get("date")), None, s["meetsV2"])
            elif meets["v2"] != s["meetsV2"]:
                self.notes.append("agi_claims claims[%d] already has meets.v2=%r; left as is" % (i, meets["v2"]))
        if not n and defs.get("v2") == s["definitionV2"]:
            self.already("agi_claims", "definitions.v2 and meets.v2")

    def do_external(self):
        e, s = self.docs["external_forecasts"], self.staged["externalForecasts"]
        rows = {(r["who"], r["what"]): r for r in s["forecasts"]}
        touched = False
        if "noteV1" not in e:
            e["noteV1"] = e.get("note")
            e["note"] = s["note"]
            self.edit("external_forecasts", "note (old kept as noteV1)", e["noteV1"], s["note"])
            touched = True
        for i, f in enumerate(e.get("forecasts") or []):
            key = (f.get("who"), f.get("what"))
            if "barV1" in f:
                continue
            if key not in rows:
                self.notes.append("external_forecasts forecasts[%d] (%s: %s) is not in the staged list; left on v1.0 wording "
                                  "for the weekly external lens" % (i, key[0], key[1]))
                continue
            f["barV1"], f["gapV1"] = f.get("bar"), f.get("gap")
            new = rows[key]
            label = "forecasts[%d] (%s: %s)" % (i, key[0], key[1])
            self.edit("external_forecasts", label + " barV1/gapV1", None, "copied from bar/gap")
            if f.get("bar") != new["bar"]:
                self.edit("external_forecasts", label + " bar", f.get("bar"), new["bar"])
            if f.get("gap") != new["gap"]:
                self.edit("external_forecasts", label + " gap", f.get("gap"), new["gap"])
            f["bar"], f["gap"] = new["bar"], new["gap"]
            touched = True
        if not touched:
            self.already("external_forecasts", "barV1/gapV1 and v2.0 bar/gap")

    def do_gauges(self):
        g, s = self.docs["gauges"], self.staged["gauges"]
        for key, fields in s.items():
            row = next((x for x in g.get("gauges") or [] if x.get("key") == key), None)
            if row is None:
                raise Refuse("gauges.json has no %s gauge" % key)
            for field, (old, new) in fields.items():
                if row.get(field) == new:
                    self.already("gauges", "%s.%s" % (key, field))
                elif row.get(field) == old:
                    self.edit("gauges", "%s.%s" % (key, field), old, new)
                    row[field] = new
                else:
                    self.notes.append("gauges %s.%s is %r, neither the staged old nor new text; left as is"
                                      % (key, field, row.get(field)))

    def do_escape(self):
        e, s = self.docs["escape"], self.staged["escape"]
        for ind in e.get("indicators") or []:
            lead = s["statusReasonLeads"].get(ind.get("key"))
            if not lead:
                continue
            r = ind.get("statusReason") or ""
            if r.startswith(lead["from"]):
                new = lead["to"] + r[len(lead["from"]):]
                self.edit("escape", "indicators[%s].statusReason (lead)" % ind["key"], lead["from"], lead["to"])
                ind["statusReason"] = new
            elif r.startswith(lead["to"]):
                self.already("escape", "%s lead" % ind["key"])
            else:
                self.notes.append("escape %s statusReason no longer opens with %r; left as is (the renderer drops a "
                                  "leading 'Watching,' clause)" % (ind["key"], lead["from"]))
        legend = e.get("statusLegend")
        if legend != s["statusLegend"]:
            self.edit("escape", "statusLegend", legend, s["statusLegend"])
            e["statusLegend"] = copy.deepcopy(s["statusLegend"])
        else:
            self.already("escape", "statusLegend")

    def do_components(self):
        c = self.docs["agi_components"]
        if c.get("adopted") == self.day:
            self.already("agi_components", "adopted %s" % self.day)
        elif c.get("adopted") is None:
            self.edit("agi_components", "adopted", None, self.day)
            c["adopted"] = self.day
        else:
            raise Refuse("agi_components.json was adopted on %s, not %s" % (c.get("adopted"), self.day))

    def do_calendar(self):
        """Display-only `short` lines for dated events whose titles cut badly in the dates line (the W2 clock: the
        report's next_dates always keeps the next alarm clock, so its line must read whole). Matched by date, kind
        and the start of the title; a missing or renamed event is a note, never a refusal (the weekly edits the file)."""
        c, s = self.docs["calendar"], self.staged.get("calendar") or {}
        for want in s.get("shorts") or []:
            ev = next((x for x in c.get("events") or [] if isinstance(x, dict) and x.get("date") == want["date"]
                       and x.get("kind") == want["kind"] and str(x.get("title") or "").startswith(want["titleStart"])),
                      None)
            label = "events[%s %s].short" % (want["date"], want["kind"])
            if ev is None:
                self.notes.append("calendar has no %s event dated %s whose title starts %r; no short written"
                                  % (want["kind"], want["date"], want["titleStart"]))
            elif ev.get("short") == want["short"]:
                self.already("calendar", label)
            else:
                self.edit("calendar", label, ev.get("short"), want["short"])
                ev["short"] = want["short"]

    # ---- run
    def plan(self, display_only):
        if display_only:
            self.do_escape()
            return
        self.preflight()
        self.do_method()
        self.do_alarm()
        self.do_claims()
        self.do_external()
        self.do_gauges()
        self.do_escape()
        self.do_components()
        self.do_calendar()
        self.validate()

    def validate(self):
        m, a, c = self.docs["method"], self.docs["alarm"], self.docs["agi_components"]
        if m.get("version") != max((e.get("version") for e in m["changelog"]), key=vtuple):
            raise Refuse("internal: method.json version is not its highest changelog version")
        if self.before["method"]["changelog"] != m["changelog"][:len(self.before["method"]["changelog"])]:
            raise Refuse("internal: method.json changelog is not append-only")
        if self.before["alarm"]["changelog"] != a["changelog"][:len(self.before["alarm"]["changelog"])]:
            raise Refuse("internal: alarm.json changelog is not append-only")
        if self.before["alarm"].get("history") != a.get("history") or self.before["alarm"].get("current") != a.get("current"):
            raise Refuse("internal: the migration must not touch alarm history or current")
        entry = next(e for e in m["changelog"] if e.get("definitions") == "2.0")
        if entry["definitionText"] != c["definition"]["text"] or c["adopted"] != entry["date"]:
            raise Refuse("internal: method entry and agi_components.json disagree")
        if any(not (0 < v <= 1) for v in entry["factors"].values()):
            raise Refuse("internal: factors must be in (0, 1]")
        if self.docs["runs"] != self.before["runs"]:
            raise Refuse("internal: runs.json must not change")

    def write(self):
        changed = [n for n in FILES if self.docs[n] != self.before[n]]
        for name in changed:
            p = self.root / "data" / (name + ".json")
            tmp = p.with_name(p.name + ".tmp-defs_v2")
            tmp.write_text(dump(self.docs[name], self.newline[name]), encoding="utf-8")
            json.loads(tmp.read_text(encoding="utf-8"))
            os.replace(tmp, p)
        return changed

    def report(self, mode):
        print("defs_v2 %s for %s (root %s)" % (mode, self.day, self.root))
        if self.edits:
            print("\nEdits (%d):" % len(self.edits))
            for name, where, old, new in self.edits:
                print("  data/%s.json  %s" % (name, where))
                if old is not None:
                    print("      was: %s" % short(old, self.full))
                print("      now: %s" % short(new, self.full))
        if self.done:
            print("\nAlready in place (%d):" % len(self.done))
            for d in self.done:
                print("  " + d)
        if self.notes:
            print("\nNotes:")
            for n in self.notes:
                print("  " + n)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Definitions v2.0 method-change migration (FINAL_SPEC 8.3-8.5).")
    ap.add_argument("--date", required=True, help="the method entry's date, YYYY-MM-DD (go-live day, Pacific)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="print every edit and write nothing (the default)")
    g.add_argument("--apply", action="store_true", help="write the edits")
    ap.add_argument("--display-only", action="store_true",
                    help="only the escape.json display wording (no definitions change); combine with --apply to write")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="repository root (default: this script's repo)")
    ap.add_argument("--full", action="store_true", help="print edits untruncated")
    a = ap.parse_args(argv)
    try:
        day = datetime.strptime(a.date, "%Y-%m-%d").date().isoformat()
    except ValueError:
        ap.error("--date must be YYYY-MM-DD")
    root = Path(a.root).resolve()
    mode = ("apply" if a.apply else "dry run") + (" (display only)" if a.display_only else "")
    try:
        mig = Migration(root, day, a.full)
        mig.plan(a.display_only)
    except Refuse as exc:
        print("defs_v2: REFUSED, nothing written: %s" % exc, file=sys.stderr)
        return 2
    mig.report(mode)
    if not mig.edits:
        print("\nNothing to do: every edit is already in place.")
        return 0
    if not a.apply:
        print("\nDry run: nothing written. Re-run with --apply to write these %d edits." % len(mig.edits))
        return 0
    changed = mig.write()
    print("\nWrote: " + ", ".join("data/%s.json" % n for n in changed))
    if not a.display_only:
        nxt = date.fromisoformat(day).toordinal() + 1
        print("Next: python3 scripts/alarm_check.py; python3 scripts/build_pages.py; python3 scripts/build_feed.py; "
              "python3 scripts/check_data.py (expect the WARN 'alarm criteria changed under changelog 1.2'); "
              "python3 scripts/defs_status.py --date %s (must print mode \"method-change\")."
              % date.fromordinal(nxt).isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
