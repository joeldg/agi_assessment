#!/usr/bin/env python3
"""Build every generated page that isn't a daily report or a weekly wrap-up, from one page shell.

    python3 scripts/build_pages.py

Two kinds of page:
  - The hubs built by the page modules in scripts/pages/ (redesign v2): index.html (Today), agi.html (Is AGI
    here?), hidden.html (Could it be hidden?), changes.html (Changes and corrections) and archive.html (Every
    reading). They are rendered server-side from the newest published reading and data/*.json.
  - The standing pages below. Most charts on them render in the browser from data/*.json; each page's
    at-a-glance line and these parts are written at build time instead, so they read without JavaScript and
    can go stale until the next build (the daily and the weekly routines run this script):
      start-here.html: the numbers diagram (#pieces) and naming key (#names), from the newest reading,
        data/agi_components.json, alarm.json and escape.json; the method and corrections line;
      alarm.html: the fire-alarm criteria, condition statuses, the signals board (#signals, from the newest
        reading), the Level-3 proof standard, the case-file standard, history and changelog;
      escape.html: Escape watch, from data/escape.json;
      about.html: the corrections stub and the weekly usage line (data/usage.json, once a full week is logged);
      the glance lines on scorecard, trends, money, disclosure-lag, agi-claims, calendar and steelman.
Every page is rendered before any file is written, so a bad data/alarm.json or data/escape.json stops the
build without leaving a blank page. A missing or malformed data/agi_components.json does not stop it: the
AGI parts show as unavailable (with a WARN) and every other page builds.
"""
import json
import re
import sys
from datetime import date
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sitekit import HYP_LABELS, REPO, SIGNAL_STATUS, display_words, page, safe_url, signal_view  # noqa: E402
import pages  # noqa: E402
from pages import common as C  # noqa: E402
from pages.changes import glance as changes_glance  # noqa: E402
from pages.home import coming_up, _forecast_glance  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Shared by every page module: fetch JSON, data-driven links (http(s) or site paths only), dates, stat
# tiles, METR model ids as readable names, and byId, which logs a missing element instead of throwing, so
# one missing id never stops a page's later charts from drawing.
PREAMBLE = r"""import * as K from "{root}assets/charts.js";
const j = p => fetch(p,{cache:"no-cache"}).then(r => { if(!r.ok) throw new Error(p + ": HTTP " + r.status); return r.json(); });
const link = (u, text, root="") => { const href = K.util.safeHref(u, root); if(!href) return null; return K.util.h("a", /^https?:/i.test(href) ? {href, target:"_blank", rel:"noopener"} : {href}, text); };
const fd = (d, o={day:"numeric",month:"short",year:"numeric"}) => K.util.fmtDate(d, o);
const tile = (label, value, sub) => { const t = K.util.h("div",{class:"tile"}); t.append(K.util.h("div",{class:"label"},label), K.util.h("div",{class:"value"},String(value))); if(sub) t.append(K.util.h("div",{class:"delta muted"},sub)); return t; };
const modelName = id => String(id||"").replace(/_inspect$/,"").replace(/_early$/," (early)").replace(/_/g," ").replace(/\b(gpt|o\d)\b/gi,s=>s.toUpperCase()).replace(/\bclaude\b/i,"Claude").replace(/\bgemini\b/i,"Gemini").replace(/\b(mythos|opus|sonnet|haiku|preview|pro|flash)\b/gi,s=>s.charAt(0).toUpperCase()+s.slice(1));
const usd = v => v != null && v !== "" && Number(v) === 0 ? "$0" : K.fmtUSDb(v);   // money axes start at $0, not $0.0B
const byId = id => { const el = document.getElementById(id); if(!el) console.error("Missing #" + id + " on this page; that part was skipped."); return el; };"""


def module(root, code):
    return f'<script type="module">\n{PREAMBLE.replace("{root}", root)}\n{code}\n</script>'


# ---------- helpers for pages rendered at build time ----------
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
NUM_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
             10: "ten", 11: "eleven", 12: "twelve"}


def day(s):
    """'2026-09-29' -> '29 Sep 2026'; anything else comes back as given ('–' when empty)."""
    try:
        d = date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return str(s) if s else "–"
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def e(s):
    return escape("" if s is None else str(s))


def a_link(u, text):
    """A link from data, or '' when the URL isn't http(s) or a site path. New tab only for absolute URLs."""
    href = safe_url(u)
    if not href:
        return ""
    new_tab = ' target="_blank" rel="noopener"' if urlsplit(href).scheme else ""
    return f'<a href="{escape(href, quote=True)}"{new_tab}>{e(text)}</a>'


LABS = ("anthropic.com", "openai.com", "deepmind.google", "deepmind.com", "blog.google", "x.ai", "ai.meta.com",
        "microsoft.com", "mistral.ai")
EVALUATORS = ("metr.org", "aisi.gov.uk", "apolloresearch.ai", "epoch.ai", "transluce.org")
PRESS = ("reuters.com", "bloomberg.com", "politico.com", "politico.eu", "fortune.com", "nbcnews.com", "thenextweb.com",
         "coindesk.com", "ft.com", "wsj.com", "nytimes.com", "washingtonpost.com", "axios.com", "theverge.com",
         "wired.com", "techcrunch.com", "cnbc.com", "apnews.com", "bbc.com", "bbc.co.uk", "theguardian.com",
         "securityweek.com", "bleepingcomputer.com", "siliconangle.com", "theinformation.com", "semafor.com", "time.com",
         "abc.net.au", "arstechnica.com", "theregister.com", "404media.co")


def source_type(u):
    """What kind of source a link is, where the host makes that clear; '' otherwise."""
    href = safe_url(u)
    if not href:
        return ""
    host = (urlsplit(href).hostname or "").lower()
    if not host:
        return "this site"

    def on(domains):
        return any(host == d or host.endswith("." + d) for d in domains)
    if on(("sec.gov",)):
        return "primary source: SEC filing"
    if on(EVALUATORS):
        return "primary source: evaluator"
    if on(LABS):
        return "primary source: lab"
    if host.endswith((".gov", ".mil")) or on(("gov.uk", "gov.au", "europa.eu", "gc.ca")):
        return "primary source: government"
    if on(("arxiv.org",)):
        return "research paper"
    if on(PRESS):
        return "press report"
    return ""


def load_json(rel):
    try:
        return json.loads((ROOT / rel).read_text())
    except (OSError, ValueError):
        return None


def as_list(v):
    return v if isinstance(v, list) else []


def as_dict(v):
    return v if isinstance(v, dict) else {}


def newest_run():
    """The newest published reading (the one the homepage shows), or {}."""
    return C.newest(load_json("data/runs.json")) or {}


def latest_run_date():
    return newest_run().get("date") or None


def short_day(s):
    """'2026-10-05' -> 'Oct 5' (the site's short form in glance lines)."""
    return C.day(s, False) if s else ""


def fold(fid, title, body, h="h2", summary_note=""):
    """A collapsed section whose <details> carries the anchor (charts.js openHashTarget opens it from a hash;
    with no JavaScript the summary line is still at the anchor). The heading sits inside the summary so
    heading navigation still reaches it."""
    note = f' <span class="muted small" style="font-weight:400">{summary_note}</span>' if summary_note else ""
    id_attr = f' id="{e(fid)}"' if fid else ""
    return (f'<details{id_attr}><summary><{h} style="display:inline">{title}</{h}>{note}</summary>'
            f'<div class="body">{body}</div></details>')


def glance(html):
    """The at-a-glance line at the top of a standing page (spec 2.2): ink, bold, one line."""
    return f'<p class="glance"><strong>{html}</strong></p>' if html else ""


def corrections():
    """data/corrections.json, newest first (a list, or {"corrections": [...]})."""
    co = load_json("data/corrections.json")
    cs = co.get("corrections") if isinstance(co, dict) else co
    cs = [c for c in as_list(cs) if isinstance(c, dict)]
    return sorted(cs, key=lambda c: str(c.get("date") or ""), reverse=True)


def changes_line():
    """'Method v2.0 (Oct 5) · alarm criteria v1.2 · 43 corrections, newest Oct 2', from the change log's own glance."""
    return changes_glance(load_json("data/method.json"), load_json("data/alarm.json"), corrections())


FLOOR_CHIP = ('<a href="disclosure-lag.html#floor"><abbr class="chip" title="Incidents nobody found can&#39;t be counted, '
              'so this is a minimum">floor</abbr></a>')

# The evidence-ratings legend (the one home is start-here.html#method), with the two chips redesign v2 adds.
RATINGS_LEGEND = """<li><strong>Evidence ratings:</strong> every factual claim links its source and carries one of these chips:
        <ul class="plain">
          <li><span class="tag fact">verified fact</span> a primary source (a filing, a lab or evaluator, a government), or two independent credible outlets that we opened.</li>
          <li><span class="tag report">credible report</span> a credible outlet's report not yet confirmed that way, including leaked documents and single anonymously sourced reports.</li>
          <li><span class="tag opinion">expert opinion</span> a named expert's or organisation's judgment or forecast.</li>
          <li><span class="tag agg">forecast aggregate</span> a crowd or market figure such as a Metaculus median or a Kalshi price; it reports what forecasters think, not a fact about AI.</li>
          <li><span class="tag ours">our inference</span> our own reasoning from the cited sources, not a claim any source makes; until now inferences carried no chip, and a fact chip followed by '(part our inference)' marks a sentence that mixes the two.</li>
          <li><span class="tag spec">speculation</span> a possibility no evidence yet supports, labelled so it is never mistaken for evidence.</li>
        </ul>
        A short qualifier in parentheses after a chip, such as <span class="tag fact">verified fact</span> <span class="muted">(lab's own evaluation)</span>, says what kind of fact it is; hover or tap the chip for the full note.</li>"""


# ---------- Start here ("How it works") ----------
def pieces_section():
    """#pieces (the numbers diagram, spec 7.1-7.2) and #names (the naming key, 7.3): the one home of how our
    numbers fit together, from the newest reading and the live files."""
    run = newest_run()
    data = C.load_components()
    alarm = as_dict(load_json("data/alarm.json"))
    esc = as_dict(load_json("data/escape.json"))
    trends, ext = load_json("data/trends.json"), load_json("data/external_forecasts.json")
    return f"""<section id="pieces" aria-labelledby="pieces-h" class="fit">
    <h2 id="pieces-h">How our numbers fit together</h2>
    {C.fit_diagram(data, run, alarm, esc, root="", trends=trends, external=ext)}
    <h3 id="names">What each number means</h3>
    {C.names_table(data, run, alarm, escape=esc, trends=trends, jobs=load_json("data/jobs/claims.json"))}
  </section>"""


HYP_GLOSS = {   # one line each; the canonical definitions live in agi_components.json and on hidden.html#hypotheses
    "A": "AGI kept from the public",
    "B": "AI builds its successor, undisclosed; needs no AGI",
    "C": "AGI acting unseen online",
    "D": "AGI covertly shaping a government decision",
    "Dopen": "the same, openly; outside the Index",
}


def level_html(al):
    """'◐ Level 1 · Watch' (the icon in its level's status colour, the words in ink), or '' with no level."""
    if not al or al.get("level") is None:
        return ""
    return (f'<span class="ico-{e(al.get("status"))}" aria-hidden="true">{e(al.get("icon"))}</span> '
            f'Level {e(al["level"])} · {e(al.get("name"))}')


def alarm_level_text(A):
    """'◐ Level 1 · Watch' from alarm.json, or '' when unreadable."""
    return level_html(C.alarm_state({"alarm": as_dict(A)}))


def start_here_body():
    run = newest_run()
    A = as_dict(load_json("data/alarm.json"))
    level = alarm_level_text(A)
    hyps = "".join(f'<li><strong>{"D-open" if k == "Dopen" else k}</strong> {e(HYP_LABELS[k])}: {e(HYP_GLOSS[k])}.</li>'
                   for k in ("A", "B", "C", "D", "Dopen"))
    idx = C.fmt(run.get("index")) if run.get("index") is not None else ""
    idx_txt = f" Today {idx}%." if idx else ""
    return f"""
  <header class="prose">
    <h1>How Hidden AGI watch works</h1>
    <p class="lede">Three questions, three kinds of number, one rule-based alarm. Every day a custom AI agent checks whether advanced AI could exist, or be acting, without the public knowing, and publishes sourced probabilities and a fire-alarm level.</p>
  </header>
  {pieces_section()}
  <section class="prose">
    <h2 id="agi-bar">What we mean by AGI</h2>
    <p>Our definition and its eight parts: <a href="agi.html">Is AGI here? →</a></p>
  </section>
  <section class="prose">
    <h2 id="hypotheses">The hidden scenarios</h2>
    <ul class="plain">{hyps}</ul>
    <p class="small"><a href="hidden.html#hypotheses">Definitions and odds →</a></p>
  </section>
  <section class="prose">
    <h2 id="index">The Hidden AGI Index</h2>
    <p>The chance that at least one of A–D is true today.{e(idx_txt)} <a href="hidden.html#index">How it's derived →</a></p>
  </section>
  <section class="prose">
    <h2 id="hidden">What "hidden" means</h2>
    <p>Kept from the public for at least 30 days, by its builders or by the system itself.</p>
    <details><summary>More</summary><div class="body">
      <p>A–D track two kinds of hiding: advanced AI that people keep from the public (a company or government that doesn't disclose what it has built, or how it's using it), and AI systems acting covertly on their own (C's rogue path). A, B and C use the same secrecy window: kept from the public for at least 30 days. Admitting that an unreleased model exists doesn't count as disclosure.</p>
      <p>A model hiding its own capability from its developer, for example by quietly underperforming on tests, is a different problem. It isn't A, because A needs the builder to know what it has, but it would undermine the evaluations these readings rely on, so we track it as the evaluation-integrity signal on the <a href="alarm.html#signals">fire alarm's signal board</a>.</p>
    </div></details>
  </section>
  <section class="prose">
    <h2 id="gauges">The five hiding-conditions gauges</h2>
    <ul class="plain">
      <li><strong>Capability gap</strong> (estimated): unreleased models' lead; in A's formula.</li>
      <li><strong>AI doing AI research</strong> (measured): a lab's AI-led share of its R&amp;D.</li>
      <li><strong>Oversight gap</strong> (estimated): how long agent incidents stayed hidden; a {FLOOR_CHIP}.</li>
      <li><strong>Money trail</strong> (measured): Big Tech's capital spending, last 12 months.</li>
      <li><strong>Delegation to AI</strong> (assessed): government decisions run through AI, on five rungs.</li>
    </ul>
    <p class="small muted">Context for our odds, not alarm conditions. <a href="hidden.html#gauges">Values →</a></p>
  </section>
  <section class="prose">
    <h2 id="alarm">The fire alarm</h2>
    <p>Set by published conditions, never by our odds.{f" Today: {level}." if level else ""} <a href="alarm.html">Conditions →</a></p>
  </section>
  <section class="prose">
    <h2 id="sending">What gets sent</h2>
    <p>Daily and weekly emails go out automatically; a person approves every alarm alert. <a href="about.html#sending">More →</a></p>
  </section>
  <section class="prose">
    <h2 id="method-h">How the numbers are made</h2>
    {fold("method", "The method in full", METHOD_BODY, h="span", summary_note="rounding, evidence ratings, signals")}
  </section>
  <section class="prose">
    <h2 id="honesty">Honesty notes</h2>
    <ul>
      <li>A custom AI agent does the work; method and sources are public.</li>
      <li>The probabilities are subjective.</li>
      <li>An absence of evidence is not proof of secrecy.</li>
      <li>Calibration isn't shown yet: see the <a href="scorecard.html">scorecard</a>.</li>
      <li>Readings freeze once emailed; fixes are dated corrections.</li>
    </ul>
  </section>
  <section class="prose">
    <h2 id="changes">Changes and corrections</h2>
    <p><a href="changes.html">{e(changes_line()) or "The method log and every correction"} →</a></p>
    <p><a class="btn" href="./">Go to today's reading</a></p>
  </section>
"""


METHOD_BODY = """<ul class="plain">
      <li><strong>Daily:</strong> a custom AI agent, built for this project, searches the news, research, lab system cards and independent evaluations such as METR, Epoch AI and the AI Security Institutes. It then reassesses each probability today, by end-2030 and by end-2035, and publishes a short report and a full analysis automatically. The analysis shows the reasoning: base rates, the strongest case on each side, and what would change our mind.</li>
      <li><strong>What the horizons mean:</strong> today = true now. By end-2030 / by end-2035 = true at any point before 1 Jan 2031 / 1 Jan 2036 (cumulative, so never below today).</li>
      <li><strong>Rounding:</strong> estimates move in 0.1-point steps below 1%, 0.5-point steps from 1% to 10%, and whole points above 10%, rounded half up. Finer steps would claim more precision than these judgments have.</li>
      """ + RATINGS_LEGEND + """
      <li><strong>Signals:</strong> the tripwires and Escape watch indicators, the specific, observable signals that would move the numbers most. Each reads Quiet, Open or Confirmed, and names the alarm condition it feeds where there is one. They move our probabilities; only the alarm conditions set the alarm level.</li>
      <li><strong>Forecast chart:</strong> <a href="hidden.html#odds">Could it be hidden?</a> draws our stated numbers (today, by end-2030, by end-2035) with outside forecasts for comparison. We don't project our daily line forward. Our end-2030 and end-2035 numbers should move only on evidence, never in a predictable direction; our numbers for today are expected to rise over time along that forecast. The shaded band is a judgment range, not a statistical interval: roughly how far our number could plausibly move as new evidence arrives, wider when our confidence is lower. <a href="trends.html">Trend watch</a> projects <em>measured</em> trends instead, such as how long a task AI can finish on its own.</li>
      <li><strong>Method changes:</strong> a change of definitions re-derives our numbers and is labelled a method change, never news. Readings and forecasts made under earlier definitions keep their meaning and resolve under them. Every change is on <a href="changes.html#method">Changes and corrections</a>.</li>
      <li><strong>What moved the needle:</strong> each day names the one development that changed an estimate most, or says plainly that it was a quiet day.</li>
      <li><strong>Weekly (Fridays, 3pm Pacific):</strong> a wrap-up with the week's key numbers and graphs, plus the <a href="scorecard.html">forecast scorecard</a>, <a href="disclosure-lag.html">disclosure lag</a>, <a href="agi-claims.html">AGI claims</a>, <a href="calendar.html">calendar</a> and <a href="steelman.html">steelman</a>.</li>
    </ul>"""

START_HERE_TOP = ('<a href="#pieces">How our numbers fit</a><a href="#names">What each number means</a>'
                  '<a href="#hypotheses">Scenarios</a><a href="#gauges">Gauges</a><a href="#method">Method</a>'
                  '<a href="#honesty">Honesty</a>')

PAGES = {}

PAGES["start-here.html"] = dict(
    title="How Hidden AGI watch works",
    description="Three questions, three kinds of number, one rule-based alarm: how Hidden AGI watch's numbers fit together, what each one means, and how the daily and weekly readings are made.",
    body=start_here_body,
    nav_top=START_HERE_TOP,
)

# ---------- About ----------
EFFORT_LINE = ("Before launch, we had 195 AI agents run 3,793 checks on this site's own facts, code and reasoning. "
               "It found 135 problems, and we fixed them.")   # owner-approved wording; keep it exactly true
USAGE_PLAN = "a Claude Max 20x plan"   # the owner approved naming the plan in the usage line only
FRIDAY = 4   # the plan's weekly usage resets on Fridays around 11:00 Pacific, after the morning reading


def _usage_readings(U):
    """[(date, percent)] from data/usage.json: a list, or {"readings": [...]}, of {date, percentUsed}
    (an ISO timestamp in "at" or "recordedAt" also works for the date)."""
    rows = U.get("readings") if isinstance(U, dict) else U
    out = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        pct = next((r[k] for k in ("percentUsed", "weeklyPercentUsed", "percent", "pct") if _num(r.get(k))), None)
        when = next((r[k] for k in ("date", "at", "recordedAt", "time") if r.get(k)), None)
        try:
            d = date.fromisoformat(str(when)[:10])
        except ValueError:
            continue
        if pct is not None and 0 <= pct <= 100:
            out[d] = pct   # one reading per day; a rerun's later value replaces an earlier one
    return sorted(out.items())


def weekly_usage_line():
    """The last full week's usage, as HTML, or '' until data/usage.json has a full week of readings.
    A week runs from the Saturday after one reset to the Friday morning before the next, so a full
    week is seven daily readings, Saturday to Friday. The Friday reading, the last before the reset,
    stands for the week's total."""
    readings = _usage_readings(load_json("data/usage.json"))
    weeks = {}
    for d, pct in readings:
        ends = date.fromordinal(d.toordinal() + (FRIDAY - d.weekday()) % 7)
        weeks.setdefault(ends, {})[d] = pct
    full = [(ends, days) for ends, days in weeks.items() if len(days) >= 7 and ends in days]
    if not full:
        return ""
    ends, days = max(full)
    pct = days[ends]
    shown = f"{pct:.0f}" if pct >= 10 or pct == int(pct) else f"{pct:.1f}"
    return (f'\n    <p id="usage">In the week to {e(day(ends.isoformat()))}, researching, writing and publishing the readings '
            f'used {e(shown)}% of the weekly allowance of {e(USAGE_PLAN)}.</p>')


def corrections_stub():
    """about.html#corrections: the count, the three newest and a link to the one full log (changes.html)."""
    cs = corrections()
    if not cs:
        return '<p class="muted">No corrections so far. The full log will be on <a href="changes.html#corrections">Changes and corrections</a>.</p>'
    items = "".join(
        f'<li><strong>{e(short_day(c.get("date")) or "Undated")}</strong> · {e(str(c.get("item") or c.get("now") or "").rstrip("."))}.'
        + (f' {a_link(c.get("page"), "Affected page")}' if c.get("page") else "") + "</li>" for c in cs[:3])
    n = len(cs)
    return (f'<p>{n} correction{"s" if n != 1 else ""} so far. The newest:</p><ul class="plain">{items}</ul>'
            f'<p><a href="changes.html#corrections">The full log →</a></p>')


def about_body():
    cite = (f'<p>Hidden AGI watch (2026), &lt;page title&gt;, &lt;url&gt;, accessed &lt;date&gt;. Licensed under CC BY 4.0.</p>'
            f'<p class="muted">For example: Hidden AGI watch (2026), The fire alarm, <span style="overflow-wrap:anywhere">{escape("https://hiddenagi.com/alarm.html")}</span>, accessed <span id="cite-date">&lt;date&gt;</span>. Licensed under CC BY 4.0. Daily reports keep their address (reports/YYYY-MM-DD.html), and the data behind every chart is in the repository\'s data folder, with its full history. A machine-readable citation is in <a href="{REPO}/blob/main/CITATION.cff">CITATION.cff</a>.</p>')
    lic = f"""<ul class="plain">
      <li><strong>Code:</strong> the scripts, the chart kit, the stylesheet and the page templates are under the <a href="{REPO}/blob/main/LICENSE">MIT License</a>.</li>
      <li><strong>The site's own text and data:</strong> the reports, readings, rulings, alarm criteria, Escape watch indicators and our own data files are under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. You can reuse and adapt them, commercially too, with credit and a link to the license.</li>
      <li><strong>Not covered:</strong> third-party material we quote, cite or plot (news excerpts, filings, METR measurements, outside forecasts, market prices and the like) stays under its owners' terms, and the brand assets (the name and wordmark, the avatar and logo, the favicon and the default share image) are all rights reserved. The details are in <a href="{REPO}/blob/main/LICENSE-content.md">LICENSE-content.md</a>.</li>
    </ul>"""
    return f"""
  <header class="prose">
    <h1>About Hidden AGI watch</h1>
    <p class="lede">A fire alarm for hidden AI: a daily, sourced reading of whether advanced AI could already exist, or already be acting, without the public knowing.</p>
  </header>
  <section class="prose">
    <h2 id="what">What this is</h2>
    <p>Each day we answer three questions: is AGI here, could it be hidden, and should you worry today? The answers are sourced probabilities, a tracker of the eight parts of AGI, an <a href="escape.html">Escape watch</a> on the resource chokepoints, and a fire alarm set by published rules. An absence of evidence is not treated as proof of secrecy.</p>

    <h2 id="how">How it's made</h2>
    <p>A custom AI agent built for this project researches, writes and publishes each daily reading automatically. The research starts each morning and the email goes out at 10am Pacific, or as soon as it is ready if later. No one reviews a daily report before it's published. The Friday wrap-up is made the same way and emailed at 3pm Pacific. The owner sets the definitions and the fire-alarm thresholds.</p>
    <p>{e(EFFORT_LINE)}</p>{weekly_usage_line()}
    <p>The method is on <a href="start-here.html">How it works</a>, the alarm criteria on <a href="alarm.html">Fire alarm</a>, and every chart follows the <a href="style.html">chart style guide</a>.</p>

    <h2 id="sending">What gets sent, and who approves it</h2>
    <p>The daily issue and the Friday wrap-up are emailed automatically, and neither is held back when the alarm level changes: they go out and show the new level. A breaking fire-alarm alert is different: it's prepared as a draft, and a person approves it before it's sent.</p>

    <h2 id="who">Who runs it</h2>
    <p>Hidden AGI watch is an independent project run by <a href="https://github.com/joeldg">joeldg</a> on GitHub. The code, the data files and the history of every page are public at <a href="{REPO}">github.com/joeldg/agi_assessment</a>.</p>

    <h2 id="contact">Contact</h2>
    <p>To report an error, question a number or suggest a source, open an issue on <a href="{REPO}/issues">GitHub Issues</a>. That's the only contact channel, so every report and its answer stay public.</p>

    <h2 id="corrections">Corrections</h2>
    <p>Past readings are frozen once emailed; corrections are dated, shown on the affected page and carried into the next email.</p>
    {corrections_stub()}

    {fold("license", "License", lic)}
    {fold("cite", "How to cite", cite)}
  </section>
"""


PAGES["about.html"] = dict(
    title="About · Hidden AGI watch",
    description="What Hidden AGI watch is, how it's made, who runs it, how to reach us, how corrections work, the license, and how to cite it.",
    body=about_body,
    scripts_code=r"""
{ const c = byId("cite-date"); if(c) c.textContent = new Date().toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric"}); }
""",
)

# ---------- Track record (scorecard) ----------
def scorecard_body():
    fc = load_json("data/forecasts.json")
    run = newest_run()
    nxt = coming_up(load_json("data/calendar.json"), run.get("date"), 1)
    nxt_txt = f"Next: {short_day(nxt[0][0])}, {nxt[0][1]}" if nxt else "Dated events that could move the numbers."
    words = nxt_txt.split()
    if len(words) > 16:
        nxt_txt = " ".join(words[:16]).rstrip(",;:") + "…"
    cl = changes_line()
    return f"""
  <header class="prose">
    <h1>Track record</h1>
    <p class="lede">Are our forecasts any good? These are short-range, checkable forecasts, each with a deadline and a resolution rule, scored in public when they resolve. The A–D probabilities can't resolve, so this is how you can check our judgment.</p>
    {glance(e(_forecast_glance(fc)))}
  </header>
  <div class="cards">
    <a class="card" href="calendar.html"><strong>Coming up</strong><span>{e(nxt_txt)}</span></a>
    <a class="card" href="steelman.html"><strong>Weekly steelman</strong><span>The strongest case against our numbers, every Friday.</span></a>
    <a class="card" href="changes.html"><strong>Changes and corrections</strong><span>{e(cl) or "Every method change and correction."}</span></a>
  </div>
  <div class="tiles" id="tiles"></div>
  <section><h2>Open forecasts</h2><p class="muted small">The amber bar is our probability; a hollow ring marks prediction-market odds where a comparable market exists.</p><noscript><p class="muted small">The forecast lists are drawn with JavaScript. Without it, every forecast, with its probability, deadline and resolution rule, is in <a href="data/forecasts.json">data/forecasts.json</a>.</p></noscript><div id="open"></div></section>
  <section><h2>Calibration</h2><p class="muted small">The chart appears once 15 forecasts have resolved.</p><div class="chart-wrap"><div id="calib"></div></div></section>
  <section><h2>Resolved</h2><div id="resolved"></div></section>
  <section id="withdrawn-sec" hidden><h2>Withdrawn forecasts</h2><p class="muted">Withdrawn forecasts aren't scored. Each shows why it was withdrawn.</p><div id="withdrawn"></div></section>
  <section class="prose">{fold("scoring", "How scoring works", '''
    <p>Each resolved forecast scores (probability − outcome)², where the outcome is 1 or 0. The Brier score is the average: 0 is perfect, and always guessing 50% scores 0.25. A raw Brier score depends on how predictable the questions were, so we also show a skill score against always forecasting the base rate of the resolved questions (above 0 beats it), and, where a prediction market priced the same question, the market's Brier score on those same questions. Every score shows how many forecasts it rests on; a handful proves little.</p>
    <p>When we say 70%, it should happen about 70% of the time. The calibration chart waits for 15 resolved forecasts, because a group of one or two would read 0% or 100% by chance; it then groups them into three bins (five once 40 have resolved), each with its count and a 90% interval, and points near the diagonal are well calibrated.</p>
    <p>New forecasts are added in each weekly wrap-up, and nothing is edited after it's made; if a forecast's stated context turns out to be wrong we add a dated correction and still score the original probability. Ill-posed forecasts can be withdrawn unscored; the reason is always shown. How we round and rate evidence: <a href="start-here.html#method">Method</a>.</p>''')}</section>
"""


PAGES["scorecard.html"] = dict(
    title="Track record · Hidden AGI watch",
    description="Are our forecasts any good? Short-range, checkable forecasts about AI, scored in public with the Brier score when they resolve.",
    body=scorecard_body,
    scripts_code=r"""
const d = await j("data/forecasts.json"), h = K.util.h;
const all = (Array.isArray(d.forecasts) ? d.forecasts : []).filter(f => f && typeof f === "object");
const isVoid = f => f.outcome === "void" || f.void === true || f.withdrawn === true;
const scored = all.filter(f => f.outcome === true || f.outcome === false);
const withdrawn = all.filter(isVoid);
const open = all.filter(f => f.outcome == null && !isVoid(f)).sort((a,b)=>String(a.deadline).localeCompare(String(b.deadline)));
const n = scored.length, b = K.brier(scored), bss = K.brierSkill(scored), mp = K.marketPaired(scored);
const next = open.map(f=>f.deadline).filter(Boolean).sort()[0];
const tiles = byId("tiles");
if(tiles){
  tiles.append(tile("Open forecasts", open.length));
  tiles.append(tile("Resolved and scored", n));
  tiles.append(tile("Brier score", b==null ? "–" : b.toFixed(3), n ? `n = ${n}; lower is better` : "after the first forecast resolves"));
  if(n >= 1){
    tiles.append(tile("Skill vs base rate", bss==null ? "–" : (bss>0?"+":"") + bss.toFixed(2), bss==null ? "needs both outcomes among the resolved" : `n = ${n}; above 0 beats the base rate`));
    tiles.append(tile("Ours vs market", mp.n ? `${mp.ours.toFixed(3)} vs ${mp.market.toFixed(3)}` : "–", mp.n ? `Brier on the ${mp.n} question${mp.n>1?"s":""} with a market price` : "no resolved question had a market price"));
  }
  if(withdrawn.length) tiles.append(tile("Withdrawn", withdrawn.length, "not scored"));
  tiles.append(tile("Next deadline", next ? fd(next) : "–"));
}
{ const o = byId("open"); if(o) K.forecastBars(o, open, {compact: true}); }
const calib = byId("calib");
if(calib) K.live(calib, () => K.calibration(calib, scored));
const r = byId("resolved");
if(r && !n) r.append(h("p",{class:"empty"}, next ? "Nothing has resolved yet. The first deadline is " + fd(next,{day:"numeric",month:"long",year:"numeric"}) + "." : "Nothing has resolved yet."));
else if(r) {
  const wrap = h("div",{class:"table-wrap"}), t = h("table");
  const hr = h("tr"); ["Forecast","Made","Resolves YES if","Ours","Outcome","Score","Corrections"].forEach(c=>hr.append(h("th",{scope:"col"},c))); t.append(hr);
  [...scored].sort((a,b)=>String(b.resolved||b.deadline).localeCompare(String(a.resolved||a.deadline))).forEach(f => {
    const tr = h("tr");
    tr.append(h("td",{}, f.question || "–"), h("td",{class:"num"}, f.made ? fd(f.made) : "–"), h("td",{class:"small"}, f.resolution || "–"), h("td",{class:"num"}, f.p + "%"));
    tr.append(h("td",{}, (f.outcome ? "Yes" : "No") + (f.resolved && !isNaN(new Date(f.resolved)) ? ", " + fd(f.resolved) : "")));
    tr.append(h("td",{class:"num"}, Math.pow(Number(f.p)/100 - (f.outcome===true?1:0), 2).toFixed(3)));
    const cc = h("td",{class:"small"}), cs = (Array.isArray(f.corrections) ? f.corrections : []).filter(Boolean);
    if(!cs.length) cc.textContent = "–";
    cs.forEach(c => { const line = h("div",{}, (c.date ? fd(c.date) + ": " : "") + (typeof c === "string" ? c : (c.text || ""))); const a = link(c.url, "source"); if(a) line.append(" ", a); cc.append(line); });
    tr.append(cc); t.append(tr);
  });
  wrap.append(t); r.append(wrap);
}
const wsec = byId("withdrawn-sec"), wbox = byId("withdrawn");
if(withdrawn.length && wsec && wbox){
  wsec.hidden = false;
  const ul = h("ul",{class:"plain"});
  const when = f => { const w = f.withdrawnOn || f.resolved; return w && !isNaN(new Date(w)) ? " " + fd(w) : ""; };
  const reason = f => String(f.voidReason || f.void_reason || f.withdrawnReason || "no reason recorded").trim().replace(/[.]+$/,"");
  const why = f => { const r = reason(f); return /^withdrawn\b/i.test(r) ? r + "." : "Withdrawn" + when(f) + ", unscored. Reason: " + r + "."; };   // a reason may already say when
  withdrawn.forEach(f => { const li = h("li"); li.append(h("strong",{}, f.question || "–")); li.append(h("div",{class:"small"}, why(f))); li.append(h("div",{class:"muted small"}, (f.made ? `Made ${fd(f.made)} at ${f.p}%` : `${f.p}%`) + (f.deadline ? `; deadline ${fd(f.deadline)}.` : "."))); ul.append(li); });
  wbox.append(ul);
}
""",
)

# ---------- Disclosure lag ----------
def _days(a, b):
    try:
        return (date.fromisoformat(str(b)[:10]) - date.fromisoformat(str(a)[:10])).days
    except (TypeError, ValueError):
        return None


def _median(xs):
    s = sorted(x for x in xs if x is not None)
    k = len(s)
    if not k:
        return None
    return s[(k - 1) // 2] if k % 2 else (s[k // 2 - 1] + s[k // 2]) / 2


def lag_stats():
    """The disclosure-lag figures charts.js lagChart computes, server-side, for the glance line:
    {n, mid, lo, hi, others} or None. Same rule: lag from `occurred` to `disclosed`, the window ends from
    occurredFrom/occurredTo, made public by others when foundBy isn't the lab."""
    d = as_dict(load_json("data/incidents.json"))
    rows = []
    for i in as_list(d.get("incidents")):
        if not isinstance(i, dict):
            continue
        lag = _days(i.get("occurred"), i.get("disclosed"))
        if lag is None:
            continue
        lo = _days(i["occurredTo"], i["disclosed"]) if i.get("occurredTo") else lag
        hi = _days(i["occurredFrom"], i["disclosed"]) if i.get("occurredFrom") else lag
        lo, hi = (lag if lo is None else lo), (lag if hi is None else hi)
        rows.append({"lag": lag, "min": min(lo, hi, lag), "max": max(lo, hi, lag), "ext": i.get("foundBy") != "lab"})
    if not rows:
        return None
    return {"n": len(rows), "mid": _median([r["lag"] for r in rows]), "lo": _median([r["min"] for r in rows]),
            "hi": _median([r["max"] for r in rows]), "others": sum(1 for r in rows if r["ext"])}


def disclosure_lag_body():
    s = lag_stats()
    if s:
        rng = f" ({round(s['lo'])}–{round(s['hi'])})" if round(s["lo"]) != round(s["hi"]) else ""
        top = glance(f"Median about {round(s['mid'])} days{rng} across {s['n']} incidents; {s['others']} of {s['n']} "
                     f"made public by outsiders.") + f'<p class="small">These lags are a {FLOOR_CHIP}, not a typical value.</p>'
        others = f"{s['others']} of the {s['n']}"
    else:
        top, others = "", "several"
    note = as_dict(load_json("data/incidents.json")).get("note")
    counts = f"<p>{e(note)}</p>" if note else '<p class="muted">The inclusion rule is unavailable right now.</p>'
    why = f"""<p>This is the closest thing we have to an empirical base rate for hypotheses A and C: how long real AI behaviour stayed out of public view, and who brought it to light. In 2026 the incidents that did come out took from days to months to surface, and {e(others)} were made public by someone other than the lab: victims, outside researchers, evaluators, governments or reporters. That shows sub-AGI agents can act out of public view for months, and that labs don't reliably disclose first. It can't show how long a careful system, or a lab set on keeping a secret, could stay hidden. New incidents are added in each weekly wrap-up.</p>
    <p class="muted small">Separate, lab-reported context: Anthropic says that in August 2026 about 30,000 research and engineering agents ran at once on its most-used internal platform, every action passed through an automated monitor before it ran, and about 1 in 47,000 actions was blocked (<a href="https://www.anthropic.com/institute/measuring-pace-of-ai-development" target="_blank" rel="noopener">Anthropic</a>; self-reported, not independently audited). It measures what one lab's monitor catches, not what reaches the public.</p>"""
    return f"""
  <header class="prose">
    <h1>Disclosure lag</h1>
    <p class="lede">How long real AI incidents stayed out of public view. Each bar runs from when an incident happened to when it was made public.</p>
    {top}
  </header>
  <div class="tiles" id="tiles"></div>
  <section><h2>Days from incident to public disclosure</h2><div class="chart-wrap"><div id="lag"></div></div><p class="muted small" id="w4"></p></section>
  <section class="prose" id="floor"><h2>What this can't show</h2><p>Only incidents that became public appear here. Anything undetected, or detected and still hidden, is missing by definition, and the tracker only covers incidents from 2026 on, so it can't yet show a secret kept for years. Read these lags as a floor on how long things stay hidden, not a typical or a maximum value. The lag also runs from when an incident happened, so it mixes time before anyone noticed with time when a lab knew and said nothing; where a source says when the lab detected it, the chart marks that date.</p></section>
  <section class="prose">{fold("counts", "What counts", counts)}</section>
  <section class="prose">{fold("why", "Why it matters", why)}</section>
"""


PAGES["disclosure-lag.html"] = dict(
    title="Disclosure lag · Hidden AGI watch",
    description="How long AI agent incidents stayed hidden before the public heard about them, and who made them public. A floor, not a typical value.",
    body=disclosure_lag_body,
    scripts_code=r"""
const d = await j("data/incidents.json"), h = K.util.h, el = byId("lag");
const rows = (el ? K.live(el, () => K.lagChart(el, d.incidents)) : null) || [];
const median = xs => { const s = xs.filter(x => x!=null && !isNaN(x)).sort((a,b)=>a-b), k = s.length; if(!k) return null; return k%2 ? s[(k-1)/2] : (s[k/2-1]+s[k/2])/2; };
const stats = rs => ({mid:median(rs.map(r=>r.lag)), lo:median(rs.map(r=>r.lagMin)), hi:median(rs.map(r=>r.lagMax)), n:rs.length});
const r0 = v => v==null ? "–" : String(Math.round(v));
const range = s => s.lo!=null && s.hi!=null && Math.round(s.lo)!==Math.round(s.hi) ? `range ${r0(s.lo)}–${r0(s.hi)}` : "";
const n = rows.length, S = stats(rows);
const others = rows.filter(r=>r.ext).length, labFirst = rows.filter(r=>r.labFirst).length, over90 = rows.filter(r=>r.lagMin > 90).length;
const longest = rows.reduce((a,b) => !a || b.lag > a.lag ? b : a, null);
const tiles = byId("tiles");
if(tiles){
  tiles.append(tile("Median lag", n ? `~${r0(S.mid)} days` : "–", n ? [range(S), `n = ${n}`].filter(Boolean).join(" · ") : ""));
  tiles.append(tile("Made public by others", n ? `${others} of ${n}` : "–", "not the lab"));
  tiles.append(tile("Lab detected it first", n ? `${labFirst} of ${n}` : "–", "the lab itself detected it; someone else made it public"));
  tiles.append(tile("Hidden more than 90 days", n ? `${over90} of ${n}` : "–", "at every date in its window"));
  tiles.append(tile("Longest seen", longest ? `${longest.lag} days` : "–", longest ? String(longest.title || longest.id || "") : ""));
}
const cut = new Date(Date.now() - 180*864e5).toISOString().slice(0,10), W = stats(rows.filter(r => String(r.disclosed) >= cut));
const w4 = byId("w4");
if(w4) w4.append("Fire-alarm condition ", h("a",{href:"alarm.html#W4"},"W4"), W.n ? ` uses the same median over incidents made public in the past 180 days: ~${r0(W.mid)} days${range(W) ? " (" + range(W) + ")" : ""} across ${W.n} incident${W.n>1?"s":""} as of today.` : " uses the same median over incidents made public in the past 180 days; there are none as of today.");
""",
)

# ---------- AGI claims ----------
def agi_claims_body():
    d = as_dict(load_json("data/agi_claims.json"))
    cl = [c for c in as_list(d.get("claims")) if isinstance(c, dict)]
    n = len(cl)
    v2 = [as_dict(c.get("meets")).get("v2") for c in cl]
    if n and all(v is not None for v in v2):
        yes = sum(1 for v in v2 if v == "yes")
        top = f"{n} claim{'s' if n != 1 else ''}; " + ("none meets definitions v2.0." if not yes else f"{yes} meet{'s' if yes == 1 else ''} definitions v2.0.")
    elif n:
        strict = sum(1 for c in cl if as_dict(c.get("meets")).get("strict") == "yes")
        top = f"{n} claim{'s' if n != 1 else ''}; " + ("none meets our v1.0 bar." if not strict else f"{strict} meet our v1.0 bar.")
    else:
        top = ""
    return f"""
  <header class="prose">
    <h1>AGI claims ledger</h1>
    <p class="lede">Public claims that AGI is already here: who made them, what they stand to gain, and whether each meets our definition and others'. Predictions about the future are not included.</p>
    {glance(e(top))}
  </header>
  <section><h2>When the claims were made</h2><div class="chart-wrap"><div id="tl"></div></div></section>
  <section><h2>The claims, checked against each definition</h2><noscript><p class="muted small">The claims table is drawn with JavaScript. Without it, every claim and its verdicts are in <a href="data/agi_claims.json">data/agi_claims.json</a>.</p></noscript><div class="table-wrap"><table id="claims"></table></div><p class="muted small">✓ meets it · ½ partly · ✗ doesn't · ? unclear</p></section>
  <section class="prose"><h2 id="definitions">The definitions</h2><p>Definitions v2.0 is ours (stated in full on <a href="agi.html#definition">Is AGI here?</a>), and the v1.0 bar is the remote-work test we used before it. The outside definitions, with their sources and how they compare with ours: <a href="agi.html#others">How others define AGI →</a></p></section>
"""


PAGES["agi-claims.html"] = dict(
    title="AGI claims ledger · Hidden AGI watch",
    description="Public claims we track that AGI has already been achieved, and whether each meets our definition (v2.0), our earlier v1.0 bar and the main outside definitions.",
    body=agi_claims_body,
    scripts_code=r"""
const d = await j("data/agi_claims.json"), h = K.util.h, claims = (d.claims||[]).filter(Boolean);
const tl = byId("tl");
if(tl) K.live(tl, () => K.dotTimeline(tl, claims, {title:"Public AGI claims by date"}));
const mark = v => ({yes:"✓ yes", partial:"½ partly", no:"✗ no", unclear:"? unclear"})[v] || v || "–";   // ◐ is kept for Watch
const t = byId("claims");
if(t){
  // our definitions first (v2.0, then the v1.0 bar); on phones the outside ones move into the compact line
  const hr = h("tr"); ["Date","Who","Claim","Definitions v2.0","v1.0 bar","DeepMind Levels","OpenAI charter","Own definition"].forEach((c,i)=>hr.append(h("th",i>3?{scope:"col",class:"claims-wide"}:{scope:"col"},c))); t.append(hr);
  claims.forEach(c => {
    const tr = h("tr"), meets = c.meets || {};
    tr.append(h("td",{}, fd(c.date)));   // may wrap on phones
    const who = h("td"); who.append(h("strong",{},c.who||"–"), h("div",{class:"muted small"},c.role||"")); tr.append(who);
    const q = h("td"); q.append(h("div",{},"“"+(c.quote||"")+"”"));
    const meta = h("div",{class:"muted small"}, (c.venue||"") + (c.interest ? ". Interest: " + c.interest : "") + " ");
    const src = link(c.url, "source"), cov = link(c.press, "coverage");
    if(src) meta.append(src); if(src && cov) meta.append(" · "); if(cov) meta.append(cov);
    q.append(meta);
    q.append(h("div",{class:"small claims-compact"}, `v1.0 bar ${mark(meets.strict)} · DeepMind Levels ${mark(meets.levels)} · OpenAI charter ${mark(meets.charter)} · Own definition ${mark(meets.narrow)}` + (c.narrowDef ? ` (${String(c.narrowDef).replace(/\.$/, "")})` : "")));
    tr.append(q);
    tr.append(h("td",{},mark(meets.v2)));
    ["strict","levels","charter"].forEach(k=>tr.append(h("td",{class:"claims-wide"},mark(meets[k]))));
    const own = h("td",{class:"claims-wide"}); own.append(h("div",{},mark(meets.narrow)), h("div",{class:"muted small"},c.narrowDef||"")); tr.append(own);
    t.append(tr);
  });
}
""",
)

# ---------- Calendar ----------
def calendar_body():
    run = newest_run()
    nxt = coming_up(load_json("data/calendar.json"), run.get("date"))
    top = " · ".join(f"{short_day(d)}: {t}" for d, t in nxt)
    return f"""
  <header class="prose">
    <h1>Coming up</h1>
    <p class="lede">Dated events that could move the numbers. "Target" means a company or government goal, not a fixed date. Updated in each weekly wrap-up.</p>
    {glance("Next: " + e(top)) if top else ""}
    <p class="muted small">The letter on each event is the scenario it bears on: A–D, or D-open for open government use (<a href="hidden.html#hypotheses">the scenarios</a>).</p>
  </header>
  <section><h2>Dated</h2><noscript><p class="muted small">The calendar is drawn with JavaScript. Without it, every event is in <a href="data/calendar.json">data/calendar.json</a>.</p></noscript><ul class="timeline-list" id="dated"></ul></section>
  <section><h2>No date yet, but watching</h2><ul class="timeline-list" id="undated"></ul></section>
"""


PAGES["calendar.html"] = dict(
    title="Coming up · Hidden AGI watch",
    description="Dated events that could move the hidden-AGI estimates: model launches, deadlines, policy dates.",
    body=calendar_body,
    scripts_code=r"""
const d = await j("data/calendar.json"), h = K.util.h, today = new Date().toISOString().slice(0,10);
const hyp = k => { const s = h("span",{class:"tw-hyp"}), sw = h("span",{class:"swatch"}); sw.style.background = K.util.cssVar(Object.prototype.hasOwnProperty.call(K.SERIES, k) ? K.SERIES[k].color : "--muted"); s.append(sw, document.createTextNode(k==="Dopen" ? "D-open" : (k || "?"))); return s; };
const row = (when, e, past) => {
  const li = h("li"); li.append(h("div",{class: past ? "when muted" : "when"}, when));
  const b = h("div"), t = h("div"); t.append(hyp(e.hyp), document.createTextNode(" " + (e.title||"")));
  if(e.certainty) t.append(h("span",{class:"chip"},e.certainty)); if(past) t.append(h("span",{class:"chip"},"past"));
  b.append(t); if(e.why) b.append(h("div",{class:"muted small"},e.why));
  const a = link(e.url, "source"); if(a){ const s = h("div",{class:"small"}); s.append(a); b.append(s); }
  li.append(b); return li;
};
const dated = byId("dated"); if(dated) [...(d.events||[])].filter(e=>e&&e.date).sort((a,b)=>String(a.date).localeCompare(String(b.date))).forEach(e=>dated.append(row(fd(e.date), e, String(e.date) < today)));
const und = byId("undated"); if(und) (d.undated||[]).filter(Boolean).forEach(e=>und.append(row("TBD", e, false)));
""",
)

# ---------- Steelman ----------
def steelman_body():
    st = as_dict(load_json("data/steelman.json"))
    es = sorted((x for x in as_list(st.get("entries")) if isinstance(x, dict) and x.get("date")),
                key=lambda x: str(x["date"]), reverse=True)
    thesis = ""
    if es:
        x = es[0]
        side = str(x.get("side") or "").strip().rstrip(".")
        head = f"The case that {side[:1].lower() + side[1:]}." if side else ""
        thesis = (f'<div class="callout" id="thesis"><p class="small muted" style="margin:0">{e(day(x["date"]))}'
                  f'{" · " + e(x["edition"]) if x.get("edition") else ""}</p>'
                  f'<p style="margin:4px 0 0"><strong>{e(head)}</strong> {e(x.get("against"))}</p></div>')
    return f"""
  <header class="prose">
    <h1>Weekly steelman</h1>
    <p class="lede">Each week, the strongest honest case for the side our numbers currently disfavour. It's here to keep us calibrated, not to persuade.</p>
    {thesis}
  </header>
<noscript><p class="muted small">The essay is drawn with JavaScript. Without it, every steelman entry is in <a href="data/steelman.json">data/steelman.json</a>.</p></noscript>
  <article class="prose" id="latest"></article>
  <section><h2>Archive</h2><div id="archive"></div></section>
"""


PAGES["steelman.html"] = dict(
    title="Weekly steelman · Hidden AGI watch",
    description="Each week, the strongest case for the side our numbers currently disfavour.",
    body=steelman_body,
    scripts_code=r"""
const d = await j("data/steelman.json"), h = K.util.h;
const e = [...(d.entries||[])].filter(x=>x&&x.date).sort((a,b)=>String(b.date).localeCompare(String(a.date)));
const side = x => String(x.side||""), lower = s => s.charAt(0).toLowerCase() + s.slice(1);
// the latest edition's heading and thesis are in the box above (server-rendered); archived editions sit
// under the Archive h2, so their own heading is an h3
const render = (x, host, {latest=false}={}) => {
  if(!latest){
    host.append(h("p",{class:"kicker muted small"}, fd(x.date,{day:"numeric",month:"long",year:"numeric"}) + (x.edition ? " · " + x.edition : "")));
    host.append(h("h3",{},"The case that " + lower(side(x))));
    if(x.against) host.append(h("p",{class:"muted"},x.against));
  }
  (x.paragraphs||[]).forEach(p=>host.append(h("p",{},p)));
  // dated corrections to an edition, shown with it (the edition's text carries the fix)
  (Array.isArray(x.corrections) ? x.corrections : []).filter(c => c && c.text).forEach(c => {
    const p = h("p",{class:"muted small"}, (c.date ? "Corrected " + fd(c.date) + ": " : "Corrected: ") + c.text + " ");
    const a = link(c.url, "source"); if(a) p.append(a); host.append(p);
  });
  if(x.wouldConvince){ const c = h("div",{class:"callout"}); c.append(h("strong",{},"What would convince us: "), document.createTextNode(x.wouldConvince)); host.append(c); }
  if(x.sources?.length){ host.append(h(latest ? "h2" : "h4",{},"Sources")); const ul = h("ul",{class:"plain"}); x.sources.forEach(s=>{ if(!s) return; const li = h("li"); li.append(link(s.url, s.title || s.url) || document.createTextNode(s.title || "")); ul.append(li); }); host.append(ul); }
};
const latest = byId("latest");
if(latest){ if(e.length) render(e[0], latest, {latest:true}); else latest.append(h("p",{class:"empty"},"The first steelman arrives with the first weekly wrap-up.")); }
const a = byId("archive");
if(a){
  if(e.length < 2) a.append(h("p",{class:"muted"},"Earlier editions will appear here."));
  else e.slice(1).forEach(x=>{ const det = h("details"); det.append(h("summary",{}, fd(x.date) + ": the case that " + side(x).toLowerCase())); const b = h("div",{class:"body prose"}); render(x,b); det.append(b); a.append(det); });
}
""",
)

# ---------- Weekly index ----------
PAGES["weekly/index.html"] = dict(
    title="Weekly wrap-up · Hidden AGI watch",
    description="Every Friday at 3pm Pacific: the week's key numbers, the biggest moves, and graphs.",
    body="""
  <header class="prose">
    <h1>Weekly wrap-up</h1>
    <p class="lede">Every Friday at 3pm Pacific: the week's key numbers at the top, then what moved and why, then the deeper sections with graphs. It's also sent by email.</p>
  </header>
  <section><noscript><p class="muted small">This list is drawn with JavaScript. Without it, the wrap-ups are listed in <a href="../data/weekly/index.json">data/weekly/index.json</a>, and every daily reading is in the <a href="../archive.html">archive</a>.</p></noscript><div id="list"></div></section>
""",
    scripts_code=r"""
const d = await j("../data/weekly/index.json"), h = K.util.h, list = byId("list");
const ws = (d.wrapups||[]).filter(w => w && /^\d{4}-\d{2}-\d{2}$/.test(String(w.date)));
if(list && !ws.length){ list.append(h("p",{class:"empty"},"The first weekly wrap-up is published Friday, October 2, 2026, at 3pm Pacific.")); }
else if(list){ const c = h("div",{class:"cards"}); [...ws].sort((a,b)=>b.date.localeCompare(a.date)).forEach(w=>{ const a = h("a",{class:"card",href:w.date+".html"}); a.append(h("strong",{}, fd(w.date,{day:"numeric",month:"long",year:"numeric"})), h("span",{},w.headline||"")); c.append(a); }); list.append(c); }
""",
)

# ---------- Trend watch ----------
def _hours(minutes):
    if minutes is None:
        return ""
    h = minutes / 60
    return f"{h:.1f} h" if h < 10 else f"{h:.0f} h"


def _trend_today(proj, on):
    """The fitted trend line's value (minutes) on date `on`, interpolated on the log scale between the
    projection's points; None when `on` is outside them."""
    import math
    pts = [(str(p.get("date")), p.get("mid")) for p in as_list(proj) if isinstance(p, dict)
           and isinstance(p.get("mid"), (int, float)) and p["mid"] > 0 and re.match(r"\d{4}-\d{2}-\d{2}$", str(p.get("date")))]
    pts.sort()
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        if d0 <= on <= d1:
            span = _days(d0, d1) or 1
            f = (_days(d0, on) or 0) / span
            return math.exp(math.log(v0) + f * (math.log(v1) - math.log(v0)))
    return None


def trends_glance():
    """'80% time horizon about 3.1 h measured (trend line about 4.8 h); a work-month around Jul 2028 (Jan 2028 –
    May 2029) if the trend holds. RLI 20.8%.' from data/trends.json, dated by the newest reading."""
    t = as_dict(load_json("data/trends.json"))
    p80 = as_dict(as_dict(t.get("metr")).get("p80"))
    anchor = as_dict(p80.get("anchor"))
    bits = []
    measured = anchor.get("measured") if isinstance(anchor.get("measured"), (int, float)) else None
    line = _trend_today(p80.get("projection"), latest_run_date() or "")
    if measured:
        bits.append(f"80% time horizon about {_hours(measured)} measured"
                    + (f" (trend line about {_hours(line)})" if line else ""))
    wm = as_dict(as_dict(p80.get("crossings")).get("workMonth"))
    my = C.month_year(wm.get("mid"))
    if my:
        rng = (f" ({C.month_year(wm['fast'])} – {C.month_year(wm['slow'])})"
               if C.month_year(wm.get("fast")) and C.month_year(wm.get("slow")) else "")
        bits.append(f"a work-month around {my}{rng} if the trend holds")
    s = "; ".join(bits)
    s = (s[:1].upper() + s[1:] + ".") if s else ""
    pts = [p for p in as_list(as_dict(as_dict(t.get("manual")).get("rli")).get("points")) if isinstance(p, dict)
           and isinstance(p.get("v"), (int, float))]
    if pts:
        s += f" Remote Labor Index (RLI) {C.fmt(round(pts[-1]['v'], 1))}%."
    return s.strip()


def trends_body():
    return f"""
  <header class="prose">
    <h1>Trend watch</h1>
    <p class="lede">Our probabilities are judgments. These are measurements, extended forward to show when they would cross thresholds that matter, if the trends hold. A projection is not a prediction: trends bend and break.</p>
    {glance(e(trends_glance()))}
  </header>
  <div class="tiles" id="tiles"></div>
  <section>
    <h2>How long a task AI can finish on its own</h2>
    <p class="muted">METR's time horizon: the length of task, in skilled-human time, that frontier models complete with 50% or 80% success on software, ML and cyber tasks. Log scale, so a straight line means steady doubling. Dots are measured models; the dashed line and bands are the projection, and the lighter band is where a single new model should land if the trend holds.</p>
    <div class="chart-wrap"><div id="metr"></div><div class="legend" id="metr-legend"></div></div>
    <div class="table-wrap"><table id="cross"></table></div>
    {fold("fit", "Fit method and sensitivity", '<p class="muted small" id="sens"></p><p class="muted small" id="metr-method"></p>', h="span")}
  </section>
  <section class="prose">
    <h2 id="meaning">What this means for AGI</h2>
    <p>The time horizon is one test of one part of AGI, and METR's suite can't yet measure a work-month. How it feeds our numbers: <a href="agi.html#horizon">Long projects</a> · <a href="agi.html#reliability">Reliability</a> · <a href="agi.html#breadth">Breadth</a> · <a href="agi.html#numbers">From the parts to our number</a>.</p>
  </section>
  <section id="rli-sec" hidden>
    <h2 id="rli-h">How much real remote work AI can already do</h2>
    <p class="muted">The Remote Labor Index (RLI): the share of real freelance projects an AI delivers at a quality a client would accept, judged by people. It is the headline measure of <a href="agi.html#breadth">Breadth</a>. Measured points only, with no projection. <span id="rli-note"></span></p>
    <div class="chart-wrap"><div id="rli"></div></div>
    <ul class="plain small" id="rli-points"></ul>
  </section>
  <section>
    <h2>How much AI research AI is already doing</h2>
    <p class="muted" id="rd-note"></p>
    <div class="chart-wrap"><div id="rd"></div></div>
  </section>
  <section class="prose"><h2>Other trends we watch</h2>
    <ul class="plain">
      <li><strong>Frontier training compute</strong> grows about 5x a year, doubling every ~5 months (<a href="https://epoch.ai/trends">Epoch AI</a>). A run or cluster at least 2x Epoch AI's trend for the largest, with nothing publicly attributed to it and no model from it released or externally evaluated within 12 months, is alarm condition <a href="alarm.html#X4">X4</a>.</li>
      <li><strong>Disclosure lag</strong>: see <a href="disclosure-lag.html">how long incidents stay hidden</a>. There are too few incidents yet for a trend line.</li>
    </ul>
  </section>
"""


PAGES["trends.html"] = dict(
    title="Trend watch · Hidden AGI watch",
    description="Measured AI trends projected forward: METR task length, AI's share of AI research, real remote work, and when they would cross key thresholds.",
    body=trends_body,
    scripts_code=r"""
const [t, runs] = await Promise.all([j("data/trends.json"), j("data/runs.json").catch(err => { console.error(err); return []; })]);
const M = t.metr, h = K.util.h;
// AGI anywhere by end-2030, from the latest published reading (one tile; the reasoning is on agi.html#numbers)
const all = Array.isArray(runs) ? runs.filter(r => r && typeof r === "object") : [];
const pub = all.filter(r => r.report && r.comparable !== false);
const lastRun = pub.length ? pub[pub.length-1] : all[all.length-1];
const y30 = lastRun?.agi?.y2030;
const agi2030 = y30 != null && y30 !== "" && !isNaN(y30) ? K.util.fmtPct(y30) : "–";
const mo = d => d ? K.util.fmtDate(d,{month:"short",year:"numeric"}) : "–";
const r0 = x => x==null || x==="" || isNaN(x) ? "–" : String(Math.round(x));
const fr = (M.models||[]).filter(m=>m && m.sota && m.date>="2023-01-01").sort((a,b)=>String(a.date).localeCompare(String(b.date)));
const hasPred = p => Array.isArray(p) && p.length > 0 && p.every(x => x.predLo!=null && x.predHi!=null);
const metr = byId("metr"), lg = byId("metr-legend");
if(metr) K.live(metr, () => {
  K.trendChart(metr, {title:"METR time horizon", color:"--accent",
    history: fr.map(m=>({date:m.date, v:m.p50, lo:m.p50lo, hi:m.p50hi, name:modelName(m.id)+" · 50%", excluded:m.excluded===true, inFit:m.excluded!==true})),
    projection: M.p50.projection,
    secondary: {label:"80% horizon", rate:"80%", color:"--ink", history: fr.filter(m=>m.p80).map(m=>({date:m.date, v:m.p80, name:modelName(m.id)+" · 80%", excluded:m.excluded80===true, inFit:m.excluded80!==true})), projection: M.p80.projection},
    thresholds: [{v:M.thresholds.workWeek, label:"1 work-week (40 hours)"},{v:M.thresholds.workMonth, label:"1 work-month (167 hours)"}]});
  if(!lg) return;
  lg.replaceChildren();
  const item = (mark, text) => { const it = h("span",{class:"lg-item"}); it.append(mark, document.createTextNode(text)); lg.append(it); };
  [["--accent","50% success (measured)"],["--ink","80% success (measured)"]].forEach(([c,l]) => { const sw = h("span",{class:"swatch"}); sw.style.background = K.util.cssVar(c); item(sw, l); });
  item(h("span",{class:"lg-dash"}), "Projection, with the 95% band of the trend line");
  if(hasPred(M.p50.projection)){ const b = h("span",{class:"lg-band"}); b.style.opacity = ".07"; item(b, "Lighter band: where a single new frontier model should land (95%)"); }
  if(fr.some(m => m.excluded || m.excluded80 || m.p50 > 960)){ const f = h("span",{class:"swatch"}); f.style.background = K.util.cssVar("--accent"); f.style.opacity = ".4"; item(f, "Faded: above 16 hours, beyond METR's reliable range; not used in the fit"); }
});
const tb = byId("cross");
if(tb){
  const hr = h("tr"); ["If the trend holds…","Central","Range (95% band of the trend line)"].forEach(c=>hr.append(h("th",{scope:"col"},c))); tb.append(hr);
  [["50% horizon reaches a work-week","p50","workWeek"],["50% horizon reaches a work-month","p50","workMonth"],["80% horizon reaches a work-week","p80","workWeek"],["80% horizon reaches a work-month (one test of Long projects; software tasks only)","p80","workMonth"]].forEach(([l,m,k]) => { const c = M[m]?.crossings?.[k]; if(!c) return; const tr = h("tr"); tr.append(h("td",{},l), h("td",{class:"num"},mo(c.mid)), h("td",{class:"num"},mo(c.fast)+" – "+mo(c.slow))); tb.append(tr); });
}
const WM = M.p80?.crossings?.workMonth || {};
const sens = [];
["p80","p50"].forEach(m => { const X = M[m], a = X?.anchor, c = X?.crossingsFromMeasured; if(a && a.measured && c?.workMonth) sens.push(`Starting the ${m==="p80"?"80%":"50%"} projection from the measured value of ${modelName(a.model)} (${K.fmtDur(a.measured)}) instead of the fitted line (${K.fmtDur(a.value)}) moves the work-month crossing from ${mo(X.crossings?.workMonth?.mid)} to ${mo(c.workMonth)}.`); });
{ const a = M.p50?.anchor; if(a && a.measured && a.measuredInRange === false) sens.push(`The measured 50% horizon of ${modelName(a.model)} (${K.fmtDur(a.measured)}) is above METR's 16-hour reliable range, so no 50% scenario starts from it.`); }
{ const s = byId("sens"); if(s) s.textContent = sens.length ? "Sensitivity: " + sens.join(" ") : ""; }
const pubCI = M.metrDoublingDays?.from_2023_on, rng = a => Array.isArray(a) && a[0]!=null && a[1]!=null ? ` (95% range ${r0(a[0])}–${r0(a[1])})` : "";
{ const mm = byId("metr-method"); if(mm) mm.textContent = (M.method || "") + ` Our fit gives a 50%-horizon doubling time of ${r0(M.p50.doublingDays)} days${rng(M.p50.doublingDaysRange)}; METR's own fit since 2023 gives ${r0(pubCI?.point_estimate)} days` + (pubCI?.ci_low!=null && pubCI?.ci_high!=null ? ` (CI ${r0(pubCI.ci_low)}–${r0(pubCI.ci_high)})` : "") + `. The 80% horizon doubles every ${r0(M.p80.doublingDays)} days${rng(M.p80.doublingDaysRange)}. Data refreshed ${t.updated} from METR.`; }
const last = fr[fr.length-1];
const tiles = byId("tiles");
if(tiles){
  tiles.append(tile("Doubling time (50%)", r0(M.p50.doublingDays) + " days", pubCI?.point_estimate ? `METR's own fit: ${r0(pubCI.point_estimate)} days` : ""));
  if(last) tiles.append(tile("Latest frontier, 50%", K.fmtDur(last.p50), modelName(last.id) + (last.p50 > 960 ? ", above METR's 16-hour reliable range" : "")));
  tiles.append(tile("80% horizon hits a work-month (projected)", mo(WM.mid), `range ${mo(WM.fast)} – ${mo(WM.slow)}`));
  tiles.append(tile("AGI anywhere by end-2030", agi2030, "our forecast, from the latest daily reading"));
}
// a horizontal reference line on a lineChart drawn with yMax 100: placed from its own gridlines
const refLine = (host, v, label) => { try{
  const s = host.querySelector("svg"), ls = [...(s?.querySelectorAll("g.axis line") || [])]; if(!ls.length) return;
  const base = ls.find(l => l.getAttribute("class")==="base") || ls[0], y0 = +base.getAttribute("y1"), y100 = Math.min(...ls.map(l => +l.getAttribute("y1")));
  const y = y0 + (y100 - y0) * v / 100, x1 = +base.getAttribute("x1"), x2 = +base.getAttribute("x2");
  s.append(K.util.svg("line",{x1, x2, y1:y, y2:y, stroke:K.util.css("--ink"), "stroke-width":1, opacity:0.5}));
  const tx = K.util.svg("text",{x:x1+6, y:y-5, class:"row-label"}); tx.textContent = label; s.append(tx);
}catch(err){ console.error(err); } };
const RL = t.manual?.rli;
const rliSec = byId("rli-sec"), rliEl = byId("rli");
if(RL && Array.isArray(RL.points) && RL.points.length && rliSec && rliEl){
  rliSec.hidden = false;
  { const n = byId("rli-note"); if(n) n.textContent = RL.note || ""; }
  const pts = RL.points.filter(p => p && p.date && p.v!=null);
  K.live(rliEl, () => { K.lineChart(rliEl, {title: RL.label || "Remote Labor Index", yMax:100, endLabels:true, series:[{label: RL.label || "Remote Labor Index", short:"RLI", color:"--accent", values: pts.map(p=>({x:p.date, y:p.v}))}]}); refLine(rliEl, 80, "80%: what the remote-work test asks for"); });
  const ul = byId("rli-points");
  if(ul) pts.forEach(p => { const li = h("li"); li.append(h("strong",{}, fd(p.date)), " · " + (p.label || K.util.fmtPct(p.v)) + " "); const a = link(p.url, "source"); if(a) li.append(a); ul.append(li); });
}
const R = t.manual?.rdShare;
if(R){
  const note = byId("rd-note");
  if(note){ note.textContent = (R.label || "") + ". " + (R.note || "") + " "; const src = link(R.points?.[R.points.length-1]?.url, "source"); if(src) note.append(src); }
  const rd = byId("rd");
  if(rd) K.live(rd, () => K.lineChart(rd, {title:R.label, yMax:100, endLabels:true, series:[{label:R.label, short:"AI-led", color:"--accent", values:(R.points||[]).map(p=>({x:p.date,y:p.v}))}]}));
}
""",
)


# ---------- Fire alarm (static, from data/alarm.json) ----------
STATUS_TOKENS = ("good", "warn", "crit")
CAUSES = {"initial": "initial reading", "stepdown": "step-down", "step-down": "step-down"}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _level_of(levels, n):
    return next((lv for lv in levels if _num(n) and lv.get("level") == n), None)


def _lname(levels, n):
    lv = _level_of(levels, n)
    return f'{n} · {lv.get("name", "?")}' if lv else ("–" if n is None else str(n))


def _color(lv):
    s = lv.get("status") if lv else None
    return f"var(--{s})" if s in STATUS_TOKENS else "var(--muted)"


def _anchor(tid):
    tid = str(tid or "")
    return tid if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", tid) else ""


def _alarm_now(cur, levels):
    """The current level as static HTML, in the same markup charts.js alarmIndicator draws (unchanged: frozen
    pages and the live swap rely on it)."""
    lv = _level_of(levels, cur.get("level"))
    if not lv:
        return '<div class="alarm alarm-unknown" role="status"><span class="muted">Fire alarm status unavailable.</span></div>'
    segs = "".join(
        f'<span class="alarm-seg{" on" if x is lv else ""}"'
        + (f' style="background:{_color(x)}"' if _num(x.get("level")) and x["level"] <= lv["level"] else "") + "></span>"
        for x in levels)
    met = cur.get("met") if isinstance(cur.get("met"), list) else None
    met_html = ("unavailable" if met is None else
                ", ".join(f'<a href="#{_anchor(m)}">{e(m)}</a>' if _anchor(m) else e(m) for m in met) or "none")
    since = f'Since {e(day(cur["since"]))} · ' if cur.get("since") else ""
    note = f' {e(cur["note"])}' if cur.get("note") else ""
    return (f'<div class="alarm alarm-{e(lv.get("level"))}" role="status">\n'
            f'    <div class="alarm-head"><span class="alarm-kicker">Fire alarm</span>'
            f'<span class="alarm-icon" style="color:{_color(lv)}">{e(lv.get("icon"))}</span>'
            f'<strong class="alarm-name">Level {e(lv.get("level"))}: {e(lv.get("name"))}</strong></div>\n'
            f'    <div class="alarm-scale" aria-hidden="true">{segs}</div>\n'
            f'    <div class="alarm-meaning">{e(lv.get("meaning"))}</div>\n'
            f'    <div class="muted small alarm-detail">{since}triggers met: {met_html}.{note}</div>\n  </div>')


def _level_strip(levels, current=None):
    """The four-step level strip: each level's icon (in its status colour), number and name, the current one marked."""
    items = []
    for x in levels:
        now = current is not None and x.get("level") == current
        txt = f'<span style="color:{_color(x)}" aria-hidden="true">{e(x.get("icon"))}</span> {e(x.get("level"))} {e(x.get("name"))}'
        items.append(f'<strong>{txt} <span class="chip">now</span></strong>' if now else txt)
    return f'<p class="glance">{" → ".join(items)}</p>'


def _levels_table(levels, current=None):
    rows = "".join(
        f'<tr><td><span style="color:{_color(x)}" aria-hidden="true">{e(x.get("icon"))}</span> {e(x.get("level"))} · {e(x.get("name"))}'
        + (' <span class="chip">now</span>' if current is not None and x.get("level") == current else "") + "</td>"
        f'<td>{e(condition_words(x.get("meaning")))}</td></tr>' for x in levels)
    return (f'<div class="table-wrap"><table class="lv-table"><thead><tr><th scope="col">Level</th>'
            f'<th scope="col">What it means</th></tr></thead><tbody>{rows}</tbody></table></div>')


BORDERLINE = ('<span class="chip" style="border-style:dotted;border-color:var(--muted)" '
              'title="The value sits at the threshold; borderline values don\'t count">borderline, doesn\'t count</span>')


def _status_badge(x, level):
    """Icon + word, never colour alone. Met is amber text at Watch and red above it. A borderline value gets
    the dotted-outline badge (spec 3.3), never ◐, which means Watch."""
    if x.get("met") is True:
        col = "var(--warn-text)" if (level or 1) <= 1 else "var(--crit)"
        return col, "● Met", "st met-yes"
    if x.get("observable") is False:
        return "var(--muted)", "◌ Can't be observed yet", "st"
    return "var(--muted)", "○ Not met", "st"


def _press_links(press):
    """' · corroborated by <a>bloomberg.com</a>' for a condition's corroborating coverage (a URL or a list)."""
    urls = press if isinstance(press, list) else [press] if press else []
    links = []
    for u in urls:
        href = safe_url(u)
        host = (urlsplit(href).hostname or "") if href else ""
        if host:
            links.append(a_link(href, re.sub(r"^www\.", "", host)))
    return (' · corroborated by ' + ", ".join(links)) if links else ""


def _short_label(x):
    """The condition's display label: its `short` (alarm.json, criteria v1.2), else its trigger text cut at the
    first clause (at most 12 words)."""
    if x.get("short"):
        return str(x["short"])
    t = re.split(r"(?<=[a-z0-9)])[:;(]|\.\s", str(x.get("trigger") or ""))[0].strip()
    w = t.split()
    return " ".join(w[:12]) + ("…" if len(w) > 12 else "")


def _condition_row(x, level):
    """One alarm condition: id · short label (its full text, threshold, why and evidence in a <details>) ·
    status · clears when. The id is on the row, so alarm.html#W4 lands on it."""
    col, badge, cls = _status_badge(x, level)
    status = f'<div class="{cls}" style="color:{col}">{badge}</div>'
    if x.get("borderline") is True:
        status += f'<div>{BORDERLINE}</div>'
    if x.get("met") is True and x.get("since"):
        status += f'<div class="muted small">since {e(day(x["since"]))}</div>'
    more = f'<p>{e(x.get("trigger"))}</p>'
    if x.get("threshold"):
        more += f'<p><strong>Threshold:</strong> {e(x["threshold"])}</p>'
    if x.get("why"):
        more += f'<p class="muted small">Why this threshold: {e(x["why"])}</p>'
    src = a_link(x.get("url"), "source")
    kind = source_type(x.get("url")) if src else ""
    if x.get("evidence") or src:
        more += (f'<p class="small"><strong>Evidence:</strong> {e(x.get("evidence"))}{" " + src if src else ""}'
                 + (f' <span class="muted">({e(kind)})</span>' if kind else "") + _press_links(x.get("press")) + "</p>")
    if x.get("note"):
        more += f'<p class="muted small">Note: {e(x["note"])}</p>'
    tid = _anchor(x.get("id"))
    id_attr = f' id="{tid}"' if tid else ""
    return (f'<tr{id_attr}><td class="num">{e(x.get("id"))}</td>'
            f'<td><details><summary>{e(_short_label(x))}</summary><div class="body">{more}</div></details></td>'
            f'<td data-label="Status">{status}</td>'
            f'<td data-label="Clears when" class="small">{e(x.get("clears") or "–")}</td></tr>')


def _condition_group(g, levels):
    level = g.get("level") if _num(g.get("level")) else None
    gl = _level_of(levels, level)
    rule = re.sub(r"^(any (?:one|two|three))\b", r"\1 of these", str(g.get("rule") or ""))
    icon = f'<span style="color:{_color(gl)}" aria-hidden="true">{e(gl.get("icon"))}</span> ' if gl else ""
    gid = f' id="level-{e(level)}"' if level is not None else ""
    rows = "".join(_condition_row(x, level) for x in g.get("triggers") or [] if isinstance(x, dict))
    return (f'<h3{gid}>{icon}Level {e(level if level is not None else "?")} · {e(gl.get("name") if gl else "?")}: {e(rule)}</h3>\n'
            f'    <div class="table-wrap"><table class="trig"><thead><tr><th scope="col">#</th><th scope="col">Condition</th>'
            f'<th scope="col">Status</th><th scope="col">Clears when</th></tr></thead><tbody>{rows}</tbody></table></div>')


def _history_row(x, levels):
    cause = str(x.get("cause") or "").strip()
    cause_txt = f' <span class="muted small">({e(CAUSES.get(cause, cause.replace("-", " ")))})</span>' if cause else ""
    trig = x.get("triggers") if isinstance(x.get("triggers"), list) else []
    cleared = x.get("cleared") if isinstance(x.get("cleared"), list) else []
    trig_txt = (", ".join(str(t) for t in trig) or "–") + ("; cleared: " + ", ".join(str(t) for t in cleared) if cleared else "")
    review = x.get("review")
    if isinstance(review, dict):
        review = review.get("text") or review.get("summary") or review.get("verdict")
    review_txt = e(review) if review else (f'review due {e(day(x["reviewDue"]))}' if x.get("reviewDue") else "–")
    src = a_link(x.get("url"), "source")
    return (f'<tr><td class="num">{e(day(x.get("date")))}</td>'
            f'<td>{e(_lname(levels, x.get("from")))} → {e(_lname(levels, x.get("to")))}{cause_txt}</td>'
            f'<td>{e(trig_txt)}</td><td>{e(x.get("note") or "–")}{" " + src if src else ""}</td><td>{review_txt}</td></tr>')


def _history(history):
    hist = [x for x in history or [] if isinstance(x, dict)]
    return sorted(list(reversed(hist)), key=lambda x: str(x.get("date") or ""), reverse=True)   # newest first


def _history_table(hist, levels):
    if not hist:
        return '<p class="empty">No level changes yet.</p>'
    return (f'<div class="table-wrap"><table class="alarm-hist"><thead><tr><th scope="col">Date</th><th scope="col">Change</th>'
            f'<th scope="col">Conditions</th><th scope="col">Why</th><th scope="col">90-day review</th></tr></thead>'
            f'<tbody>{"".join(_history_row(x, levels) for x in hist)}</tbody></table></div>')


def _criteria_entry(c):
    return (f'<li><strong>v{e(c.get("version"))}</strong> ({e(day(c.get("date")))}): {e(c.get("change"))}'
            + (f' <span class="muted">Why: {e(c["why"])}</span>' if c.get("why") else "") + "</li>")


def _criteria_latest(changelog):
    """alarm.html#changelog keeps the latest entry; the full log is on changes.html#criteria."""
    cl = [c for c in changelog or [] if isinstance(c, dict)]
    if not cl:
        return '<p class="muted">No changes yet.</p>'
    latest = max(enumerate(cl), key=lambda t: (str(t[1].get("date") or ""), t[0]))[1]
    return (f'<ul class="plain">{_criteria_entry(latest)}</ul>'
            f'<p><a href="changes.html#criteria">Every change to these criteria →</a></p>')


# The owner's pre-registered case-file format (2026-09-30), used only if data/alarm.json lacks "caseFile".
CASE_FILE_FALLBACK = {
    "name": "Alarm case-file standard",
    "note": "The format of a Level-3 alarm, fixed before any case exists. The breaking email and the case page follow it "
            "section by section, and a full evidence appendix is published on the site.",
    "verdict": "One sentence, first: what we conclude, and why it meets the Level-3 standard.",
    "sections": [
        {"title": "What we claim, and what we don't", "requires": "Exactly what we claim, and just as plainly what we don't."},
        {"title": "The independent lines of evidence", "requires": "Each fact with its source and how it was authenticated, "
         "and how the lines are independent."},
        {"title": "Every innocent explanation we considered", "requires": "The defense's best case for each one, and the "
         "evidence it fails to explain."},
        {"title": "What could have disproved it, and proof we checked", "requires": "The findings that would have sunk the "
         "case, and what we found when we checked."},
        {"title": "What we still don't know", "requires": "Open questions and the weakest links."},
        {"title": "What readers can do", "requires": "How to check the evidence and send us more, either way."},
    ],
    "correction": "If the case turns out to be wrong, we publish a correction at once and the level drops.",
}


def _proof_section(P):
    """The Level-3 proof standard from alarm.json "proofStandard", collapsed under #proof; '' when it's absent."""
    if not isinstance(P, dict):
        return ""
    reqs = "".join(f'<li><strong>{e(r.get("title"))}.</strong> {e(r.get("text"))}</li>'
                   for r in P.get("requirements") or [] if isinstance(r, dict))
    mods = "".join(f"<li>{e(m)}</li>" for m in P.get("modalities") or [] if m)
    out = ""
    if P.get("summary"):
        out += f'<p>{e(P["summary"])}</p>'
    if reqs:
        out += f'<p>A case must meet all of these:</p><ol>{reqs}</ol>'
    if mods:
        out += f'<p>Modalities of evidence (each line comes from a different one):</p><ul>{mods}</ul>'
    if P.get("tribunal"):
        out += f'<p class="small">{e(P["tribunal"])}</p>'
    if P.get("otherwise"):
        out += f'<p class="small muted">{e(P["otherwise"])}</p>'
    return f'\n  <section class="prose">{fold("proof", "Proof standard for Level 3 (Alarm)", out)}</section>'


def _cases_register(cases):
    rows = []
    for c in cases or []:
        if not isinstance(c, dict):
            continue
        page_link = a_link(c.get("page"), "case page") if c.get("page") else ""
        rows.append(f'<tr><td>{e(c.get("id") or "–")}</td><td class="num">{e(c.get("trigger") or "–")}</td>'
                    f'<td>{e(c.get("status") or "–")}</td><td class="num">{e(day(c.get("opened")))}</td>'
                    f'<td class="num">{e(day(c.get("decided")) if c.get("decided") else "–")}</td><td>{page_link or "–"}</td></tr>')
    if not rows:
        return '<p class="muted small">Cases: none has been opened.</p>'
    return ('<h3>Cases</h3><div class="table-wrap"><table><thead><tr><th scope="col">Case</th><th scope="col">Condition</th>'
            '<th scope="col">Status</th><th scope="col">Opened</th><th scope="col">Decided</th><th scope="col">Page</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _open_cases(cases):
    return [c for c in cases or [] if isinstance(c, dict) and str(c.get("status") or "").lower() not in ("passed", "failed", "closed")]


def _case_file_section(C_, cases):
    """The pre-registered Level-3 case-file format, from alarm.json "caseFile" (or the owner's fallback), collapsed
    under #case-file; the summary says whether any case is open."""
    C_ = C_ if isinstance(C_, dict) and C_.get("sections") else CASE_FILE_FALLBACK
    secs = "".join(f'<li><strong>{e(s.get("title"))}.</strong> {e(s.get("requires"))}</li>'
                   for s in C_.get("sections") or [] if isinstance(s, dict))
    out = ""
    if C_.get("note"):
        out += f'<p>{e(C_["note"])}</p>'
    if C_.get("verdict"):
        out += f'<p><strong>The verdict.</strong> {e(C_["verdict"])}</p>'
    if secs:
        out += f'<p>Then, in this order:</p><ol>{secs}</ol>'
    if C_.get("correction"):
        out += f'<p><strong>Public-correction commitment.</strong> {e(C_["correction"])}</p>'
    if C_.get("appendix"):
        out += f'<p><strong>Evidence appendix.</strong> {e(C_["appendix"])}</p>'
    # C_["register"] describes the data format for maintainers; readers get the plain version.
    out += ('<p class="small muted">Every case, whether open (under investigation), passed or failed, is listed here with its '
            'status and dates, and a met Level-3 condition counts only once its case has passed.</p>')
    n_open = len(_open_cases(cases))
    note = f"{n_open} case{'s' if n_open != 1 else ''} open" if n_open else "no case open"
    return (f'\n  <section class="prose">{fold("case-file", e(C_.get("name") or "Alarm case-file standard"), out + _cases_register(cases), summary_note=note)}</section>')


def signals_section():
    """#signals: the standing tripwire board, server-rendered from the newest published reading. Icon + word +
    name + the condition it feeds; the note, date and source in each row's <details>."""
    run = newest_run()
    alarm = as_dict(load_json("data/alarm.json"))
    tws = [t for t in as_list(run.get("tripwires")) if isinstance(t, dict) and t.get("signal")]
    if not tws:
        return ('<section id="signals"><h2>Signals</h2><p class="muted">The signal board is unavailable right now; '
                'the newest reading has no signals.</p></section>')
    order = {"tripped": 0, "watching": 1, "quiet": 2}
    tws = sorted(tws, key=lambda t: order.get(t.get("status"), 3))
    cnt = {s: sum(1 for t in tws if t.get("status") == s) for s in ("tripped", "watching", "quiet")}
    items = []
    for t in tws:
        # sitekit.signal_view: amber "Confirmed · counts toward Watch" for a W-linked or unlinked confirmed signal,
        # red only for X/Y (charts.js statusView's rule, and the 2026-09-30 "Tripwire colours" correction)
        icon, tok, word = signal_view(t.get("status"), t.get("trigger"), alarm)
        cond = _anchor(t.get("trigger"))
        feeds = e(t["trigger"]) if t.get("trigger") else "no condition"
        hyp = "D-open" if t.get("hyp") == "Dopen" else t.get("hyp")
        meta = " · ".join(x for x in (
            f"Since {e(day(t['since']))}" if t.get("since") else "",
            f"Scenario {e(hyp)}" if hyp else "",
            f'Alarm condition <a href="#{cond}">{e(t["trigger"])}</a>' if cond else "",
            a_link(t.get("url"), "source")) if x)
        items.append(f'<details><summary><span class="ico-{e(tok)}" aria-hidden="true">{e(icon)}</span> '
                     f'{e(word)} · <span style="font-weight:400">{e(t["signal"])}</span> '
                     f'<span class="muted small" style="font-weight:400">· {feeds}</span></summary>'
                     f'<div class="body"><p>{e(display_words(t.get("note")))}</p><p class="muted small">{meta}</p></div></details>')
    return f"""
  <section id="signals"><h2>Signals</h2>
    <p>{cnt['tripped']} confirmed · {cnt['watching']} open · {cnt['quiet']} quiet ({e(short_day(run.get('date')))} reading). A confirmed signal goes to a ruling on the condition it names. Also: <a href="escape.html">Escape watch</a>.</p>
    <div class="signal-board">{"".join(items)}</div>
  </section>"""


def alarm_body():
    A = load_alarm()
    levels = [lv for lv in A.get("levels") or [] if isinstance(lv, dict)]
    cur = A.get("current") if isinstance(A.get("current"), dict) else {}
    n_word = {3: "three ", 4: "four ", 5: "five "}.get(len(levels), "")
    groups = "\n    ".join(_condition_group(g, levels) for g in A.get("groups") or [] if isinstance(g, dict))
    rules = "".join(f"<li>{e(r)}</li>" for r in A.get("rules") or [] if r)
    as_of = A.get("asOf") or A.get("updated") or latest_run_date()
    version = f'First published {e(day(A.get("published")))}; statuses as of {e(day(as_of))}.' 
    al = C.alarm_state({"alarm": A})
    met = [str(m) for m in al["met"]]
    top = ""
    if al.get("level") is not None:
        top = (level_html(al) + (f' since {e(short_day(al["since"]))}, {e(al["since"][:4])}' if al.get("since") else "")
               + (f', on {e(", ".join(met))}' if met else "") + f' · criteria v{e(A.get("version") or "?")}')
    hist = _history(A.get("history"))
    hist_note = (f"{len(hist)} level change{'s' if len(hist) != 1 else ''}; latest {e(short_day(hist[0].get('date')))}"
                 if hist else "no level changes yet")
    return f"""
  <header class="prose">
    <h1>The fire alarm</h1>
    <p class="lede" id="purpose">{e(condition_words(A.get("purpose")))}</p>
    {glance(top)}
    <p class="small muted">{version} <a href="#changelog">Changes</a>.</p>
  </header>
  <div id="now">{_alarm_now(cur, levels)}</div>
  <section class="prose"><h2>The {n_word}levels</h2>{_level_strip(levels, cur.get("level"))}
    <details><summary>What each level means</summary><div class="body">{_levels_table(levels, cur.get("level"))}</div></details>
    <details><summary>Evidence standard</summary><div class="body"><p>{e(condition_words(A.get("evidenceStandard")) or "–")} <a href="#proof">Proof standard for Level 3</a>.</p></div></details></section>
  <section id="conditions"><h2>The alarm conditions, and where each stands</h2>
    <p class="muted small">● Met · ○ Not met · ◌ Can't be observed yet · a dotted badge: borderline, doesn't count. Open a condition for its full text and evidence.</p>
    {groups}
    <p class="muted small">A met Level-3 condition counts only when its case passes the <a href="#proof">proof standard</a>, published in the <a href="#case-file">case-file format</a>.</p>
  </section>{signals_section()}{_proof_section(A.get("proofStandard"))}{_case_file_section(A.get("caseFile"), A.get("cases"))}
  <section class="prose">{fold("rules", "Rules that keep the alarm honest", f"<ol>{rules}</ol>")}</section>
  <section>{fold("history", "Alarm history", '<p class="muted">Every level change, the evidence behind it, and a review after 90 days: did it hold up, or was it a false alarm?</p>' + _history_table(hist, levels), summary_note=hist_note)}</section>
  <section class="prose">{fold("changelog", "Changes to these criteria", _criteria_latest(A.get("changelog")), summary_note="the latest change, and the full log")}</section>
"""


def load_required(rel, ok, problem):
    """A data file a static page is built from. Stops the build, before any page is written, when the
    file can't be read or ok(data) is false, so a bad file never leaves a blank page."""
    try:
        data = json.loads((ROOT / rel).read_text())
    except (OSError, ValueError) as err:
        sys.exit(f"build_pages: can't read {rel} ({err}); no pages were written")
    if not ok(data):
        sys.exit(f"build_pages: {rel} {problem}; no pages were written")
    return data


def load_alarm():
    return load_required("data/alarm.json", lambda A: isinstance(A, dict), "is not an object")


PAGES["alarm.html"] = dict(
    title="Fire alarm · Hidden AGI watch",
    description="The published, versioned criteria for Hidden AGI watch's fire alarm for hidden AI: four levels, the alarm conditions and where each stands, the signals, and a public history.",
    body=alarm_body,
    # The criteria above are static HTML. This only swaps in the live indicator, and keeps the
    # static one if alarm.json can't be read or is malformed.
    scripts_code=r"""
try {
  const A = await j("data/alarm.json"), box = document.createElement("div"), now = byId("now");
  if(!Array.isArray(A?.current?.met)) throw new Error("data/alarm.json: current.met is not a list; keeping the static indicator");
  K.alarmIndicator(box, A, {root:""});
  if(now && box.firstChild && !box.querySelector(".alarm-unknown")) now.replaceChildren(...box.childNodes);
} catch(err){ console.error("Fire alarm indicator:", err); }
""",
)

# ---------- Escape watch (static, from data/escape.json) ----------
# (icon, word, token): an explicitly reordered view of sitekit.SIGNAL_STATUS, which is (icon, token, word)
ESC_STATUS = {k: (i, w, t) for k, (i, t, w) in SIGNAL_STATUS.items()}
RATING_TAG = {"verified fact": "fact", "credible report": "report", "expert opinion": "opinion", "speculation": "spec",
              "forecast aggregate": "agg", "our inference": "ours"}


def load_escape():
    return load_required("data/escape.json", lambda E: isinstance(E, dict) and isinstance(E.get("indicators"), list),
                         "has no indicators list")


def escape_indicators(E=None):
    E = E if E is not None else load_escape()
    return [i for i in E.get("indicators") or [] if isinstance(i, dict) and i.get("name")]


def _esc_status(s):
    """(icon, word, css color) for an indicator status; unknown statuses show as such, in muted."""
    icon, word, tok = ESC_STATUS.get(str(s or "").lower(), ("?", str(s or "Unknown").capitalize(), "muted"))
    return icon, word, f"var(--{tok})"


def _esc_alarm_links(triggers):
    ids = triggers if isinstance(triggers, list) else [triggers] if triggers else []
    return ", ".join(f'<a href="alarm.html#{_anchor(t)}">{e(t)}</a>' if _anchor(t) else e(t) for t in ids)


def condition_words(s):
    """Alarm-page copy from alarm.json with "trigger(s)" shown as "condition(s)" (spec 3.1)."""
    return re.sub(r"\btrigger(s?)\b", r"condition\1", str(s or ""))


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“‘(])")
_STATUS_LEAD = re.compile(r"^(?:Watching|Open|Quiet|Tripped|Confirmed)\b,?\s*", re.I)


def _sentences(s):
    return [x for x in _SENT.split(str(s or "").strip()) if x]


def esc_short(i):
    """The indicator's one-line summary: `short` (written by the weekly Escape lens), else the first sentence of
    statusReason with a leading status clause ("Watching, …" / "Open, …") dropped. When that clause is all the
    first sentence says ("Watching, at the high end."), the next sentence is used."""
    if i.get("short"):
        return str(i["short"])
    ss = _sentences(i.get("statusReason"))
    while ss:
        first = ss.pop(0)
        if _STATUS_LEAD.match(first):
            rest = _STATUS_LEAD.sub("", first, count=1)
            if len(rest.split()) < 8 and ss:
                continue
            first = rest[:1].upper() + rest[1:]
        return first
    return ""


def _esc_confirm(i):
    """What a confirmed case would look like: the signature, the confirm rule (`tripRule` in data) and the alarm link."""
    look = (f'<p style="white-space:pre-line">{e(display_words(i["whatItWouldLookLike"]))}</p>'
            if i.get("whatItWouldLookLike") else "")
    rule = (f'<p style="white-space:pre-line"><strong>Confirm rule:</strong> {e(display_words(i["tripRule"]))}</p>'
            if i.get("tripRule") else "")
    links = _esc_alarm_links(i.get("alarmTriggers"))
    alarm = ""
    if links or i.get("alarmNote"):
        note = f' {e(display_words(i["alarmNote"]))}' if i.get("alarmNote") else ""
        alarm = f'<p class="muted small">Alarm conditions it feeds: {links or "none"}.{note} See <a href="alarm.html">the fire alarm</a>.</p>'
    if not (look or rule or alarm):
        return ""
    return f'<h3>What a confirmed case would look like</h3>{look}{rule}{alarm}'


def _esc_evidence_item(x):
    rating = str(x.get("rating") or "").strip()
    cls = RATING_TAG.get(rating.lower())
    tag = f' <span class="{"tag " + cls if cls else "tag"}">{e(rating)}</span>' if rating else ""
    src = a_link(x.get("url"), "source")
    return f'<li><span class="rdate">{e(day(x.get("date")))}</span> {e(display_words(x.get("text")))}{tag}{" " + src if src else ""}</li>'


def _esc_evidence(i):
    ev = sorted((x for x in i.get("evidence") or [] if isinstance(x, dict) and x.get("text")),
                key=lambda x: str(x.get("date") or ""), reverse=True)
    if not ev:
        return '<p class="muted small">No dated evidence logged yet.</p>'
    items = "".join(_esc_evidence_item(x) for x in ev)
    return f'<details><summary>Evidence ({len(ev)})</summary><div class="body"><ul class="plain">{items}</ul></div></details>'


def _esc_sources(i):
    feeds = [f for f in i.get("feeds") or [] if isinstance(f, dict) and f.get("name")]
    if not feeds:
        return ""
    items = "".join(
        f'<li>{a_link(f.get("url"), f.get("name")) or e(f.get("name"))}'
        + (f' <span class="muted small">({e(f["cadence"])})</span>' if f.get("cadence") else "") + "</li>" for f in feeds)
    return f'<details><summary>Sources we monitor ({len(feeds)})</summary><div class="body"><ul class="plain">{items}</ul></div></details>'


def _esc_indicator(i):
    """One indicator: status icon + word + name, the one-line summary, and its dossier collapsed under the same #key."""
    icon, word, col = _esc_status(i.get("status"))
    key = _anchor(i.get("key"))
    id_attr = f' id="{key}"' if key else ""
    dossier = (f'<p>{e(display_words(i.get("statusReason")))}</p>{_esc_confirm(i)}{_esc_evidence(i)}{_esc_sources(i)}')
    return (f'\n  <section{id_attr} class="prose">\n'
            f'    <h2><span style="color:{col}" aria-hidden="true">{icon}</span> {e(i.get("name"))} '
            f'<span class="chip esc-chip" style="border-color:{col}">{e(word)}</span></h2>\n'
            f'    <p>{e(esc_short(i))}</p>\n'
            f'    <details><summary>The dossier</summary><div class="body">{dossier}</div></details>\n  </section>')


def esc_counts(inds):
    c = {s: sum(1 for i in inds if str(i.get("status") or "").lower() == s) for s in ("tripped", "watching", "quiet")}
    return c


def escape_body():
    E = load_escape()
    inds = escape_indicators(E)
    legend = E.get("statusLegend") if isinstance(E.get("statusLegend"), dict) else {}
    key_items = []
    for s in ("quiet", "watching", "tripped"):
        icon, word, col = _esc_status(s)   # the words always come from sitekit.SIGNAL_STATUS; only meanings from data
        meaning = legend.get(s, {}).get("meaning") if isinstance(legend.get(s), dict) else ""
        meaning = re.sub(r"\s*\(see alarmNote\)", "", str(meaning or ""))   # a field name, not reader copy
        key_items.append(f'<li><span style="color:{col}" aria-hidden="true">{icon}</span> <strong>{word}</strong>'
                         + (f': {e(meaning)}' if meaning else "") + "</li>")
    c = esc_counts(inds)
    n = len(inds)
    checked = f" · checked {e(short_day(E.get('updated')))}" if E.get("updated") else ""
    count = (f"{c['tripped']} of {n} confirmed · {c['watching']} open" + (f" · {c['quiet']} quiet" if c["quiet"] else "")
             + checked)
    lede_s, rest_s = [], []
    for s in _sentences(E.get("intro")):
        (lede_s if not rest_s and len(" ".join(lede_s + [s]).split()) <= 60 else rest_s).append(s)
    if not lede_s and rest_s:
        lede_s, rest_s = rest_s[:1], rest_s[1:]
    more = (f'\n    <details><summary>Why these chokepoints</summary><div class="body"><p>{e(" ".join(rest_s))}</p></div></details>'
            if rest_s else "")
    lim = "<p>" + e(E.get("limits")) + "</p>"
    limits = (f'\n  <section class="prose">{fold("limits", "What this can&#39;t see", lim)}</section>'
              if E.get("limits") else "")
    return f"""
  <header class="prose">
    <h1>Escape watch</h1>
    <p class="lede">{e(" ".join(lede_s))}</p>
    {glance(count)}
    <p class="muted small">Detection signatures only. Each indicator reads Quiet, Open or Confirmed under a published confirm rule, and names the <a href="alarm.html">fire-alarm</a> conditions a confirmed case would feed.</p>{more}
  </header>
  <section class="prose" id="indicators"><h2>The {NUM_WORDS.get(n, str(n))} indicators</h2>
    <details><summary>What the statuses mean</summary><div class="body"><ul class="plain">{"".join(key_items)}</ul></div></details>
  </section>{"".join(_esc_indicator(i) for i in inds)}{limits}
"""


def escape_description():
    try:
        n = len(escape_indicators())
    except SystemExit:
        n = 0
    count = f"{NUM_WORDS.get(n, n)} sourced indicators" if n else "sourced indicators"
    return f"Signs that an AI system is operating on its own, outside anyone's control: {count} at the resource chokepoints."


PAGES["escape.html"] = dict(
    title="Escape watch · Hidden AGI watch",
    description=escape_description,
    body=escape_body,
)

# ---------- Follow the money ----------
def money_glance():
    m = as_dict(load_json("data/money.json"))
    ttm = as_dict(m.get("ttm"))
    v = ttm.get("usd_b")
    if not isinstance(v, (int, float)):
        return ""
    return f"Big Tech capex ${v:,.0f}B / yr · context only (<a href=\"alarm.html#X4\">X4</a> is the test)"


def _money_sec(title, first, rest, open_=False, sid=""):
    """A money section collapsed after its first line (spec 12); the chart or table is inside the <details>."""
    id_attr = f' id="{sid}"' if sid else ""
    return (f'<section><h2>{title}</h2><p class="muted">{first}</p>'
            f'<details{id_attr}{" open" if open_ else ""}><summary>{"Hide" if open_ else "Show"} the details</summary><div class="body">{rest}</div></details></section>')


def money_body():
    secs = [
        _money_sec("Big Tech capital spending, per quarter",
                   "Combined cash capital expenditure of Microsoft, Alphabet, Amazon and Meta, from their SEC filings.",
                   '<p class="muted small">All property and equipment: mostly data centers and chips, also Amazon logistics.</p>'
                   '<div class="chart-wrap"><div id="capex"></div></div><div id="capex-by"></div>', open_=True),
        _money_sec("Spending and capability, side by side (context only)",
                   "Both lines indexed to 100 at the first quarter; the gap between them is not a test.",
                   '<p class="muted small">One log scale. The capability line is the best METR-measured frontier time horizon '
                   "released by each quarter's end. The two lines measure different things, and capability tends to rise faster. "
                   'The check that matters is condition <a href="alarm.html#X4">X4</a>: an operating cluster or training run at '
                   "least 2x Epoch AI's trend for the largest, with nothing publicly attributed to it and no model from "
                   'it released or externally evaluated within 12 months.</p><div class="chart-wrap"><div id="index"></div></div>'
                   '<p class="muted small" id="index-flags"></p><p class="muted small" id="method"></p>'),
        _money_sec("Nvidia data-center revenue", "What the chip supplier sells to everyone building AI, per quarter.",
                   '<div class="chart-wrap"><div id="nvda"></div></div>'),
        _money_sec("AI lab revenue", "If labs kept their best models for their own use, revenue from selling access would flatten.",
                   '<p class="muted small">This is the exclusive-use signal; see <a href="alarm.html#W6">W6</a>.</p>'
                   '<div class="table-wrap"><table id="labs"></table></div>'),
        _money_sec("Prediction markets", "What traders price on AGI questions, for comparison with our odds.",
                   '<div class="table-wrap"><table id="markets"></table></div>', sid="prediction-markets"),
        _money_sec("What would be a red flag", "Compute with no matching release, which is alarm condition X4.", RED_FLAGS),
    ]
    return f"""
  <header class="prose">
    <h1>Follow the money</h1>
    <p class="lede">Code can be hidden; money is harder to hide. Spending, revenue and markets might show a lab sitting on something far beyond its public models before any announcement. In an AI investment boom, a spending spike means "bubble" far more often than "hidden AGI".</p>
    {glance(money_glance())}
  </header>
  <div class="tiles" id="tiles"></div>
  """ + "\n  ".join(secs) + "\n"


RED_FLAGS = """<ul class="plain">
    <li><strong>Compute with no matching release:</strong> an operating cluster or training run at least 2x Epoch AI's trend for the largest, with nothing publicly attributed to it and no model from it released or externally evaluated within 12 months (<a href="alarm.html#X4">condition X4</a>). Planned or announced capacity doesn't count.</li>
    <li><strong>Revenue mix shifting:</strong> revenue from selling access flattening while labs' own research, trading or products grow (<a href="alarm.html#W6">W6</a> and the exclusive-use signal).</li>
    <li><strong>Insiders:</strong> heavy insider buying, or departures that give up equity with warnings attached.</li>
    <li><strong>Markets:</strong> a sharp repricing of AGI prediction markets with no public news behind it.</li>
  </ul><p class="muted">Money is context for our odds. On its own it sets no alarm condition; only X4, unexplained compute, can.</p>"""


PAGES["money.html"] = dict(
    title="Follow the money · Hidden AGI watch",
    description="Big Tech capital spending, Nvidia data-center revenue, AI lab revenue and prediction markets, each with its source, and the compute test for hidden AI (condition X4).",
    body=money_body,
    scripts_code=r"""
const M = await j("data/money.json"), h = K.util.h, $ = usd;
const capex = (Array.isArray(M.capexTotal) ? M.capexTotal : []).filter(Boolean);
const nv = (M.nvdaDatacenter||[]).filter(r => r && r.usd_b!=null);
const lastNv = nv[nv.length-1], lastQ = capex[capex.length-1], LM = M.latestMeasured;
const tiles = byId("tiles");
if(tiles){
  tiles.append(tile("Big-4 capex, last 12 months", M.ttm ? $(M.ttm.usd_b) : "–", M.ttm ? `four quarters to ${M.ttm.asOf}` : ""));
  tiles.append(tile("Growth vs a year earlier", M.ttm && M.ttm.yoyPct!=null ? (M.ttm.yoyPct>0?"+":"") + Number(M.ttm.yoyPct).toFixed(0) + "%" : "–"));
  tiles.append(tile("Nvidia data-center, latest quarter", lastNv ? $(lastNv.usd_b) : "–", lastNv ? lastNv.q : ""));
  if(LM && LM.p50) tiles.append(tile("Latest METR-measured frontier", K.fmtDur(LM.p50), `50% horizon: ${modelName(LM.model)}, released ${fd(LM.date)}` + (LM.aboveSuiteRange ? "; above METR's reliable 16-hour range" : "")));
  else tiles.append(tile("Latest quarter, all four", lastQ ? $(lastQ.usd_b) : "–", lastQ ? lastQ.q : ""));
}
const cx = byId("capex");
if(cx) K.live(cx, () => K.lineChart(cx, {title:"Big-4 capital spending per quarter", yFormat:$, series:[{label:"Microsoft + Alphabet + Amazon + Meta", short:"Total", color:"--accent", values:capex.map(t=>({x:t.end, y:t.usd_b}))}]}));
const CO = [["MSFT","Microsoft"],["GOOGL","Alphabet"],["AMZN","Amazon"],["META","Meta"]];
{ const by = byId("capex-by"); if(by && capex.length) by.append(K.util.tableView("Capital spending by company, per quarter", ["Quarter", ...CO.map(c=>c[1]), "Total"], capex.map(t=>[t.q, ...CO.map(([k])=>t.by && t.by[k]!=null ? $(t.by[k]) : "–"), $(t.usd_b)]), "Show each company as a table")); }
const S = (Array.isArray(M.spendVsCapability) ? M.spendVsCapability : []).filter(Boolean);
const ix = byId("index");
if(ix) K.live(ix, () => K.lineChart(ix, {title:"Spending and capability, indexed (context only)", log:true, yFormat:v=>v >= 1000 ? Math.round(v/1000) + "k" : String(Math.round(v)), series:[
  {label:"Big-4 capex (index)", short:"Capex", color:"--accent", values:S.map(t=>({x:t.end, y:t.spend}))},
  {label:"METR-measured frontier horizon (index)", short:"Horizon", color:"--ink", values:S.map(t=>({x:t.end, y:t.capability}))}]}));
const above = S.filter(t=>t.aboveSuiteRange).map(t=>t.q), stale = S.filter(t=>t.stale).map(t=>t.q), flags = [];
if(above.length) flags.push(`Capability value above METR's reliable 16-hour range: ${above.join(", ")}.`);
if(stale.length) flags.push(`After METR's latest measured release, so newer models may be missing: ${stale.join(", ")}.`);
{ const f = byId("index-flags"); if(f) f.textContent = flags.join(" "); }
{ const m = byId("method"); if(m) m.textContent = (M.method || "") + (M.capexDefinition ? " Line item: " + M.capexDefinition : "") + (M.updated ? " Updated " + M.updated + "." : ""); }
const nd = byId("nvda");
if(nd) K.live(nd, () => K.lineChart(nd, {title:"Nvidia data-center revenue", yFormat:$, series:[{label:"Nvidia data-center revenue", short:"Nvidia", color:"--accent", values:nv.map(r=>({x:r.end, y:r.usd_b}))}]}));
const LT = byId("labs");
if(LT){
  { const tr=h("tr"); ["Date","Company","Figure","Measure","Source"].forEach(c=>tr.append(h("th",{scope:"col"},c))); LT.append(tr); }
  [...(M.labRevenue||[])].filter(Boolean).sort((a,b)=>String(b.date).localeCompare(String(a.date))).forEach(r => { const tr = h("tr"), src = h("td"); src.append(link(r.url, "source") || document.createTextNode("–")); tr.append(h("td",{class:"num"}, fd(r.date,{month:"short",year:"numeric"})), h("td",{}, r.company||"–"), h("td",{class:"num"}, $(r.usd_b)), h("td",{}, (r.metric||"") + (r.note ? ". " + r.note : "")), src); LT.append(tr); });
}
const MT = byId("markets");
if(MT){
  { const tr=h("tr"); ["Market","Venue","Price","As of"].forEach(c=>tr.append(h("th",{scope:"col"},c))); MT.append(tr); }
  (M.predictionMarkets||[]).filter(Boolean).forEach(r => { const tr = h("tr"), a = h("td"); a.append(link(r.url, r.market) || document.createTextNode(r.market||"–")); if(r.note) a.append(h("div",{class:"muted small"}, r.note)); tr.append(a, h("td",{}, r.venue||"–"), h("td",{class:"num"}, r.price_pct!=null ? r.price_pct + "%" : "–"), h("td",{class:"num"}, fd(r.date,{day:"numeric",month:"short"}))); MT.append(tr); });
}
""",
)

# ---------- Chart style guide ----------
GLYPH_ROWS = [
    ("○ ◐ ◉ ●", "Fire-alarm levels Normal, Watch, Warning, Alarm (from data/alarm.json; unchanged)"),
    ("○ ◔ ●", "Signal status Quiet, Open, Confirmed, for tripwires and Escape watch indicators. ◔ marks Open so that ◐ always means Watch."),
    ('<span class="am-pips" aria-hidden="true"><span class="pip on"></span><span class="pip"></span><span class="pip"></span><span class="pip"></span></span> … '
     '<span class="am-pips" aria-hidden="true"><span class="pip on"></span><span class="pip on"></span><span class="pip on"></span><span class="pip on"></span></span> plus a word',
     "AGI part status Far, Partial, Close, Met"),
    ("✓ ≈ – ?", "Parts of a test: Passed, Overall figure only (doesn't count as passed), Not yet, Not measured"),
    ('<span class="swatch ix-sw-round"></span> hatched ink', "The Index bar's rounding segment: the distance from the sum of its parts to the published, grid-rounded Index"),
    ('<span class="chip" style="border-style:dotted;border-color:var(--muted)">borderline</span>', "A borderline alarm value (\"borderline, doesn't count\"); it replaces ◐ in the condition table"),
    ("● ○ ■ ◇ △", "In tracker lanes: public result, result from an unreleased model, new test, on-trend date, coming up"),
]


def _status_scale_rows():
    data = C.load_components()
    scale = [s for s in as_list(as_dict(data).get("statusScale")) if isinstance(s, dict)] or C.STATUS_SCALE
    rows = "".join(f'<tr><td>{C.pips(s.get("key"), data or None)}</td><td>{e(s.get("meaning") or "–")}</td></tr>' for s in scale)
    rule = as_dict(data).get("statusRule")
    return rows, (f'<p class="muted small">{e(rule)}</p>' if rule else "")


def style_body():
    hy = "".join(
        f'<tr><td><span class="swatch" style="background:{lc}"></span> {"D-open" if k == "Dopen" else k}</td><td data-label="Light">{lc}</td><td data-label="Dark">{dc}</td><td data-label="Used for">{e(HYP_LABELS[k])}</td></tr>'
        for k, lc, dc in (("A", "#B8700C", "#C4861A"), ("B", "#00897B", "#139A8C"), ("C", "#9150B8", "#A36ED0"),
                          ("D", "#C8413A", "#DC564A"), ("Dopen", "#3569D4", "#4F82DC")))
    glyphs = "".join(f'<tr><td>{g}</td><td>{e(m)}</td></tr>' for g, m in GLYPH_ROWS)
    scale_rows, rule = _status_scale_rows()
    sample = json.dumps(STYLE_AGI_SAMPLE, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"""
  <header class="prose">
    <h1>Chart style guide</h1>
    <p class="lede">One quiet, consistent style for every graph, so readers learn it once. The data is the only thing allowed to be loud. Every chart on the site is drawn by <code>assets/charts.js</code>, and the email and share-card images follow the same rules.</p>
  </header>
  <section><h2>Palette</h2>
    <p class="prose">Each hypothesis has a fixed color everywhere: on the dashboard, in charts, on cards and in email. Colors follow the hypothesis, never its rank, and the order is always A, B, C, D, D-open. Both sets pass a colorblind-safety check (lightness band, chroma floor, deuteranopia and tritanopia separation, and contrast), and dark mode uses its own validated steps rather than an automatic flip.</p>
    <div class="table-wrap"><table class="am-names"><tr><th>Series</th><th>Light</th><th>Dark</th><th>Used for</th></tr>
    {hy}
    <tr><td><span class="swatch" style="background:#B8700C"></span> Accent</td><td data-label="Light">#B8700C</td><td data-label="Dark">#D9A441</td><td data-label="Used for">The one thing a single-series chart is about: highlights, forecast bars</td></tr>
    <tr id="agi-part-status"><td><span class="swatch" style="background:var(--prog)"></span> AGI part status</td><td data-label="Light">#747B83</td><td data-label="Dark">#9399A0</td><td data-label="Used for">Ink pips plus a word: Far, Partial, Close, Met. The pips show distance to a published test, not danger: never a status colour (green, amber, red), never the alarm's glyphs, never a hypothesis colour. Distance meters use <code>--prog</code> on <code>--grid</code>, linear on the measure's own scale with an ink tick at the bar; growth measures add a labelled log axis inside the drill-down only. Projections of a measured trend are dashed ink with an ink 95% band.</td></tr>
    <tr id="index-bar"><td><span class="swatch ix-sw-A"></span><span class="swatch ix-sw-B"></span><span class="swatch ix-sw-CD"></span><span class="swatch ix-sw-round"></span> Index decomposition bar</td><td data-label="Light">A, B; <code>--muted</code>; hatched <code>--ink</code></td><td data-label="Dark">the same tokens</td><td data-label="Used for">The one place the Index shows hypothesis colours, because its parts are hypotheses: A in A's colour, B outside A in B's colour; C or D outside A in neutral ink-grey, because it mixes two hypotheses and must not take either's identity. A hatched ink segment closes the gap to the published Index when its parts, rounded to 0.05, sum below it; the key says 'parts sum to 2.3; shown as 2.5 on our rounding grid'. Fixed 0–5% scale with '0' and '5%' printed in ink and an ink end tick. A run with no breakdown draws one neutral segment.</td></tr>
    </table></div>
    <p class="prose"><strong>Status colors are reserved for signals and the fire alarm</strong> and always come with an icon and a word. Signals (tripwires and Escape watch indicators): ○ Quiet (green), ◔ Open (amber), ● Confirmed (red). Fire alarm: ○ Normal (green), ◐ Watch (amber), ◉ Warning (red), ● Alarm (red). They never stand in for a hypothesis, and AGI parts never use them.</p>
    <p class="prose"><strong>Text variants.</strong> Text on a background uses its own tokens so it passes WCAG AA contrast (4.5:1); the series colors stay for marks only.</p>
    <div class="table-wrap"><table class="am-names"><tr><th>Token</th><th>Light</th><th>Dark</th><th>Used for</th></tr>
    <tr><td><code>--link</code></td><td data-label="Light">#2F62C8</td><td data-label="Dark">#6B96E6</td><td data-label="Used for">Links and the "credible report" tag</td></tr>
    <tr><td><code>--sA-text</code></td><td data-label="Light">#8A5608</td><td data-label="Dark">#C4861A</td><td data-label="Used for">Amber text, such as the "expert opinion" tag</td></tr>
    <tr><td><code>--warn-text</code></td><td data-label="Light">#855C00</td><td data-label="Dark">#D4A72C</td><td data-label="Used for">Amber status words, such as a met Watch condition</td></tr>
    <tr><td><code>--crit-bg</code></td><td data-label="Light">#B42318</td><td data-label="Dark">#B42318</td><td data-label="Used for">The alarm banner, behind white text</td></tr>
    <tr><td><code>--prog</code></td><td data-label="Light">#747B83</td><td data-label="Dark">#9399A0</td><td data-label="Used for">Distance-meter fill on the AGI part tracker (3.4:1 on <code>--grid</code> in light, 4.6:1 in dark)</td></tr>
    </table></div>
  </section>
  <section class="prose"><h2>Rules</h2>
    <ul class="plain">
      <li><strong>Pick the form first.</strong> One number gets a stat tile, not a chart. Change over time gets lines. Durations get range bars. Probabilities get meters. Distance to a published test gets a meter on the measure's own scale.</li>
      <li><strong>Thin marks.</strong> 2px lines with round joins. Dots at least 8px with a 2px ring in the surface color. Bars no thicker than 24px, with 4px rounded ends.</li>
      <li><strong>Recessive chrome.</strong> Gridlines and axes are 1px solid hairlines one step off the surface, never dashed. Ticks fall on clean values.</li>
      <li><strong>One axis.</strong> Never two y-scales on one chart. Different measures get separate charts.</li>
      <li><strong>Identity is never color alone.</strong> Two or more series always have a legend, plus a few direct labels at line ends where they don't collide. Never a number on every point.</li>
      <li><strong>Text stays ink.</strong> Labels and values use the text colors. The colored mark beside them carries identity.</li>
      <li><strong>Emphasis over rainbow.</strong> When one thing matters (disclosed by outsiders, our forecast), it gets the accent and everything else goes gray.</li>
      <li><strong>Every chart is interactive and readable without the picture.</strong> Hover or tap shows a tooltip, and every chart has a "Show as table" view.</li>
      <li><strong>Forecasts vs projections.</strong> Our forecast is a solid line through the three numbers we actually state (today, end-2030, end-2035), with a shaded judgment band: not a statistical interval, but roughly how far our number could plausibly move as evidence arrives. A projection of a measured trend is dashed, with the 95% band of the trend line and a lighter band where a single new measurement should land. We never project our own daily probability line: the dated forecasts (end-2030, end-2035) shouldn't drift predictably; the line for today is expected to rise along our own forecast. Outside forecasts are hollow rings, and those that only measure an announcement are left off the chart.</li>
      <li><strong>Definition changes break lines.</strong> When our definitions change, a line of readings over time gets a dashed hairline labelled with the new definitions, and no series joins across it.</li>
      <li><strong>Log scales for growth.</strong> Exponential trends go on a log axis labelled in human units (a workday, a work-week), so a straight line means steady doubling.</li>
      <li><strong>Type.</strong> Headings in Source Serif 4. Everything else, including big numbers, in Public Sans. Aligned columns use tabular figures.</li>
    </ul>
  </section>
  <section class="prose" id="glyphs"><h2>Glyphs: one meaning each</h2>
    <div class="table-wrap"><table><tr><th>Glyphs</th><th>Meaning, and nothing else</th></tr>{glyphs}</table></div>
  </section>
  <section class="prose" id="part-status-scale"><h2>AGI part status scale</h2>
    <p class="muted">Four words, each with a published meaning. A part's status is set by its test's own marks, never by our judgment of danger.</p>
    <div class="table-wrap"><table><tr><th>Status</th><th>What it means</th></tr>{scale_rows}</table></div>
    {rule}
  </section>
  <section id="tracker-example"><h2>The eight-part tracker</h2>
    <p class="muted">One row per part: status in pips and a word, a distance meter on the part's own scale, and a timeline lane (● public result, ○ unreleased-model result, ■ new test, ◇ on-trend date, △ coming up). This example draws two parts from a sample frozen on Oct 5, 2026, so the guide never changes daily; the live tracker is on <a href="agi.html#tracker">Is AGI here?</a></p>
    <div id="ex-agimap" class="am"><p class="muted small">The example draws with JavaScript.</p></div>
    <script type="application/json" id="ex-agimap-data">{sample}</script>
  </section>
  <section><h2>The Hidden AGI Index dial</h2><p class="muted">Retired on live pages from redesign v2 (definitions v2.0); frozen reports keep it. An eye whose iris has 100 ticks, one per percentage point, lit in the accent color.</p><div id="ex-dial"></div></section>
  <section><h2>Lines: change over time</h2><div class="chart-wrap"><div id="ex-line"></div></div></section>
  <section><h2>Range bars: how long something lasted</h2><div class="chart-wrap"><div id="ex-lag"></div></div></section>
  <section><h2>Meters: a probability, with market odds as a hollow ring</h2><div id="ex-fc"></div></section>
  <section><h2>Status board: signals</h2><div id="ex-tw"></div></section>
  <section><h2>Forecast: stated numbers, judgment band, outside forecasts</h2><div class="chart-wrap"><div id="ex-fcst"></div></div></section>
  <section><h2>Projection: measured trend on a log scale</h2><p class="muted">Dashed line: the fitted trend, projected. Darker band: the 95% band of the trend line. Lighter band: where a single new measurement should land. Faded dots: above METR's reliable range, left out of the fit.</p><div class="chart-wrap"><div id="ex-trend"></div></div></section>
"""


PAGES["style.html"] = dict(
    title="Chart style guide · Hidden AGI watch",
    description="The one graphics style used for every chart on Hidden AGI watch: palette, marks, glyphs, the AGI part status scale, labels and interaction.",
    body=style_body,
    scripts_code=r"""
const ex = (id, draw) => { const el = byId(id); if(!el) return; try{ K.live(el, () => draw(el)); }catch(err){ console.error(id, err); } };
const soft = p => j(p).catch(err => { console.error(err); return null; });
{ const host = byId("ex-agimap"), raw = byId("ex-agimap-data");
  if(host && raw){ try{ const S = JSON.parse(raw.textContent); K.agiMap(host, S.data, {today:{date:S.today}, trends:S.trends, root:""}); }catch(err){ console.error("ex-agimap", err); } } }
ex("ex-dial", el => K.dial(el, 4, {size:240}));
const days = ["2026-09-01","2026-09-08","2026-09-15","2026-09-22","2026-09-29"];
const demo = {A:[1.5,2,2,2.5,3],B:[1,1,1.5,1.5,2],C:[0.3,0.4,0.5,0.8,1],D:[0.2,0.3,0.3,0.4,0.5]};
ex("ex-line", el => K.lineChart(el, {title:"Example (illustrative data)", series:Object.entries(demo).map(([k,v])=>({label:(K.SERIES[k].name || K.SERIES[k].label)+" (example)", short:k, color:K.SERIES[k].color, values:days.map((d,i)=>({x:d,y:v[i]}))}))}));
const [inc, fc, ext, tr, runs] = await Promise.all(["data/incidents.json","data/forecasts.json","data/external_forecasts.json","data/trends.json","data/runs.json"].map(soft));
if(inc) ex("ex-lag", el => K.lagChart(el, (inc.incidents||[]).slice(0,4)));
if(fc){ const fs = (fc.forecasts||[]).filter(f => f && f.outcome!=="void" && f.void!==true), host = byId("ex-fc"); if(host) K.forecastBars(host, fs.filter(f=>f.market!=null).concat(fs.filter(f=>f.market==null).slice(0,1))); }
const all = Array.isArray(runs) ? runs.filter(r => r && typeof r === "object") : [];
const pub = all.filter(r => r.report && r.comparable !== false), lastRun = pub.length ? pub[pub.length-1] : all[all.length-1];
if(lastRun?.agi) ex("ex-fcst", el => K.forecastChart(el, {title:"AGI anywhere, public or hidden", today:lastRun.date, yMax:100, series:[{label:"Our forecast: AGI anywhere", color:"--ink", ...lastRun.agi}], markers:(ext?.forecasts||[]).filter(m => m && m.bar !== "announcement")}));
if(tr){ const fr = (tr.metr?.models||[]).filter(m=>m && m.sota && m.date>="2023-01-01");
  ex("ex-trend", el => K.trendChart(el, {title:"METR 50% horizon", history:fr.map(m=>({date:m.date, v:m.p50, name:modelName(m.id), excluded:m.excluded===true, inFit:m.excluded!==true})), projection:tr.metr.p50.projection, thresholds:[{v:tr.metr.thresholds.workMonth, label:"1 work-month"}]})); }
{ const tw = byId("ex-tw"); if(lastRun && tw) K.tripwireBoard(tw, (lastRun.tripwires||[]).filter((w,i,a)=>a.findIndex(x=>x.status===w.status)===i)); }
""",
)

# ---------- The generated hubs (scripts/pages/, WP-C2): index, agi, hidden, changes, archive ----------
PAGES.update(pages.all_pages())


def build():
    rendered = []
    for path, p in PAGES.items():
        root = "../" * path.count("/") or "./"
        body = p["body"]() if callable(p["body"]) else p["body"]
        if body is None:  # a page with no data yet (jobs.html before the first Jobs import) is not built
            continue
        desc = p["description"]() if callable(p["description"]) else p["description"]
        scripts = module(root, p["scripts_code"]) if p.get("scripts_code") else p.get("scripts", "")
        rendered.append((path, page(path=path, title=p["title"], description=desc, body=body,
                                    active=path if path != "weekly/index.html" else "weekly/", scripts=scripts,
                                    head_extra=p.get("head_extra", "") or "", nav_top=p.get("nav_top", "") or "")))
    for path, html in rendered:
        out = ROOT / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html)
        print("wrote", path)


# ---------- Frozen sample for the style guide's tracker example ----------
# Two of the eight parts (reasoning and long projects) as data/agi_components.json had them on Oct 5, 2026,
# trimmed; and the 80% horizon crossings from data/trends.json that day. Frozen on purpose: the style guide
# shows how the tracker looks and must not change daily. Never edit it to track the live data.
STYLE_AGI_SAMPLE = json.loads(r'''{
 "today": "2026-10-05",
 "data": {
  "definitionsVersion": "2.0",
  "statusScale": [
   {
    "key": "far",
    "word": "Far",
    "pips": 1,
    "meaning": "No part of the test is passed and the test's own 'Partial' mark is not reached."
   },
   {
    "key": "partial",
    "word": "Partial",
    "pips": 2,
    "meaning": "At least one part of the test is passed, or the test's own 'Partial' mark is reached, but not its 'Close' mark. A part passed on the overall figure only (results by occupation unpublished) does not count as passed."
   },
   {
    "key": "close",
    "word": "Close",
    "pips": 3,
    "meaning": "The test's own 'Close' mark is reached, but not the bar."
   },
   {
    "key": "met",
    "word": "Met",
    "pips": 4,
    "meaning": "A public system passes every part of the test, as published by the test's named source."
   }
  ],
  "components": [
   {
    "id": "reasoning",
    "order": 4,
    "name": "Reasoning",
    "short": "Reasoning",
    "question": "Can the system think problems through as well as a skilled professional: answer hard expert questions correctly, and work out new answers nobody has found yet, in any field?",
    "clause": "v2.0: \"can learn, reason, plan and generalize knowledge across any intellectual domain\" (the word \"reason\" and \"any intellectual domain\"); v1.0 test: \"at the level of a median skilled professional\" and \"with no task-specific human scaffolding\".",
    "status": "partial",
    "statusBasis": "Partial: the expert-exam half (part 1) is passed; AI-alone research solves are 4 of the 10 we ask for.",
    "basisShort": "expert exams passed",
    "since": "2026-10-05",
    "lastReviewed": "2026-10-05",
    "glance": "Expert exams are passed (GPQA Diamond 96%); new research results by AI alone: 4 of the 10 we ask for.",
    "statusNote": "Part 1 is met: 96% on GPQA Diamond (GPT-6 Astra), 100% on FrontierMath Tier 4 (GPT-6.1 Sol) and 54.8% on Humanity's Last Exam without tools. Part 2, the binding half, is not: public models hold 4 of the 10 AI-alone solves we ask for on Epoch's Open Problems, none above 'solid result', and credited new results outside mathematics are few.",
    "bar": "Expert-exam scores (met), plus 10 AI-alone solves of open math problems, one a major advance, and 3 credited results in two other fields.",
    "test": {
     "measure": "Two parts. (1) Closed-answer reasoning: the best public model on fixed-answer tests that span many fields: GPQA Diamond (198 graduate-level biology, chemistry and physics questions), Humanity's Last Exam without tools (2,500 expert-written questions across mathematics, the humanities and the sciences), FrontierMath Tier 4 (research-level mathematics). (2) Open-ended research reasoning: new results that a public model produces under a general harness, without task-specific human direction, and that independent experts accept. In mathematics we count AI-alone solves on Epoch AI's FrontierMath: Open Problems (problems that resisted serious attempts by professional mathematicians), using Epoch's 'Solved (AI)' label. Outside mathematics we count new results whose human co-authors credit the model with the core idea, in refereed or author-posted papers.",
     "threshold": "Partial: either part passed. Close: part 1 passed and the mathematics half of part 2 met (10 AI-alone solves on Epoch's Open Problems by public models, one a major advance or breakthrough). Met: both parts, including 3 credited new results in two or more fields outside mathematics.",
     "why": "A median skilled professional both knows the answers in their field and can work out a new one on their own; part 1 checks the first, part 2 the second. Part 1 tests saturate fast, so part 2 is the binding test. Epoch's bar for a listed problem is a result publishable in its own right, which is what a working researcher produces. The numbers 10, one 'major advance' and three outside results are our choice, not a published standard, and part 2 asks for more than a median professional does: these problems resisted professional mathematicians. What it misses: reasoning in fields with no checker (law, strategy, policy, medical judgment), where tests rely on expert grading; results by public models on problems outside Epoch's list; and how often a model reasons badly while sounding sure."
    },
    "parts": [
     {
      "name": "Expert exams: GPQA Diamond 74%+, FrontierMath Tier 4 50%+, Humanity's Last Exam 50%+",
      "state": "pass",
      "value": "96%, 100%, 54.8%"
     },
     {
      "name": "Open research: 10 AI-alone solves incl. a major advance, plus 3 credited results outside maths",
      "state": "no",
      "value": "4 solves, none above 'solid result'"
     }
    ],
    "headline": {
     "label": "AI-alone solves on Epoch's FrontierMath: Open Problems",
     "value": 4,
     "display": "4 solves",
     "target": 10,
     "targetDisplay": "10 solves",
     "unit": "solves",
     "scale": "count",
     "min": 0,
     "max": 10,
     "system": "Public models (Claude Fable 5, GPT-5.6 Sol, GPT-6 Astra)",
     "asOf": "2026-09-16",
     "url": "https://epoch.ai/frontiermath/open-problems",
     "rating": "verified fact"
    },
    "also": {
     "text": "Exam half met: GPQA Diamond 96% (GPT-6 Astra, Epoch's run), against a 74% mark; FrontierMath Tier 4 and Humanity's Last Exam are past their marks too (see the measurements).",
     "url": "https://epoch.ai/benchmarks/gpqa-diamond",
     "rating": "verified fact"
    },
    "sharedWith": null,
    "current": [
     {
      "metric": "FrontierMath Tier 4 (v2), Epoch's private set of research-level math problems that take specialists hours to days",
      "value": "100% (GPT-6.1 Sol); GPT-6 Astra 98%, Claude Opus 5.5 95%, Claude Fable 5.1 88% (Epoch runs)",
      "system": "GPT-6.1 Sol (OpenAI, released Sept 29, 2026)",
      "asOf": "2026-09-29 (Epoch run; read Oct 5)",
      "url": "https://epoch.ai/benchmarks/frontiermath-tier-4-v2",
      "rating": "verified fact"
     }
    ],
    "milestones": [
     {
      "date": "2023-11-20",
      "text": "GPQA published: PhD experts score 65% on questions in their own field (74% excluding mistakes they later recognized), skilled non-experts with web access 34%, GPT-4 39%.",
      "url": "https://arxiv.org/abs/2311.12022",
      "rating": "verified fact",
      "kind": "yardstick"
     },
     {
      "date": "2024-11-07",
      "text": "Epoch AI publishes FrontierMath, research-level problems that take specialists hours to days; the best models solve under 2%.",
      "url": "https://arxiv.org/abs/2411.04872",
      "rating": "verified fact",
      "kind": "yardstick"
     },
     {
      "date": "2025-01-24",
      "text": "The Humanity's Last Exam paper reports the best models at 9.1% (o1) and 9.4% (DeepSeek-R1, text only), with calibration errors above 80%.",
      "url": "https://arxiv.org/abs/2501.14249v1",
      "rating": "verified fact",
      "kind": "yardstick"
     },
     {
      "date": "2025-07-21",
      "text": "Google DeepMind's Gemini Deep Think scores 35/42 at IMO 2025, a gold-medal score certified by IMO coordinators, in natural language within the time limit. A year earlier AlphaProof and AlphaGeometry needed Lean translations and days of computation for silver.",
      "url": "https://deepmind.google/discover/blog/advanced-version-of-gemini-with-deep-think-officially-achieves-gold-medal-standard-at-the-international-mathematical-olympiad/",
      "rating": "verified fact",
      "kind": "result"
     },
     {
      "date": "2026-02-12",
      "text": "Physicists from IAS, Harvard, Cambridge and Vanderbilt post a paper with OpenAI showing that single-minus gluon tree amplitudes can be nonzero; OpenAI says the public GPT-5.2 Pro first conjectured the general formula and an internal GPT-5.2 version proved it.",
      "url": "https://openai.com/index/new-result-theoretical-physics/",
      "rating": "verified fact",
      "kind": "internal"
     }
    ],
    "projection": {
     "text": "No published forecast targets this threshold. Part 1 is already met. For part 2, AI-alone solves on Epoch's Open Problems went from 0 to 4 between June 9 and late summer 2026 (two of them found in existing work), and unreleased models at OpenAI and Anthropic produced research-level results in May, August and September. If public models keep closing that gap at the pace of months, they could meet the mathematics half within about a year; we see no trend that dates the part outside mathematics.",
     "rating": "our inference",
     "url": "https://epoch.ai/frontiermath/open-problems"
    },
    "upcoming": [],
    "challenges": [
     {
      "text": "Closed-answer tests saturate and contain errors: Epoch's FrontierMath v2 (June 12, 2026) fixed errors in 42% of problems, Tier 4 is now at 100%, and OpenAI, which funded FrontierMath, has exclusive access to part of it. Once saturated, they no longer separate models from experts (our reading).",
      "url": "https://epoch.ai/benchmarks/frontiermath-tier-4-v2",
      "rating": "verified fact",
      "ratingNote": "Verified fact, except the clause marked \"our reading\" or \"our calculation\", which is our inference from the cited source.",
      "ratingQual": "part our inference"
     }
    ],
    "who": [
     {
      "name": "Epoch AI",
      "what": "Runs FrontierMath (Tiers 1–4, Open Problems, Erdős) and grades which open problems are solved by AI, by humans with AI, or by humans.",
      "url": "https://epoch.ai/frontiermath",
      "rating": "verified fact"
     },
     {
      "name": "Center for AI Safety and Scale AI",
      "what": "Built Humanity's Last Exam; Scale runs its leaderboard (last updated Sept 17, 2026), tracking accuracy and calibration, and CAIS keeps HLE-Rolling, a continually updated fork.",
      "url": "https://labs.scale.com/leaderboard/humanitys_last_exam",
      "rating": "verified fact"
     },
     {
      "name": "OpenAI",
      "what": "GPT-6.1 Sol (100%) and GPT-6 Astra (98%) top FrontierMath Tier 4, and GPT-6 Astra is the only one of five models Epoch tested to solve any of its 68 open Erdős problems (2). Unreleased internal models produced the Erdős unit-distance disproof (May 20) and, with researchers steering about 10,000 agents, the Navier–Stokes blow-up proof (Sept 8).",
      "url": "https://openai.com/index/navier-stokes-solution/",
      "rating": "verified fact"
     }
    ],
    "watching": [
     {
      "signal": "AI-alone solves on Epoch's FrontierMath: Open Problems",
      "threshold": "We'd mark the mathematics half met when AI alone has solved 10 or more, at least one rated 'major advance' or 'breakthrough', by a public model (now 4 across public models, at most 2 by one model, the best rated 'solid result'; two of the four were existing human constructions).",
      "why": "It is the cleanest public count of new, checkable research results without human steering, though Epoch's labels rest on how authors describe the AI's part.",
      "sourceName": "Epoch AI",
      "url": "https://epoch.ai/frontiermath/open-problems",
      "sourceDetail": "https://epoch.ai/frontiermath/open-problems (changelog)"
     }
    ],
    "hiddenAngle": "Reasoning is the component most likely to show if a hidden system has it, because its products are checkable and valuable: a solved open problem, a Lean proof, an unusual run of papers. So far labs have claimed such results openly, often from unreleased models: OpenAI's Erdős unit-distance disproof (May 20) and Navier–Stokes proof (Sept 8), and Anthropic's Riemann-zeros bound (Aug 10). That shows internal reasoning runs ahead of public models (relevant to A), but because the results were disclosed they are not evidence of secrecy; Epoch notes that the most impressive AI math results have come from inside AI companies with little transparency about how they were obtained. Attribution is already loose: Epoch marks the Sept 17 proof that ζ(5) is irrational 'human + AI' with an 'unknown AI system', though the preprint does not acknowledge particularly substantial AI use. So one unattributed solution would not point to a hidden system; a run of strong solutions to listed problems (Epoch's lists, erdosproblems.com) or Lean submissions with no stated author or model would matter for C. It would not show if the owner keeps results private: a government program (A) or a system advising decision-makers (D) leaves no published trace, and Epoch says only OpenAI has bought its Open Problems verifiers, so private checking is possible. Mathematical reasoning says little directly about B; AI R&D share is the better gauge there (our inference)."
   },
   {
    "id": "horizon",
    "order": 5,
    "name": "Planning and long projects",
    "short": "Long projects",
    "question": "Can an AI take on a project that would keep a skilled person busy for several weeks, plan it, keep at it, fix its own mistakes and finish it, reliably rather than now and then?",
    "clause": "v2.0: \"plan ... without task-specific retraining\"; v1.0 test kept in v2.0: \"reliably (80% or better) ... including multi-week projects, with no task-specific human scaffolding\"",
    "status": "far",
    "statusBasis": "Far: the best measured 80% horizon, about 3.1 h, is short of the 8-hour Partial mark.",
    "basisShort": "3.1 h; Partial at 8 h",
    "since": "2026-10-05",
    "lastReviewed": "2026-10-05",
    "glance": "The best measured 80% time horizon is about 3.1 hours, some 54 times short of a work-month.",
    "statusNote": "METR's best published 80% time horizon is about 3.1 hours (Claude Mythos Preview, early snapshot; 95% CI 1.6–6.6 h), about 54 times short of a 167-hour work-month; our trend fit reads about 4.8 hours today. On precisely specified software, models already finish weeks-scale work, but nobody has shown that on open-ended work.",
    "bar": "An 80% time horizon of a work-month (167 h) on a suite able to measure it, plus a documented multi-week project. Close at a work-week (40 h).",
    "test": {
     "measure": "METR-style 80% time horizon: the length of task, in skilled-human working hours, that the best public system completes with 80% success in a general agent harness, read from METR's published measurements (work-week = 40 h, work-month = 167 h, as on Trend watch; our trend fit there is context and projection, not a measurement). It must be measured on a task suite that can resolve horizons that long. For 'met' it must also be backed by at least one independently documented multi-week project outside formally checkable domains, delivered at professional quality with no task-specific scaffolding.",
     "threshold": "Partial: an 80% time horizon of a workday (8 h). Close: a work-week (40 h) on a suite able to measure it. Met: a work-month (167 h) on a suite able to measure it, plus a documented multi-week project outside formally checkable work.",
     "why": "The 80% success rate is the definition's \"reliably (80% or better)\", and human-hours of work are the most direct published measure of \"multi-week projects\"; a work-month covers projects of two to four weeks. It misses messiness: METR describes its tasks as mostly software, machine-learning and cybersecurity work, self-contained and well specified, and both METR and MirrorCode's authors find far longer horizons where a precise, checkable target exists. That is why checkable-only results don't count by themselves and why we require a documented real project for 'met'. The status is the same with a looser two-week (80-hour) bar."
    },
    "parts": [
     {
      "name": "80% time horizon of a work-month on a suite able to measure it",
      "state": "no",
      "value": "about 3.1 h, about 54 times short"
     },
     {
      "name": "A documented multi-week project outside formally checkable work",
      "state": "no",
      "value": "none documented"
     }
    ],
    "headline": {
     "label": "METR 80% time horizon: task length done right four times in five",
     "value": 186,
     "display": "3.1 h",
     "target": 10020,
     "targetDisplay": "167 h (a work-month)",
     "closeAt": 2400,
     "closeDisplay": "40 h",
     "unit": "min",
     "scale": "linear",
     "min": 0,
     "max": 10020,
     "growth": true,
     "logTicks": [
      [
       1,
       "1 min"
      ],
      [
       60,
       "1 h"
      ],
      [
       480,
       "workday"
      ],
      [
       2400,
       "work-week"
      ],
      [
       10020,
       "work-month (167 h)"
      ]
     ],
     "system": "Claude Mythos Preview (early snapshot)",
     "asOf": "2026-05-08",
     "url": "https://metr.org/time-horizons/",
     "rating": "verified fact",
     "partialAt": 480,
     "partialDisplay": "8 h"
    },
    "also": {
     "text": "MirrorCode, precisely specified rebuilds: 77.4% full solves (Claude Opus 5.5). Checkable work only, so on its own it moves nothing.",
     "url": "https://epoch.ai/benchmarks/mirrorcode",
     "rating": "verified fact"
    },
    "sharedWith": "METR's 80% horizon also feeds Reliability, with the same Partial and Close steps (a workday, a work-week).",
    "current": [
     {
      "metric": "METR 80% time horizon (published)",
      "value": "about 3.1 hours (186 min; 95% CI 97–399 min)",
      "system": "Claude Mythos Preview (early snapshot; limited-release preview)",
      "asOf": "2026-05-08",
      "url": "https://metr.org/time-horizons/",
      "rating": "verified fact"
     }
    ],
    "milestones": [
     {
      "date": "2019-02-14",
      "text": "GPT-2: METR's retroactive 50% time horizon is about 3 seconds of human work.",
      "url": "https://metr.org/time-horizons/",
      "rating": "verified fact",
      "kind": "result"
     },
     {
      "date": "2023-03-14",
      "text": "GPT-4: 50% horizon about 4 minutes; 80% horizon under 1 minute.",
      "url": "https://metr.org/time-horizons/",
      "rating": "verified fact",
      "kind": "result"
     },
     {
      "date": "2025-02-20",
      "text": "Andon Labs' Vending-Bench: in a simple business simulation run for more than 20M tokens, every model tested has runs that derail, misreading delivery schedules, forgetting orders or falling into 'meltdown' loops.",
      "url": "https://arxiv.org/abs/2502.15840",
      "rating": "verified fact",
      "kind": "result"
     },
     {
      "date": "2025-03-18",
      "text": "METR's paper introduces the time horizon: Claude 3.7 Sonnet completes half of tasks that take experts about 50 minutes, and frontier horizons have doubled about every seven months since 2019.",
      "url": "https://arxiv.org/abs/2503.14499",
      "rating": "verified fact",
      "kind": "yardstick"
     },
     {
      "date": "2025-08-07",
      "text": "GPT-5: 50% horizon about 3.4 hours; 80% about 38 minutes.",
      "url": "https://metr.org/time-horizons/",
      "rating": "verified fact",
      "kind": "result"
     }
    ],
    "projection": {
     "text": "If the 80% trend holds and someone builds a suite that can measure it, the 80% horizon would reach a work-week (40 h) around November 2027 and a work-month (167 h) around late July 2028. The 95% band of the trend line puts the work-month between January 2028 and May 2029.",
     "rating": "our inference",
     "url": "https://hiddenagi.com/trends.html",
     "trend": {
      "source": "data/trends.json",
      "path": "metr.p80.crossings",
      "marks": [
       "workWeek",
       "workMonth"
      ],
      "note": null
     }
    },
    "upcoming": [
     {
      "date": "2026-11-30",
      "text": "Our forecast deadline: METR publishes a time-horizon estimate for GPT-6 Astra (we said 50%).",
      "url": "scorecard.html",
      "rating": "verified fact"
     }
    ],
    "challenges": [
     {
      "text": "Reliability lags capability. For Claude Mythos Preview the 80% horizon (3.1 hours) is under a fifth of the 50% horizon (17.4 hours): it finishes half of 17-hour tasks, but four in five only at about 3 hours.",
      "url": "https://metr.org/time-horizons/",
      "rating": "verified fact"
     }
    ],
    "who": [
     {
      "name": "METR",
      "what": "Publishes the time-horizon series (Time Horizon 1.1: software, machine-learning and cybersecurity tasks) and runs pre-deployment long-horizon and AI R&D evaluations, including GPT-5.6 Sol (June 26) and Claude Opus 5.5 (Sept 22, 2026).",
      "url": "https://metr.org/time-horizons/",
      "rating": "verified fact"
     },
     {
      "name": "Epoch AI (with METR)",
      "what": "Runs MirrorCode: rebuilding whole programs, estimated at weeks to months of human work, from their behaviour alone, on a 7-day, 10-billion-token budget per attempt; Claude Opus 5.5 leads at 77.4%.",
      "url": "https://epoch.ai/benchmarks/mirrorcode",
      "rating": "verified fact"
     },
     {
      "name": "Proximal",
      "what": "Runs FrontierSWE v2: 34 ultra-long engineering and research tasks with a 20-hour budget and partial-credit scoring, in its own Proximus harness.",
      "url": "https://frontierswe.com",
      "rating": "verified fact"
     }
    ],
    "watching": [
     {
      "signal": "METR publishes an 80% time horizon for a model newer than Mythos Preview (GPT-6 Astra, Claude Fable 5.1, Claude Opus 5.5 or Gemini 4 Argon), or releases a longer task suite",
      "threshold": "Partial at a workday (8 h); Close at a work-week (40 h) with a lower confidence bound above 20 hours, on a suite METR says can measure it; Met only at 167 hours, with a documented multi-week project outside formally checkable work.",
      "why": "This is the direct measure in our test. Today's 3.1 hours is nearly four doublings short of a work-week.",
      "sourceName": "METR",
      "url": "https://metr.org/time-horizons/",
      "sourceDetail": "https://metr.org/time-horizons/ (our calendar has the 'METR horizon for GPT-6 Astra by Nov 30' forecast deadline; METR plans another review of labs' internal models in late 2026)"
     }
    ],
    "hiddenAngle": "Long-horizon autonomy is the component a lab would most likely see first internally. The main public check is outside review of internal models: in METR's Feb–Mar 2026 pilot, Anthropic, Google, Meta and OpenAI said they shared their internal state of the art, and METR put the internal frontier about 2 months ahead on time horizon; METR plans another round in late 2026. A hidden system at multi-week reliability would show up as a jump in that round, unless a lab stops sharing (hypothesis A). It would also show up as a fully autonomous share of AI R&D above zero, or speed-up estimates above about 3x (hypothesis B). Today Anthropic reports no fully autonomous share as of August, and a separate METR team's preliminary estimate is about 1.5x. A third sign would be headline results from 'internal' models that labs call comparable to public ones, as with the Fermat run. Agent fleets or operations running for weeks with no human operator would be the observable sign for hypothesis C (our Escape watch). Hypothesis D needs months of sustained planning and would be the hardest to see. One blind spot: no general-purpose public suite measures an 80% horizon past about 16 hours (MirrorCode reaches weeks of human work, but only on precisely specified software), so even a public system near the threshold could go unconfirmed for months. Incidents also surface a median of about 106 days late (our gauge). (our inference)"
   }
  ]
 },
 "trends": {
  "metr": {
   "p80": {
    "crossings": {
     "workWeek": {
      "mid": "2027-11-02",
      "fast": "2027-05-22",
      "slow": "2028-06-24"
     },
     "workMonth": {
      "mid": "2028-07-24",
      "fast": "2028-01-03",
      "slow": "2029-05-13"
     }
    }
   }
  }
 }
}''')


if __name__ == "__main__":
    build()
