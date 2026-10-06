"""index.html, "Today" (spec 4): three answer cards, then top stories, coming up and six hub tiles.

Rendered server-side from the newest published run, data/agi_components.json, alarm.json, escape.json,
calendar.json, forecasts.json and weekly/index.json. No JavaScript is needed to read it (the old assets/app.js is
retired). The Index bar is an <svg> in every state, so the weekly smoke check's chart rule holds even when the
newest run is a legacy one without indexParts. Anchors kept for frozen links: #tripwires (card 3's signals line),
#alarm (card 3), #gauges (card 2), #escape (a span in card 3), #roundup (top stories).
"""
import re

from sitekit import story_date

from . import common as C
from .common import as_dict, as_list, e

TITLE = "Hidden AGI watch"
DESCRIPTION = ("A daily, sourced reading of three questions: is AGI here, could it be hidden from the public, and "
               "should we worry today. Eight parts of AGI tracked against published tests, the Hidden AGI Index, and a "
               "fire alarm set by published rules, with our forecasts scored in public.")
# Search Console depends on this meta tag; the JSON-LD names the site and its publisher.
HEAD_EXTRA = """<meta name="google-site-verification" content="Be6S0c9DH1XRhRYohVFVG33a6kEYS-DwjR_c-UjvJmw" />
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
 {"@type":"WebSite","@id":"https://hiddenagi.com/#website","url":"https://hiddenagi.com/","name":"Hidden AGI watch","description":"%s","inLanguage":"en","publisher":{"@id":"https://hiddenagi.com/#organization"}},
 {"@type":"Organization","@id":"https://hiddenagi.com/#organization","name":"Hidden AGI watch","url":"https://hiddenagi.com/","logo":{"@type":"ImageObject","url":"https://hiddenagi.com/assets/brand/avatar.png","width":1024,"height":1024},"sameAs":["https://github.com/joeldg/agi_assessment"]}
]}
</script>""" % DESCRIPTION.replace('"', '\\"')

TOP_SHOWN = 5          # top stories on the homepage (spec 1: five; the 500-word budget holds)
TOP_WORDS = 25         # the writer's whole short (25 words at most), so a hedge at its end is never cut (ED8)
DATES_SHOWN = 3


def _top_items(run):
    """The newest run's top items in order: (date text, text, url, rating) for up to TOP_SHOWN."""
    out = []
    for g in as_list(as_dict(run).get("roundup")):
        for it in as_list(as_dict(g).get("items")):
            if isinstance(it, dict) and it.get("top"):
                out.append(it)
    return out


def _story_date(it):
    """One rule with the short report and the email (sitekit.story_date): "{date} (earlier event)"."""
    return story_date(it)


# Quotation marks, not apostrophes: an opening mark starts a word, a closing one ends it ("OpenAI's" is neither).
_QUOTE_OPEN = re.compile(r"(?:^|(?<=[\s(\[—–]))['‘\"“](?=\S)")
_QUOTE_CLOSE = re.compile(r"(?<=\S)['’\"”](?=[\s.,;:!?)\]—–…]|$)")
_SENTENCE = re.compile(r"(?<=[.!?])[\"'’”)]*\s+(?=[A-Z0-9\"“‘(])")


def _snippet(it):
    """A top story's line: the writer's short whole (format 2), else, for a legacy item, its first sentence when that
    fits, or the text cut at the last clause boundary, never inside a quotation (V16, ED8)."""
    short = str(it.get("short") or "").strip()
    if short:
        return C.clip_words(short, TOP_WORDS)
    text = " ".join(str(it.get("text") or "").split())
    first = _SENTENCE.split(text, maxsplit=1)[0]
    if C.words(first) <= TOP_WORDS:
        return first
    toks, out = first.split(), []
    for w in toks[:TOP_WORDS]:
        out.append(w)
    cut = " ".join(out)
    # back off to the last clause boundary, and never leave a quotation open
    m = re.search(r"^(.*[;:,–—])\s", cut)
    cut = m.group(1).rstrip(";:,–— ") if m and C.words(m.group(1)) >= 8 else cut
    opens = [m.start() for m in _QUOTE_OPEN.finditer(cut)]
    if len(opens) > len(_QUOTE_CLOSE.findall(cut)):
        cut = cut[:opens[-1]].rstrip(" ,;:")
    if cut.count("(") > cut.count(")"):
        cut = cut[:cut.rfind("(")].rstrip(" ,;:")
    return cut + "…"


def top_stories(run, root=""):
    items = _top_items(run)
    lis = []
    for it in items[:TOP_SHOWN]:
        text = _snippet(it)
        lis.append(f'<li><span class="rdate">{e(_story_date(it))}</span> {e(text)} {C.tag(it.get("rating"))}'
                   f'{" " if it.get("rating") else ""}{C.link(it.get("url"), "source", root)}</li>')
    total = sum(len(as_list(as_dict(g).get("items"))) for g in as_list(as_dict(run).get("roundup")))
    if run.get("analysis"):
        more = f'<a href="{e(C.href(run["analysis"], root))}#roundup">All {total} stories in today\'s analysis →</a>'
    elif run.get("report"):
        more = f'<a href="{e(C.href(run["report"], root))}#roundup">All {total} stories in today\'s report →</a>'
    else:
        more = ""
    if not lis:
        return '<p class="muted small">No top stories in the latest reading.</p>'
    return f'<ul class="plain hq-tops">{"".join(lis)}</ul>' + (f'<p class="small">{more}</p>' if more else "")


_PAREN_ID = re.compile(r"\s*\(([a-z0-9]+(?:-[a-z0-9]+)+)\)")


def _forecast_items(ev, forecasts):
    """Our forecasts an event names by id ("(openai-resume-by-oct31)"), each as '“{proposition}” (we said N%)', so a
    deadline never reads as news (ED19). [] when the event names none we can find."""
    byid = {f.get("id"): f for f in as_list(as_dict(forecasts).get("forecasts")) if isinstance(f, dict)}
    out = []
    for fid in _PAREN_ID.findall(str(ev.get("title") or "")):
        f = byid.get(fid)
        if not f or not f.get("question"):
            continue
        q = re.sub(r"\s+by\s+\w+\.? \d{1,2}, \d{4}\s*$", "", str(f["question"]).strip()).rstrip(".")
        q = re.sub(r"\s*\([^()]*\)", "", q)
        p = f" (we said {C.fmt(f['p'])}%)" if C.num(f.get("p")) is not None else ""
        out.append(f"“{C.clip_words(q, 12)}”{p}")
    return out


def _event_short(ev, forecasts=None):
    """The event's `short`, else its title up to the first ' (' or ';', at most 14 words."""
    if ev.get("short"):
        return str(ev["short"])
    t = re.split(r" \(|;", str(ev.get("title") or ""), maxsplit=1)[0]
    t = re.sub(r"^Forecast deadlines?:\s*", "", t)
    return C.clip_words(t, 14)


def coming_up(cal, after, n=DATES_SHOWN, forecasts=None):
    """The next n dated calendar.json events after `after` (forecast deadlines on one date merge into one line,
    read as ours; with forecasts.json each is quoted with our probability, ED19)."""
    evs = sorted((x for x in as_list(as_dict(cal).get("events"))
                  if isinstance(x, dict) and re.match(r"\d{4}-\d{2}-\d{2}$", str(x.get("date") or ""))
                  and str(x["date"]) > str(after or "")), key=lambda x: x["date"])
    rows = []
    for ev in evs:
        if ev.get("kind") == "forecast":
            items = _forecast_items(ev, forecasts) or [_event_short(ev)]
            same = next((r for r in rows if r["date"] == ev["date"] and r["forecast"]), None)
            if same:
                same["items"].extend(items)
                continue
            rows.append({"date": ev["date"], "forecast": True, "items": items})
        else:
            rows.append({"date": ev["date"], "forecast": False, "items": [_event_short(ev)]})
        if len(rows) > n:
            break
    out = []
    for r in rows[:n]:
        if r["forecast"]:
            k = len(r["items"])
            head = "Deadline for one of our forecasts" if k == 1 else f"Deadline for {C.NUM_WORDS.get(k, k)} of our forecasts"
            out.append((r["date"], f"{head}: {'; '.join(r['items'])}"))
        else:
            out.append((r["date"], r["items"][0]))
    return out


def _forecast_glance(fc):
    fs = [f for f in as_list(as_dict(fc).get("forecasts")) if isinstance(f, dict)]
    if not fs:
        return "Our checkable forecasts, scored when they resolve."
    open_ = [f for f in fs if f.get("outcome") is None]
    void = sum(1 for f in fs if f.get("outcome") == "void")
    resolved = sum(1 for f in fs if f.get("outcome") in (True, False))
    s = f"{len(fs)} forecasts: {len(open_)} open, {void} withdrawn, {resolved} resolved"
    nxt = min((str(f.get("deadline")) for f in open_ if f.get("deadline")), default=None)
    return s + (f"; next deadline {C.day(nxt, False)}." if nxt else ".")


def explore(data, run, alarm, fc, weekly):
    al = C.alarm_state({"alarm": alarm}, run)
    f = C.furthest(data) if C.ok_view(data) else None
    c = C.status_counts(data) if C.ok_view(data) else None
    n = len(data["components"]) if c else 8
    if c:
        agi = f"Not in public: {c['met']} of {n} parts met." + (f" Furthest behind: {str(f.get('short') or f['id']).lower()}." if f else "")
        if C.answer_text(data).startswith(("Yes", "Possibly")):
            agi = C.answer_text(data)
    else:
        agi = "What we mean by AGI, and how close each of its eight parts is."
    b = C.b_only(run)
    hid = f"Hidden AGI Index {C.fmt(run.get('index'))}%" + (
        ", mostly hidden self-improvement." if b is not None and b * 2 > (C.num(run.get("index")) or 0) else
        ": how a hidden system would show in our numbers.")
    met = [str(m) for m in al["met"]]
    on = (", on " + (", ".join(met[:-1]) + " and " + met[-1] if len(met) > 1 else met[0])) if met else ""
    alarm_t = f"Level {al['level']} · {al['name']}" + (f" since {C.day(al['since'], False)}" if al.get("since") else "") + on + "."
    wk = as_list(as_dict(weekly).get("wrapups"))
    wk = sorted((w for w in wk if isinstance(w, dict)), key=lambda w: str(w.get("date") or ""))
    week = (str(wk[-1].get("headline") or "The Friday wrap-up.") if wk else "The Friday wrap-up.")
    tiles = [
        ("agi.html", "Is AGI here?", agi),
        ("hidden.html", "Could it be hidden?", hid),
        ("alarm.html", "Fire alarm", alarm_t),
        ("scorecard.html", "Track record", _forecast_glance(fc)),
        ("weekly/", "This week", week),
        ("start-here.html", "How it works", "Three questions, three kinds of number, one rule-based alarm."),
    ]
    return "".join(f'<a class="card" href="{u}"><strong>{e(t)}</strong><span>{e(s)}</span></a>' for u, t, s in tiles)


def render(root_dir=None):
    """The homepage body (between the nav and the appended subscribe box)."""
    load = lambda rel: C.load_json(rel, root_dir)  # noqa: E731
    runs = load("data/runs.json")
    run = C.newest(runs) or {}
    prev = C.prev_published(runs, run) if run else None
    data = C.load_components(root_dir)
    alarm, esc = load("data/alarm.json"), load("data/escape.json")
    cal, fc, weekly = load("data/calendar.json"), load("data/forecasts.json"), load("data/weekly/index.json")
    date = run.get("date")
    reading = f" Reading of {C.day(date)}." if date else ""
    dates = "".join(f'<li><span class="when">{e(C.day(d, False))}</span><span>{e(t)}</span></li>'
                    for d, t in coming_up(cal, date, forecasts=fc))
    from sitekit import subscribe_box
    return f"""  <header class="hq-head">
    <h1>Hidden AGI watch</h1>
    <p class="lede">Could advanced AI already exist, or be acting, without the public knowing? <span class="hq-hide-m">We check every day.{e(reading)}</span></p>
  </header>
  {C.method_banner(run, prev)}
  {C.card_agi(data, run, prev, "", {"card": "agi-now", "q": "q1"})}
  {C.card_hidden(run, prev, "", {"card": "gauges", "q": "q2"})}
  {C.card_alarm({"alarm": alarm, "escape": esc}, run, "", {"card": "alarm", "q": "q3", "signals": "tripwires", "escape": "escape"})}
  {subscribe_box()}
  <section class="hq-below" id="roundup" aria-labelledby="top-h">
    <h2 id="top-h" class="hq-h2">Top stories</h2>
    {top_stories(run)}
  </section>
  <section class="hq-below" id="coming" aria-labelledby="cu-h">
    <h2 id="cu-h" class="hq-h2">Coming up</h2>
    {f'<ul class="timeline-list hq-cal">{dates}</ul>' if dates else '<p class="muted small">No dated events ahead.</p>'}
    <p class="small"><a href="calendar.html">Full calendar →</a></p>
  </section>
  <section class="hq-below" aria-labelledby="ex-h">
    <h2 id="ex-h" class="hq-h2">Explore</h2>
    <div class="cards">{explore(data, run, alarm, fc, weekly)}</div>
    <p class="small"><a href="archive.html">Every reading →</a></p>
  </section>"""


PAGE = dict(title=TITLE, description=DESCRIPTION, body=render, scripts_code="", head_extra=HEAD_EXTRA)
