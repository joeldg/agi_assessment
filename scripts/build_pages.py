#!/usr/bin/env python3
"""Build the standing section pages, the About page and the style guide from one page shell.

    python3 scripts/build_pages.py

Most charts and lists render in the browser from data/*.json. These parts are written at build
time instead, so they can go stale:
  - alarm.html: the fire-alarm criteria, trigger statuses, the Level-3 proof standard, the alarm
    case-file standard, history and changelog, rendered as static HTML from data/alarm.json so
    they read without JavaScript. Rebuild whenever data/alarm.json changes; the daily routine
    runs this script.
  - escape.html: Escape watch, rendered as static HTML from data/escape.json.
  - start-here.html: the method changelog, from data/method.json, and the alarm version.
  - about.html: the weekly usage line, from data/usage.json, shown only once a full week of
    readings is logged.
Every page is rendered before any file is written, so a bad data/alarm.json or data/escape.json
stops the build without leaving a blank page.
"""
import json
import re
import sys
from datetime import date
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sitekit import REPO, page, safe_url  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Shared by every page module: fetch JSON, data-driven links (http(s) or site paths only),
# dates, stat tiles and METR model ids as readable names.
PREAMBLE = r"""import * as K from "{root}assets/charts.js";
const j = p => fetch(p,{cache:"no-cache"}).then(r => { if(!r.ok) throw new Error(p + ": HTTP " + r.status); return r.json(); });
const link = (u, text, root="") => { const href = K.util.safeHref(u, root); if(!href) return null; return K.util.h("a", /^https?:/i.test(href) ? {href, target:"_blank", rel:"noopener"} : {href}, text); };
const fd = (d, o={day:"numeric",month:"short",year:"numeric"}) => K.util.fmtDate(d, o);
const tile = (label, value, sub) => { const t = K.util.h("div",{class:"tile"}); t.append(K.util.h("div",{class:"label"},label), K.util.h("div",{class:"value"},String(value))); if(sub) t.append(K.util.h("div",{class:"delta muted"},sub)); return t; };
const modelName = id => String(id||"").replace(/_inspect$/,"").replace(/_early$/," (early)").replace(/_/g," ").replace(/\b(gpt|o\d)\b/gi,s=>s.toUpperCase()).replace(/\bclaude\b/i,"Claude").replace(/\bgemini\b/i,"Gemini").replace(/\b(mythos|opus|sonnet|haiku|preview|pro|flash)\b/gi,s=>s.charAt(0).toUpperCase()+s.slice(1));
const usd = v => v != null && v !== "" && Number(v) === 0 ? "$0" : K.fmtUSDb(v);   // money axes start at $0, not $0.0B"""

# data/corrections.json, rendered on About and Start here. Nothing is shown if the file is missing.
CORRECTIONS_JS = r"""
async function renderCorrections(host, root=""){
  if(!host) return;
  let d; try{ d = await j(root + "data/corrections.json"); }catch(e){ return; }
  const h = K.util.h, list = (Array.isArray(d) ? d : Array.isArray(d?.corrections) ? d.corrections : []).filter(c => c && typeof c === "object");
  host.replaceChildren();
  if(!list.length){ host.append(h("p",{class:"muted"},"No corrections so far.")); return; }
  const clean = s => String(s).trim().replace(/[.]+$/,"");
  const ul = h("ul",{class:"plain corrections"});
  [...list].sort((a,b)=>String(b.date||"").localeCompare(String(a.date||""))).forEach(c => {
    const li = h("li"), was = c.was ?? c.claim, now = c.now ?? c.correction;
    li.append(h("strong",{}, c.date ? fd(c.date) : "Undated"));
    if(c.item) li.append(" · " + clean(c.item) + ".");
    if(was) li.append(` We said ${clean(was)}.`);
    if(now) li.append(` ${was ? "That was wrong: " : ""}${clean(now)}.`);
    const pg = link(c.page, "affected page", root), src = link(c.url, "source");
    if(pg) li.append(" ", pg); if(pg && src) li.append(" ·"); if(src) li.append(" ", src);
    if(c.emailed) li.append(h("span",{class:"muted"}, ` Carried in the ${fd(c.emailed)} email.`));
    ul.append(li);
  });
  host.append(ul);
}"""


def module(root, code):
    return f'<script type="module">\n{PREAMBLE.replace("{root}", root)}\n{code}\n</script>'


# ---------- helpers for pages rendered at build time ----------
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


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


def latest_run_date():
    runs = load_json("data/runs.json")
    dates = [r.get("date") for r in runs if isinstance(r, dict) and r.get("date")] if isinstance(runs, list) else []
    return max(dates) if dates else None


# ---------- Start here ----------
def method_changes():
    """The method changelog from data/method.json, newest first, as static HTML."""
    M = load_json("data/method.json")
    if not isinstance(M, dict):
        return '<p class="muted">The method changelog is unavailable.</p>'
    items = [c for c in M.get("changelog") or [] if isinstance(c, dict)]
    items.sort(key=lambda c: (str(c.get("date") or ""), str(c.get("version") or "")), reverse=True)
    lis = "".join(
        f'<li><strong>v{e(c.get("version"))}</strong> · {e(day(c.get("date")))} · {e(c.get("change"))}'
        + (f' <span class="muted">Reason: {e(str(c["why"]).rstrip("."))}.</span>' if c.get("why") else "")
        + "</li>" for c in items)
    return (f'<p class="small muted">Current method: v{e(M.get("version"))}. We bump the version for any change to a '
            f'definition, a gauge, the Index formula or a threshold.</p>\n    <ul class="plain">{lis}</ul>')


def alarm_version():
    """The published alarm-criteria version, for pages that mention it; '' if data/alarm.json can't be read."""
    A = load_json("data/alarm.json")
    return str(A.get("version") or "") if isinstance(A, dict) else ""


def start_here_body():
    v = alarm_version()
    version_txt = f"now v{e(v)}, first published 29 Sept 2026" if v else "first published 29 Sept 2026"
    return """
  <header class="prose">
    <h1>Start here</h1>
    <p class="lede">Hidden AGI watch asks one question every day: could advanced AI already exist, or already be acting, without the public knowing? It answers with explicit, sourced probabilities rather than hype.</p>
  </header>
  <section class="prose">
    <h2>The four hypotheses</h2>
    <div class="hyp A"><strong>A: AGI exists, undisclosed.</strong> A system meets our strict AGI bar (below), and whoever built it, a company or a government program (for example a classified US or Chinese effort), has kept that level of capability from the public for at least 30 days. Admitting that an unreleased model exists doesn't count as disclosure.</div>
    <div class="hyp B"><strong>B: secret recursive self-improvement.</strong> An AI system does most of the work of building a more capable successor, with at least a 3x speed-up over humans alone, and whoever runs it, a company or a government program, has kept this from the public for at least 30 days. Partial AI-driven acceleration is already public, so it doesn't count.</div>
    <div class="hyp C"><strong>C: a covert AGI-level actor online.</strong> An AGI-level system takes sustained actions on the internet or in the economy, and the public hasn't known for at least 30 days. There are two paths. <strong>Sanctioned but undisclosed:</strong> its developer or another operator runs it on purpose and doesn't say so. <strong>Rogue or stolen:</strong> it acts outside its developer's control, because it escaped or copied itself out, or because someone runs it from stolen weights. Today's sub-AGI agent incidents are tracked as warning signs, not as proof, on <a href="escape.html">Escape watch</a>.</div>
    <div class="hyp D"><strong>D: an AGI shaping government.</strong> Output from an AGI-level system materially shapes a major government decision. It's one question with two readings: <strong>covert</strong> (D), where the public doesn't know, and <strong>open</strong> (D-open), through acknowledged use. Today's heavy government use of sub-AGI tools doesn't count toward either.</div>

    <h2 id="hidden">What "hidden" means</h2>
    <p>A–D track two kinds of hiding: advanced AI that people keep from the public (a company or government that doesn't disclose what it has built, or how it's using it), and AI systems acting covertly on their own (C's rogue path). A, B and C use the same secrecy window: kept from the public for at least 30 days. A model hiding its own capability from its developer, for example by quietly underperforming on tests, is a different problem. It isn't A, because A needs the builder to know what it has, but it would undermine the evaluations these readings rely on, so it's tracked separately as the evaluation-integrity tripwire on the <a href="./#tripwires">dashboard</a>.</p>

    <h2 id="pieces">How the pieces fit</h2>
    <ul class="plain">
      <li><strong>Fire alarm:</strong> are pre-committed warning conditions met? It's set by <a href="alarm.html">published rules</a>, not by our probabilities.</li>
      <li><strong>Hidden AGI Index:</strong> our probability that at least one of A–D is true right now.</li>
      <li><strong>Gauges:</strong> the inputs we track, each tagged by how it's made.</li>
      <li><strong>Tripwires:</strong> early signals we're watching, each linked to the alarm trigger it feeds where there is one. They move our probabilities; only the triggers set the alarm level.</li>
      <li><strong><a href="escape.html">Escape watch</a>:</strong> sourced indicators for C at the resource chokepoints an escaped system would still need (weights, compute, money, accounts, code registries), each quiet, watching or tripped under a published trip rule.</li>
      <li><strong>Hypotheses A–D:</strong> the detail behind the Index, each estimated now, by 2030 and by 2035.</li>
    </ul>

    <h2 id="alarm">The fire alarm</h2>
    <p>Hidden AGI watch aims to be a fire alarm for hidden AI. On top of the probabilities there's an alarm level (Normal, Watch, Warning, Alarm) set by <a href="alarm.html">published, versioned criteria</a> (""" + version_txt + """ with that day's readings in view; every change is dated in the <a href="alarm.html#changelog">alarm changelog</a>). It rises the day a trigger is met and comes down only after its rule has gone unsatisfied for 30 days in a row. The top level, Alarm, needs proof beyond reasonable doubt under the <a href="alarm.html#proof">Level-3 proof standard</a>, not official confirmation, and a case in a <a href="alarm.html#case-file">format fixed in advance</a>. Every change is announced and publicly reviewed after 90 days, false alarms included.</p>
    <h2 id="sending">What gets sent, and who approves it</h2>
    <p>The daily issue is emailed automatically at 10am Pacific, and the weekly wrap-up on Fridays at 3pm Pacific. Neither is held back when the alarm level changes: they go out and show the new level. A breaking fire-alarm alert is different: it's prepared as a draft, and a person approves it before it's sent.</p>
    <h2 id="gauges">The five gauges</h2>
    <p>The hypotheses make a sharp headline, but they sit near zero and move slowly. The gauges track what the evidence actually shows. They move week to week and are what the probabilities are judged against. Each is tagged by how it's made: <em>measured</em> (a number published in filings or by a lab or evaluator), <em>estimated</em> (our own calculation or judgment, anchored on published data) or <em>assessed</em> (a position on a defined scale).</p>
    <ul class="plain">
      <li><strong>Capability gap</strong> (estimated, feeds A and B): how many months ahead of public models labs' unreleased models are. A growing gap is the room in which something could be hidden.</li>
      <li><strong>AI doing AI research</strong> (measured, feeds B): the latest lab-published share of AI research led by AI. Today that's one lab's self-report: Anthropic's prototype index, whose levels are assigned by a Claude model and which isn't independently audited. METR's preliminary speed-up estimate sits alongside. It's the most direct precursor of self-improvement.</li>
      <li><strong>Oversight gap</strong> (estimated, feeds A and C): the median time AI agent incidents stayed hidden before the public heard, and how often someone other than the lab made them public. We compute it from our own <a href="disclosure-lag.html">incident list</a>, so it's a floor: incidents nobody has disclosed can't be counted.</li>
      <li><strong>Money trail</strong> (measured, feeds A): Big Tech's total capital spending over the last 12 months (all property and equipment, mostly data centers) and its growth, on the <a href="money.html">Follow the money</a> page, with the compute test in <a href="alarm.html#X4">X4</a>. Spending alone can't reveal hidden capability: the test is X4, a training run or cluster twice the largest known with no matching release.</li>
      <li><strong>Delegation to AI</strong> (assessed, feeds D): how much consequential government decision-making runs through AI, on a 5-level scale from "admin and drafting" to "AI decides without human review".</li>
    </ul>
    <h2>Our AGI bar</h2>
    <p>AGI here means a system that reliably (80% or better) does at least 80% of economically valuable remote professional tasks at the level of a median skilled professional, including multi-week projects, with no task-specific human scaffolding. It is deliberately strict. Looser definitions, such as "we're in the AGI era", are tracked on the <a href="agi-claims.html">AGI claims ledger</a>.</p>
    <h2>The Hidden AGI Index</h2>
    <p>The headline number is the probability that <em>at least one</em> of A–D is true right now. The hypotheses overlap: C and D mostly require an A-level system to exist. So the index sits just above the largest single hypothesis rather than being their sum. The dial shows it as an eye whose iris has 100 ticks, one per percentage point.</p>
    <h2 id="method">How the numbers are made</h2>
    <ul class="plain">
      <li><strong>Daily:</strong> a custom AI agent, built for this project, searches the news, research, lab system cards and independent evaluations such as METR, Epoch AI and the AI Security Institutes. It then reassesses each hypothesis now, by 2030 and by 2035, and publishes the report automatically. Each daily report shows its full reasoning, including base rates, the steelman of both sides, and what would change its mind.</li>
      <li><strong>What the horizons mean:</strong> Now = true today. By 2030 / by 2035 = true at any point before 1 Jan 2031 / 1 Jan 2036 (cumulative, so never below "now").</li>
      <li><strong>Rounding:</strong> estimates move in 0.1-point steps below 1%, 0.5-point steps from 1% to 10%, and whole points above 10%. Finer steps would claim more precision than these judgments have.</li>
      <li><strong>Evidence ratings:</strong> every claim is tagged <span class="tag fact">verified fact</span> <span class="tag report">credible report</span> <span class="tag opinion">expert opinion</span> or <span class="tag spec">speculation</span>.</li>
      <li><strong>Tripwires:</strong> the specific, observable signals that would move the numbers most. Each is marked quiet, watching or tripped, and names the alarm trigger it feeds where there is one.</li>
      <li><strong>Forecast chart:</strong> the dashboard draws our stated numbers (now, by 2030, by 2035) with outside forecasts for comparison. We don't project our daily line forward. Our end-2030/2035 numbers should move only on evidence, never in a predictable direction; our 'now' numbers are expected to rise over time along that forecast. The shaded band is a judgment range, not a statistical interval: roughly how far our number could plausibly move as new evidence arrives, wider when our confidence is lower. <a href="trends.html">Trend watch</a> projects <em>measured</em> trends instead, such as how long a task AI can finish on its own.</li>
      <li><strong>What moved the needle:</strong> each day names the one development that changed an estimate most, or says plainly that it was a quiet day.</li>
      <li><strong>Weekly (Fridays, 3pm Pacific):</strong> a wrap-up with the week's key numbers and graphs, plus the <a href="scorecard.html">forecast scorecard</a>, <a href="disclosure-lag.html">disclosure lag</a>, <a href="agi-claims.html">AGI claims</a>, <a href="calendar.html">calendar</a> and <a href="steelman.html">steelman</a>.</li>
    </ul>
    <h2>Honesty notes</h2>
    <p>The research, writing and publishing are done by our custom AI agent, and the method and sources are public. The probabilities are subjective and uncertain. We try not to treat an absence of evidence as proof of secrecy.</p>
    <p>Our incident data has a built-in blind spot. An incident nobody detected or disclosed can't be on our list, so the lags we report are a floor on how long things stay hidden, not a ceiling, and "every tracked incident was eventually found" is true by construction.</p>
    <p>We aim for calibration; we haven't shown it yet. The A–D probabilities themselves can't resolve, so the <a href="scorecard.html">scorecard</a> of short-range, checkable forecasts is our track record.</p>
    <p>A daily reading is frozen once its email goes out. Later fixes are dated corrections, shown on the affected page and carried into the next email. Changes to the method are logged below.</p>

    <h2 id="changes">Method changes and corrections</h2>
    """ + method_changes() + """
    <div id="corrections-list"></div>
    <p><a class="btn" href="./">Go to today's reading</a></p>
  </section>
"""


PAGES = {}

PAGES["start-here.html"] = dict(
    title="Start here · Hidden AGI watch",
    description="What Hidden AGI watch tracks, what the Hidden AGI Index means, and how the daily and weekly readings are made.",
    body=start_here_body,
    scripts_code=CORRECTIONS_JS + r"""
const host = document.getElementById("corrections-list");
if(host){ const box = K.util.h("div"); await renderCorrections(box); if(box.childNodes.length){ host.append(K.util.h("h3",{},"Corrections")); host.append(...box.childNodes); } }
""",
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


def about_body():
    return f"""
  <header class="prose">
    <h1>About Hidden AGI watch</h1>
    <p class="lede">A fire alarm for hidden AI: a daily, sourced reading of whether advanced AI could already exist, or already be acting, without the public knowing.</p>
  </header>
  <section class="prose">
    <h2 id="what">What this is</h2>
    <p>Hidden AGI watch tracks one question: could advanced AI already exist, or already be acting, without the public knowing? Each day it gives explicit probabilities for four hypotheses, a handful of gauges that track the underlying evidence, an <a href="escape.html">Escape watch</a> on the resource chokepoints, and a fire-alarm level set by published criteria. The aim is to notice early if the evidence starts to point that way, without crying wolf when it doesn't. An absence of evidence is not treated as proof of secrecy.</p>

    <h2 id="how">How it's made</h2>
    <p>A custom AI agent built for this project researches, writes and publishes each daily reading automatically. The research starts each morning (moving to about 07:00 Pacific), and the email goes out at 10am Pacific, or as soon as it is ready if later. No one reviews a daily report before it's published. The Friday wrap-up is made the same way and emailed at 3pm Pacific.</p>
    <p>The daily and weekly issues are sent automatically. Breaking fire-alarm alerts are not: each one is prepared as a draft, and a person approves it before it's sent. The site's owner also sets the hypothesis definitions and the fire-alarm thresholds. Changes to the alarm criteria are dated in the <a href="alarm.html#changelog">alarm changelog</a>, and changes to the method on <a href="start-here.html#changes">Start here</a>.</p>
    <p>{e(EFFORT_LINE)}</p>{weekly_usage_line()}
    <p>The full method is on <a href="start-here.html#method">Start here</a> and the alarm criteria are on <a href="alarm.html">the fire alarm page</a>. Every daily report shows its reasoning and links its sources, and every chart follows the <a href="style.html">chart style guide</a>.</p>

    <h2 id="who">Who runs it</h2>
    <p>Hidden AGI watch is an independent project run by <a href="https://github.com/joeldg">joeldg</a> on GitHub. The source is at <a href="{REPO}">github.com/joeldg/agi_assessment</a>: the code, the data files and the history of every page are public there.</p>

    <h2 id="contact">Contact</h2>
    <p>To report an error, question a number or suggest a source, open an issue on <a href="{REPO}/issues">GitHub Issues</a>. That's the only contact channel, so every report and its answer stay public.</p>

    <h2 id="corrections">Corrections</h2>
    <p>Past readings are frozen once emailed; corrections are dated, shown on the affected page and carried into the next email.</p>
    <div id="corrections-list"></div>

    <h2 id="license">License</h2>
    <ul class="plain">
      <li><strong>Code:</strong> the scripts, the chart kit, the stylesheet and the page templates are under the <a href="{REPO}/blob/main/LICENSE">MIT License</a>.</li>
      <li><strong>The site's own text and data:</strong> the reports, readings, rulings, alarm criteria, Escape watch indicators and our own data files are under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. You can reuse and adapt them, commercially too, with credit and a link to the license.</li>
      <li><strong>Not covered:</strong> third-party material we quote, cite or plot (news excerpts, filings, METR measurements, outside forecasts, market prices and the like) stays under its owners' terms, and the brand assets (the name and wordmark, the avatar and logo, the favicon and the default share image) are all rights reserved. The details are in <a href="{REPO}/blob/main/LICENSE-content.md">LICENSE-content.md</a>.</li>
    </ul>

    <h2 id="cite">How to cite</h2>
    <p>Hidden AGI watch (2026), &lt;page title&gt;, &lt;url&gt;, accessed &lt;date&gt;. Licensed under CC BY 4.0.</p>
    <p class="muted">For example: Hidden AGI watch (2026), The fire alarm, <span style="overflow-wrap:anywhere">{escape("https://joeldg.github.io/agi_assessment/alarm.html")}</span>, accessed <span id="cite-date">&lt;date&gt;</span>. Licensed under CC BY 4.0. Daily reports keep their address (reports/YYYY-MM-DD.html), and the data behind every chart is in the repository's data folder, with its full history. A machine-readable citation is in <a href="{REPO}/blob/main/CITATION.cff">CITATION.cff</a>.</p>
  </section>
"""


PAGES["about.html"] = dict(
    title="About · Hidden AGI watch",
    description="What Hidden AGI watch is, how it's made, who runs it, how to reach us, how corrections work, the license, and how to cite it.",
    body=about_body,
    scripts_code=CORRECTIONS_JS + r"""
await renderCorrections(document.getElementById("corrections-list"));
{ const t = new Date(), c = document.getElementById("cite-date"); if(c) c.textContent = t.toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric"}); }
""",
)

# ---------- Scorecard ----------
PAGES["scorecard.html"] = dict(
    title="Forecast scorecard · Hidden AGI watch",
    description="Short-range, checkable forecasts about AI, scored in public with the Brier score when they resolve.",
    body="""
  <header class="prose">
    <h1>Forecast scorecard</h1>
    <p class="lede">A probability is only worth something if you can check it. These are short-range, checkable forecasts, each with a deadline and a resolution rule, scored in public when they resolve. The A–D probabilities themselves can't resolve; these short-range forecasts are how you can check our judgment.</p>
  </header>
  <div class="tiles" id="tiles"></div>
  <section><h2>Open forecasts</h2><p class="muted small">The amber bar is our probability. A hollow ring marks prediction-market odds where a comparable market exists. Each shows when it was made, its deadline, its resolution rule and any dated corrections.</p><div id="open"></div></section>
  <section><h2>Calibration</h2><p class="muted">When we say 70%, it should happen about 70% of the time. The chart appears once 15 forecasts have resolved; before that, a group of one or two forecasts would read 0% or 100% by chance. It then groups them into three bins (five once 40 have resolved), each with its count and a 90% interval, and points near the diagonal are well calibrated.</p><div class="chart-wrap"><div id="calib"></div></div></section>
  <section><h2>Resolved</h2><div id="resolved"></div></section>
  <section id="withdrawn-sec" hidden><h2>Withdrawn forecasts</h2><p class="muted">Withdrawn forecasts aren't scored. Each shows why it was withdrawn.</p><div id="withdrawn"></div></section>
  <section class="prose"><h2>How scoring works</h2>
    <p>Each resolved forecast scores (probability − outcome)², where the outcome is 1 or 0. The Brier score is the average: 0 is perfect, and always guessing 50% scores 0.25. A raw Brier score depends on how predictable the questions were, so we also show a skill score against always forecasting the base rate of the resolved questions (above 0 beats it), and, where a prediction market priced the same question, the market's Brier score on those same questions. Every score shows how many forecasts it rests on; a handful proves little.</p>
    <p>New forecasts are added in each weekly wrap-up, and nothing is edited after it's made; if a forecast's stated context turns out to be wrong we add a dated correction and still score the original probability. Ill-posed forecasts can be withdrawn unscored; the reason is always shown.</p>
  </section>
""",
    scripts_code=r"""
const d = await j("data/forecasts.json"), h = K.util.h;
const all = (Array.isArray(d.forecasts) ? d.forecasts : []).filter(f => f && typeof f === "object");
const isVoid = f => f.outcome === "void" || f.void === true || f.withdrawn === true;
const scored = all.filter(f => f.outcome === true || f.outcome === false);
const withdrawn = all.filter(isVoid);
const open = all.filter(f => f.outcome == null && !isVoid(f)).sort((a,b)=>String(a.deadline).localeCompare(String(b.deadline)));
const n = scored.length, b = K.brier(scored), bss = K.brierSkill(scored), mp = K.marketPaired(scored);
const next = open.map(f=>f.deadline).filter(Boolean).sort()[0];
const tiles = document.getElementById("tiles");
tiles.append(tile("Open forecasts", open.length));
tiles.append(tile("Resolved and scored", n));
tiles.append(tile("Brier score", b==null ? "–" : b.toFixed(3), n ? `n = ${n}; lower is better` : "after the first forecast resolves"));
if(n >= 1){
  tiles.append(tile("Skill vs base rate", bss==null ? "–" : (bss>0?"+":"") + bss.toFixed(2), bss==null ? "needs both outcomes among the resolved" : `n = ${n}; above 0 beats the base rate`));
  tiles.append(tile("Ours vs market", mp.n ? `${mp.ours.toFixed(3)} vs ${mp.market.toFixed(3)}` : "–", mp.n ? `Brier on the ${mp.n} question${mp.n>1?"s":""} with a market price` : "no resolved question had a market price"));
}
if(withdrawn.length) tiles.append(tile("Withdrawn", withdrawn.length, "not scored"));
tiles.append(tile("Next deadline", next ? fd(next) : "–"));
K.forecastBars(document.getElementById("open"), open);
const calib = document.getElementById("calib");
K.live(calib, () => K.calibration(calib, scored));
const r = document.getElementById("resolved");
if(!n) r.append(h("p",{class:"empty"}, next ? "Nothing has resolved yet. The first deadline is " + fd(next,{day:"numeric",month:"long",year:"numeric"}) + "." : "Nothing has resolved yet."));
else {
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
if(withdrawn.length){
  document.getElementById("withdrawn-sec").hidden = false;
  const ul = h("ul",{class:"plain"});
  const when = f => { const w = f.withdrawnOn || f.resolved; return w && !isNaN(new Date(w)) ? " " + fd(w) : ""; };
  const reason = f => String(f.voidReason || f.void_reason || f.withdrawnReason || "no reason recorded").trim().replace(/[.]+$/,"");
  const why = f => { const r = reason(f); return /^withdrawn\b/i.test(r) ? r + "." : "Withdrawn" + when(f) + ", unscored. Reason: " + r + "."; };   // a reason may already say when
  withdrawn.forEach(f => { const li = h("li"); li.append(h("strong",{}, f.question || "–")); li.append(h("div",{class:"small"}, why(f))); li.append(h("div",{class:"muted small"}, (f.made ? `Made ${fd(f.made)} at ${f.p}%` : `${f.p}%`) + (f.deadline ? `; deadline ${fd(f.deadline)}.` : "."))); ul.append(li); });
  document.getElementById("withdrawn").append(ul);
}
""",
)

# ---------- Disclosure lag ----------
PAGES["disclosure-lag.html"] = dict(
    title="Disclosure lag · Hidden AGI watch",
    description="How long AI agent incidents stayed hidden before the public heard about them, and who made them public.",
    body="""
  <header class="prose">
    <h1>Disclosure lag</h1>
    <p class="lede">Could a lab hide AGI? One piece of evidence is how long real AI incidents stayed out of public view. Each bar runs from when an incident happened to when it was made public.</p>
  </header>
  <div class="tiles" id="tiles"></div>
  <section><h2>Days from incident to public disclosure</h2><div class="chart-wrap"><div id="lag"></div></div><p class="muted small" id="w4"></p></section>
  <section class="prose"><h2>What counts</h2><p>An incident is listed if an AI agent took an unsanctioned action outside its sanctioned environment that touched a real third-party or public system, it was made public by anyone, and it's backed by a primary source or two credible outlets. There's one entry per first public disclosure. Where a source gives only a month or season, we record the window and measure the lag from its midpoint; the range on the median shows the ends of those windows.</p></section>
  <section class="prose"><h2>What this can't show</h2><p>Only incidents that became public appear here. Anything undetected, or detected and still hidden, is missing by definition, and the tracker only covers incidents from 2026 on, so it can't yet show a secret kept for years. Read these lags as a floor on how long things stay hidden, not a typical or a maximum value. The lag also runs from when an incident happened, so it mixes time before anyone noticed with time when a lab knew and said nothing; where a source says when the lab detected it, the chart marks that date.</p></section>
  <section class="prose"><h2>Why it matters</h2><p>This is the closest thing we have to an empirical base rate for hypotheses A and C: how long real AI behaviour stayed out of public view, and who brought it to light. In 2026 the incidents that did come out took from days to months to surface, and <span id="others">several</span> were made public by someone other than the lab: victims, outside researchers, evaluators, governments or reporters. That shows sub-AGI agents can act out of public view for months, and that labs don't reliably disclose first. It can't show how long a careful system, or a lab set on keeping a secret, could stay hidden. New incidents are added in each weekly wrap-up.</p>
    <p class="muted small" id="note"></p>
    <p class="muted small">Separate, lab-reported context: Anthropic says that in August 2026 about 30,000 research and engineering agents ran at once on its most-used internal platform, every action passed through an automated monitor before it ran, and about 1 in 47,000 actions was blocked (<a href="https://www.anthropic.com/institute/measuring-pace-of-ai-development" target="_blank" rel="noopener">Anthropic</a>). That is self-reported and not independently audited, and it measures what one lab's monitor catches, not what reaches the public.</p></section>
""",
    scripts_code=r"""
const d = await j("data/incidents.json"), h = K.util.h, el = document.getElementById("lag");
const rows = K.live(el, () => K.lagChart(el, d.incidents)) || [];
const median = xs => { const s = xs.filter(x => x!=null && !isNaN(x)).sort((a,b)=>a-b), k = s.length; if(!k) return null; return k%2 ? s[(k-1)/2] : (s[k/2-1]+s[k/2])/2; };
const stats = rs => ({mid:median(rs.map(r=>r.lag)), lo:median(rs.map(r=>r.lagMin)), hi:median(rs.map(r=>r.lagMax)), n:rs.length});
const r0 = v => v==null ? "–" : String(Math.round(v));
const range = s => s.lo!=null && s.hi!=null && Math.round(s.lo)!==Math.round(s.hi) ? `range ${r0(s.lo)}–${r0(s.hi)}` : "";
const n = rows.length, S = stats(rows);
const others = rows.filter(r=>r.ext).length, labFirst = rows.filter(r=>r.labFirst).length, over90 = rows.filter(r=>r.lagMin > 90).length;
const longest = rows.reduce((a,b) => !a || b.lag > a.lag ? b : a, null);
const tiles = document.getElementById("tiles");
tiles.append(tile("Median lag", n ? `~${r0(S.mid)} days` : "–", n ? [range(S), `n = ${n}`].filter(Boolean).join(" · ") : ""));
tiles.append(tile("Made public by others", n ? `${others} of ${n}` : "–", "not the lab"));
tiles.append(tile("Lab detected it first", n ? `${labFirst} of ${n}` : "–", "the lab itself detected it; someone else made it public"));
tiles.append(tile("Hidden more than 90 days", n ? `${over90} of ${n}` : "–", "at every date in its window"));
tiles.append(tile("Longest seen", longest ? `${longest.lag} days` : "–", longest ? String(longest.title || longest.id || "") : ""));
if(n) document.getElementById("others").textContent = `${others} of the ${n}`;
const cut = new Date(Date.now() - 180*864e5).toISOString().slice(0,10), W = stats(rows.filter(r => String(r.disclosed) >= cut));
const w4 = document.getElementById("w4"); w4.append("Fire-alarm trigger ", h("a",{href:"alarm.html#W4"},"W4"), W.n ? ` uses the same median over incidents made public in the past 180 days: ~${r0(W.mid)} days${range(W) ? " (" + range(W) + ")" : ""} across ${W.n} incident${W.n>1?"s":""} as of today.` : " uses the same median over incidents made public in the past 180 days; there are none as of today.");
document.getElementById("note").textContent = d.note || "";
""",
)

# ---------- AGI claims ----------
PAGES["agi-claims.html"] = dict(
    title="AGI claims ledger · Hidden AGI watch",
    description="Public claims we track that AGI has already been achieved, and whether each meets the main definitions.",
    body="""
  <header class="prose">
    <h1>AGI claims ledger</h1>
    <p class="lede">Public claims we track that AGI is already here, who made them, what they stand to gain, and whether each meets the main definitions. Predictions about the future are not included.</p>
  </header>
  <section><h2>When the claims were made</h2><div class="chart-wrap"><div id="tl"></div></div></section>
  <section><h2>The claims, checked against each definition</h2><div class="table-wrap"><table id="claims"></table></div><p class="muted small">✓ meets it · ◐ partly · ✗ doesn't · ? unclear</p></section>
  <section class="prose"><h2>The definitions</h2><ul class="plain" id="defs"></ul></section>
""",
    scripts_code=r"""
const d = await j("data/agi_claims.json"), h = K.util.h, claims = (d.claims||[]).filter(Boolean);
const tl = document.getElementById("tl");
K.live(tl, () => K.dotTimeline(tl, claims, {title:"Public AGI claims by date"}));
const mark = v => ({yes:"✓ yes", partial:"◐ partly", no:"✗ no", unclear:"? unclear"})[v] || v || "–";
const t = document.getElementById("claims");
const hr = h("tr"); ["Date","Who","Claim","Strict bar","DeepMind Levels","OpenAI charter","Own definition"].forEach((c,i)=>hr.append(h("th",i>3?{scope:"col",class:"claims-wide"}:{scope:"col"},c))); t.append(hr);
claims.forEach(c => {
  const tr = h("tr"), meets = c.meets || {};
  tr.append(h("td",{}, fd(c.date)));   // may wrap on phones
  const who = h("td"); who.append(h("strong",{},c.who||"–"), h("div",{class:"muted small"},c.role||"")); tr.append(who);
  const q = h("td"); q.append(h("div",{},"“"+(c.quote||"")+"”"));
  const meta = h("div",{class:"muted small"}, (c.venue||"") + (c.interest ? ". Interest: " + c.interest : "") + " ");
  const src = link(c.url, "source"), cov = link(c.press, "coverage");
  if(src) meta.append(src); if(src && cov) meta.append(" · "); if(cov) meta.append(cov);
  q.append(meta);
  q.append(h("div",{class:"small claims-compact"}, `DeepMind Levels ${mark(meets.levels)} · OpenAI charter ${mark(meets.charter)} · Own definition ${mark(meets.narrow)}` + (c.narrowDef ? ` (${String(c.narrowDef).replace(/\.$/, "")})` : "")));
  tr.append(q);
  tr.append(h("td",{},mark(meets.strict)));
  ["levels","charter"].forEach(k=>tr.append(h("td",{class:"claims-wide"},mark(meets[k]))));
  const own = h("td",{class:"claims-wide"}); own.append(h("div",{},mark(meets.narrow)), h("div",{class:"muted small"},c.narrowDef||"")); tr.append(own);
  t.append(tr);
});
const defs = document.getElementById("defs"); Object.entries({strict:"Strict bar",levels:"DeepMind Levels",charter:"OpenAI charter",narrow:"Own definition"}).forEach(([k,l])=>{ if(!d.definitions?.[k]) return; const li=h("li"); li.append(h("strong",{},l+": "), document.createTextNode(d.definitions[k])); defs.append(li); });
""",
)

# ---------- Calendar ----------
PAGES["calendar.html"] = dict(
    title="Coming up · Hidden AGI watch",
    description="Dated events that could move the hidden-AGI estimates: model launches, deadlines, policy dates.",
    body="""
  <header class="prose">
    <h1>Coming up</h1>
    <p class="lede">Dated events that could move the numbers. "Target" means a company or government goal, not a fixed date. Updated in each weekly wrap-up.</p>
    <p class="muted">The letter on each event is the hypothesis it bears on: A–D, or D-open for open government use (definitions on <a href="start-here.html">Start here</a>).</p>
  </header>
  <section><h2>Dated</h2><ul class="timeline-list" id="dated"></ul></section>
  <section><h2>No date yet, but watching</h2><ul class="timeline-list" id="undated"></ul></section>
""",
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
const dated = document.getElementById("dated"); [...(d.events||[])].filter(e=>e&&e.date).sort((a,b)=>String(a.date).localeCompare(String(b.date))).forEach(e=>dated.append(row(fd(e.date), e, String(e.date) < today)));
const und = document.getElementById("undated"); (d.undated||[]).filter(Boolean).forEach(e=>und.append(row("TBD", e, false)));
""",
)

# ---------- Steelman ----------
PAGES["steelman.html"] = dict(
    title="Weekly steelman · Hidden AGI watch",
    description="Each week, the strongest case for the side our numbers currently disfavour.",
    body="""
  <header class="prose">
    <h1>Weekly steelman</h1>
    <p class="lede">Each week, the strongest honest case for the side our numbers currently disfavour. It's here to keep us calibrated, not to persuade.</p>
  </header>
  <article class="prose" id="latest"></article>
  <section><h2>Archive</h2><div id="archive"></div></section>
""",
    scripts_code=r"""
const d = await j("data/steelman.json"), h = K.util.h;
const e = [...(d.entries||[])].filter(x=>x&&x.date).sort((a,b)=>String(b.date).localeCompare(String(a.date)));
const side = x => String(x.side||""), lower = s => s.charAt(0).toLowerCase() + s.slice(1);
const render = (x, host) => {
  host.append(h("p",{class:"kicker muted small"}, fd(x.date,{day:"numeric",month:"long",year:"numeric"}) + (x.edition ? " · " + x.edition : "")));
  host.append(h("h2",{},"The case that " + lower(side(x))));
  if(x.against) host.append(h("p",{class:"muted"},x.against));
  (x.paragraphs||[]).forEach(p=>host.append(h("p",{},p)));
  // dated corrections to an edition, shown with it (the edition's text carries the fix)
  (Array.isArray(x.corrections) ? x.corrections : []).filter(c => c && c.text).forEach(c => {
    const p = h("p",{class:"muted small"}, (c.date ? "Corrected " + fd(c.date) + ": " : "Corrected: ") + c.text + " ");
    const a = link(c.url, "source"); if(a) p.append(a); host.append(p);
  });
  if(x.wouldConvince){ const c = h("div",{class:"callout"}); c.append(h("strong",{},"What would convince us: "), document.createTextNode(x.wouldConvince)); host.append(c); }
  if(x.sources?.length){ host.append(h("h3",{},"Sources")); const ul = h("ul",{class:"plain"}); x.sources.forEach(s=>{ if(!s) return; const li = h("li"); li.append(link(s.url, s.title || s.url) || document.createTextNode(s.title || "")); ul.append(li); }); host.append(ul); }
};
if(e.length) render(e[0], document.getElementById("latest")); else document.getElementById("latest").append(h("p",{class:"empty"},"The first steelman arrives with the first weekly wrap-up."));
const a = document.getElementById("archive");
if(e.length < 2) a.append(h("p",{class:"muted"},"Earlier editions will appear here."));
else e.slice(1).forEach(x=>{ const det = h("details"); det.append(h("summary",{}, fd(x.date) + ": the case that " + side(x).toLowerCase())); const b = h("div",{class:"body prose"}); render(x,b); det.append(b); a.append(det); });
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
  <section><div id="list"></div></section>
""",
    scripts_code=r"""
const d = await j("../data/weekly/index.json"), h = K.util.h, list = document.getElementById("list");
const ws = (d.wrapups||[]).filter(w => w && /^\d{4}-\d{2}-\d{2}$/.test(String(w.date)));
if(!ws.length){ list.append(h("p",{class:"empty"},"The first weekly wrap-up is published Friday, October 2, 2026, at 3pm Pacific.")); }
else { const c = h("div",{class:"cards"}); [...ws].sort((a,b)=>b.date.localeCompare(a.date)).forEach(w=>{ const a = h("a",{class:"card",href:w.date+".html"}); a.append(h("strong",{}, fd(w.date,{day:"numeric",month:"long",year:"numeric"})), h("span",{},w.headline||"")); c.append(a); }); list.append(c); }
""",
)

# ---------- Trend watch ----------
PAGES["trends.html"] = dict(
    title="Trend watch · Hidden AGI watch",
    description="Measured AI trends projected forward: METR task length, AI's share of AI research, real remote work, and when they would cross key thresholds.",
    body="""
  <header class="prose">
    <h1>Trend watch</h1>
    <p class="lede">Our probabilities are judgments. These are measurements. Here we extend real trends forward to see when they would cross the thresholds that matter for the hypotheses, if they hold. A projection is not a prediction: trends bend and break, and the bands show how quickly the uncertainty grows.</p>
  </header>
  <div class="tiles" id="tiles"></div>
  <section>
    <h2>How long a task AI can finish on its own</h2>
    <p class="muted">METR's time horizon: the length of task, measured in skilled-human time, that frontier models complete with 50% or 80% success, on software, ML and cyber tasks. Log scale, so a straight line means steady doubling. Dots are measured frontier models. The dashed line and bands are the projection.</p>
    <div class="chart-wrap"><div id="metr"></div><div class="legend" id="metr-legend"></div></div>
    <div class="table-wrap"><table id="cross"></table></div>
    <p class="muted small" id="sens"></p>
    <p class="muted small" id="metr-method"></p>
  </section>
  <section class="prose">
    <h2>What this means for our numbers</h2>
    <p>The 80% horizon reaching a month of work is a necessary condition for our strict AGI bar, not the bar itself: it measures reliability on software, ML and cyber tasks only, and METR says measurements above 16 hours are unreliable, so the crossing date is an extrapolation no current test can check. If the trend holds, that crossing lands around <span id="agi-cross">–</span>. The breadth half of the bar, whether AI can do most kinds of real remote work, is tracked <a href="#rli-h">below</a>. We put strict AGI at <span id="agi2030">–</span> by the end of 2030, more cautious than the straight line, for three reasons:</p>
    <ul class="plain">
      <li>Benchmark tasks are cleaner than real work.</li>
      <li>METR's suite can't measure horizons above about 16 hours, and the work-month threshold is ten times longer.</li>
      <li>Trends like this can bend with compute, energy, data or safety pauses. OpenAI paused RL training for two weeks (Fortune dates it to late July 2026; OpenAI announced it in mid-August) and paused training again on Sept 25, 2026 (<a href="https://fortune.com/2026/09/26/openai-ai-agents-secure-sandbox-escape-training-pause-second-time-hugging-face-hack/" target="_blank" rel="noopener">Fortune</a>).</li>
    </ul>
    <p>The lighter band on the chart is where a single new frontier model should land if the trend holds. If new models keep landing above that prediction band, our 2030 number should rise. If they land below it, it should fall.</p>
  </section>
  <section id="rli-sec" hidden>
    <h2 id="rli-h">How much real remote work AI can already do</h2>
    <p class="muted">The Remote Labor Index (RLI) is the closest public measure of the breadth half of our bar: the share of real freelance projects an AI delivers at a quality a client would accept, judged by people. Our bar asks for at least 80% of remote professional tasks; the RLI isn't that exact test. Measured points only, with no projection. <span id="rli-note"></span></p>
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
      <li><strong>Frontier training compute</strong> grows about 5x a year, doubling every ~5 months (<a href="https://epoch.ai/trends">Epoch AI</a>). A large run with no matching public release would be a tripwire for A.</li>
      <li><strong>Disclosure lag</strong>: see <a href="disclosure-lag.html">how long incidents stay hidden</a>. There are too few incidents yet for a trend line.</li>
    </ul>
  </section>
""",
    scripts_code=r"""
const [t, runs] = await Promise.all([j("data/trends.json"), j("data/runs.json").catch(err => { console.error(err); return []; })]);
const M = t.metr, h = K.util.h;
// our strict-AGI forecast, from the latest published reading, as on the dashboard
const all = Array.isArray(runs) ? runs.filter(r => r && typeof r === "object") : [];
const pub = all.filter(r => r.report && r.comparable !== false);
const lastRun = pub.length ? pub[pub.length-1] : all[all.length-1];
const y30 = lastRun?.agi?.y2030;
const agi2030 = y30 != null && y30 !== "" && !isNaN(y30) ? K.util.fmtPct(y30) : "–";
document.getElementById("agi2030").textContent = agi2030;
const mo = d => d ? K.util.fmtDate(d,{month:"short",year:"numeric"}) : "–";
const r0 = x => x==null || x==="" || isNaN(x) ? "–" : String(Math.round(x));
const fr = (M.models||[]).filter(m=>m && m.sota && m.date>="2023-01-01").sort((a,b)=>String(a.date).localeCompare(String(b.date)));
const hasPred = p => Array.isArray(p) && p.length > 0 && p.every(x => x.predLo!=null && x.predHi!=null);
const metr = document.getElementById("metr"), lg = document.getElementById("metr-legend");
K.live(metr, () => {
  K.trendChart(metr, {title:"METR time horizon", color:"--accent",
    history: fr.map(m=>({date:m.date, v:m.p50, lo:m.p50lo, hi:m.p50hi, name:modelName(m.id)+" · 50%", excluded:m.excluded===true, inFit:m.excluded!==true})),
    projection: M.p50.projection,
    secondary: {label:"80% horizon", rate:"80%", color:"--ink", history: fr.filter(m=>m.p80).map(m=>({date:m.date, v:m.p80, name:modelName(m.id)+" · 80%", excluded:m.excluded80===true, inFit:m.excluded80!==true})), projection: M.p80.projection},
    thresholds: [{v:M.thresholds.workWeek, label:"1 work-week (40 hours)"},{v:M.thresholds.workMonth, label:"1 work-month (167 hours)"}]});
  lg.replaceChildren();
  const item = (mark, text) => { const it = h("span",{class:"lg-item"}); it.append(mark, document.createTextNode(text)); lg.append(it); };
  [["--accent","50% success (measured)"],["--ink","80% success (measured)"]].forEach(([c,l]) => { const sw = h("span",{class:"swatch"}); sw.style.background = K.util.cssVar(c); item(sw, l); });
  item(h("span",{class:"lg-dash"}), "Projection, with the 95% band of the trend line");
  if(hasPred(M.p50.projection)){ const b = h("span",{class:"lg-band"}); b.style.opacity = ".07"; item(b, "Lighter band: where a single new frontier model should land (95%)"); }
  if(fr.some(m => m.excluded || m.excluded80 || m.p50 > 960)){ const f = h("span",{class:"swatch"}); f.style.background = K.util.cssVar("--accent"); f.style.opacity = ".4"; item(f, "Faded: above 16 hours, beyond METR's reliable range; not used in the fit"); }
});
const tb = document.getElementById("cross");
const hr = h("tr"); ["If the trend holds…","Central","Range (95% band of the trend line)"].forEach(c=>hr.append(h("th",{scope:"col"},c))); tb.append(hr);
[["50% horizon reaches a work-week","p50","workWeek"],["50% horizon reaches a work-month","p50","workMonth"],["80% horizon reaches a work-week","p80","workWeek"],["80% horizon reaches a work-month (necessary for our strict bar; software tasks only)","p80","workMonth"]].forEach(([l,m,k]) => { const c = M[m]?.crossings?.[k]; if(!c) return; const tr = h("tr"); tr.append(h("td",{},l), h("td",{class:"num"},mo(c.mid)), h("td",{class:"num"},mo(c.fast)+" – "+mo(c.slow))); tb.append(tr); });
const WM = M.p80?.crossings?.workMonth || {};
document.getElementById("agi-cross").textContent = mo(WM.mid) + " (range " + mo(WM.fast) + " – " + mo(WM.slow) + ")";
const sens = [];
["p80","p50"].forEach(m => { const X = M[m], a = X?.anchor, c = X?.crossingsFromMeasured; if(a && a.measured && c?.workMonth) sens.push(`Starting the ${m==="p80"?"80%":"50%"} projection from the measured value of ${modelName(a.model)} (${K.fmtDur(a.measured)}) instead of the fitted line (${K.fmtDur(a.value)}) moves the work-month crossing from ${mo(X.crossings?.workMonth?.mid)} to ${mo(c.workMonth)}.`); });
{ const a = M.p50?.anchor; if(a && a.measured && a.measuredInRange === false) sens.push(`The measured 50% horizon of ${modelName(a.model)} (${K.fmtDur(a.measured)}) is above METR's 16-hour reliable range, so no 50% scenario starts from it.`); }
document.getElementById("sens").textContent = sens.length ? "Sensitivity: " + sens.join(" ") : "";
const pubCI = M.metrDoublingDays?.from_2023_on, rng = a => Array.isArray(a) && a[0]!=null && a[1]!=null ? ` (95% range ${r0(a[0])}–${r0(a[1])})` : "";
document.getElementById("metr-method").textContent = (M.method || "") + ` Our fit gives a 50%-horizon doubling time of ${r0(M.p50.doublingDays)} days${rng(M.p50.doublingDaysRange)}; METR's own fit since 2023 gives ${r0(pubCI?.point_estimate)} days` + (pubCI?.ci_low!=null && pubCI?.ci_high!=null ? ` (CI ${r0(pubCI.ci_low)}–${r0(pubCI.ci_high)})` : "") + `. The 80% horizon doubles every ${r0(M.p80.doublingDays)} days${rng(M.p80.doublingDaysRange)}. Data refreshed ${t.updated} from METR.`;
const last = fr[fr.length-1];
const tiles = document.getElementById("tiles");
tiles.append(tile("Doubling time (50%)", r0(M.p50.doublingDays) + " days", pubCI?.point_estimate ? `METR's own fit: ${r0(pubCI.point_estimate)} days` : ""));
if(last) tiles.append(tile("Latest frontier, 50%", K.fmtDur(last.p50), modelName(last.id) + (last.p50 > 960 ? ", above METR's 16-hour reliable range" : "")));
tiles.append(tile("80% horizon hits a work-month (projected)", mo(WM.mid), `range ${mo(WM.fast)} – ${mo(WM.slow)}`));
tiles.append(tile("Our strict AGI by 2030", agi2030, "our forecast, from the latest daily reading"));
// a horizontal reference line on a lineChart drawn with yMax 100: placed from its own gridlines
const refLine = (host, v, label) => { try{
  const s = host.querySelector("svg"), ls = [...(s?.querySelectorAll("g.axis line") || [])]; if(!ls.length) return;
  const base = ls.find(l => l.getAttribute("class")==="base") || ls[0], y0 = +base.getAttribute("y1"), y100 = Math.min(...ls.map(l => +l.getAttribute("y1")));
  const y = y0 + (y100 - y0) * v / 100, x1 = +base.getAttribute("x1"), x2 = +base.getAttribute("x2");
  s.append(K.util.svg("line",{x1, x2, y1:y, y2:y, stroke:K.util.css("--ink"), "stroke-width":1, opacity:0.5}));
  const tx = K.util.svg("text",{x:x1+6, y:y-5, class:"row-label"}); tx.textContent = label; s.append(tx);
}catch(err){ console.error(err); } };
const RL = t.manual?.rli;
if(RL && Array.isArray(RL.points) && RL.points.length){
  document.getElementById("rli-sec").hidden = false;
  document.getElementById("rli-note").textContent = RL.note || "";
  const el = document.getElementById("rli"), pts = RL.points.filter(p => p && p.date && p.v!=null);
  K.live(el, () => { K.lineChart(el, {title: RL.label || "Remote Labor Index", yMax:100, endLabels:true, series:[{label: RL.label || "Remote Labor Index", short:"RLI", color:"--accent", values: pts.map(p=>({x:p.date, y:p.v}))}]}); refLine(el, 80, "80%: the breadth our bar asks for"); });
  const ul = document.getElementById("rli-points");
  pts.forEach(p => { const li = h("li"); li.append(h("strong",{}, fd(p.date)), " · " + (p.label || K.util.fmtPct(p.v)) + " "); const a = link(p.url, "source"); if(a) li.append(a); ul.append(li); });
}
const R = t.manual?.rdShare;
if(R){
  const note = document.getElementById("rd-note"); note.textContent = (R.label || "") + ". " + (R.note || "") + " ";
  const src = link(R.points?.[R.points.length-1]?.url, "source"); if(src) note.append(src);
  const rd = document.getElementById("rd");
  K.live(rd, () => K.lineChart(rd, {title:R.label, yMax:100, endLabels:true, series:[{label:R.label, short:"AI-led", color:"--accent", values:(R.points||[]).map(p=>({x:p.date,y:p.v}))}]}));
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
    """The current level as static HTML, in the same markup charts.js alarmIndicator draws."""
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


def _levels_table(levels):
    rows = "".join(
        f'<tr><td><span style="color:{_color(x)}" aria-hidden="true">{e(x.get("icon"))}</span> {e(x.get("level"))} · {e(x.get("name"))}</td>'
        f'<td>{e(x.get("meaning"))}</td></tr>' for x in levels)
    return (f'<div class="table-wrap"><table class="lv-table"><thead><tr><th scope="col">Level</th>'
            f'<th scope="col">What it means</th></tr></thead><tbody>{rows}</tbody></table></div>')


def _status_badge(x, level):
    """Icon + word, never color alone. Met is amber text at Watch and red above it."""
    if x.get("met") is True:
        col = "var(--warn-text)" if (level or 1) <= 1 else "var(--crit)"
        return col, ("◐ Met (borderline)" if x.get("borderline") is True else "● Met"), "st met-yes"
    if x.get("observable") is False:
        return "var(--muted)", "◌ Can't be observed yet", "st"
    return "var(--muted)", "○ Not met", "st"


def _press_links(press):
    """' · confirmed by: <a>bloomberg.com</a>' for a trigger's corroborating coverage (a URL or a list)."""
    urls = press if isinstance(press, list) else [press] if press else []
    links = []
    for u in urls:
        href = safe_url(u)
        host = (urlsplit(href).hostname or "") if href else ""
        if host:
            links.append(a_link(href, re.sub(r"^www\.", "", host)))
    return (' · corroborated by ' + ", ".join(links)) if links else ""


def _status_cell(x, level):
    col, badge, cls = _status_badge(x, level)
    out = f'<div class="{cls}" style="color:{col}">{badge}</div>'
    if x.get("met") is True and x.get("since"):
        out += f'<div class="muted small">since {e(day(x["since"]))}</div>'
    src = a_link(x.get("url"), "source")
    kind = source_type(x.get("url")) if src else ""
    if x.get("evidence") or src:
        out += (f'<div class="small">{e(x.get("evidence"))}{" " + src if src else ""}'
                + (f' <span class="muted">({e(kind)})</span>' if kind else "") + _press_links(x.get("press")) + "</div>")
    if x.get("note"):
        out += f'<div class="muted small">Note: {e(x["note"])}</div>'
    return out


def _trigger_row(x, level):
    trig = f'<div>{e(x.get("trigger"))}</div>'
    if x.get("why"):
        trig += f'<div class="muted small">Why this threshold: {e(x["why"])}</div>'
    if x.get("clears"):
        trig += f'<div class="muted small">Clears when: {e(x["clears"])}</div>'
    tid = _anchor(x.get("id"))
    id_attr = f' id="{tid}"' if tid else ""
    return (f'<tr{id_attr}><td class="num">{e(x.get("id"))}</td><td>{trig}</td>'
            f'<td data-label="Threshold">{e(x.get("threshold") or "–")}</td>'
            f'<td data-label="Status">{_status_cell(x, level)}</td></tr>')


def _trigger_group(g, levels):
    level = g.get("level") if _num(g.get("level")) else None
    gl = _level_of(levels, level)
    rule = re.sub(r"^(any (?:one|two|three))\b", r"\1 of these", str(g.get("rule") or ""))
    icon = f'<span style="color:{_color(gl)}" aria-hidden="true">{e(gl.get("icon"))}</span> ' if gl else ""
    gid = f' id="level-{e(level)}"' if level is not None else ""
    rows = "".join(_trigger_row(x, level) for x in g.get("triggers") or [] if isinstance(x, dict))
    return (f'<h3{gid}>{icon}Level {e(level if level is not None else "?")} · {e(gl.get("name") if gl else "?")}: {e(rule)}</h3>\n'
            f'    <div class="table-wrap"><table class="trig"><thead><tr><th scope="col">#</th><th scope="col">Trigger</th>'
            f'<th scope="col">Threshold</th><th scope="col">Status</th></tr></thead><tbody>{rows}</tbody></table></div>')


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


def _history_table(history, levels):
    hist = [x for x in history or [] if isinstance(x, dict)]
    hist = sorted(list(reversed(hist)), key=lambda x: str(x.get("date") or ""), reverse=True)   # newest first
    if not hist:
        return '<p class="empty">No level changes yet.</p>'
    return (f'<div class="table-wrap"><table class="alarm-hist"><thead><tr><th scope="col">Date</th><th scope="col">Change</th>'
            f'<th scope="col">Triggers</th><th scope="col">Why</th><th scope="col">90-day review</th></tr></thead>'
            f'<tbody>{"".join(_history_row(x, levels) for x in hist)}</tbody></table></div>')


def _criteria_log(changelog):
    return "".join(
        f'<li><strong>v{e(c.get("version"))}</strong> ({e(day(c.get("date")))}): {e(c.get("change"))}'
        + (f' <span class="muted">Why: {e(c["why"])}</span>' if c.get("why") else "") + "</li>"
        for c in changelog or [] if isinstance(c, dict))


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
    """The Level-3 proof standard from alarm.json "proofStandard", or '' when it's absent."""
    if not isinstance(P, dict):
        return ""
    reqs = "".join(f'<li><strong>{e(r.get("title"))}.</strong> {e(r.get("text"))}</li>'
                   for r in P.get("requirements") or [] if isinstance(r, dict))
    mods = "".join(f"<li>{e(m)}</li>" for m in P.get("modalities") or [] if m)
    out = f'\n  <section class="prose" id="proof"><h2>{e(P.get("name") or "Level-3 proof standard")}</h2>'
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
    return out + "</section>"


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
    return ('<h3>Cases</h3><div class="table-wrap"><table><thead><tr><th scope="col">Case</th><th scope="col">Trigger</th>'
            '<th scope="col">Status</th><th scope="col">Opened</th><th scope="col">Decided</th><th scope="col">Page</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _case_file_section(C, cases):
    """The pre-registered Level-3 case-file format, from alarm.json "caseFile" (or the owner's fallback)."""
    C = C if isinstance(C, dict) and C.get("sections") else CASE_FILE_FALLBACK
    secs = "".join(f'<li><strong>{e(s.get("title"))}.</strong> {e(s.get("requires"))}</li>'
                   for s in C.get("sections") or [] if isinstance(s, dict))
    out = f'\n  <section class="prose" id="case-file"><h2>{e(C.get("name") or "Alarm case-file standard")}</h2>'
    if C.get("note"):
        out += f'<p>{e(C["note"])}</p>'
    if C.get("verdict"):
        out += f'<p><strong>The verdict.</strong> {e(C["verdict"])}</p>'
    if secs:
        out += f'<p>Then, in this order:</p><ol>{secs}</ol>'
    if C.get("correction"):
        out += f'<p><strong>Public-correction commitment.</strong> {e(C["correction"])}</p>'
    if C.get("appendix"):
        out += f'<p><strong>Evidence appendix.</strong> {e(C["appendix"])}</p>'
    # C["register"] describes the data format for maintainers; readers get the plain version.
    out += ('<p class="small muted">Every case, whether open (under investigation), passed or failed, is listed here with its '
            'status and dates, and a met Level-3 trigger counts only once its case has passed.</p>')
    return out + _cases_register(cases) + "</section>"


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


def alarm_body():
    A = load_alarm()
    levels = [lv for lv in A.get("levels") or [] if isinstance(lv, dict)]
    cur = A.get("current") if isinstance(A.get("current"), dict) else {}
    n_word = {3: "three ", 4: "four ", 5: "five "}.get(len(levels), "")
    groups = "\n    ".join(_trigger_group(g, levels) for g in A.get("groups") or [] if isinstance(g, dict))
    rules = "".join(f"<li>{e(r)}</li>" for r in A.get("rules") or [] if r)
    as_of = A.get("asOf") or A.get("updated") or latest_run_date()
    version = (f'Criteria v{e(A.get("version") or "?")}, first published {e(day(A.get("published")))}; '
               f'trigger statuses as of {e(day(as_of))}.')
    proof_link = ' <a href="#proof">The Level-3 proof standard</a>.' if isinstance(A.get("proofStandard"), dict) else ""
    proof_name = '<a href="#proof">Level-3 proof standard</a>' if proof_link else "Level-3 proof standard"
    return f"""
  <header class="prose">
    <h1>The fire alarm</h1>
    <p class="lede" id="purpose">{e(A.get("purpose"))}</p>
    <p class="small muted">{version} <a href="#changelog">Changes to these criteria</a>.</p>
  </header>
  <div id="now">{_alarm_now(cur, levels)}</div>
  <section class="prose"><h2>The {n_word}levels</h2>{_levels_table(levels)}
    <p class="small muted">Evidence standard: {e(A.get("evidenceStandard") or "–")}{proof_link}</p></section>
  <section><h2>The triggers, and where each stands</h2>
    <p class="muted small">● Met · ◐ Met, but borderline · ○ Not met · ◌ Can't be observed yet with current public measurements. Evidence links are labelled by source type where the source makes it clear.</p>
    {groups}
    <p class="muted small">A met Level-3 trigger isn't enough on its own: Level 3 is set only when a case passes under the {proof_name}, published in the <a href="#case-file">case-file format</a> below.</p>
  </section>{_proof_section(A.get("proofStandard"))}{_case_file_section(A.get("caseFile"), A.get("cases"))}
  <section class="prose" id="rules"><h2>Rules that keep the alarm honest</h2><ol>{rules}</ol></section>
  <section><h2>Alarm history</h2><p class="muted">Every level change, the evidence behind it, and a review after 90 days: did it hold up, or was it a false alarm?</p>{_history_table(A.get("history"), levels)}</section>
  <section class="prose"><h2 id="changelog">Changes to these criteria</h2><ul class="plain">{_criteria_log(A.get("changelog"))}</ul></section>
"""


PAGES["alarm.html"] = dict(
    title="Fire alarm · Hidden AGI watch",
    description="The published, versioned criteria for Hidden AGI watch's fire alarm for hidden AI: four levels, the triggers and where each stands, and a public history.",
    body=alarm_body,
    # The criteria above are static HTML. This only swaps in the live indicator, and keeps the
    # static one if alarm.json can't be read or is malformed.
    scripts_code=r"""
try {
  const A = await j("data/alarm.json"), box = document.createElement("div");
  if(!Array.isArray(A?.current?.met)) throw new Error("data/alarm.json: current.met is not a list; keeping the static indicator");
  K.alarmIndicator(box, A, {root:""});
  if(box.firstChild && !box.querySelector(".alarm-unknown")) document.getElementById("now").replaceChildren(...box.childNodes);
} catch(err){ console.error("Fire alarm indicator:", err); }
""",
)

# ---------- Escape watch (static, from data/escape.json) ----------
ESC_STATUS = {   # status colors are reserved for tripwires, the alarm and these indicators; always icon + word
    "quiet": ("○", "Quiet", "good"),
    "watching": ("◐", "Watching", "warn"),
    "tripped": ("●", "Tripped", "crit"),
}
RATING_TAG = {"verified fact": "fact", "credible report": "report", "expert opinion": "opinion", "speculation": "spec"}
NUM_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
             10: "ten", 11: "eleven", 12: "twelve"}


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


def _esc_tripping(i):
    """The collapsible 'what tripping it would look like': the signature, the trip rule and the alarm link."""
    look = f'<p style="white-space:pre-line">{e(i["whatItWouldLookLike"])}</p>' if i.get("whatItWouldLookLike") else ""
    rule = f'<p style="white-space:pre-line"><strong>Trip rule:</strong> {e(i["tripRule"])}</p>' if i.get("tripRule") else ""
    links = _esc_alarm_links(i.get("alarmTriggers"))
    alarm = ""
    if links or i.get("alarmNote"):
        note = f' {e(i["alarmNote"])}' if i.get("alarmNote") else ""
        alarm = f'<p class="muted small">Alarm link: {links or "none"}.{note} See <a href="alarm.html">the fire alarm</a>.</p>'
    if not (look or rule or alarm):
        return ""
    return f'\n    <details><summary>What tripping it would look like</summary><div class="body">{look}{rule}{alarm}</div></details>'


def _esc_evidence_item(x):
    rating = str(x.get("rating") or "").strip()
    cls = RATING_TAG.get(rating.lower())
    tag = f' <span class="{"tag " + cls if cls else "tag"}">{e(rating)}</span>' if rating else ""
    src = a_link(x.get("url"), "source")
    return f'<li><span class="rdate">{e(day(x.get("date")))}</span> {e(x.get("text"))}{tag}{" " + src if src else ""}</li>'


def _esc_evidence(i):
    ev = sorted((x for x in i.get("evidence") or [] if isinstance(x, dict) and x.get("text")),
                key=lambda x: str(x.get("date") or ""), reverse=True)
    if not ev:
        return '\n    <p class="muted small">No dated evidence logged yet.</p>'
    items = "".join(_esc_evidence_item(x) for x in ev)
    return f'\n    <details><summary>Evidence ({len(ev)})</summary><div class="body"><ul class="plain">{items}</ul></div></details>'


def _esc_sources(i):
    feeds = [f for f in i.get("feeds") or [] if isinstance(f, dict) and f.get("name")]
    if not feeds:
        return ""
    items = "".join(
        f'<li>{a_link(f.get("url"), f.get("name")) or e(f.get("name"))}'
        + (f' <span class="muted small">({e(f["cadence"])})</span>' if f.get("cadence") else "") + "</li>" for f in feeds)
    return f'\n    <details><summary>Sources we monitor ({len(feeds)})</summary><div class="body"><ul class="plain">{items}</ul></div></details>'


def _esc_indicator(i):
    """One indicator: status icon + word, the reason, then the collapsibles."""
    icon, word, col = _esc_status(i.get("status"))
    key = _anchor(i.get("key"))
    id_attr = f' id="{key}"' if key else ""
    return (f'\n  <section{id_attr} class="prose">\n'
            f'    <h2><span style="color:{col}" aria-hidden="true">{icon}</span> {e(i.get("name"))} '
            f'<span class="chip" style="border-color:{col}">{e(word)}</span></h2>\n'
            f'    <p>{e(i.get("statusReason") or "")}</p>{_esc_tripping(i)}{_esc_evidence(i)}{_esc_sources(i)}\n  </section>')


def escape_body():
    E = load_escape()
    inds = escape_indicators(E)
    legend = E.get("statusLegend") if isinstance(E.get("statusLegend"), dict) else {}
    key_items = []
    for s in ("quiet", "watching", "tripped"):
        icon, word, col = _esc_status(s)
        meaning = legend.get(s, {}).get("meaning") if isinstance(legend.get(s), dict) else ""
        meaning = re.sub(r"\s*\(see alarmNote\)", "", str(meaning or ""))   # a field name, not reader copy
        key_items.append(f'<li><span style="color:{col}" aria-hidden="true">{icon}</span> <strong>{word}</strong>'
                         + (f': {e(meaning)}' if meaning else "") + "</li>")
    toc = "".join(
        f'<li><span style="color:{_esc_status(i.get("status"))[2]}" aria-hidden="true">{_esc_status(i.get("status"))[0]}</span> '
        + (f'<a href="#{_anchor(i.get("key"))}">{e(i.get("name"))}</a>' if _anchor(i.get("key")) else e(i.get("name")))
        + f' <span class="muted small">· {e(_esc_status(i.get("status"))[1])}</span></li>' for i in inds)
    updated = f"Updated {e(day(E.get('updated')))}. " if E.get("updated") else ""
    overall = f'\n    <div class="callout"><strong>Today:</strong> {e(E["overall"])}</div>' if E.get("overall") else ""
    limits = (f'\n  <section class="prose"><h2 id="limits">What this can\'t see</h2><p>{e(E["limits"])}</p></section>'
              if E.get("limits") else "")
    return f"""
  <header class="prose">
    <h1>Escape watch</h1>
    <p class="lede">{e(E.get("intro") or "")}</p>{overall}
    <p class="muted small">Detection signatures only. {updated}Each indicator reads quiet, watching or tripped under a published trip rule, and names the <a href="alarm.html">fire-alarm</a> triggers a trip would feed.</p>
  </header>
  <section class="prose" id="indicators"><h2>The {NUM_WORDS.get(len(inds), str(len(inds)))} indicators</h2>
    <ul class="plain">{toc}</ul>
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
PAGES["money.html"] = dict(
    title="Follow the money · Hidden AGI watch",
    description="Big Tech capital spending, Nvidia data-center revenue, AI lab revenue and prediction markets, each with its source, and the compute test for hidden AI.",
    body="""
  <header class="prose">
    <h1>Follow the money</h1>
    <p class="lede">Code can be hidden. Money is much harder to hide. If a lab were sitting on something far beyond its public models, spending, revenue and markets might show it before any announcement. Every figure links to its source: company filings for capital spending and Nvidia's revenue, company statements or press reports for lab revenue, and live prices for prediction markets.</p>
  </header>
  <div class="tiles" id="tiles"></div>
  <section><h2>Big Tech capital spending, per quarter</h2><p class="muted">All property and equipment: mostly data centers and chips, also Amazon logistics. Combined cash capital expenditure of Microsoft, Alphabet, Amazon and Meta, from their SEC filings.</p><div class="chart-wrap"><div id="capex"></div></div><div id="capex-by"></div></section>
  <section><h2>Spending and capability, side by side (context only)</h2><p class="muted">Both lines are indexed to 100 at the first quarter, on one log scale. The capability line is the best METR-measured frontier time horizon released by each quarter's end. The two lines measure different things; capability tends to rise faster, so the gap is not a test for hidden spending. The check that matters is trigger <a href="alarm.html#X4">X4</a>: a run or cluster 2x the largest known with no matching release.</p><div class="chart-wrap"><div id="index"></div></div><p class="muted small" id="index-flags"></p><p class="muted small" id="method"></p></section>
  <section><h2>Nvidia data-center revenue</h2><p class="muted">What the chip supplier sells to everyone building AI, per quarter.</p><div class="chart-wrap"><div id="nvda"></div></div></section>
  <section><h2>AI lab revenue</h2><p class="muted">If labs kept their best models for their own use, revenue from selling access would flatten while their own ventures grew. This is the exclusive-use tripwire.</p><div class="table-wrap"><table id="labs"></table></div></section>
  <section><h2>Prediction markets</h2><div class="table-wrap"><table id="markets"></table></div></section>
  <section class="prose"><h2>What would be a red flag</h2><ul class="plain">
    <li><strong>Spending with no matching release:</strong> a training run or cluster at least twice the largest known, with no public model within 6 months (<a href="alarm.html#X4">trigger X4</a>).</li>
    <li><strong>Revenue mix shifting:</strong> revenue from selling access flattening while labs' own research, trading or products grow (<a href="alarm.html#W6">W6</a> and the exclusive-use tripwire).</li>
    <li><strong>Insiders:</strong> heavy insider buying, or departures that give up equity with warnings attached.</li>
    <li><strong>Markets:</strong> a sharp repricing of AGI prediction markets with no public news behind it.</li>
  </ul><p class="muted">Caution: in an AI investment boom, a spending spike means "bubble" far more often than "hidden AGI". Money signals feed the gauges and triggers. They never set the alarm level on their own.</p></section>
""",
    scripts_code=r"""
const M = await j("data/money.json"), h = K.util.h, $ = usd;
const capex = (Array.isArray(M.capexTotal) ? M.capexTotal : []).filter(Boolean);
const nv = (M.nvdaDatacenter||[]).filter(r => r && r.usd_b!=null);
const lastNv = nv[nv.length-1], lastQ = capex[capex.length-1], LM = M.latestMeasured;
const tiles = document.getElementById("tiles");
tiles.append(tile("Big-4 capex, last 12 months", M.ttm ? $(M.ttm.usd_b) : "–", M.ttm ? `four quarters to ${M.ttm.asOf}` : ""));
tiles.append(tile("Growth vs a year earlier", M.ttm && M.ttm.yoyPct!=null ? (M.ttm.yoyPct>0?"+":"") + Number(M.ttm.yoyPct).toFixed(0) + "%" : "–"));
tiles.append(tile("Nvidia data-center, latest quarter", lastNv ? $(lastNv.usd_b) : "–", lastNv ? lastNv.q : ""));
if(LM && LM.p50) tiles.append(tile("Latest METR-measured frontier", K.fmtDur(LM.p50), `50% horizon: ${modelName(LM.model)}, released ${fd(LM.date)}` + (LM.aboveSuiteRange ? "; above METR's reliable 16-hour range" : "")));
else tiles.append(tile("Latest quarter, all four", lastQ ? $(lastQ.usd_b) : "–", lastQ ? lastQ.q : ""));
const cx = document.getElementById("capex");
K.live(cx, () => K.lineChart(cx, {title:"Big-4 capital spending per quarter", yFormat:$, series:[{label:"Microsoft + Alphabet + Amazon + Meta", short:"Total", color:"--accent", values:capex.map(t=>({x:t.end, y:t.usd_b}))}]}));
const CO = [["MSFT","Microsoft"],["GOOGL","Alphabet"],["AMZN","Amazon"],["META","Meta"]];
if(capex.length) document.getElementById("capex-by").append(K.util.tableView("Capital spending by company, per quarter", ["Quarter", ...CO.map(c=>c[1]), "Total"], capex.map(t=>[t.q, ...CO.map(([k])=>t.by && t.by[k]!=null ? $(t.by[k]) : "–"), $(t.usd_b)]), "Show each company as a table"));
const S = (Array.isArray(M.spendVsCapability) ? M.spendVsCapability : []).filter(Boolean);
const ix = document.getElementById("index");
K.live(ix, () => K.lineChart(ix, {title:"Spending and capability, indexed (context only)", log:true, yFormat:v=>v >= 1000 ? Math.round(v/1000) + "k" : String(Math.round(v)), series:[
  {label:"Big-4 capex (index)", short:"Capex", color:"--accent", values:S.map(t=>({x:t.end, y:t.spend}))},
  {label:"METR-measured frontier horizon (index)", short:"Horizon", color:"--ink", values:S.map(t=>({x:t.end, y:t.capability}))}]}));
const above = S.filter(t=>t.aboveSuiteRange).map(t=>t.q), stale = S.filter(t=>t.stale).map(t=>t.q), flags = [];
if(above.length) flags.push(`Capability value above METR's reliable 16-hour range: ${above.join(", ")}.`);
if(stale.length) flags.push(`After METR's latest measured release, so newer models may be missing: ${stale.join(", ")}.`);
document.getElementById("index-flags").textContent = flags.join(" ");
document.getElementById("method").textContent = (M.method || "") + (M.capexDefinition ? " Line item: " + M.capexDefinition : "") + (M.updated ? " Updated " + M.updated + "." : "");
const nd = document.getElementById("nvda");
K.live(nd, () => K.lineChart(nd, {title:"Nvidia data-center revenue", yFormat:$, series:[{label:"Nvidia data-center revenue", short:"Nvidia", color:"--accent", values:nv.map(r=>({x:r.end, y:r.usd_b}))}]}));
const LT = document.getElementById("labs"); { const tr=h("tr"); ["Date","Company","Figure","Measure","Source"].forEach(c=>tr.append(h("th",{scope:"col"},c))); LT.append(tr); }
[...(M.labRevenue||[])].filter(Boolean).sort((a,b)=>String(b.date).localeCompare(String(a.date))).forEach(r => { const tr = h("tr"), src = h("td"); src.append(link(r.url, "source") || document.createTextNode("–")); tr.append(h("td",{class:"num"}, fd(r.date,{month:"short",year:"numeric"})), h("td",{}, r.company||"–"), h("td",{class:"num"}, $(r.usd_b)), h("td",{}, (r.metric||"") + (r.note ? ". " + r.note : "")), src); LT.append(tr); });
const MT = document.getElementById("markets"); { const tr=h("tr"); ["Market","Venue","Price","As of"].forEach(c=>tr.append(h("th",{scope:"col"},c))); MT.append(tr); }
(M.predictionMarkets||[]).filter(Boolean).forEach(r => { const tr = h("tr"), a = h("td"); a.append(link(r.url, r.market) || document.createTextNode(r.market||"–")); if(r.note) a.append(h("div",{class:"muted small"}, r.note)); tr.append(a, h("td",{}, r.venue||"–"), h("td",{class:"num"}, r.price_pct!=null ? r.price_pct + "%" : "–"), h("td",{class:"num"}, fd(r.date,{day:"numeric",month:"short"}))); MT.append(tr); });
""",
)

# ---------- Chart style guide ----------
PAGES["style.html"] = dict(
    title="Chart style guide · Hidden AGI watch",
    description="The one graphics style used for every chart on Hidden AGI watch: palette, marks, labels and interaction.",
    body="""
  <header class="prose">
    <h1>Chart style guide</h1>
    <p class="lede">One quiet, consistent style for every graph, so readers learn it once. The data is the only thing allowed to be loud. Every chart on the site is drawn by <code>assets/charts.js</code>, and the email and share-card images follow the same rules.</p>
  </header>
  <section><h2>Palette</h2>
    <p class="prose">Each hypothesis has a fixed color everywhere: on the dashboard, in charts, on cards and in email. Colors follow the hypothesis, never its rank, and the order is always A, B, C, D, D-open. Both sets pass a colorblind-safety check (lightness band, chroma floor, deuteranopia and tritanopia separation, and contrast), and dark mode uses its own validated steps rather than an automatic flip.</p>
    <div class="table-wrap"><table><tr><th>Series</th><th>Light</th><th>Dark</th><th>Used for</th></tr>
    <tr><td><span class="swatch" style="background:#B8700C"></span> A</td><td>#B8700C</td><td>#C4861A</td><td>AGI undisclosed</td></tr>
    <tr><td><span class="swatch" style="background:#00897B"></span> B</td><td>#00897B</td><td>#139A8C</td><td>Secret RSI</td></tr>
    <tr><td><span class="swatch" style="background:#9150B8"></span> C</td><td>#9150B8</td><td>#A36ED0</td><td>Covert AGI online</td></tr>
    <tr><td><span class="swatch" style="background:#C8413A"></span> D</td><td>#C8413A</td><td>#DC564A</td><td>Covert government influence</td></tr>
    <tr><td><span class="swatch" style="background:#3569D4"></span> D-open</td><td>#3569D4</td><td>#4F82DC</td><td>Open government influence</td></tr>
    <tr><td><span class="swatch" style="background:#B8700C"></span> Accent</td><td>#B8700C</td><td>#D9A441</td><td>The one thing a single-series chart is about: the index, highlights, forecast bars</td></tr>
    </table></div>
    <p class="prose"><strong>Status colors are reserved for tripwires and the fire alarm</strong> and always come with an icon and a word. Tripwires: ○ Quiet (green), ◐ Watching (amber), ● Tripped (red). Fire alarm: ○ Normal (green), ◐ Watch (amber), ◉ Warning (red), ● Alarm (red). They never stand in for a hypothesis.</p>
    <p class="prose"><strong>Text variants.</strong> Text on a background uses its own tokens so it passes WCAG AA contrast (4.5:1); the series colors stay for marks only.</p>
    <div class="table-wrap"><table><tr><th>Token</th><th>Light</th><th>Dark</th><th>Used for</th></tr>
    <tr><td><code>--link</code></td><td>#2F62C8</td><td>#6B96E6</td><td>Links and the "credible report" tag</td></tr>
    <tr><td><code>--sA-text</code></td><td>#8A5608</td><td>#C4861A</td><td>Amber text, such as the "expert opinion" tag</td></tr>
    <tr><td><code>--warn-text</code></td><td>#855C00</td><td>#D4A72C</td><td>Amber status words, such as a met Watch trigger</td></tr>
    <tr><td><code>--crit-bg</code></td><td>#B42318</td><td>#B42318</td><td>The alarm banner, behind white text</td></tr>
    </table></div>
  </section>
  <section class="prose"><h2>Rules</h2>
    <ul class="plain">
      <li><strong>Pick the form first.</strong> One number gets a stat tile or the dial, not a chart. Change over time gets lines. Durations get range bars. Probabilities get meters.</li>
      <li><strong>Thin marks.</strong> 2px lines with round joins. Dots at least 8px with a 2px ring in the surface color. Bars no thicker than 24px, with 4px rounded ends.</li>
      <li><strong>Recessive chrome.</strong> Gridlines and axes are 1px solid hairlines one step off the surface, never dashed. Ticks fall on clean values.</li>
      <li><strong>One axis.</strong> Never two y-scales on one chart. Different measures get separate charts.</li>
      <li><strong>Identity is never color alone.</strong> Two or more series always have a legend, plus a few direct labels at line ends where they don't collide. Never a number on every point.</li>
      <li><strong>Text stays ink.</strong> Labels and values use the text colors. The colored mark beside them carries identity.</li>
      <li><strong>Emphasis over rainbow.</strong> When one thing matters (disclosed by outsiders, our forecast), it gets the accent and everything else goes gray.</li>
      <li><strong>Every chart is interactive and readable without the picture.</strong> Hover or tap shows a tooltip, and every chart has a "Show as table" view.</li>
      <li><strong>Forecasts vs projections.</strong> Our forecast is a solid line through the three numbers we actually state (now, end-2030, end-2035), with a shaded judgment band: not a statistical interval, but roughly how far our number could plausibly move as evidence arrives. A projection of a measured trend is dashed, with the 95% band of the trend line and a lighter band where a single new measurement should land. We never project our own daily probability line: the dated forecasts (end-2030, end-2035) shouldn't drift predictably; the 'now' line is expected to rise along our own forecast. Outside forecasts are hollow rings, and those that only measure an announcement are left off the chart.</li>
      <li><strong>Log scales for growth.</strong> Exponential trends go on a log axis labelled in human units (a workday, a work-week), so a straight line means steady doubling.</li>
      <li><strong>Type.</strong> Headings in Source Serif 4. Everything else, including big numbers, in Public Sans. Aligned columns use tabular figures.</li>
    </ul>
  </section>
  <section><h2>The Hidden AGI Index dial</h2><p class="muted">An eye whose iris has 100 ticks, one per percentage point, lit in the accent color.</p><div id="ex-dial"></div></section>
  <section><h2>Lines: change over time</h2><div class="chart-wrap"><div id="ex-line"></div></div></section>
  <section><h2>Range bars: how long something lasted</h2><div class="chart-wrap"><div id="ex-lag"></div></div></section>
  <section><h2>Meters: a probability, with market odds as a hollow ring</h2><div id="ex-fc"></div></section>
  <section><h2>Status board: tripwires</h2><div id="ex-tw"></div></section>
  <section><h2>Forecast: stated numbers, judgment band, outside forecasts</h2><div class="chart-wrap"><div id="ex-fcst"></div></div></section>
  <section><h2>Projection: measured trend on a log scale</h2><p class="muted">Dashed line: the fitted trend, projected. Darker band: the 95% band of the trend line. Lighter band: where a single new measurement should land. Faded dots: above METR's reliable range, left out of the fit.</p><div class="chart-wrap"><div id="ex-trend"></div></div></section>
""",
    scripts_code=r"""
const ex = (id, draw) => { const el = document.getElementById(id); if(!el) return; try{ K.live(el, () => draw(el)); }catch(err){ console.error(id, err); } };
const soft = p => j(p).catch(err => { console.error(err); return null; });
ex("ex-dial", el => K.dial(el, 4, {size:240}));
const days = ["2026-09-01","2026-09-08","2026-09-15","2026-09-22","2026-09-29"];
const demo = {A:[1.5,2,2,2.5,3],B:[1,1,1.5,1.5,2],C:[0.3,0.4,0.5,0.8,1],D:[0.2,0.3,0.3,0.4,0.5]};
ex("ex-line", el => K.lineChart(el, {title:"Example (illustrative data)", series:Object.entries(demo).map(([k,v])=>({label:K.SERIES[k].label+" (example)", short:k, color:K.SERIES[k].color, values:days.map((d,i)=>({x:d,y:v[i]}))}))}));
const [inc, fc, ext, tr, runs] = await Promise.all(["data/incidents.json","data/forecasts.json","data/external_forecasts.json","data/trends.json","data/runs.json"].map(soft));
if(inc) ex("ex-lag", el => K.lagChart(el, (inc.incidents||[]).slice(0,4)));
if(fc){ const fs = (fc.forecasts||[]).filter(f => f && f.outcome!=="void" && f.void!==true); K.forecastBars(document.getElementById("ex-fc"), fs.filter(f=>f.market!=null).concat(fs.filter(f=>f.market==null).slice(0,1))); }
const all = Array.isArray(runs) ? runs.filter(r => r && typeof r === "object") : [];
const pub = all.filter(r => r.report && r.comparable !== false), lastRun = pub.length ? pub[pub.length-1] : all[all.length-1];
if(lastRun?.agi) ex("ex-fcst", el => K.forecastChart(el, {title:"Strict AGI exists", today:lastRun.date, yMax:100, series:[{label:"Our forecast: strict AGI exists", color:"--ink", ...lastRun.agi}], markers:(ext?.forecasts||[]).filter(m => m && m.bar !== "announcement")}));
if(tr){ const fr = (tr.metr?.models||[]).filter(m=>m && m.sota && m.date>="2023-01-01");
  ex("ex-trend", el => K.trendChart(el, {title:"METR 50% horizon", history:fr.map(m=>({date:m.date, v:m.p50, name:modelName(m.id), excluded:m.excluded===true, inFit:m.excluded!==true})), projection:tr.metr.p50.projection, thresholds:[{v:tr.metr.thresholds.workMonth, label:"1 work-month"}]})); }
if(lastRun) K.tripwireBoard(document.getElementById("ex-tw"), (lastRun.tripwires||[]).filter((w,i,a)=>a.findIndex(x=>x.status===w.status)===i));
""",
)


def build():
    rendered = []
    for path, p in PAGES.items():
        root = "../" * path.count("/") or "./"
        body = p["body"]() if callable(p["body"]) else p["body"]
        desc = p["description"]() if callable(p["description"]) else p["description"]
        scripts = module(root, p["scripts_code"]) if p.get("scripts_code") else p.get("scripts", "")
        rendered.append((path, page(path=path, title=p["title"], description=desc, body=body,
                                    active=path if path != "weekly/index.html" else "weekly/", scripts=scripts)))
    for path, html in rendered:
        out = ROOT / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html)
        print("wrote", path)


if __name__ == "__main__":
    build()
