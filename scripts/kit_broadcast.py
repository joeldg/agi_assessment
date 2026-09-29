#!/usr/bin/env python3
"""Create a Kit broadcast for a daily report, using the same email body as feed.xml.

Kit's RSS-to-email is a paid feature, but its API is available on every plan, so the
routine pushes each issue in directly.

    python3 scripts/kit_broadcast.py                 # latest report, saved as a Kit DRAFT
    python3 scripts/kit_broadcast.py --date 2026-09-29
    python3 scripts/kit_broadcast.py --dry-run       # build and print, send nothing
    python3 scripts/kit_broadcast.py --send-at 2026-09-30T13:00:00Z   # schedule a send

Credentials come from the environment: KIT_API_KEY (v4 key, sent as X-Kit-Api-Key) or,
failing that, the v3 KIT_API_SECRET. Keys are never printed or written to disk.
data/kit_broadcasts.json records which dates already have a broadcast, so reruns don't
create duplicates.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_feed import SITE, fmt, issue_html, pretty_date, prob  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data/kit_broadcasts.json"


def request(method, url, headers=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Accept": "application/json", "Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def create_broadcast(fields):
    """Try the v4 API with KIT_API_KEY, then fall back to v3 with KIT_API_SECRET."""
    key, secret = os.environ.get("KIT_API_KEY"), os.environ.get("KIT_API_SECRET")
    if key:
        status, body = request("POST", "https://api.kit.com/v4/broadcasts",
                               {"X-Kit-Api-Key": key}, fields)
        if status < 300:
            return "v4", body.get("broadcast", body)
        if status not in (401, 403):
            sys.exit(f"Kit v4 API error {status}: {body.get('errors') or body}")
    if secret:
        status, body = request("POST", "https://api.convertkit.com/v3/broadcasts", None,
                               {"api_secret": secret, **fields})
        if status < 300:
            return "v3", body.get("broadcast", body)
        sys.exit(f"Kit v3 API error {status}: {body.get('error') or body.get('message') or body}")
    sys.exit("No usable Kit credentials: set KIT_API_KEY (v4) or KIT_API_SECRET (v3).")


def preview(text, limit=140):
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="run date (YYYY-MM-DD); defaults to the latest report")
    ap.add_argument("--send-at", help="ISO 8601 UTC time to schedule the send; omit for a draft")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="create even if this date was already pushed")
    args = ap.parse_args()

    runs = json.loads((ROOT / "data/runs.json").read_text())
    idx = [i for i, r in enumerate(runs) if r.get("report") and (not args.date or r["date"] == args.date)]
    if not idx:
        sys.exit("No report found for that date.")
    i = idx[-1]
    run, prev = runs[i], (runs[i - 1] if i > 0 else None)

    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if run["date"] in state and not args.force and not args.dry_run:
        print(f"Already pushed {run['date']} to Kit (broadcast {state[run['date']]['id']}); use --force to push again.")
        return

    headline = " · ".join(f"{k} {fmt(prob(run, k, 'now'))}%" for k in ("A", "B", "C", "D"))
    fields = {
        "subject": f"Hidden AGI watch, {pretty_date(run['date'])}: {headline}",
        "preview_text": preview(run.get("summary") or ""),
        "description": f"Daily issue for {run['date']}",
        "content": issue_html(run, prev),
        "public": True,  # also publishes to the Kit web archive / creator profile
        "send_at": args.send_at,  # None keeps it as a draft
    }
    if args.dry_run:
        print(f"Subject: {fields['subject']}\nPreview: {fields['preview_text']}\n"
              f"Body: {len(fields['content'])} chars of HTML\nMode: {'scheduled ' + args.send_at if args.send_at else 'draft'}")
        return

    api, bc = create_broadcast(fields)
    state[run["date"]] = {"id": bc.get("id"), "api": api, "send_at": args.send_at, "report": SITE + run["report"]}
    STATE.write_text(json.dumps(state, indent=1) + "\n")
    print(f"Created Kit broadcast {bc.get('id')} via {api} ({'scheduled ' + args.send_at if args.send_at else 'draft'}).")


if __name__ == "__main__":
    main()
