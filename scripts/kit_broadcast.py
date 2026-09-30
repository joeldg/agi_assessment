#!/usr/bin/env python3
"""Create a Kit broadcast for a daily report, a Friday wrap-up or a fire-alarm alert.

Kit's RSS-to-email is a paid feature, but its API is available on every plan, so the routine
pushes each issue in directly. The daily email body is the same HTML as the feed item.

    python3 scripts/kit_broadcast.py                  # latest report, saved as a Kit DRAFT
    python3 scripts/kit_broadcast.py --date 2026-09-29
    python3 scripts/kit_broadcast.py --dry-run        # build and print, call nothing
    python3 scripts/kit_broadcast.py --date 2026-09-30 --send-at 10am
          # 10:00 Pacific, today's issue only; '10:30am' and '3 pm' work too
    python3 scripts/kit_broadcast.py --send-at 2026-09-30T17:00:00Z   # ISO 8601, timezone required
    python3 scripts/kit_broadcast.py --weekly 2026-10-02 --send-at 3pm # Friday wrap-up, Fridays only
    python3 scripts/kit_broadcast.py --alarm          # alert for the latest level change: ALWAYS a draft
    python3 scripts/kit_broadcast.py --date 2026-09-30 --update --send-at 10am   # change the recorded broadcast
    python3 scripts/kit_broadcast.py --date 2026-09-30 --cancel  # delete a recorded draft or scheduled broadcast

Sending rules:
- Sent, never left as a draft (owner directive, 2026-09-30). A Pacific hour like '10am' schedules
  today's issue (and, for --weekly, only on a Friday). If that time has passed or is under 10 minutes
  away, the issue SENDS AS SOON AS POSSIBLE: scheduled 15 minutes out, after the live check.
  Only a past date's issue (not today's) stays a DRAFT.
- Never a broken email. With a send time (and no --dry-run), the script first checks that HEAD is
  pushed to origin/main and that the report and card return 200 on the live site, retrying for up
  to 10 minutes. If they don't, it creates nothing and exits 2. --skip-live-check overrides this.
- Alarm alerts wait for a person. The daily and weekly issues still send on a day the fire-alarm level
  changes; the separate breaking alert (--alarm) is ALWAYS a draft for the owner to approve.
- Never twice. data/kit_broadcasts.json records each push. A "pending" entry is written before
  the POST; if the outcome is unclear (a timeout, a dropped connection, a 5xx, a reply with no id),
  the entry stays "unknown" and the script exits 2. The next run looks the broadcast up in Kit and
  adopts it instead of creating another. --force refuses while the recorded broadcast is still
  scheduled: --cancel it first, or use --update.

Exit codes: 0 done (including "already pushed", a draft, or a hold); 1 an error for a person to look
at (the message says whether anything was created); 2 the site isn't live yet, or Kit's answer was
unclear: rerun once without --force. A run that gets as far as deciding what to do with Kit ends with
a "KIT_STATUS: ..." line for the routine to read (SCHEDULED, DRAFT, HELD AS DRAFT, EXISTS, UNKNOWN, ...).

Credentials come from the environment: KIT_API_KEY (v4 key, sent as X-Kit-Api-Key) or, failing
that, the v3 KIT_API_SECRET. Keys are never printed, logged or written to disk, and messages never
include a request URL (a v3 GET carries the secret in its query string). Kit's v3 API has no
preview_text field, so on v3 the preview travels as a hidden preheader at the top of the body.
"""
import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_feed import (FONT, INK, MUTED, alarm_level_on, email_footer, fmt, issue_html, link,  # noqa: E402
                        p as para, pretty_date, prev_published, source_link, ul)
from sitekit import SITE, SUBSCRIBE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data/kit_broadcasts.json"
PACIFIC = ZoneInfo("America/Los_Angeles")
V4, V3 = "https://api.kit.com/v4/", "https://api.convertkit.com/v3/"
MIN_LEAD = timedelta(minutes=10)      # Kit needs at least this much lead for a scheduled send
SEND_SOON = timedelta(minutes=15)     # owner directive: a late issue is SENT this far out, never left as a draft
RECONCILE_SLACK = timedelta(minutes=5)  # clock skew allowed when matching an earlier attempt in Kit
LIVE_WAIT_S, LIVE_EVERY_S = 600, 20   # how long to wait for GitHub Pages, and how often to look
CLIP_WARN = 70_000  # bytes; Kit's template and tracking links add ~15-25 KB, and Gmail clips at ~102 KB
SUBJECT_WARN = 60   # characters; phones show roughly the first 40-60
# Whether Kit also publishes each issue as a web post on the Creator Profile. The owner decides
# (see the Kit settings review); False would leave the site as the only public archive.
PUBLIC = True
NO_CREDS = -1


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def status_line(text):
    print(f"KIT_STATUS: {text}")


def parse_ts(s):
    """A Kit or ISO timestamp ('2026-09-29T22:51:16.000Z') as an aware UTC datetime; None if absent or unreadable."""
    if not s:
        return None
    v = re.sub(r"[Zz]$", "+00:00", str(s).strip())
    v = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], v)  # 3.9 wants 3 or 6 fraction digits
    try:
        t = datetime.fromisoformat(v)
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def check_date(d, what="date"):
    try:
        datetime.strptime(d, "%Y-%m-%d")
    except (TypeError, ValueError):
        sys.exit(f"{what} {d!r} is not a YYYY-MM-DD date.")
    return d


# ---- Kit API ----

def request(method, url, headers=None, body=None):
    """(status, body dict). A 2xx whose body isn't JSON gives (status, {}): Kit accepted it. A network
    failure gives (None, {"_net": "<exception type>"}): the outcome is unknown. Never raises for either."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Accept": "application/json", "Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:  # first: HTTPError is also a URLError and an OSError
        try:
            parsed = json.loads(e.read() or b"{}")
        except (ValueError, OSError, http.client.HTTPException):
            parsed = {}
        return e.code, parsed if isinstance(parsed, dict) else {"_data": parsed}
    except (OSError, http.client.HTTPException) as e:  # timeouts, resets, DNS, TLS, IncompleteRead
        return None, {"_net": type(e).__name__}
    try:
        parsed = json.loads(raw or b"{}")
    except ValueError:
        return status, {}
    return status, parsed if isinstance(parsed, dict) else {"_data": parsed}


def kit_call(api, method, path, body=None, query=None):
    """One call to Kit's v4 or v3 API; path like 'broadcasts/123'. (NO_CREDS, {}) if that API has no key."""
    if api == "v4":
        key = os.environ.get("KIT_API_KEY")
        if not key:
            return NO_CREDS, {}
        return request(method, V4 + path + ("?" + urlencode(query) if query else ""), {"X-Kit-Api-Key": key}, body)
    secret = os.environ.get("KIT_API_SECRET")
    if not secret:
        return NO_CREDS, {}
    if method in ("GET", "DELETE"):
        return request(method, V3 + path + "?" + urlencode({**(query or {}), "api_secret": secret}))
    return request(method, V3 + path, None, {"api_secret": secret, **(body or {})})


def errtext(body):
    e = body.get("errors") or body.get("error") or body.get("message") or body
    return str(e)[:300]


def preheader(text):
    """Hidden inbox-preview line. Kit's v3 API has no preview_text field, so on v3 it has to live in the body.
    The padding stops the email's first visible words from running on into the preview."""
    if not text:
        return ""
    return ('<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;opacity:0">'
            + escape(text) + "&#847;&zwnj;&nbsp;" * 60 + "</div>")


def api_fields(api, fields):
    """The body for one API: v4 keeps preview_text; v3 drops it and carries it as a hidden preheader instead."""
    if api == "v4":
        return {**fields, "published_at": fields.get("send_at") or _iso(_now())}
    v3 = {k: v for k, v in fields.items() if k != "preview_text"}
    v3["content"] = preheader(fields.get("preview_text")) + fields["content"]
    return v3


def preview_mode():
    """How the preview text will travel, judged from which credentials are set (a dry run calls nothing)."""
    key, secret = os.environ.get("KIT_API_KEY"), os.environ.get("KIT_API_SECRET")
    if key and secret:
        return "v4 preview_text field if KIT_API_KEY is a working v4 key; otherwise a hidden preheader on the v3 fallback"
    if key:
        return "v4 preview_text field"
    if secret:
        return "v3 hidden preheader (v3 has no preview_text field)"
    return "no Kit credentials here: a v4 preview_text field or a v3 hidden preheader, depending on the key"


def _outcome(api, status, body):
    """Classify one create attempt as ('created', api, broadcast), ('ambiguous', api, why) or ('failed', api, why)."""
    if status is None:
        return "ambiguous", api, f"network error ({body.get('_net', 'unknown')})"
    if 200 <= status < 300:
        bc = body.get("broadcast") if isinstance(body.get("broadcast"), dict) else body
        if bc.get("id"):
            return "created", api, bc
        return "ambiguous", api, f"Kit {api} answered {status} without a broadcast id"
    if status >= 500:  # a proxy or backend error can come after the broadcast was stored
        return "ambiguous", api, f"Kit {api} server error {status}"
    return "failed", api, f"Kit {api} API error {status}: {errtext(body)}"


def create_broadcast(fields):
    """POST the broadcast: v4 with KIT_API_KEY, then v3 with KIT_API_SECRET. Returns (outcome, api, result):
    'created' with Kit's broadcast dict, or 'ambiguous'/'failed' with a message. An unclear v4 result never
    falls through to v3, since that could create a second broadcast. A v4 401/403 falls back quietly; other
    v4 4xx errors are reported and fall back when a v3 secret is set."""
    key, secret = os.environ.get("KIT_API_KEY"), os.environ.get("KIT_API_SECRET")
    if not key and not secret:
        return "failed", None, "No usable Kit credentials: set KIT_API_KEY (v4) or KIT_API_SECRET (v3)."
    if key:
        status, body = kit_call("v4", "POST", "broadcasts", api_fields("v4", fields))
        result = _outcome("v4", status, body)
        if result[0] != "failed" or not secret:
            return result
        if status not in (401, 403):
            print(f"{result[2]}; trying v3.", file=sys.stderr)
    status, body = kit_call("v3", "POST", "broadcasts", api_fields("v3", fields))
    return _outcome("v3", status, body)


def list_recent(api_hint=None):
    """(api, [broadcast, ...]) newest first, or (None, None) if no API answered."""
    order = [api_hint] if api_hint in ("v4", "v3") else []
    order += [a for a in ("v4", "v3") if a not in order]
    for api in order:
        query = {"per_page": 50} if api == "v4" else {"sort_order": "desc"}
        status, body = kit_call(api, "GET", "broadcasts", query=query)
        if status is not None and status != NO_CREDS and 200 <= status < 300 and isinstance(body.get("broadcasts"), list):
            return api, body["broadcasts"]
    return None, None


def get_broadcast(api, bid):
    """Kit's full record for one broadcast; None if Kit says it doesn't exist; "error" if Kit can't be asked."""
    status, body = kit_call(api, "GET", f"broadcasts/{bid}")
    if status == 404:
        return None
    if status is None or status == NO_CREDS or not 200 <= status < 300:
        return "error"
    return body.get("broadcast") if isinstance(body.get("broadcast"), dict) else body


# ---- state (data/kit_broadcasts.json) ----

def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(state):
    tmp = STATE.with_name(STATE.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=1) + "\n")
    os.replace(tmp, STATE)


def describe(entry):
    """One line about a recorded push, for messages and the dry run."""
    if not entry:
        return "not pushed yet"
    st = entry.get("status") or ("created" if entry.get("id") else "?")
    if st in ("pending", "unknown"):
        return (f"an earlier attempt (started {entry.get('started', '?')}) ended with an unknown outcome; "
                "a real run looks it up in Kit before creating anything")
    if st == "cancelled":
        return f"broadcast {entry.get('id')} was cancelled; --force creates a new one"
    when = entry.get("send_at")
    return f"already pushed as broadcast {entry.get('id')} ({entry.get('api', '?')}, {'send time ' + when if when else 'draft'})"


def reconcile(key, prior, state, meta):
    """Look for a broadcast that an earlier, unclear attempt may have created. True if found and adopted.
    Exits 2 if Kit can't be asked, since creating blind could email everyone twice."""
    cant = "Could not confirm whether Kit already has this broadcast; check Kit > Broadcasts before retrying."
    api, items = list_recent(prior.get("api"))
    if items is None:
        print(cant, file=sys.stderr)
        status_line("UNKNOWN (Kit unreachable while checking an earlier attempt)")
        sys.exit(2)
    started = parse_ts(prior.get("started"))
    since = started - RECONCILE_SLACK if started else None
    for b in items:
        made = parse_ts(b.get("created_at"))
        if b.get("subject") != prior.get("subject") or (since and (made is None or made < since)):
            continue
        full = get_broadcast(api, b.get("id"))
        if full == "error":
            print(cant, file=sys.stderr)
            status_line("UNKNOWN (Kit unreachable while checking an earlier attempt)")
            sys.exit(2)
        if not full or (prior.get("description") and full.get("description")
                        and full["description"] != prior["description"]):
            continue
        state[key] = {"id": full.get("id") or b.get("id"), "api": api, "send_at": full.get("send_at"),
                      "report": meta["report"], "status": "created", "recovered": _iso(_now())}
        save_state(state)
        print(f"Recovered broadcast {state[key]['id']} created by an earlier run; not creating another. "
              f"Send time in Kit: {full.get('send_at') or 'none (draft)'}.")
        return True
    return False


# ---- send time, live check, alarm hold ----

def parse_send_at(value, run_date):
    """(aware datetime, True if it was a Pacific clock time like '10am'). Exits on input that isn't a time."""
    v = value.strip()
    m = re.fullmatch(r"(\d{1,2})(?::([0-5]\d))?\s*([ap]m)", v.lower())
    if m:
        hour = int(m.group(1))
        if not 1 <= hour <= 12:
            sys.exit(f"--send-at {value!r}: the hour must be 1-12 with am or pm.")
        return datetime.strptime(check_date(run_date), "%Y-%m-%d").replace(
            hour=hour % 12 + (12 if m.group(3) == "pm" else 0), minute=int(m.group(2) or 0), tzinfo=PACIFIC), True
    try:
        when = datetime.fromisoformat(re.sub(r"[Zz]$", "+00:00", v))  # 3.9's fromisoformat has no 'Z'
    except ValueError:
        sys.exit(f"--send-at {value!r} is not a time: use '10am', '10:30am', '3 pm' "
                 "or ISO 8601 with a timezone, e.g. 2026-09-30T17:00:00Z.")
    if when.tzinfo is None:
        sys.exit(f"--send-at {value!r} has no timezone: add Z or an offset such as -07:00.")
    return when, False


def resolve_send_at(value, run_date, friday_only=False):
    """--send-at -> a UTC ISO time, or None to keep a draft. Accepts a Pacific time on the run date
    ('10am', '10:30am', '3 pm'; hour 1-12) or ISO 8601 with a timezone. The Pacific form only schedules
    today's issue, and with friday_only only on a Friday. Any time under 10 minutes away stays a draft.
    Prints the Pacific and UTC times; exits on anything that isn't a time."""
    if not value:
        return None
    when, clock = parse_send_at(value, run_date)
    local, utc = when.astimezone(PACIFIC), when.astimezone(timezone.utc)
    shown = f"{local:%Y-%m-%d %H:%M %Z} ({utc:%Y-%m-%dT%H:%M:%SZ})"
    today = _now().astimezone(PACIFIC).date().isoformat()
    if clock and run_date != today:
        print(f"{shown}: {run_date} is not today's issue (today is {today} Pacific), so it stays a DRAFT. "
              "Send it by hand in Kit if it should still go out.")
        return None
    if clock and friday_only and local.weekday() != 4:
        print(f"{shown}: {run_date} is not a Friday, so the wrap-up stays a DRAFT. Send it by hand in Kit if it should still go out.")
        return None
    if not clock and local.date().isoformat() != run_date:
        print(f"warning: --send-at is on {local:%Y-%m-%d} Pacific, not the issue date {run_date}.", file=sys.stderr)
    if utc - _now() < MIN_LEAD:
        soon = (_now() + SEND_SOON).astimezone(timezone.utc)
        print(f"{shown} has passed or is under 10 minutes away, so it SENDS AS SOON AS POSSIBLE: "
              f"{soon.astimezone(PACIFIC):%H:%M %Z} ({_iso(soon)}).")
        return _iso(soon)
    print(f"Send time: {shown}.")
    return _iso(utc)


def draft_reason(value, send_at):
    """Why an issue is a draft, for the KIT_STATUS line ('' when it is scheduled)."""
    return "" if send_at else "no --send-at" if not value else "send time not usable, see above"


def git_published(files):
    """None when HEAD is on origin/main and `files` are committed with no local changes; else the reason."""
    def git(*a):
        return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, timeout=120)
    try:
        if git("fetch", "-q", "origin", "main").returncode:
            return "git fetch origin main failed, so the push can't be confirmed"
        if git("merge-base", "--is-ancestor", "HEAD", "origin/main").returncode:
            return "this checkout has commits that are not on origin/main (the push failed or hasn't run)"
        for f in files:
            if git("ls-files", "--error-unmatch", "--", f).returncode:
                return f"{f} is not committed"
        dirty = [f for f in files if git("diff", "--quiet", "HEAD", "--", f).returncode]
        if dirty:
            return f"uncommitted changes in {', '.join(dirty)}, so the email wouldn't match the live site"
    except (OSError, subprocess.SubprocessError) as e:
        return f"git failed ({type(e).__name__})"
    return None


def url_ok(u):
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(u, method=method, headers={"User-Agent": "hidden-agi-watch-live-check"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return 200 <= r.status < 300
        except urllib.error.HTTPError as e:
            if e.code == 405 and method == "HEAD":
                continue
            return False
        except (OSError, http.client.HTTPException):
            return False
    return False


def site_live(urls, wait_s=None, every_s=None):
    """URLs still failing after retrying for up to wait_s seconds ([] when all return 2xx)."""
    wait_s = LIVE_WAIT_S if wait_s is None else wait_s
    every_s = LIVE_EVERY_S if every_s is None else every_s
    deadline = time.monotonic() + wait_s
    while True:
        bad = [u for u in urls if not url_ok(u)]
        left = deadline - time.monotonic()
        if not bad or left <= 0:
            return bad
        print(f"Waiting for GitHub Pages: {len(bad)} URL(s) not live yet; checking again in {every_s}s.")
        time.sleep(min(every_s, left))


def ensure_live(meta, args, what="No Kit broadcast created"):
    """Exit 2 unless the push is on origin/main and every page the email links to is live."""
    if args.skip_live_check or not meta.get("live"):
        return
    why = git_published(meta.get("files", []))
    bad = [why] if why else site_live(meta["live"])
    if bad:
        print(f"SITE NOT LIVE: {'; '.join(bad)}. {what}. Fix the push or Pages build and rerun.", file=sys.stderr)
        status_line("NOT CREATED (site not live)")
        sys.exit(2)
    print("Live check passed: " + ", ".join(meta["live"]))


def still_ahead(send_at):
    """After waiting on the live check, keep the send time only if it's still at least 10 minutes away."""
    t = parse_ts(send_at)
    if t and t - _now() < MIN_LEAD:
        soon = _iso((_now() + SEND_SOON).astimezone(timezone.utc))
        print(f"{send_at} is now under 10 minutes away, so it sends as soon as possible instead: {soon}.")
        return soon
    return send_at


def alarm_change(date, run=None, prev=None):
    """The fire-alarm change to hold an issue for: an alarm-history entry dated `date` that moves the level
    (the initial reading, with from=None, doesn't count), or a published run whose level differs from the
    previous published reading's. {'from': L, 'to': L} or None."""
    ap = ROOT / "data/alarm.json"
    hist = json.loads(ap.read_text()).get("history", []) if ap.exists() else []
    for e in reversed(hist):
        if e.get("date") == date and e.get("from") is not None and e.get("to") != e.get("from"):
            return {"from": e["from"], "to": e["to"]}
    if run is not None and prev is not None:
        cur, old = alarm_level_on(date, run), alarm_level_on(prev["date"], prev)
        if cur and old and cur.get("level") != old.get("level"):
            return {"from": old.get("level"), "to": cur.get("level")}
    return None


def check_size(html):
    n = len(html.encode("utf-8"))
    if n > CLIP_WARN:
        print(f"warning: the email body is {n:,} bytes; with Kit's template and tracking links Gmail may clip it "
              "(~102 KB). Trim the roundup.", file=sys.stderr)
    return n


def check_subject(subject):
    if len(subject) > SUBJECT_WARN:
        print(f"warning: the subject is {len(subject)} characters; phones show roughly the first 40-60.", file=sys.stderr)


def preview(text, limit=140):
    """At most `limit` characters: whole sentences when they fill at least half of it, else cut at a word with '…'."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    ends = [m.end() for m in re.finditer(r"[.!?][\"'”’)]?(?=\s|$)", text) if m.end() <= limit]
    if ends and ends[-1] >= limit // 2:
        return text[:ends[-1]]
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def print_dry_run(key, fields, meta, extra=()):
    state = load_state()
    print(f"State: {describe(state.get(key))}")
    print(f"Subject ({len(fields['subject'])} chars): {fields['subject']}")
    print(f"Preview ({len(fields.get('preview_text') or '')} chars, sent as {preview_mode()}): {fields.get('preview_text') or '(none)'}")
    print(f"Body: {check_size(fields['content']):,} bytes of HTML (UTF-8)")
    for line in extra:
        print(line)
    if fields.get("send_at") and meta.get("live"):
        print("Live check: a real run first confirms the push and waits for " + ", ".join(meta["live"]))
    print(f"Mode: {'scheduled ' + fields['send_at'] if fields.get('send_at') else 'draft'} (dry run: nothing was sent to Kit)")


# ---- create / update / cancel ----

def _settle_prior(key, state, meta, args):
    """Deal with an earlier record for `key` before creating anything. Returns (prior, stop); stop means done."""
    prior = state.get(key)
    if prior and prior.get("status") in ("pending", "unknown"):
        if reconcile(key, prior, state, meta):
            status_line(f"EXISTS (recovered broadcast {state[key]['id']})")
            return None, True
        previous = prior.get("previous")  # the ambiguous attempt was a --force run
        if previous:
            state[key] = previous
            save_state(state)
            print(f"The earlier --force attempt did not create a broadcast; the recorded broadcast {previous.get('id')} stands. "
                  "Rerun with --force only if you still want a new one.")
            status_line(f"EXISTS (broadcast {previous.get('id')})")
            return previous, True
        state.pop(key)
        save_state(state)
        print("Kit has no broadcast from the earlier attempt, so creating it now.")
        return None, False
    if prior and prior.get("id") and not args.force:
        print(f"{key}: {describe(prior)}. Use --update to change it or --cancel to delete it.")
        status_line(f"EXISTS (broadcast {prior.get('id')})")
        return prior, True
    if args.force and prior and prior.get("id") and prior.get("status") != "cancelled":
        when = parse_ts(prior.get("send_at"))
        if when and when > _now():
            sys.exit(f"Broadcast {prior['id']} for {key} is still scheduled for {prior['send_at']}. Creating another "
                     "would email subscribers twice: run --cancel first, or use --update to change it.")
        print(f"note: --force creates a second broadcast; the earlier one ({prior['id']}, "
              f"{'sent at ' + prior['send_at'] if when else 'a draft'}) stays in Kit.")
    return prior, False


def _report_created(api, bc, fields, why):
    """Say what Kit made. Exits 1 if a send time was asked for and Kit didn't confirm one."""
    if fields["send_at"] and not bc.get("send_at"):
        print(f"Created Kit broadcast {bc['id']} via {api}, but Kit did not confirm the send time "
              f"({fields['send_at']}). It may be a draft: check Kit > Broadcasts. Do not rerun with --force.", file=sys.stderr)
        status_line(f"DRAFT? (send time not confirmed) broadcast {bc['id']}")
        sys.exit(1)
    if bc.get("send_at"):
        print(f"Created Kit broadcast {bc['id']} via {api}, scheduled for {bc['send_at']}.")
        status_line(f"SCHEDULED {bc['send_at']} broadcast {bc['id']}")
    else:
        print(f"Created Kit broadcast {bc['id']} via {api} as a DRAFT.")
        status_line(f"{'HELD AS DRAFT' if why == HELD else 'DRAFT'} ({why or 'no send time'}) broadcast {bc['id']}")


def push(key, fields, meta, args, why=""):
    """Create the broadcast for `key` once: settle any earlier record, check the site is live before
    scheduling, write a pending marker, POST, then record the outcome. See the module docstring."""
    state = load_state()
    prior, stop = _settle_prior(key, state, meta, args)
    if stop:
        return
    if fields["send_at"]:
        ensure_live(meta, args)
        fields["send_at"] = still_ahead(fields["send_at"])
        why = why if fields["send_at"] else "send time passed during the live check"
    earlier = prior if prior and prior.get("id") else None
    state[key] = {"status": "pending", "subject": fields["subject"], "description": fields["description"],
                  "started": _iso(_now()), **({"previous": earlier} if earlier else {})}
    save_state(state)
    outcome, api, result = create_broadcast(fields)
    if outcome == "failed":  # Kit said no: nothing exists, so clear the marker (or restore the earlier record)
        if earlier:
            state[key] = earlier
        else:
            state.pop(key, None)
        save_state(state)
        print(result, file=sys.stderr)
        status_line("FAILED (nothing was created in Kit)")
        sys.exit(1)
    if outcome == "ambiguous":
        state[key].update(status="unknown", api=api)
        save_state(state)
        print(f"{result}. Kit may already have created this broadcast. Rerun (the script will look it up); "
              "do NOT use --force.", file=sys.stderr)
        status_line("UNKNOWN (rerun without --force)")
        sys.exit(2)
    state[key] = {"id": result["id"], "api": api, "send_at": result.get("send_at"), "report": meta["report"],
                  "status": "created", **({"previous_id": earlier["id"]} if earlier else {})}
    save_state(state)
    _report_created(api, result, fields, why)


def update(key, fields, meta, args):
    """PUT new subject, content and send time onto the recorded broadcast (Kit refuses once it is sending or sent)."""
    state = load_state()
    prior = state.get(key)
    if not prior or not prior.get("id"):
        sys.exit(f"Nothing recorded for {key} ({describe(prior)}); run without --update to create it.")
    if prior.get("status") == "cancelled":
        sys.exit(f"Broadcast {prior['id']} for {key} was cancelled; run with --force to create a new one.")
    if fields["send_at"]:
        ensure_live(meta, args, "No Kit change made")
        fields["send_at"] = still_ahead(fields["send_at"])
    api = prior.get("api") or "v3"
    status, body = kit_call(api, "PUT", f"broadcasts/{prior['id']}", api_fields(api, fields))
    if status == NO_CREDS:
        sys.exit(f"Broadcast {prior['id']} was made with the {api} API, and its credentials aren't set.")
    if status is None:
        print(f"Network error ({body.get('_net')}): Kit may or may not have applied the update. Rerun --update "
              "(repeating it is safe) or check Kit > Broadcasts.", file=sys.stderr)
        status_line("UNKNOWN (rerun --update)")
        sys.exit(2)
    if not 200 <= status < 300:
        print(f"Kit {api} refused the update ({status}): {errtext(body)}. Broadcasts that are sending or "
              "sent can't be changed.", file=sys.stderr)
        status_line("FAILED (update refused)")
        sys.exit(1)
    bc = body.get("broadcast") if isinstance(body.get("broadcast"), dict) else body
    prior.update({"send_at": bc.get("send_at", fields["send_at"]), "status": "created", "updated": _iso(_now())})
    state[key] = prior
    save_state(state)
    when = prior["send_at"]
    print(f"Updated Kit broadcast {prior['id']} via {api} ({'scheduled for ' + when if when else 'draft'}).")
    status_line(f"{'SCHEDULED ' + when if when else 'DRAFT'} broadcast {prior['id']} (updated)")


def cancel(key, args):
    """DELETE the recorded draft or scheduled broadcast and mark it cancelled."""
    state = load_state()
    prior = state.get(key)
    if prior and prior.get("status") in ("pending", "unknown"):
        sys.exit(f"The last attempt for {key} has an unknown outcome; rerun without --cancel first so the script "
                 "can look it up in Kit.")
    if not prior or not prior.get("id"):
        sys.exit(f"No broadcast recorded for {key}; nothing to cancel.")
    if prior.get("status") == "cancelled":
        print(f"Broadcast {prior['id']} for {key} is already cancelled.")
        status_line(f"CANCELLED broadcast {prior['id']}")
        return
    if args.dry_run:
        print(f"Dry run: would delete broadcast {prior['id']} ({describe(prior)}).")
        return
    api = prior.get("api") or "v3"
    status, body = kit_call(api, "DELETE", f"broadcasts/{prior['id']}")
    if status == NO_CREDS:
        sys.exit(f"Broadcast {prior['id']} was made with the {api} API, and its credentials aren't set.")
    if status is None:
        print(f"Network error ({body.get('_net')}): Kit may or may not have deleted broadcast {prior['id']}. "
              "Rerun --cancel (repeating it is safe) or check Kit > Broadcasts.", file=sys.stderr)
        status_line("UNKNOWN (rerun --cancel)")
        sys.exit(2)
    if status == 404:
        print(f"Kit has no broadcast {prior['id']} (already deleted?); marking it cancelled.")
    elif not 200 <= status < 300:
        print(f"Kit {api} refused to delete broadcast {prior['id']} ({status}): {errtext(body)}. Broadcasts that are "
              "sending or sent can't be deleted.", file=sys.stderr)
        status_line("FAILED (delete refused)")
        sys.exit(1)
    prior.update({"status": "cancelled", "cancelled": _iso(_now())})
    state[key] = prior
    save_state(state)
    print(f"Cancelled Kit broadcast {prior['id']} for {key}. Run with --force to create a new one.")
    status_line(f"CANCELLED broadcast {prior['id']}")


def dispatch(key, fields, meta, args, why="", extra=()):
    check_subject(fields["subject"])
    if args.dry_run:
        print_dry_run(key, fields, meta, extra)
        return
    check_size(fields["content"])
    if args.update:
        return update(key, fields, meta, args)
    return push(key, fields, meta, args, why)


HELD = "alarm level changed"


def hold_line(change, when, what):
    return (f"ALARM LEVEL CHANGED {when} (L{change['from']}→L{change['to']}): the {what} still sends; "
            "the breaking alarm alert is created separately as a DRAFT for owner review")


# ---- the three kinds of email ----

def _trigger_items(ids, trig, evidence=True):
    """List items for trigger IDs, each linked to its row on alarm.html, with the evidence and its source if asked."""
    out = []
    for t in ids:
        x = trig.get(t)
        if not x:
            out.append(f"<strong>{escape(str(t))}</strong>")
            continue
        s = f'<strong>{link(SITE + "alarm.html#" + t, t)}</strong> · {escape(x.get("trigger", ""))}.'
        if x.get("threshold"):
            s += f' Threshold: {escape(x["threshold"])}.'
        if evidence and x.get("evidence"):
            s += " " + escape(x["evidence"]) + source_link(x)
        out.append(s)
    return out


def _and_list(ids):
    ids = [str(i) for i in ids]
    return ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " and " + ids[-1]


def alarm_skip(e):
    """Why the history entry `e` gets no alert ('' when it should get one): not a change, or stale."""
    age = (_now().astimezone(PACIFIC).date() - datetime.strptime(check_date(e["date"]), "%Y-%m-%d").date()).days
    if e.get("from") is None:
        return "the initial reading is not a level change"
    if e["from"] == e["to"]:
        return f"the level did not change (Level {e['to']})"
    return f"it is dated {e['date']}, more than a day ago" if age > 1 else ""


def alarm_cause(e):
    """'initial', 'trigger' (raised), 'decay' or 'retraction'. The direction of the move decides raise vs lower;
    a lowering is a decay unless the entry says 'retraction'."""
    frm, to, cause = e.get("from"), e["to"], e.get("cause")
    want = ("initial" if frm is None else "trigger" if to > frm
            else cause if cause in ("decay", "retraction") else "decay")
    if cause and cause != want:
        print(f"warning: history cause {cause!r} doesn't fit a move from {frm} to {to}; writing it as {want!r}.", file=sys.stderr)
    return want


def alarm_copy(a, e, cause):
    """Kicker, subject, heading, trigger lists and the rule-based reason for one alert, matching the published rules."""
    lv = next(l for l in a["levels"] if l["level"] == e["to"])
    trig = {t["id"]: t for g in a["groups"] for t in g["triggers"]}
    triggers, cleared, frm = list(e.get("triggers") or []), list(e.get("cleared") or []), e.get("from")
    name, level = f'Level {e["to"]} ({lv["name"]})', f'Level {e["to"]}: {escape(lv["name"])}'
    if cause == "initial":
        return {"kicker": "Fire alarm · first reading", "subject": f'{lv["icon"]} Fire alarm starts at {name}', "head": level,
                "lists": [("Triggers met:", _trigger_items(triggers, trig))],
                "reason": f'This is the first reading under the criteria published on {pretty_date(a.get("published") or e["date"])}.'}
    if cause == "trigger":
        return {"kicker": "Breaking · fire alarm raised", "subject": f'{lv["icon"]} Fire alarm raised to {name}', "head": "Raised to " + level,
                "lists": [("Triggers met:", _trigger_items(triggers, trig))],
                "reason": ("The level rose because the trigger above met a published threshold." if len(triggers) == 1
                           else "The level rose because the triggers above met published thresholds." if triggers
                           else "The level rose because a trigger met a published threshold; the note above gives the evidence.")}
    still = ("Still met:", _trigger_items(triggers, trig))
    if cause == "decay":
        rule = next((g.get("rule", "") for g in a["groups"] if g.get("level") == frm), "")
        lapsed = f"fewer than two Level-{frm} triggers have" if rule.startswith("any two") else f"no Level-{frm} trigger has"
        return {"kicker": "Fire alarm lowered", "subject": f'{lv["icon"]} Fire alarm lowered to {name}', "head": "Lowered to " + level,
                "lists": [("No longer met:", _trigger_items(cleared, trig, evidence=False)), still],
                "reason": f"The level fell because {lapsed} been met for 30 days, as the published rules require."}
    behind = _and_list(cleared) if cleared else "a trigger"
    return {"kicker": "Correction · fire alarm", "subject": f"Correction: fire alarm lowered to {name}", "head": "Corrected to " + level,
            "lists": [("Retracted:", _trigger_items(cleared, trig, evidence=False)), still],
            "reason": f"The level fell at once because the evidence behind {behind} was retracted. The alarm history records the error."}


def alarm_email(a, e, copy):
    """The alert body: dateline, heading, the move, what the level means, the note, trigger lists (never an
    empty heading), the reason under the published rules, the review date, and the alarm footer."""
    levels = {lv["level"]: lv for lv in a["levels"]}
    lv, frm = levels[e["to"]], e.get("from")
    body = [para(f'<span style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:600">'
                 f'{copy["kicker"]} · {datetime.strptime(e["date"], "%Y-%m-%d").strftime("%a")} {pretty_date(e["date"])}</span>',
                 "margin-bottom:6px"),
            f'<h1 style="{FONT}font-size:26px;color:{INK};margin:6px 0"><span aria-hidden="true">{lv["icon"]}</span> {copy["head"]}</h1>']
    if frm is not None:
        body.append(para(f'The fire-alarm level moved from Level {frm} ({escape(levels[frm]["name"] if frm in levels else "?")}) '
                         f'to Level {e["to"]} ({escape(lv["name"])}) on {pretty_date(e["date"])}.'))
    body.append(para(f'<strong>What Level {e["to"]} means:</strong> {escape(lv["meaning"])}'))
    if e.get("note"):
        body.append(para(escape(e["note"])))
    for label, items in copy["lists"]:
        if items:
            body += [para(f"<strong>{label}</strong>"), ul(items)]
    body.append(para(f'These criteria were published in advance. {copy["reason"]} '
                     f'See the {link(SITE + "alarm.html#rules", "published rules")}.'))
    if e.get("reviewDue"):
        body.append(para(f'This change will be reviewed publicly on {pretty_date(e["reviewDue"])}, false alarms included.'))
    body += [para(f'Forwarded this? {link(SUBSCRIBE, "Subscribe to Hidden AGI watch")}. It\'s free.'), email_footer("alarm")]
    return "".join(body)


def push_alarm(args):
    """Alert for the latest fire-alarm level change. ALWAYS a draft: the owner reviews and sends every one."""
    a = json.loads((ROOT / "data/alarm.json").read_text())
    if not a.get("history"):
        sys.exit("data/alarm.json has no history entries.")
    e = a["history"][-1]
    key = f"alarm-{e['date']}-{e['to']}"
    if args.cancel:
        return cancel(key, args)
    if args.send_at:
        print("note: alarm alerts are always drafts; --send-at is ignored.")
    skip = "" if args.force else alarm_skip(e)
    if skip:
        print(f"No alarm alert for the latest history entry ({e['date']}): {skip}. Nothing to draft (--force overrides).")
        status_line("SKIPPED (no new level change)")
        return
    cause = alarm_cause(e)
    copy = alarm_copy(a, e, cause)
    meaning = next(l["meaning"] for l in a["levels"] if l["level"] == e["to"])
    fields = {"subject": copy["subject"], "preview_text": preview(e.get("note") or meaning),
              "description": f"Alarm change {e['date']}", "content": alarm_email(a, e, copy), "public": PUBLIC, "send_at": None}
    meta = {"report": SITE + "alarm.html"}  # always a draft, so no live check
    frm = "none" if e.get("from") is None else e["from"]
    dispatch(key, fields, meta, args, "alarm alerts are always drafts",
             extra=[f"Cause: {cause} (Level {frm} → {e['to']})", "Alarm alerts are always drafts: the owner reviews and sends them."])


def weekly_alarm_change(date):
    """A level change dated on the wrap-up day or the day before (earlier ones went out with a held daily issue)."""
    runs = json.loads((ROOT / "data/runs.json").read_text())
    day_before = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    for d in (day_before, date):
        idx = [i for i, r in enumerate(runs) if r.get("date") == d and r.get("report")]
        change = alarm_change(d, runs[idx[-1]], prev_published(runs, idx[-1])) if idx else alarm_change(d)
        if change:
            return change
    return None


def push_weekly(args):
    from build_weekly import day_mon, weekly_email_html
    date = check_date(args.weekly, "--weekly")
    src = ROOT / f"data/weekly/{date}.json"
    if not src.exists():
        sys.exit(f"No data/weekly/{date}.json: write the wrap-up and run scripts/build_weekly.py {date} first.")
    w = json.loads(src.read_text())
    if "keyNumbers" not in w:
        sys.exit(f"Run scripts/build_weekly.py {date} first.")
    key = f"weekly-{date}"
    if args.cancel:
        return cancel(key, args)
    send_at = resolve_send_at(args.send_at, date, friday_only=True)
    why = draft_reason(args.send_at, send_at)
    change = weekly_alarm_change(date)
    hold = hold_line(change, "THIS WEEK", "weekly wrap-up") if change else ""
    if hold:  # owner directive 2026-09-30: the issue still SENDS; only the breaking alarm alert is a draft
        print(hold)
    k = w["keyNumbers"]
    hook = (str(w.get("subject") or "").strip().rstrip(" .")
            or preview(str(w.get("headline") or "").strip(), 50).rstrip(" .") or "Weekly wrap-up")
    fields = {
        "subject": f"Week to {day_mon(date)} · " + (f"Index {fmt(k['index'])}% · " if k.get("index") is not None else "") + hook,
        "preview_text": preview(w.get("summary") or ""),
        "description": f"Weekly wrap-up for {date}",
        "content": weekly_email_html(w),
        "public": PUBLIC,
        "send_at": send_at,
    }
    live = [f"{SITE}weekly/{date}.html"]
    files = [f"weekly/{date}.html", f"data/weekly/{date}.json"]
    if (ROOT / f"cards/weekly-{date}.png").exists():  # the email embeds the card only when it exists
        live.append(f"{SITE}cards/weekly-{date}.png")
        files.append(f"cards/weekly-{date}.png")
    meta = {"report": f"{SITE}weekly/{date}.html", "live": live, "files": files}
    dispatch(key, fields, meta, args, why, extra=[f"Alarm: {hold or 'no level change on the wrap-up day or the day before'}"])


def daily_subject(run):
    """'Index 4% · <needle subject>': plain words, no hypothesis letters, no trailing period."""
    n = run.get("needle") or {}
    sub = str(n.get("subject") or "").strip().rstrip(" .")
    if n.get("quiet"):
        hook = sub if sub.lower().startswith("quiet day") else "Quiet day: " + (sub or "nothing moved the odds")
    else:
        hook = sub or preview(str(n.get("headline") or "").strip(), 50).rstrip(" .") or "Today's reading"
    idx = run.get("index")
    return f"Index {fmt(idx)}% · {hook}" if idx is not None else f"Hidden AGI watch · {hook}"


def push_daily(args):
    runs = json.loads((ROOT / "data/runs.json").read_text())
    if args.date:
        check_date(args.date, "--date")
    idx = [i for i, r in enumerate(runs) if r.get("report") and (not args.date or r["date"] == args.date)]
    if not idx:
        sys.exit("No report found for that date.")
    i = idx[-1]
    run, prev = runs[i], prev_published(runs, i)
    date = check_date(run["date"])
    key = date
    if args.cancel:
        return cancel(key, args)
    prior = load_state().get(key)
    if prior and prior.get("id") and prior.get("status") != "cancelled" and not (args.force or args.update or args.dry_run):
        print(f"{key}: {describe(prior)}. Use --update to change it or --cancel to delete it.")
        status_line(f"EXISTS (broadcast {prior.get('id')})")
        return
    send_at = resolve_send_at(args.send_at, date)
    why = draft_reason(args.send_at, send_at)
    change = alarm_change(date, run, prev)
    hold = hold_line(change, "TODAY", "daily issue") if change else ""
    if hold:  # owner directive 2026-09-30: the issue still SENDS; only the breaking alarm alert is a draft
        print(hold)
    needle = run.get("needle") or {}
    fields = {
        "subject": daily_subject(run),
        "preview_text": preview(needle.get("detail") or run.get("summary") or ""),
        "description": f"Daily issue for {date}",
        "content": issue_html(run, prev),
        "public": PUBLIC,
        "send_at": send_at,  # None keeps it as a draft
    }
    live, files = [SITE + run["report"]], [run["report"], "data/runs.json"]
    if (ROOT / f"cards/{date}.png").exists():  # issue_html embeds the card only when it exists
        live.append(f"{SITE}cards/{date}.png")
        files.append(f"cards/{date}.png")
    meta = {"report": SITE + run["report"], "live": live, "files": files}
    dispatch(key, fields, meta, args, why,
             extra=[f"Compared with: {prev['date'] + ' reading' if prev else 'nothing (first reading)'}",
                    f"Alarm: {hold or 'no level change today'}"])


def main():
    ap = argparse.ArgumentParser(description="Push a daily issue, a Friday wrap-up or a fire-alarm alert to Kit.")
    ap.add_argument("--date", help="run date (YYYY-MM-DD); defaults to the latest report")
    ap.add_argument("--send-at", help="a Pacific time on the run date such as '10am', '10:30am' or '3 pm' (today's issue "
                                      "only; the wrap-up only on a Friday), or ISO 8601 with a timezone such as "
                                      "2026-09-30T17:00:00Z. It must be at least 10 minutes away, or the issue stays a "
                                      "draft. Omit for a draft.")
    ap.add_argument("--alarm", action="store_true", help="draft an alert for the latest alarm-level change (always a draft for the owner to approve)")
    ap.add_argument("--weekly", metavar="DATE", help="push the weekly wrap-up for DATE (built by build_weekly.py) instead of a daily issue")
    ap.add_argument("--dry-run", action="store_true", help="build and print what would be sent; call nothing")
    ap.add_argument("--skip-live-check", action="store_true", help="schedule without confirming that the push and the pages are live")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--force", action="store_true", help="create a new broadcast although one is recorded "
                      "(refused while the recorded one is still scheduled: --cancel it first)")
    mode.add_argument("--update", action="store_true", help="PUT the new subject, content and send time onto the recorded broadcast")
    mode.add_argument("--cancel", action="store_true", help="delete the recorded draft or scheduled broadcast")
    args = ap.parse_args()
    if args.alarm and args.weekly:
        ap.error("use --alarm or --weekly, not both")
    if args.alarm:
        return push_alarm(args)
    if args.weekly:
        return push_weekly(args)
    return push_daily(args)


if __name__ == "__main__":
    main()
