"""Bring the week's Jobs edition into the newsletter (the Jobs plugin's spec, 8.1).

    python3 scripts/import_jobs.py --date FRIDAY [--plugin DIR] [--root DIR]

The plugin is the post_agi_work repo: --plugin, else $JOBS_PLUGIN, else ../post_agi_work next to this repo. Only its
committed HEAD is read (git show), so a half-finished Thursday run is invisible. The newest editions/<date>.json dated
in the seven days up to and including FRIDAY is validated with the newsletter's own rules (checks/jobs.py and the
denylist in check_data.py), then written to data/jobs/<FRIDAY>.json (with "edition" and "source" added) along with
data/jobs/claims.json; any corrections it carries are appended once to data/corrections.json (section "jobs",
emailed null), so they reach changes.html and the next daily email like any other correction.

Exit 0: imported. Exit 3: no plugin, or no edition in the window (normal: the wrap-up goes out without Jobs).
Exit 2: the edition or claims are invalid; nothing is written. Running it again with the same inputs changes nothing.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from checks.jobs import validate_claims, validate_edition  # noqa: E402

ROOT = SCRIPTS.parent
WINDOW_DAYS = 6


def _git(plugin, *args):
    r = subprocess.run(["git", "-C", str(plugin), *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def find_plugin(arg, root):
    """The plugin checkout: a directory whose committed HEAD has claims.json, or None."""
    for cand in (arg, os.environ.get("JOBS_PLUGIN"), str(Path(root).resolve().parent / "post_agi_work")):
        if not cand:
            continue
        p = Path(cand).expanduser()
        return p if p.is_dir() and _git(p, "cat-file", "-e", "HEAD:claims.json") is not None else None
    return None


def pick_edition(plugin, friday):
    """(date, text) of the newest committed edition dated friday-6 .. friday, or None."""
    end = date.fromisoformat(friday)
    start = (end - timedelta(days=WINDOW_DAYS)).isoformat()
    names = (_git(plugin, "ls-tree", "--name-only", "HEAD", "editions/") or "").split()
    dated = sorted(Path(n).stem for n in names if n.endswith(".json") and start <= Path(n).stem <= friday)
    if not dated:
        return None
    d = dated[-1]
    return d, _git(plugin, "show", f"HEAD:editions/{d}.json")


def _dump(doc):
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def _strict_loads(text):
    """json.loads that refuses duplicate keys and NaN/Infinity, which check_data refuses too."""
    def pairs(items):
        seen = {}
        for k, v in items:
            if k in seen:
                raise ValueError(f"duplicate key {k!r}")
            seen[k] = v
        return seen

    def const(name):
        raise ValueError(f"{name} is not valid JSON")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=const)


def _data_problems(doc, text, label):
    """The rules check_data.py applies to every data file, run before anything is written, so a file the import
    accepts can never stop the Friday push later (the 2026-10-06 review's Important 2): every URL-like field strict
    (the denylist is an error), no script or data: strings anywhere, nothing that looks like a key."""
    import check_data
    f = check_data.Findings()
    check_data.walk_urls(f, doc, label, lambda where: True)
    for name, pat in check_data.KEY_PATTERNS:
        if pat.search(text or ""):
            f.err(f"{label} looks like it holds {name}")
    return f.errors


def import_edition(root, plugin, friday):
    """(exit code, one line)."""
    root = Path(root)
    if plugin is None:
        return 3, "Jobs: skipped (no plugin checkout with a committed claims.json)"
    got = pick_edition(plugin, friday)
    if not got:
        return 3, f"Jobs: skipped (no edition dated in the seven days to {friday})"
    d, text = got
    claims_text = _git(plugin, "show", "HEAD:claims.json")
    sha = (_git(plugin, "rev-parse", "--short", "HEAD") or "").strip()
    rel = f"data/jobs/{friday}.json"
    try:
        doc, claims = _strict_loads(text), _strict_loads(claims_text)
        if not isinstance(doc, dict):
            raise ValueError("the edition is not a JSON object")
        doc["edition"] = doc.get("date")
        doc["source"] = f"post_agi_work@{sha}"
        problems = (validate_edition(doc, rel) + [f"claims.json: {m}" for m in validate_claims(claims)]
                    + _data_problems(doc, text, rel) + _data_problems(claims, claims_text, "data/jobs/claims.json"))
    except Exception as e:  # noqa: BLE001 - any surprise is a refusal (exit 2, nothing written), never a traceback
        return 2, f"Jobs: refused ({type(e).__name__}: {e})"
    if problems:
        return 2, "Jobs: refused (" + "; ".join(problems[:5]) + (f"; and {len(problems) - 5} more" if len(problems) > 5 else "") + ")"
    (root / "data/jobs").mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(_dump(doc), encoding="utf-8")
    (root / "data/jobs/claims.json").write_text(claims_text if claims_text.endswith("\n") else claims_text + "\n", encoding="utf-8")
    added = _append_corrections(root, doc.get("corrections") or [])
    return 0, f"Jobs: imported the edition of {d} into {rel} (post_agi_work@{sha})" + (f"; {added} correction(s) logged" if added else "")


def _append_corrections(root, corrections):
    path = root / "data/corrections.json"
    if not corrections or not path.exists():
        return 0
    log = json.loads(path.read_text(encoding="utf-8"))
    have = {(c.get("date"), c.get("item"), c.get("section")) for c in log.get("corrections") or []}
    added = 0
    for c in corrections:
        if (c.get("date"), c.get("item"), "jobs") in have:
            continue
        entry = {k: c.get(k) for k in ("date", "page", "item", "was", "now", "url")}
        entry["page"] = entry.get("page") or "jobs.html"
        entry.update(emailed=None, section="jobs")
        log.setdefault("corrections", []).append(entry)
        added += 1
    if added:
        path.write_text(_dump(log), encoding="utf-8")
    return added


def main(argv=None):
    ap = argparse.ArgumentParser(description="Import the week's Jobs edition from the post_agi_work plugin.")
    ap.add_argument("--date", required=True, help="the wrap-up's Friday, YYYY-MM-DD")
    ap.add_argument("--plugin", help="the plugin checkout (default: $JOBS_PLUGIN, then ../post_agi_work)")
    ap.add_argument("--root", default=str(ROOT), help="the newsletter repo root")
    a = ap.parse_args(argv)
    code, line = import_edition(Path(a.root), find_plugin(a.plugin, a.root), a.date)
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
