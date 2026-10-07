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


def _is_str(v, empty=False):
    return isinstance(v, str) and (empty or bool(v.strip()))


def _opt_str(v):
    return v is None or isinstance(v, str)


def _dicts(v):
    return isinstance(v, list) and all(isinstance(x, dict) for x in v)


def _strs(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def validate_claims(doc):
    """Problems with the claims document, as strings. Strict about every type the pages render; never raises (the
    2026-10-06 review's Important 1: a value the renderer cannot handle must be refused at import, not crash Friday)."""
    try:
        return _validate_claims(doc)
    except Exception as e:  # noqa: BLE001 - any surprise in the structure is a refusal, never a traceback
        return ["claims.json has an unexpected structure (%s: %s)" % (type(e).__name__, e)]


def _validate_claims(doc):
    out = []
    if not isinstance(doc, dict):
        return ["claims.json must be an object"]
    claims = doc.get("claims")
    if not _dicts(claims):
        return ["claims must be a list of objects"]
    if [c.get("id") for c in claims] != CLAIM_IDS:
        out.append("claims must be J0 to J12 in order")
    for c in claims:
        cid = c.get("id", "?")
        for key in ("label", "wording"):
            if not _is_str(c.get(key)):
                out.append("%s: %s must be a non-empty string" % (cid, key))
        if not _opt_str(c.get("why")):
            out.append("%s: why must be a string" % cid)
        if c.get("status") not in STATUS:
            out.append("%s: %s" % (cid, STATUS_RULE))
        marks = c.get("marks")
        if not isinstance(marks, dict) or not all(_is_str(marks.get(k)) for k in MARK_KEYS) \
                or not all(isinstance(v, str) for v in marks.values()):
            out.append("%s: marks need contradicted, emerging, supported and established" % cid)
        inds = c.get("indicators")
        if not _dicts(inds) or not inds:
            out.append("%s: indicators must be a non-empty list of objects" % cid)
        else:
            for i in inds:
                if not all(_is_str(i.get(k)) for k in ("name", "url")) or not all(_opt_str(i.get(k)) for k in
                                                                                    ("source", "cadence", "dataKind", "comparison")):
                    out.append("%s: indicator %s needs string name, url, source, cadence, dataKind and comparison" % (cid, i.get("id")))
                if not _strs(i.get("confounders") or []):
                    out.append("%s: indicator %s: confounders must be strings" % (cid, i.get("id")))
        pending = c.get("pending")
        if pending is not None and (not isinstance(pending, dict) or pending.get("to") not in EXTREMES):
            out.append("%s: pending.to must be established or contradicted" % cid)
        hist = c.get("history")
        if not _dicts(hist if hist is not None else []):
            out.append("%s: history must be a list of objects" % cid)
            continue
        hist = hist or []
        for n, row in enumerate(hist, 1):
            if not _is_str(row.get("date")) or not _opt_str(row.get("why")) or row.get("to") not in STATUS \
                    or (row.get("from") is not None and row.get("from") not in STATUS):
                out.append("%s: history row %d needs a date, from and to on the scale, and a string why" % (cid, n))
            if n > 1 and row.get("from") != hist[n - 2].get("to"):
                out.append("%s: history row %d: from must equal the previous row's to" % (cid, n))
        if hist and hist[-1].get("to") != c.get("status"):
            out.append("%s: last history row's to must equal status" % cid)
    return out


def validate_edition(doc, rel):
    """Problems with one imported edition (rel is its data/jobs/<FRIDAY>.json path), as strings. Strict about every
    type the wrap-up page, the email and the corrections log use; never raises."""
    try:
        return _validate_edition(doc, rel)
    except Exception as e:  # noqa: BLE001 - any surprise in the structure is a refusal, never a traceback
        return ["%s has an unexpected structure (%s: %s)" % (rel, type(e).__name__, e)]


def _validate_edition(doc, rel):
    out = []
    p = lambda msg: out.append("%s: %s" % (rel, msg))  # noqa: E731
    if not isinstance(doc, dict):
        return ["%s must be an object" % rel]
    m = EDITION_FILE.match(rel)
    try:
        lag = (_date.fromisoformat(m.group(1)) - _date.fromisoformat(str(doc.get("date")))).days if m else None
    except ValueError:
        lag = None
    if lag is None or not 0 <= lag <= 6:
        p("the edition (date %s) must be dated 0 to 6 days before the wrap-up it is filed under" % doc.get("date"))
    if doc.get("edition") not in (None, doc.get("date")):
        p("edition must equal date")
    if not _is_str(doc.get("headline")) or len(doc["headline"]) > 90:
        p("headline is required, a string of at most 90 characters")
    if not isinstance(doc.get("dek"), str):
        p("dek must be a string")
    elif _words(doc["dek"]) > 60:
        p("dek is over 60 words")
    if not isinstance(doc.get("baseline", False), bool):
        p("baseline must be true or false")
    strip = doc.get("strip")
    if not _dicts(strip):
        p("strip must be a list of objects")
        strip = []
    if [s.get("id") for s in strip] != CLAIM_IDS:
        p("strip must list J0 to J12 in order")
    for s in strip:
        if s.get("status") not in STATUS:
            p("strip %s: %s" % (s.get("id"), STATUS_RULE))
        if s.get("prev") is not None and s.get("prev") not in STATUS:
            p("strip %s: prev must be null or on the scale" % s.get("id"))
        pend = s.get("pending")
        if pend is not None and (not isinstance(pend, dict) or pend.get("to") not in EXTREMES):
            p("strip %s: pending must be null or an object whose to is established or contradicted" % s.get("id"))
    evidence = doc.get("evidence")
    if not _dicts(evidence):
        p("evidence must be a list of objects")
        evidence = []
    ids = [e.get("id") for e in evidence]
    for eid in sorted({str(i) for i in ids if ids.count(i) > 1}):
        p("evidence id %s is used twice" % eid)
    for e in evidence:
        w = "evidence %s" % e.get("id")
        if not _is_str(e.get("id")):
            p(w + ": id must be a string")
        if e.get("rating") not in RATINGS:
            p(w + ": rating must be one of the six ratings")
        for key in ("text", "url", "eventDate"):
            if not _is_str(e.get(key)):
                p(w + ": %s must be a non-empty string" % key)
        for key in ("via", "ratingQual", "ratingNote", "confounder"):
            if not _opt_str(e.get(key)):
                p(w + ": %s must be a string or null" % key)
        if not _strs(e.get("otherUrls") or []):
            p(w + ": otherUrls must be strings")
        if not _dicts(e.get("bears") or []):
            p(w + ": bears must be a list of objects")
    for kind in ("moves", "pendingOwner"):
        rows = doc.get(kind) or []
        if not _dicts(rows):
            p("%s must be a list of objects" % kind)
            continue
        for mv in rows:
            w = "%s %s" % ("move" if kind == "moves" else "pendingOwner", mv.get("id"))
            if mv.get("id") not in CLAIM_IDS:
                p(w + ": id must be a claim id")
            if not _is_str(mv.get("why")):
                p(w + ": why must be a non-empty string")
            a, b = mv.get("from"), mv.get("to")
            if a not in STATUS or b not in STATUS:
                p(w + ": move from and to must be on the scale")
            elif kind == "pendingOwner":
                if b not in EXTREMES:
                    p(w + ": pending.to must be established or contradicted")
            elif mv.get("by") != "owner":
                if abs(STATUS.index(a) - STATUS.index(b)) > 1:
                    p("%s: move of %d steps needs by: owner" % (w, abs(STATUS.index(a) - STATUS.index(b))))
                if b in EXTREMES:
                    p("%s: move to %s needs by: owner" % (w, b))
            if not _strs(mv.get("evidence") or []):
                p(w + ": evidence must be a list of ids")
            for eid in mv.get("evidence") or []:
                if eid not in ids:
                    p("%s: evidence id %s is not defined" % (w, eid))
    nc = doc.get("nullCase")
    if not isinstance(nc, dict) or not (_is_str(nc.get("text")) or _is_str(nc.get("none"))):
        p("nullCase is required, with a string text or none")
    elif not _strs(nc.get("evidence") or []):
        p("nullCase.evidence must be a list of ids")
    if not _dicts(doc.get("releases") or []):
        p("releases must be a list of objects")
    else:
        for r in doc.get("releases") or []:
            if not _is_str(r.get("series")) or not _opt_str(r.get("period")) or not _opt_str(r.get("note")) \
                    or not (r.get("value") is None or (isinstance(r.get("value"), (int, float)) and not isinstance(r.get("value"), bool))):
                p("release %s needs a series string, a string period and note, and a number value" % r.get("series"))
    corr = doc.get("corrections") or []
    if not _dicts(corr):
        p("corrections must be a list of objects")
    else:
        for j, c in enumerate(corr):
            if not all(_is_str(c.get(k)) for k in ("date", "item", "was", "now", "url")) or not _opt_str(c.get("page")):
                p("corrections[%d] needs non-empty string date, item, was, now and url" % j)
    if not _dicts(doc.get("gaps") or []) and not _strs(doc.get("gaps") or []):
        p("gaps must be a list of strings")
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

    def published(rel):
        """Committed and unchanged: then only the frozen comparison applies, never today's content rules, so a rule
        tightened or a domain denylisted later can never fail every daily check (the 2026-10-06 review's I4)."""
        return bool(ctx.git.ok) and ctx.git.show_json(rel) is not None and ctx.git.show_json(rel) == data.get(rel)

    claims = data.get(CLAIMS_REL)
    if claims is None:
        f.err("%s is missing although data/jobs/ has editions" % CLAIMS_REL)
    elif not published(CLAIMS_REL):
        for msg in validate_claims(claims):
            f.err("%s: %s" % (CLAIMS_REL, msg))
    for rel in rels:
        if not EDITION_FILE.match(rel) or published(rel):
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
