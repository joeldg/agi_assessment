#!/usr/bin/env python3
"""Which AGI definitions are in force for a reading, and is it the first reading under new ones? (FINAL_SPEC 8.3, 10.1)

    python3 scripts/defs_status.py [--date YYYY-MM-DD] [--root DIR]     # default date: today, Pacific

Prints one JSON object and never writes anything:
  date            the reading's date
  defsInForce     the `definitions` value of the last data/method.json changelog entry (in list order) that has
                  one and is dated before `date`; "1.0" if none. The method entry's own day stays on the old
                  definitions; the next day's reading is the first under the new ones.
  latestRunDefs   `defs` of the newest published reading dated before `date` (missing = "1.0"). Readings dated
                  `date` itself are ignored, so a same-day rerun still compares with yesterday.
  mode            "method-change" when latestRunDefs differs from defsInForce, else "steady"
  entry           the method entry in force {version, date, definitions, factors, rule}, or null
  prevPublished   {date, report, analysis?, defs} of that newest published reading, or null
  componentsFile  true when data/agi_components.json exists and parses with its eight parts
  definitionsVersion, adopted, definitionText, hypotheses
                  from data/agi_components.json (null when it is missing), for the workflow's DEFS_V2 block
  componentsError present only when the file exists but can't be used

A published reading is a runs.json entry with a `report` whose `comparable` isn't false (the chat baseline isn't).
Exit codes: 0 always when it can read method.json and runs.json; 2 when it can't. Stdlib only.
"""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def today_pacific():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:  # no tz database: fall back to the machine's clock (the routines run in Pacific time)
        return date.today().isoformat()


def _defs_in_force(method, day):
    """The definitions in force for a reading dated `day` (FINAL_SPEC 8.3). Same contract as sitekit.defs_in_force."""
    found = "1.0"
    for e in (method or {}).get("changelog") or []:
        if isinstance(e, dict) and e.get("definitions") and isinstance(e.get("date"), str) and e["date"] < day:
            found = str(e["definitions"])
    return found


def _entry_in_force(method, day):
    found = None
    for e in (method or {}).get("changelog") or []:
        if isinstance(e, dict) and e.get("definitions") and isinstance(e.get("date"), str) and e["date"] < day:
            found = e
    return found


def defs_in_force(method, day):
    """Use the shared helper in sitekit when it exists (one rule for the feed, check_data and this script)."""
    local = _defs_in_force(method, day)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import sitekit  # noqa: E402
        shared = getattr(sitekit, "defs_in_force", None)
        value = shared(method, day) if callable(shared) else None
    except Exception:
        value = None
    if value is None:
        return local
    if value != local:
        print("defs_status: sitekit.defs_in_force gives %r, the local rule %r; using sitekit's" % (value, local),
              file=sys.stderr)
    return value


def published(runs):
    return [r for r in runs if isinstance(r, dict) and r.get("report") and r.get("comparable") is not False]


def status(root, day):
    method = json.loads((root / "data/method.json").read_text(encoding="utf-8"))
    runs = json.loads((root / "data/runs.json").read_text(encoding="utf-8"))
    in_force = defs_in_force(method, day)
    entry = _entry_in_force(method, day)
    if entry is not None and str(entry.get("definitions")) != in_force:
        entry = None   # sitekit and the local rule disagree; never pair a value with the wrong entry
    before = [r for r in published(runs) if isinstance(r.get("date"), str) and r["date"] < day]
    prev = before[-1] if before else None
    latest = str(prev.get("defs") or "1.0") if prev else None
    out = {
        "date": day,
        "defsInForce": in_force,
        "latestRunDefs": latest,
        "mode": "method-change" if prev is not None and latest != in_force else "steady",
        "entry": ({k: entry.get(k) for k in ("version", "date", "definitions", "factors", "rule")} if entry else None),
        "prevPublished": ({k: v for k, v in (("date", prev.get("date")), ("report", prev.get("report")),
                                             ("analysis", prev.get("analysis")), ("defs", latest)) if v is not None}
                          if prev else None),
        "componentsFile": False,
        "definitionsVersion": None,
        "adopted": None,
        "definitionText": None,
        "hypotheses": None,
    }
    p = root / "data/agi_components.json"
    if p.exists():
        try:
            comp = json.loads(p.read_text(encoding="utf-8"))
            parts = comp.get("components")
            if not isinstance(parts, list) or len(parts) != 8:
                raise ValueError("it does not list the eight parts")
            out.update(componentsFile=True, definitionsVersion=comp.get("definitionsVersion"), adopted=comp.get("adopted"),
                       definitionText=(comp.get("definition") or {}).get("text"), hypotheses=comp.get("hypotheses"))
        except (ValueError, AttributeError) as exc:
            out["componentsError"] = "data/agi_components.json can't be used: %s" % exc
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Definitions in force for a reading (read-only).")
    ap.add_argument("--date", help="the reading's date, YYYY-MM-DD (default: today, Pacific)")
    ap.add_argument("--root", default=str(ROOT), help="repository root (default: this script's repo)")
    a = ap.parse_args(argv)
    day = a.date or today_pacific()
    try:
        day = datetime.strptime(day, "%Y-%m-%d").date().isoformat()
    except ValueError:
        ap.error("--date must be YYYY-MM-DD")
    try:
        out = status(Path(a.root).resolve(), day)
    except (OSError, ValueError) as exc:
        print("defs_status: can't read data/method.json or data/runs.json: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
