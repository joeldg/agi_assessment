#!/usr/bin/env python3
"""Create a Kit broadcast for a daily report, using the same email body as feed.xml.

Kit's RSS-to-email is a paid feature, but its API is available on every plan, so the
routine pushes each issue in directly.

    python3 scripts/kit_broadcast.py                 # latest report, saved as a Kit DRAFT
    python3 scripts/kit_broadcast.py --date 2026-09-29
    python3 scripts/kit_broadcast.py --dry-run       # build and print, send nothing
    python3 scripts/kit_broadcast.py --send-at 2026-09-30T13:00:00Z   # schedule a send
    python3 scripts/kit_broadcast.py --send-at 10am  # 10:00 America/Los_Angeles on the run date;
                                                     # if that has passed, it stays a draft

Credentials come from the environment: KIT_API_KEY (v4 key, sent as X-Kit-Api-Key) or,
failing that, the v3 KIT_API_SECRET. Keys are never printed or written to disk.
data/kit_broadcasts.json records which dates already have a broadcast, so reruns don't
create duplicates.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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


def resolve_send_at(value, run_date):
    """Turn --send-at into a UTC ISO time, or None (draft) if a local time has already passed."""
    if not value:
        return None
    m = re.fullmatch(r"(\d{1,2})(am|pm)", value.lower())
    if not m:
        return value
    hour = int(m.group(1)) % 12 + (12 if m.group(2) == "pm" else 0)
    local = datetime.strptime(run_date, "%Y-%m-%d").replace(hour=hour, tzinfo=ZoneInfo("America/Los_Angeles"))
    if local <= datetime.now(timezone.utc):
        print(f"{value} Pacific on {run_date} has already passed, so this issue stays a DRAFT. Send it by hand in Kit.")
        return None
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def preview(text, limit=140):
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def push_alarm(args):
    """Breaking alert for the latest alarm-level change. Always created as a DRAFT: the owner approves every alarm email."""
    from build_feed import FONT, INK, MUTED, SANS, link, p as para  # noqa: F401
    from html import escape
    a = json.loads((ROOT / "data/alarm.json").read_text())
    e = a["history"][-1]
    key = f"alarm-{e['date']}-{e['to']}"
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if key in state and not args.force and not args.dry_run:
        print(f"Alarm alert for {e['date']} already drafted (broadcast {state[key]['id']}).")
        return
    lv = next(l for l in a["levels"] if l["level"] == e["to"])
    up = e["from"] is None or e["to"] > e["from"]
    trig = {t["id"]: t for g in a["groups"] for t in g["triggers"]}
    items = "".join(f'<li><strong>{t}</strong>: {escape(trig[t]["trigger"])}. {escape(trig[t].get("evidence") or "")}'
                    + (f' {link(trig[t]["url"] if trig[t]["url"].startswith("http") else SITE + trig[t]["url"], "source")}' if trig[t].get("url") else "")
                    + "</li>" for t in e["triggers"] if t in trig)
    body = (para(f'<span style="{SANS}font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:{MUTED};font-weight:600">Breaking · fire alarm</span>')
            + f'<h1 style="{FONT}font-size:26px;color:{INK};margin:6px 0">{lv["icon"]} Level {lv["level"]}: {lv["name"]}</h1>'
            + para(escape(lv["meaning"]))
            + para(escape(e["note"]))
            + para("<strong>Triggers met:</strong>") + f'<ul style="{SANS}font-size:15px;line-height:1.5;color:{INK}">{items}</ul>'
            + para(f'These criteria were published in advance. The level {"rose" if up else "fell"} because the triggers above were met, under the '
                   f'{link(SITE + "alarm.html", "published rules")}. This change will be reviewed publicly on {e["reviewDue"]}.')
            + para(f'Forwarded this? {link("https://hidden-agi.kit.com/f2b4d2f30e", "Subscribe to Hidden AGI watch")}.')
            + para(f'<span style="color:{MUTED};font-size:13px">Researched and drafted by a custom AI agent. Not investment, policy or security advice.</span>'))
    fields = {"subject": f'{lv["icon"]} Fire alarm: Level {lv["level"]} ({lv["name"]}) · Hidden AGI watch',
              "preview_text": preview(e["note"]), "description": f"Alarm change {e['date']}", "content": body,
              "public": True, "send_at": None}
    if args.dry_run:
        print(f"Subject: {fields['subject']}\nBody: {len(body)} chars\nMode: draft (alarm alerts are always drafts)")
        return
    api, bc = create_broadcast(fields)
    state[key] = {"id": bc.get("id"), "api": api, "send_at": None, "report": SITE + "alarm.html"}
    STATE.write_text(json.dumps(state, indent=1) + "\n")
    print(f"Created Kit ALARM broadcast {bc.get('id')} via {api} as a DRAFT. The owner must review and send it.")


def push_weekly(args):
    from build_weekly import weekly_email_html
    date = args.weekly
    w = json.loads((ROOT / f"data/weekly/{date}.json").read_text())
    if "keyNumbers" not in w:
        sys.exit(f"Run scripts/build_weekly.py {date} first.")
    key = f"weekly-{date}"
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if key in state and not args.force and not args.dry_run:
        print(f"Already pushed the {date} wrap-up to Kit (broadcast {state[key]['id']}).")
        return
    send_at = resolve_send_at(args.send_at, date)
    fields = {
        "subject": f"Weekly wrap-up · Hidden AGI Index {fmt(w['keyNumbers']['index'])}% · {w['headline']}",
        "preview_text": preview(w.get("summary") or ""),
        "description": f"Weekly wrap-up for {date}",
        "content": weekly_email_html(w),
        "public": True,
        "send_at": send_at,
    }
    if args.dry_run:
        print(f"Subject: {fields['subject']}\nBody: {len(fields['content'])} chars\nMode: {'scheduled ' + send_at if send_at else 'draft'}")
        return
    api, bc = create_broadcast(fields)
    state[key] = {"id": bc.get("id"), "api": api, "send_at": send_at, "report": f"{SITE}weekly/{date}.html"}
    STATE.write_text(json.dumps(state, indent=1) + "\n")
    print(f"Created Kit weekly broadcast {bc.get('id')} via {api} ({'scheduled ' + send_at if send_at else 'draft'}).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="run date (YYYY-MM-DD); defaults to the latest report")
    ap.add_argument("--send-at", help="ISO 8601 UTC time, or a Pacific hour like '10am' / '3pm' on the run date; omit for a draft")
    ap.add_argument("--alarm", action="store_true", help="create a BREAKING alert for the latest alarm-level change (always a draft for the owner to approve)")
    ap.add_argument("--weekly", metavar="DATE", help="push the weekly wrap-up for DATE (built by build_weekly.py) instead of a daily issue")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="create even if this date was already pushed")
    args = ap.parse_args()
    if args.alarm:
        return push_alarm(args)
    if args.weekly:
        return push_weekly(args)

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

    send_at = resolve_send_at(args.send_at, run["date"])
    needle = run.get("needle") or {}
    hook = "Quiet day" if needle.get("quiet") else (needle.get("headline") or " · ".join(
        f"{k} {fmt(prob(run, k, 'now'))}%" for k in ("A", "B", "C", "D")))
    idx = run.get("index")
    fields = {
        "subject": (f"Hidden AGI Index {fmt(idx)}% · " if idx is not None else "Hidden AGI watch · ") + hook,
        "preview_text": preview(run.get("summary") or ""),
        "description": f"Daily issue for {run['date']}",
        "content": issue_html(run, prev),
        "public": True,  # also publishes to the Kit web archive / creator profile
        "send_at": send_at,  # None keeps it as a draft
    }
    if args.dry_run:
        print(f"Subject: {fields['subject']}\nPreview: {fields['preview_text']}\n"
              f"Body: {len(fields['content'])} chars of HTML\nMode: {'scheduled ' + send_at if send_at else 'draft'}")
        return

    api, bc = create_broadcast(fields)
    state[run["date"]] = {"id": bc.get("id"), "api": api, "send_at": send_at, "report": SITE + run["report"]}
    STATE.write_text(json.dumps(state, indent=1) + "\n")
    print(f"Created Kit broadcast {bc.get('id')} via {api} ({'scheduled ' + send_at if send_at else 'draft'}).")


if __name__ == "__main__":
    main()
