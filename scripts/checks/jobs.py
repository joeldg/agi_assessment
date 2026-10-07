"""The Jobs plugin's data in data/jobs/ (the plugin's spec, sections 4 and 8.4).

data/jobs/claims.json is a copy of the plugin's tracker; data/jobs/<FRIDAY>.json is the edition a wrap-up carried,
written by scripts/import_jobs.py. The plugin validates its own data; these rules are the newsletter's own check of
what it imports and publishes, so a bad edition never reaches a page. Every rule is a no-op while data/jobs/ is absent.

validate_claims() and validate_edition() are pure (import_jobs.py reuses them); check(ctx) adds the URL rules (the
newsletter's own denylist, through ctx.check_url) and the frozen rules against git.
"""
import re
from datetime import date as _date

CLAIM_IDS = ["J%d" % i for i in range(13)]
STATUS = ["contradicted", "no-clear-sign", "emerging", "supported", "established"]
EXTREMES = {"contradicted", "established"}
MARK_KEYS = ("contradicted", "emerging", "supported", "established")
RATINGS = {"verified fact", "credible report", "expert opinion", "forecast aggregate", "our inference", "speculation"}
FROZEN_CLAIM_FIELDS = ("label", "wording", "marks", "indicators")
FROZEN_TOP_FIELDS = ("lists", "defaultMarks")
EDITION_FILE = re.compile(r"^data/jobs/(\d{4}-\d{2}-\d{2})\.json$")
CLAIMS_REL = "data/jobs/claims.json"
STATUS_RULE = "status must be one of " + ", ".join(STATUS)


def _words(s):
    return len(str(s or "").split())


def validate_claims(doc):
    """Problems with the claims document, as strings."""
    out = []
    if not isinstance(doc, dict):
        return ["claims.json must be an object"]
    claims = doc.get("claims") or []
    if [c.get("id") for c in claims if isinstance(c, dict)] != CLAIM_IDS:
        out.append("claims must be J0 to J12 in order")
    for c in claims:
        if not isinstance(c, dict):
            continue
        cid = c.get("id", "?")
        if c.get("status") not in STATUS:
            out.append("%s: %s" % (cid, STATUS_RULE))
        marks = c.get("marks") or {}
        if not all(str(marks.get(k) or "").strip() for k in MARK_KEYS):
            out.append("%s: marks need contradicted, emerging, supported and established" % cid)
        pending = c.get("pending")
        if pending is not None and (not isinstance(pending, dict) or pending.get("to") not in EXTREMES):
            out.append("%s: pending.to must be established or contradicted" % cid)
        hist = c.get("history") or []
        for n, row in enumerate(hist, 1):
            if n > 1 and row.get("from") != hist[n - 2].get("to"):
                out.append("%s: history row %d: from must equal the previous row's to" % (cid, n))
        if hist and hist[-1].get("to") != c.get("status"):
            out.append("%s: last history row's to must equal status" % cid)
    return out


def validate_edition(doc, rel):
    """Problems with one imported edition (rel is its data/jobs/<FRIDAY>.json path), as strings."""
    out = []
    if not isinstance(doc, dict):
        return ["%s must be an object" % rel]
    m = EDITION_FILE.match(rel)
    try:
        lag = (_date.fromisoformat(m.group(1)) - _date.fromisoformat(str(doc.get("date")))).days if m else None
    except ValueError:
        lag = None
    if lag is None or not 0 <= lag <= 6:
        out.append("%s: the edition (date %s) must be dated 0 to 6 days before the wrap-up it is filed under" % (rel, doc.get("date")))
    if doc.get("edition") not in (None, doc.get("date")):
        out.append("%s: edition must equal date" % rel)
    if not str(doc.get("headline") or "").strip() or len(str(doc.get("headline"))) > 90:
        out.append("%s: headline is required, at most 90 characters" % rel)
    if _words(doc.get("dek")) > 60:
        out.append("%s: dek is over 60 words" % rel)
    strip = doc.get("strip") or []
    if [s.get("id") for s in strip if isinstance(s, dict)] != CLAIM_IDS:
        out.append("%s: strip must list J0 to J12 in order" % rel)
    for s in strip:
        if isinstance(s, dict) and s.get("status") not in STATUS:
            out.append("%s: strip %s: %s" % (rel, s.get("id"), STATUS_RULE))
    ids = [e.get("id") for e in doc.get("evidence") or [] if isinstance(e, dict)]
    for eid in sorted({i for i in ids if ids.count(i) > 1}):
        out.append("%s: evidence id %s is used twice" % (rel, eid))
    for mv in doc.get("moves") or []:
        a, b = mv.get("from"), mv.get("to")
        where = "%s: move %s" % (rel, mv.get("id"))
        if a not in STATUS or b not in STATUS:
            out.append(where + ": move from and to must be on the scale")
        elif mv.get("by") != "owner":
            if abs(STATUS.index(a) - STATUS.index(b)) > 1:
                out.append("%s: move of %d steps needs by: owner" % (where, abs(STATUS.index(a) - STATUS.index(b))))
            if b in EXTREMES:
                out.append("%s: move to %s needs by: owner" % (where, b))
        for eid in mv.get("evidence") or []:
            if eid not in ids:
                out.append("%s: evidence id %s is not defined" % (where, eid))
    for e in doc.get("evidence") or []:
        if not isinstance(e, dict):
            continue
        if e.get("rating") not in RATINGS:
            out.append("%s: evidence %s: rating must be one of the six ratings" % (rel, e.get("id")))
        if not str(e.get("text") or "").strip():
            out.append("%s: evidence %s: text is required" % (rel, e.get("id")))
    nc = doc.get("nullCase")
    if not isinstance(nc, dict) or not (str(nc.get("text") or "").strip() or str(nc.get("none") or "").strip()):
        out.append("%s: nullCase is required" % rel)
    return out


def edition_urls(doc):
    """(where, url) for every link an edition publishes."""
    for e in doc.get("evidence") or []:
        if isinstance(e, dict):
            yield "evidence %s.url" % e.get("id"), e.get("url")
            for j, u in enumerate(e.get("otherUrls") or []):
                yield "evidence %s.otherUrls[%d]" % (e.get("id"), j), u
    for j, c in enumerate(doc.get("corrections") or []):
        if isinstance(c, dict):
            yield "corrections[%d].url" % j, c.get("url")


def check(ctx):
    data = ctx.data
    rels = sorted(r for r in data if r.startswith("data/jobs/"))
    if not rels:
        return
    f = ctx.f
    claims = data.get(CLAIMS_REL)
    if claims is None:
        f.err("%s is missing although data/jobs/ has editions" % CLAIMS_REL)
    else:
        for msg in validate_claims(claims):
            f.err("%s: %s" % (CLAIMS_REL, msg))
    for rel in rels:
        if not EDITION_FILE.match(rel):
            continue
        doc = data.get(rel)
        for msg in validate_edition(doc, rel):
            f.err(msg)
        for where, url in edition_urls(doc if isinstance(doc, dict) else {}):
            ctx.check_url(f, "%s %s" % (rel, where), url, True)
    if not ctx.git.ok:
        return
    for rel in [r for r in ctx.git.lines("ls-tree", "--name-only", ctx.git.base, "data/jobs/") if EDITION_FILE.match(r)]:
        head = ctx.git.show_json(rel)
        if rel not in data:
            f.freeze("%s was removed; published Jobs editions are frozen" % rel)
        elif head is not None and head != data.get(rel):
            f.freeze("%s changed since HEAD; published Jobs editions are frozen" % rel)
    head = ctx.git.show_json(CLAIMS_REL)
    if not isinstance(head, dict) or not isinstance(claims, dict):
        return
    now = {c.get("id"): c for c in claims.get("claims") or [] if isinstance(c, dict)}
    bumped = claims.get("version") != head.get("version") and len(claims.get("changelog") or []) > len(head.get("changelog") or [])
    for hc in head.get("claims") or []:
        nc = now.get(hc.get("id"))
        if nc is None:
            continue
        old, new = hc.get("history") or [], nc.get("history") or []
        for n, row in enumerate(old, 1):
            if n > len(new) or new[n - 1] != row:
                f.freeze("%s: %s: history row %d changed since HEAD; history is append-only" % (CLAIMS_REL, hc.get("id"), n))
                break
        if not bumped:
            for field in FROZEN_CLAIM_FIELDS:
                if nc.get(field) != hc.get(field):
                    f.freeze("%s: %s: %s changed since HEAD without a version bump and changelog entry" % (CLAIMS_REL, hc.get("id"), field))
    if not bumped:
        for field in FROZEN_TOP_FIELDS:
            if claims.get(field) != head.get(field):
                f.freeze("%s: %s changed since HEAD without a version bump and changelog entry" % (CLAIMS_REL, field))
