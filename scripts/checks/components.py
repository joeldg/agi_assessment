"""data/agi_components.json (spec 8.1, 11). The reference is validate_components() in
.claude/work/redesign/final_build_prototype.py; this module is the full rule set.

URLs are checked by check_data's own URL walk (strict for this file: a denylisted domain is an ERROR).
The file is optional until a definitions entry exists in data/method.json; after that it is required.
"""
import json
import re

from . import COMPONENT_IDS, HYP_KEYS, RATINGS, SCALE_KEYS, definitions_entries, is_num, iso, words

REL = "data/agi_components.json"
PART_STATES = {"pass", "aggregate", "no", "unmeasured"}
SCALES = {"linear", "count"}
KINDS = {"result", "internal", "yardstick"}
NO_BODY = re.compile(r"physical|embodied|robot", re.I)
OUR_READING = re.compile(r"\bour (?:reading|calculation|inference|read)\b", re.I)
INTERNAL = [("data/", re.compile(r"data/")), ("go-live", re.compile(r"go-live", re.I)),
            ("tripped", re.compile(r"\btripped\b", re.I)), ("trigger", re.compile(r"\btrigger", re.I)),
            ("watching", re.compile(r"\bwatching\b", re.I))]
BUDGETS = [("glance", 25), ("statusNote", 60), ("bar", 35), ("statusBasis", 30), ("basisShort", 8), ("question", 45),
           ("sharedWith", 25)]
HEADLINE_M = ["label", "target", "targetDisplay", "partialAt", "partialDisplay", "closeAt", "closeDisplay", "scale",
              "min", "max", "unit", "growth", "logTicks"]
COMPONENT_M = ["id", "order", "name", "short", "v1Test", "clause", "bar", "test"]


def canon(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def m_fields(doc):
    """The fields that change only with a method.json changelog entry (class M in spec 8.1)."""
    if not isinstance(doc, dict):
        return {}
    out = {k: doc.get(k) for k in ("definitionsVersion", "adopted", "definition", "hypotheses", "statusScale",
                                   "statusRule")}
    for c in doc.get("components") or []:
        if not isinstance(c, dict):
            continue
        h = c.get("headline") if isinstance(c.get("headline"), dict) else {}
        proj = c.get("projection") if isinstance(c.get("projection"), dict) else {}
        m = {k: c.get(k) for k in COMPONENT_M}
        m["parts.name"] = [p.get("name") for p in c.get("parts") or [] if isinstance(p, dict)]
        m["headline"] = {k: h.get(k) for k in HEADLINE_M}
        m["projection.trend"] = proj.get("trend")
        out["components." + str(c.get("id"))] = m
    return out


def items_with_rating(obj, path):
    """(path, dict) for every object under obj that carries a rating or ratingNote."""
    if isinstance(obj, dict):
        if "rating" in obj or "ratingNote" in obj:
            yield path, obj
        for k, v in obj.items():
            yield from items_with_rating(v, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from items_with_rating(v, "%s[%d]" % (path, i))


def resolve(doc, dotted):
    cur = doc
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def check_top(ctx, doc, method):
    f, js = ctx.f, ctx.js
    scale = doc.get("statusScale")
    if not isinstance(scale, list) or [s.get("key") if isinstance(s, dict) else None for s in scale] != SCALE_KEYS:
        f.err("agi_components.statusScale must be exactly far, partial, close, met in that order")
        words_ = {}
    else:
        words_ = {s["key"]: s.get("word") for s in scale}
        for i, s in enumerate(scale):
            if s.get("pips") != i + 1:
                f.err("agi_components.statusScale[%d].pips=%s must be %d" % (i, js(s.get("pips")), i + 1))
            if not isinstance(s.get("word"), str) or not s["word"]:
                f.err("agi_components.statusScale[%d].word is missing" % i)
            if not isinstance(s.get("meaning"), str) or not s["meaning"]:
                f.err("agi_components.statusScale[%d].meaning is missing" % i)
    if not isinstance(doc.get("statusRule"), str) or not doc["statusRule"].strip():
        f.err("agi_components.statusRule is missing")
    hyp = doc.get("hypotheses")
    for k in HYP_KEYS:
        h = hyp.get(k) if isinstance(hyp, dict) else None
        if not isinstance(h, dict) or not isinstance(h.get("name"), str) or not isinstance(h.get("text"), str):
            f.err("agi_components.hypotheses.%s must be {name, text}" % k)
    d = doc.get("definition")
    if not isinstance(d, dict) or not isinstance(d.get("text"), str) or not d["text"].strip():
        f.err("agi_components.definition.text is missing")
    for k in ("lastReviewed",):
        if iso(doc.get(k)) is None:
            f.err("agi_components.%s=%s is not YYYY-MM-DD" % (k, js(doc.get(k))))
    # definitionsVersion and adopted agree with method.json
    dv = doc.get("definitionsVersion")
    if not isinstance(dv, str):
        f.err("agi_components.definitionsVersion=%s must be a version string such as \"2.0\"" % js(dv))
    entries = definitions_entries(method)
    adopting = [e for e in entries if e.get("definitions") == dv]
    last = entries[-1] if entries else None
    adopted = doc.get("adopted")
    if adopted is not None and iso(adopted) is None:
        f.err("agi_components.adopted=%s must be null or YYYY-MM-DD" % js(adopted))
    elif last is not None and last.get("definitions") == dv:
        want = adopting[-1].get("date")
        if adopted != want:
            f.err("agi_components.adopted=%s but data/method.json adopted definitions %s on %s" % (
                js(adopted), dv, js(want)))
    elif adopted is not None:
        f.err("agi_components.adopted=%s but no definitions %s entry is in force in data/method.json (the last "
              "definitions entry is %s); adopted stays null until the method entry" % (
                  js(adopted), js(dv), js(last.get("definitions")) if last else "none"))
    pub = doc.get("publicAgi")
    if pub is not None and not (isinstance(pub, dict) and all(pub.get(k) for k in ("system", "date", "url"))):
        f.err("agi_components.publicAgi must be absent or {system, date, url}")
    return words_


def check_identity(ctx, c, i, p):
    f, js = ctx.f, ctx.js
    if c.get("order") != i + 1:
        f.err("%s.order=%s must be %d" % (p, js(c.get("order")), i + 1))
    for k in ("id", "name", "short"):
        if isinstance(c.get(k), str) and NO_BODY.search(c[k]):
            f.err("%s.%s=%s: physical and embodied work is out of scope in definitions v2.0" % (p, k, js(c[k])))
    if not isinstance(c.get("v1Test"), bool):
        f.err("%s.v1Test must be true or false" % p)
    if iso(c.get("since")) is None:
        f.err("%s.since=%s is not YYYY-MM-DD" % (p, js(c.get("since"))))
    test = c.get("test") if isinstance(c.get("test"), dict) else {}
    thr = test.get("threshold")
    if not isinstance(thr, str) or not all(m in thr for m in ("Partial:", "Close:", "Met:")):
        f.err("%s.test.threshold must state every mark as \"Partial: … Close: … Met: …\"" % p)


def check_parts(ctx, c, p):
    """The parts of the test; returns (parts, any part passed)."""
    parts = c.get("parts") if isinstance(c.get("parts"), list) else []
    for j, part in enumerate(parts):
        if not isinstance(part, dict) or part.get("state") not in PART_STATES:
            ctx.f.err("%s.parts[%d].state=%s must be pass, aggregate, no or unmeasured" % (
                p, j, ctx.js(part.get("state") if isinstance(part, dict) else part)))
    return parts, any(isinstance(x, dict) and x.get("state") == "pass" for x in parts)


def check_headline(ctx, h, p, reviewed=None):
    """Shape of the headline measure; returns (Partial mark reached, a marker counting as Partial, Close mark)."""
    f, js = ctx.f, ctx.js
    v, lo, hi, tgt = h.get("value"), h.get("min"), h.get("max"), h.get("target")
    if not all(is_num(x) for x in (v, lo, hi, tgt)):
        f.err("%s.headline: value, min, max and target must be numbers (got %s, %s, %s, %s)" % (
            p, js(v), js(lo), js(hi), js(tgt)))
    elif not lo <= v <= hi:
        f.err("%s.headline.value=%s is outside min %s – max %s" % (p, v, lo, hi))
    if h.get("scale") not in SCALES:
        f.err("%s.headline.scale=%s must be linear or count" % (p, js(h.get("scale"))))
    if h.get("growth") and not (isinstance(h.get("logTicks"), list) and h["logTicks"]):
        f.err("%s.headline.growth needs logTicks (the drill-down's log axis)" % p)
    for k in ("partialAt", "closeAt"):
        if h.get(k) is not None and not is_num(h.get(k)):
            f.err("%s.headline.%s=%s must be a number or absent" % (p, k, js(h.get(k))))
    asof = iso(h.get("asOf"))
    if asof and (ctx.today - asof).days > 120 and not (reviewed and (ctx.today - reviewed).days <= 14):
        # an old measurement is fine while the weekly lens keeps re-checking it (lastReviewed within 14 days)
        f.warn("%s.headline.asOf=%s is more than 120 days old and the part wasn't re-checked in 14 days" % (
            p, js(h.get("asOf"))))
    part_mark = is_num(v) and is_num(h.get("partialAt")) and v >= h["partialAt"]
    close_mark = is_num(v) and is_num(h.get("closeAt")) and v >= h["closeAt"]
    marker_mark = any(isinstance(m, dict) and m.get("counts") == "partial" and is_num(m.get("value"))
                      and is_num(m.get("partialAt")) and m["value"] >= m["partialAt"] for m in h.get("markers") or [])
    return part_mark, marker_mark, close_mark


def check_status(ctx, c, p, word, h, parts, passed, marks):
    """Status against its evidence: ERROR for a Met or Partial the evidence doesn't support, WARN on position."""
    f, st, basis = ctx.f, c.get("status"), c.get("statusBasis")
    part_mark, marker_mark, close_mark = marks
    if not isinstance(basis, str) or not basis.lower().startswith(word.lower() + ":"):
        f.err("%s.statusBasis must start with \"%s:\" (its status word), got %s" % (p, word, ctx.js(basis, 40)))
    if st == "met" and not (parts and all(isinstance(x, dict) and x.get("state") == "pass" for x in parts)):
        f.err("%s is Met but not every part of its test is passed" % p)
    if st == "partial" and not (passed or part_mark or marker_mark):
        f.err("%s is Partial with no passed part and no Partial mark reached (a part passed on the overall figure "
              "only does not count)" % p)
    if close_mark and st in ("far", "partial"):
        f.warn("%s: the headline (%s) is at or past the Close mark (%s) while the status is %s" % (
            p, h.get("display"), h.get("closeDisplay") or h.get("closeAt"), word))
    if st == "far" and (passed or part_mark or marker_mark) and not re.search(
            r"overall figure only|does(?: not|n't) count|unreleased", basis or "", re.I):
        f.warn("%s is Far although a part is passed or a Partial mark is reached; say why in statusBasis" % p)
    v, tgt = h.get("value"), h.get("target")
    if is_num(v) and is_num(tgt) and v >= tgt and st != "met":
        f.warn("%s: headline at the bar; other parts pending" % p)


def check_ratings(ctx, c, p):
    f, js = ctx.f, ctx.js
    for path, item in items_with_rating(c, p):
        r = item.get("rating")
        if r is not None and r not in RATINGS:
            f.err("%s.rating=%s is not one of: %s" % (path, js(r), ", ".join(sorted(RATINGS))))
        note = item.get("ratingNote")
        if isinstance(note, str) and note.count("(") != note.count(")"):
            f.err("%s.ratingNote has unbalanced parentheses" % path)
        if isinstance(item.get("ratingQual"), str) and words(item["ratingQual"]) > 5:
            f.warn("%s.ratingQual is %d words (5 at most)" % (path, words(item["ratingQual"])))
        if r == "verified fact" and not item.get("ratingNote"):
            txt = " ".join(str(item.get(k, "")) for k in ("text", "value", "what", "metric"))
            if OUR_READING.search(txt):
                f.warn("%s: a verified-fact item states our own reading without a ratingNote" % path)


def check_milestones(ctx, c, p):
    f, js, prev = ctx.f, ctx.js, None
    for j, m in enumerate(c.get("milestones") or []):
        mp = "%s.milestones[%d]" % (p, j)
        raw = m.get("date") if isinstance(m, dict) else m
        d = iso(raw) if isinstance(raw, str) and len(raw) == 10 else None
        if d is None:
            f.err("%s.date=%s is not YYYY-MM-DD" % (mp, js(raw)))
            continue
        if raw < "2019-01-01" or d > ctx.today:
            f.err("%s.date=%s is outside 2019-01-01 to today" % (mp, raw))
        if prev and d < prev:
            f.err("%s.date=%s is earlier than the milestone before it (sorted by date)" % (mp, raw))
        prev = d
        if m.get("kind") not in KINDS:
            f.warn("%s.kind=%s should be result, internal or yardstick" % (mp, js(m.get("kind"))))
        if words(m.get("text")) > 40:
            f.warn("%s.text is %d words (budget 40)" % (mp, words(m.get("text"))))


def check_trend(ctx, tr, p, trends):
    """projection.trend names a published fit: the dates are read from trends.json, never copied."""
    f, js = ctx.f, ctx.js
    src = tr.get("source") if isinstance(tr, dict) else None
    doc = trends.get(src) if isinstance(src, str) else None
    node = resolve(doc, tr.get("path", "")) if isinstance(doc, dict) and isinstance(tr.get("path"), str) else None
    if not isinstance(node, dict):
        f.err("%s.projection.trend %s does not resolve to an object" % (
            p, js({k: tr.get(k) for k in ("source", "path")} if isinstance(tr, dict) else tr)))
        return
    for mk in tr.get("marks") or []:
        if mk not in node:
            f.err("%s.projection.trend mark %s is not in %s %s" % (p, js(mk), src, tr["path"]))
        elif not isinstance(node[mk], dict) or not node[mk].get("mid"):
            f.warn("%s.projection.trend mark %s is null in %s (shown as \"beyond 2030\")" % (p, js(mk), src))


def check_upkeep(ctx, c, p, proj):
    """WARN: staleness, word budgets, list sizes and internal words in reader-facing text."""
    f, js = ctx.f, ctx.js
    lr = iso(c.get("lastReviewed"))
    if lr is None:
        f.err("%s.lastReviewed=%s is not YYYY-MM-DD" % (p, js(c.get("lastReviewed"))))
    elif (ctx.today - lr).days > 14:
        f.warn("%s.lastReviewed=%s is more than 14 days old" % (p, c["lastReviewed"]))
    for k, lim in BUDGETS:
        n = words(c.get(k))
        if n > lim:
            f.warn("%s.%s is %d words (budget %d)" % (p, k, n, lim))
    if isinstance(c.get("short"), str) and len(c["short"]) > 14:
        f.warn("%s.short=%s is longer than 14 characters" % (p, js(c["short"])))
    for k in ("who", "watching", "challenges"):
        n = len(c.get(k) or [])
        if n < 3 or n > 8:
            f.warn("%s.%s has %d items (3–8)" % (p, k, n))
    vis = {k: c.get(k) for k in ("glance", "statusNote", "statusBasis", "bar", "sharedWith", "hiddenAngle")}
    vis["test.threshold"] = (c.get("test") or {}).get("threshold") if isinstance(c.get("test"), dict) else None
    vis["projection.text"] = proj.get("text")
    for k, text in vis.items():
        for term, pat in INTERNAL if isinstance(text, str) else []:
            if pat.search(text):
                f.warn("%s.%s uses the internal word %s in reader-facing text" % (p, k, js(term)))


def check_component(ctx, c, i, words_, trends):
    p = "agi_components.components[%d] (%s)" % (i, c.get("id"))
    check_identity(ctx, c, i, p)
    parts, passed = check_parts(ctx, c, p)
    st = c.get("status")
    h = c.get("headline") if isinstance(c.get("headline"), dict) else None
    if h is None:
        ctx.f.err("%s.headline is missing" % p)
    marks = check_headline(ctx, h, p, iso(c.get("lastReviewed"))) if h is not None else (False, False, False)
    if st not in SCALE_KEYS:
        ctx.f.err("%s.status=%s is not on the scale (far, partial, close, met)" % (p, ctx.js(st)))
    elif h is not None:
        check_status(ctx, c, p, words_.get(st) or st.capitalize(), h, parts, passed, marks)
    check_ratings(ctx, c, p)
    check_milestones(ctx, c, p)
    proj = c.get("projection") if isinstance(c.get("projection"), dict) else {}
    if proj.get("trend") is not None:
        check_trend(ctx, proj["trend"], p, trends)
    check_upkeep(ctx, c, p, proj)


def check_history(ctx, doc, head):
    f, js = ctx.f, ctx.js
    hist = doc.get("history")
    if not isinstance(hist, list):
        f.err("agi_components.history must be a list")
        return
    last = {}
    for j, row in enumerate(hist):
        if not isinstance(row, dict) or row.get("id") not in COMPONENT_IDS or iso(row.get("date")) is None:
            f.err("agi_components.history[%d] must be {date, id, from, to, why} with a known part id" % j)
            continue
        if row.get("to") not in SCALE_KEYS:
            f.err("agi_components.history[%d].to=%s is not on the scale" % (j, js(row.get("to"))))
        last[row["id"]] = (j, row)
    for c in doc.get("components") or []:
        if not isinstance(c, dict) or c.get("id") not in COMPONENT_IDS:
            continue
        hit = last.get(c["id"])
        if hit is None:
            f.err("agi_components.history has no row for %s (every part needs its baseline row)" % c["id"])
        elif hit[1].get("to") != c.get("status"):
            f.err("agi_components.history[%d]: the last row for %s says %s but the status is %s" % (
                hit[0], c["id"], js(hit[1].get("to")), js(c.get("status"))))
    if not isinstance(head, dict):
        return
    ctx.append_only(f, "agi_components.history", head.get("history"), hist)
    hstat = {c.get("id"): c.get("status") for c in head.get("components") or [] if isinstance(c, dict)}
    new_rows = hist[len(head.get("history") or []):]
    for c in doc.get("components") or []:
        if not isinstance(c, dict) or c.get("id") not in hstat or hstat[c["id"]] == c.get("status"):
            continue
        if not any(isinstance(r, dict) and r.get("id") == c["id"] and r.get("to") == c.get("status") for r in new_rows):
            f.err("agi_components: %s changed %s → %s since HEAD without a new history row" % (
                c["id"], js(hstat[c["id"]]), js(c.get("status"))))


def check_frozen(ctx, doc, head, method):
    """M fields change only with a new method.json changelog entry."""
    if not isinstance(head, dict):
        return
    hm = ctx.git.show_json("data/method.json")
    hlog = hm.get("changelog") if isinstance(hm, dict) and isinstance(hm.get("changelog"), list) else []
    wlog = method.get("changelog") if isinstance(method, dict) and isinstance(method.get("changelog"), list) else []
    if len(wlog) > len(hlog):
        return
    a, b = m_fields(head), m_fields(doc)
    changed = [k for k in sorted(set(a) | set(b)) if canon(a.get(k)) != canon(b.get(k))]
    if changed:
        detail = []
        for k in changed:
            if isinstance(a.get(k), dict) and isinstance(b.get(k), dict):
                sub = [s for s in sorted(set(a[k]) | set(b[k])) if canon(a[k].get(s)) != canon(b[k].get(s))]
                detail.append("%s (%s)" % (k, ", ".join(sub)))
            else:
                detail.append(k)
        ctx.f.err("agi_components: %s changed since HEAD; the definition, scale, tests and marks change only with a "
                  "new data/method.json changelog entry (a method change)" % "; ".join(detail))


def check_consistency(ctx, doc, runs):
    """WARN: all parts met while AGI anywhere is low, or AGI anywhere high with 3+ parts far."""
    if not isinstance(runs, list):
        return
    newest = next((r for r in reversed(runs) if isinstance(r, dict) and r.get("report")), None)
    agi = (newest or {}).get("agi")
    now = agi.get("now") if isinstance(agi, dict) else None
    if not is_num(now):
        return
    st = [c.get("status") for c in doc.get("components") or [] if isinstance(c, dict)]
    if st and all(s == "met" for s in st) and now < 50:
        ctx.f.warn("agi_components: all 8 parts are met but AGI anywhere today is %s%%" % now)
    if now > 10 and st.count("far") >= 3:
        ctx.f.warn("agi_components: AGI anywhere today is %s%% with %d parts far" % (now, st.count("far")))


def check(ctx, runs):
    f, js = ctx.f, ctx.js
    method = ctx.data.get("data/method.json")
    in_force = isinstance(method, dict) and bool(definitions_entries(method))
    if REL not in ctx.data:
        if in_force and any(e.get("definitions") != "1.0" for e in definitions_entries(method)):
            f.err("%s is missing although data/method.json has a definitions entry; restore the last committed "
                  "version (git checkout -- %s)" % (REL, REL))
        return
    doc = ctx.data.get(REL)
    if doc is None:
        return  # check_data already reported the parse error
    if not isinstance(doc, dict):
        f.err("%s must be an object" % REL)
        return
    comps = doc.get("components")
    ids = [c.get("id") if isinstance(c, dict) else None for c in comps] if isinstance(comps, list) else None
    if ids != COMPONENT_IDS:
        f.err("agi_components.components must be exactly the 8 parts in order: %s (got %s)" % (
            ", ".join(COMPONENT_IDS), js(ids)))
    words_ = check_top(ctx, doc, method if isinstance(method, dict) else {})
    trends = {k: v for k, v in ctx.data.items() if isinstance(k, str)}
    for i, c in enumerate(comps if isinstance(comps, list) else []):
        if isinstance(c, dict):
            check_component(ctx, c, i, words_, trends)
    lr = iso(doc.get("lastReviewed"))
    if lr and (ctx.today - lr).days > 10:
        f.warn("agi_components.lastReviewed=%s is more than 10 days old (the weekly components lens)" % (
            doc["lastReviewed"]))
    for j, fw in enumerate(doc.get("frameworks") or []):
        if not isinstance(fw, dict) or not all(isinstance(fw.get(k), str) for k in ("name", "definition")):
            f.err("agi_components.frameworks[%d] needs name and definition" % j)
    check_ratings(ctx, {"frameworks": doc.get("frameworks")}, "agi_components")
    head = ctx.git.show_json(REL) if ctx.git.ok else None
    check_history(ctx, doc, head)
    check_frozen(ctx, doc, head, method)
    check_consistency(ctx, doc, runs)
