#!/usr/bin/env python3
"""Build the standing section pages. Their charts render in the browser from data/*.json,
so these pages only need rebuilding when their layout or copy changes.

    python3 scripts/build_pages.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sitekit import page  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def module(root, code):
    return f'<script type="module">\nimport * as K from "{root}assets/charts.js";\nconst j = p => fetch(p,{{cache:"no-cache"}}).then(r=>r.json());\n{code}\n</script>'


PAGES = {}

# ---------- Start here ----------
PAGES["start-here.html"] = dict(
    title="Start here · Hidden AGI watch",
    description="What Hidden AGI watch tracks, what the Hidden AGI Index means, and how the daily and weekly readings are made.",
    body="""
  <header class="prose">
    <h1>Start here</h1>
    <p class="lede">Hidden AGI watch asks one question every day: could advanced AI already exist, or already be acting, without the public knowing? It answers with explicit, sourced probabilities rather than hype.</p>
  </header>
  <section class="prose">
    <h2>The four hypotheses</h2>
    <div class="hyp A"><strong>A: AGI exists, undisclosed.</strong> A system meets our strict AGI bar (below), and its developer has kept that level of capability from the public for at least 30 days. Admitting that an unreleased model exists doesn't count as disclosure.</div>
    <div class="hyp B"><strong>B: secret recursive self-improvement.</strong> An AI system does most of the work of building a more capable successor, with at least a 3x speed-up over humans alone, and this hasn't been disclosed. Partial AI-driven acceleration is already public, so it doesn't count.</div>
    <div class="hyp C"><strong>C: a covert AGI-level actor online.</strong> An AGI-level system takes sustained actions on the internet or in the economy, without its developer's sanction or without public knowledge. Today's sub-AGI agent incidents are tracked as warning signs, not as proof.</div>
    <div class="hyp D"><strong>D: an AGI covertly shaping government.</strong> Output from an AGI-level system materially shapes a major government decision, and the public doesn't know. <strong>D-open</strong> tracks the same influence through open, acknowledged use.</div>
    <h2>Our AGI bar</h2>
    <p>AGI here means a system that reliably (80% or better) does at least 80% of economically valuable remote professional tasks at the level of a median skilled professional, including multi-week projects, with no task-specific human scaffolding. It is deliberately strict. Looser definitions, such as "we're in the AGI era", are tracked on the <a href="agi-claims.html">AGI claims ledger</a>.</p>
    <h2>The Hidden AGI Index</h2>
    <p>The headline number is the probability that <em>at least one</em> of A–D is true right now. The hypotheses overlap: C and D mostly require an A-level system to exist. So the index sits just above the largest single hypothesis rather than being their sum. The dial shows it as an eye whose iris has 100 ticks, one per percentage point.</p>
    <h2>How the numbers are made</h2>
    <ul class="plain">
      <li><strong>Daily:</strong> an automated analyst (Claude) searches the news, research, lab system cards and independent evaluations such as METR, Epoch AI and the AI Security Institutes. It then reassesses each hypothesis now, by 2030 and by 2035. Each daily report shows its full reasoning, including base rates, the steelman of both sides, and what would change its mind.</li>
      <li><strong>Evidence ratings:</strong> every claim is tagged <span class="tag fact">verified fact</span> <span class="tag report">credible report</span> <span class="tag opinion">expert opinion</span> or <span class="tag spec">speculation</span>.</li>
      <li><strong>Tripwires:</strong> the specific, observable signals that would move the numbers most. Each is marked quiet, watching or tripped.</li>
      <li><strong>Forecast chart:</strong> the dashboard draws our stated numbers (now, by 2030, by 2035) with a band for our confidence and outside forecasts for comparison. We don't extrapolate our own daily line: if we expected our estimate to rise, we should already have raised it. <a href="trends.html">Trend watch</a> projects <em>measured</em> trends instead, such as how long a task AI can finish on its own.</li>
      <li><strong>What moved the needle:</strong> each day names the one development that changed an estimate most, or says plainly that it was a quiet day.</li>
      <li><strong>Weekly (Fridays, 3pm Pacific):</strong> a wrap-up with the week's key numbers and graphs, plus the <a href="scorecard.html">forecast scorecard</a>, <a href="disclosure-lag.html">disclosure lag</a>, <a href="agi-claims.html">AGI claims</a>, <a href="calendar.html">calendar</a> and <a href="steelman.html">steelman</a>.</li>
    </ul>
    <h2>Honesty notes</h2>
    <p>The research and drafting are done by AI, and the method and sources are public. The probabilities are subjective and uncertain. We try not to treat an absence of evidence as proof of secrecy, and we score our own short-range forecasts in public so you can judge our calibration.</p>
    <p><a class="btn" href="./">Go to today's reading</a></p>
  </section>
""",
    scripts="",
)

# ---------- Scorecard ----------
PAGES["scorecard.html"] = dict(
    title="Forecast scorecard · Hidden AGI watch",
    description="Short-range, checkable forecasts about AI, scored in public with the Brier score when they resolve.",
    body="""
  <header class="prose">
    <h1>Forecast scorecard</h1>
    <p class="lede">A probability is only worth something if you can check it. These are short-range, checkable forecasts, each with a deadline and a resolution rule, scored in public when they resolve.</p>
  </header>
  <div class="tiles" id="tiles"></div>
  <section><h2>Open forecasts</h2><p class="muted small">The amber bar is our probability. A hollow ring marks prediction-market odds where a comparable market exists.</p><div id="open"></div></section>
  <section><h2>Calibration</h2><p class="muted">When we say 70%, it should happen about 70% of the time. Points on the diagonal are well calibrated.</p><div id="calib"></div></section>
  <section><h2>Resolved</h2><div id="resolved"></div></section>
  <section class="prose"><h2>How scoring works</h2><p>Each resolved forecast scores (probability − outcome)², where the outcome is 1 or 0. The Brier score is the average. 0 is perfect, and always guessing 50% scores 0.25. New forecasts are added in each weekly wrap-up, and nothing is edited after it's made.</p></section>
""",
    scripts_code="""
const d = await j("data/forecasts.json");
const open = d.forecasts.filter(f=>f.outcome==null), done = d.forecasts.filter(f=>f.outcome!=null);
const b = K.brier(done);
const tiles = document.getElementById("tiles");
[["Open forecasts", open.length],["Resolved", done.length],["Brier score", b==null?"–":b.toFixed(3)],["Next deadline", open.length?K.util.fmtDate(open.map(f=>f.deadline).sort()[0]):"–"]].forEach(([l,v])=>{ const t=K.util.h("div",{class:"tile"}); t.append(K.util.h("div",{class:"label"},l), K.util.h("div",{class:"value"},String(v))); tiles.append(t); });
K.forecastBars(document.getElementById("open"), open.sort((a,b)=>a.deadline.localeCompare(b.deadline)));
K.calibration(document.getElementById("calib"), done);
const r = document.getElementById("resolved");
if(!done.length) r.append(K.util.h("p",{class:"empty"},"Nothing has resolved yet. The first deadline is " + K.util.fmtDate(open.map(f=>f.deadline).sort()[0],{day:"numeric",month:"long",year:"numeric"}) + "."));
else r.append(K.util.tableView("Resolved forecasts",["Forecast","Ours","Outcome","Score"], done.map(f=>[f.question, f.p+"%", f.outcome?"Yes":"No", Math.pow(f.p/100-(f.outcome?1:0),2).toFixed(3)])));
""",
)

# ---------- Disclosure lag ----------
PAGES["disclosure-lag.html"] = dict(
    title="Disclosure lag · Hidden AGI watch",
    description="How long AI agent incidents stayed hidden before the public heard about them, and who exposed them.",
    body="""
  <header class="prose">
    <h1>Disclosure lag</h1>
    <p class="lede">Could a lab hide AGI? The best evidence is how long real incidents have stayed hidden. Each bar runs from when an incident happened to when the public learned of it.</p>
  </header>
  <div class="tiles" id="tiles"></div>
  <section><h2>Days from incident to public disclosure</h2><div class="chart-wrap"><div id="lag"></div></div></section>
  <section class="prose"><h2>Why it matters</h2><p>This is the empirical base rate behind hypotheses A and C. In 2026, serious agent incidents stayed hidden for weeks to months, and most were exposed by someone other than the lab: victims, outside researchers, governments or reporters. That points to secrets that are short but real, not ones that last for years. New incidents are added in each weekly wrap-up.</p><p class="muted small" id="note"></p></section>
""",
    scripts_code="""
const d = await j("data/incidents.json");
const rows = K.lagChart(document.getElementById("lag"), d.incidents);
const lags = rows.map(r=>r.lag).sort((a,b)=>a-b), med = lags.length%2 ? lags[(lags.length-1)/2] : Math.round((lags[lags.length/2-1]+lags[lags.length/2])/2);
const ext = rows.filter(r=>r.ext).length;
const tiles = document.getElementById("tiles");
[["Median lag", med+" days"],["Longest", lags[lags.length-1]+" days"],["Exposed by others", Math.round(ext/rows.length*100)+"%"],["Incidents tracked", rows.length]].forEach(([l,v])=>{ const t=K.util.h("div",{class:"tile"}); t.append(K.util.h("div",{class:"label"},l), K.util.h("div",{class:"value"},String(v))); tiles.append(t); });
document.getElementById("note").textContent = d.note;
""",
)

# ---------- AGI claims ----------
PAGES["agi-claims.html"] = dict(
    title="AGI claims ledger · Hidden AGI watch",
    description="Every public claim that AGI has already been achieved, and whether it meets the main definitions.",
    body="""
  <header class="prose">
    <h1>AGI claims ledger</h1>
    <p class="lede">Every public claim that AGI is already here, who made it, what they stand to gain, and whether it meets the main definitions. Predictions about the future are not included.</p>
  </header>
  <section><h2>When the claims were made</h2><div class="chart-wrap"><div id="tl"></div></div></section>
  <section><h2>The claims, checked against each definition</h2><div class="table-wrap"><table id="claims"></table></div><p class="muted small">✓ meets it · ◐ partly · ✗ doesn't · ? unclear</p></section>
  <section class="prose"><h2>The definitions</h2><ul class="plain" id="defs"></ul></section>
""",
    scripts_code="""
const d = await j("data/agi_claims.json");
K.dotTimeline(document.getElementById("tl"), d.claims, {title:"Public AGI claims by date"});
const mark = v => ({yes:"✓ yes", partial:"◐ partly", no:"✗ no", unclear:"? unclear"})[v] || v;
const t = document.getElementById("claims"), h = K.util.h;
const hr = h("tr"); ["Date","Who","Claim","Strict bar","DeepMind Levels","OpenAI charter","Own definition"].forEach(c=>hr.append(h("th",{scope:"col"},c))); t.append(hr);
d.claims.forEach(c=>{ const tr=h("tr"); tr.append(h("td",{class:"num"},K.util.fmtDate(c.date,{day:"numeric",month:"short",year:"numeric"}))); const who=h("td"); who.append(h("strong",{},c.who), h("div",{class:"muted small"},c.role)); tr.append(who); const q=h("td"); q.append(h("div",{},"“"+c.quote+"”"), h("div",{class:"muted small"},c.venue+". Interest: "+c.interest+" ")); q.lastChild.append(h("a",{href:c.url,target:"_blank",rel:"noopener"},"source")); tr.append(q); ["strict","levels","charter"].forEach(k=>tr.append(h("td",{},mark(c.meets[k])))); const own=h("td"); own.append(h("div",{},mark(c.meets.narrow)), h("div",{class:"muted small"},c.narrowDef)); tr.append(own); t.append(tr); });
const defs = document.getElementById("defs"); Object.entries({strict:"Strict bar",levels:"DeepMind Levels",charter:"OpenAI charter",narrow:"Own definition"}).forEach(([k,l])=>{ const li=h("li"); li.append(h("strong",{},l+": "), document.createTextNode(d.definitions[k])); defs.append(li); });
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
  </header>
  <section><h2>Dated</h2><ul class="timeline-list" id="dated"></ul></section>
  <section><h2>No date yet, but watching</h2><ul class="timeline-list" id="undated"></ul></section>
""",
    scripts_code="""
const d = await j("data/calendar.json"), h = K.util.h, today = new Date().toISOString().slice(0,10);
const sw = k => { const s=h("span",{class:"swatch"}); s.style.background=K.util.css(K.SERIES[k]?.color||"--muted"); return s; };
const row = (when, e, past) => { const li=h("li"); if(past) li.style.opacity=.55; li.append(h("div",{class:"when"},when)); const b=h("div"); const t=h("div"); t.append(sw(e.hyp), document.createTextNode(" "+e.title)); if(e.certainty) t.append(h("span",{class:"chip"},e.certainty)); if(past) t.append(h("span",{class:"chip"},"past")); b.append(t); if(e.why) b.append(h("div",{class:"muted small"},e.why)); if(e.url){ const s=h("div",{class:"small"}); s.append(h("a",{href:e.url,target:"_blank",rel:"noopener"},"source")); b.append(s);} li.append(b); return li; };
const dated = document.getElementById("dated"); d.events.sort((a,b)=>a.date.localeCompare(b.date)).forEach(e=>dated.append(row(K.util.fmtDate(e.date,{day:"numeric",month:"short",year:"numeric"}), e, e.date<today)));
const und = document.getElementById("undated"); d.undated.forEach(e=>und.append(row("TBD", e, false)));
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
    scripts_code="""
const d = await j("data/steelman.json"), h = K.util.h;
const e = [...d.entries].sort((a,b)=>b.date.localeCompare(a.date));
const render = (x, host) => { host.append(h("p",{class:"kicker muted small"}, K.util.fmtDate(x.date,{day:"numeric",month:"long",year:"numeric"})+(x.edition?" · "+x.edition:""))); host.append(h("h2",{},"The case that "+x.side.charAt(0).toLowerCase()+x.side.slice(1))); host.append(h("p",{class:"muted"},x.against)); x.paragraphs.forEach(p=>host.append(h("p",{},p))); if(x.wouldConvince){ const c=h("div",{class:"callout"}); c.append(h("strong",{},"What would convince us: "), document.createTextNode(x.wouldConvince)); host.append(c);} if(x.sources?.length){ host.append(h("h3",{},"Sources")); const ul=h("ul",{class:"plain"}); x.sources.forEach(s=>{ const li=h("li"); li.append(h("a",{href:s.url,target:"_blank",rel:"noopener"},s.title)); ul.append(li); }); host.append(ul);} };
if(e.length) render(e[0], document.getElementById("latest")); else document.getElementById("latest").append(h("p",{class:"empty"},"The first steelman arrives with the first weekly wrap-up."));
const a = document.getElementById("archive"); if(e.length<2) a.append(h("p",{class:"muted"},"Earlier editions will appear here.")); else e.slice(1).forEach(x=>{ const det=h("details"); det.append(h("summary",{},K.util.fmtDate(x.date,{day:"numeric",month:"short",year:"numeric"})+": the case that "+x.side.toLowerCase())); const b=h("div",{class:"body prose"}); render(x,b); det.append(b); a.append(det); });
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
    scripts_code="""
const d = await j("../data/weekly/index.json"), h = K.util.h, list = document.getElementById("list");
if(!d.wrapups.length){ list.append(h("p",{class:"empty"},"The first weekly wrap-up is published Friday, October 2, 2026, at 3pm Pacific.")); }
else { const c=h("div",{class:"cards"}); [...d.wrapups].sort((a,b)=>b.date.localeCompare(a.date)).forEach(w=>{ const a=h("a",{class:"card",href:w.date+".html"}); a.append(h("strong",{},K.util.fmtDate(w.date,{day:"numeric",month:"long",year:"numeric"})), h("span",{},w.headline||"")); c.append(a); }); list.append(c); }
""",
)

# ---------- Trend watch ----------
PAGES["trends.html"] = dict(
    title="Trend watch · Hidden AGI watch",
    description="Measured AI trends projected forward: METR task length, AI's share of AI research, and when they would cross key thresholds.",
    body="""
  <header class="prose">
    <h1>Trend watch</h1>
    <p class="lede">Our probabilities are judgments. These are measurements. Here we extend real trends forward to see when they would cross the thresholds that matter for the hypotheses, if they hold. A projection is not a prediction: trends bend and break, and the bands show how quickly the uncertainty grows.</p>
  </header>
  <div class="tiles" id="tiles"></div>
  <section>
    <h2>How long a task AI can finish on its own</h2>
    <p class="muted">METR's time horizon: the length of task, measured in skilled-human time, that frontier models complete with 50% or 80% success. Log scale, so a straight line means steady doubling. Dots are measured frontier models. The dashed line and band are the projection.</p>
    <div class="chart-wrap"><div id="metr"></div><div class="legend" id="metr-legend"></div></div>
    <div class="table-wrap"><table id="cross"></table></div>
    <p class="muted small" id="metr-method"></p>
  </section>
  <section class="prose">
    <h2>What this means for our numbers</h2>
    <p>Our strict AGI bar is roughly the <strong>80% horizon reaching a month of work</strong>, with that reliability holding on real, messy jobs rather than benchmark tasks. If the trend holds, that crossing lands around <span id="agi-cross">–</span>. We put strict AGI at 45% by the end of 2030, which is more cautious than the straight line, for three reasons:</p>
    <ul class="plain">
      <li>Benchmark tasks are cleaner than real work.</li>
      <li>METR's task suite saturates above about 16 hours, so the recent top end is measured least well.</li>
      <li>Trends like this can bend with compute, energy, data or safety pauses. OpenAI has paused training twice in three months.</li>
    </ul>
    <p>If the dots keep landing on or above the dashed line, our 2030 number should rise. If they fall below the band, it should fall.</p>
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
    scripts_code="""
const t = await j("data/trends.json"), M = t.metr, h = K.util.h;
const nm = id => id.replace(/_inspect$/,"").replace(/_/g," ").replace(/\\b(gpt|o\\d)\\b/gi,s=>s.toUpperCase()).replace(/\\bclaude\\b/i,"Claude").replace(/\\bgemini\\b/i,"Gemini");
const fr = M.models.filter(m=>m.sota && m.date>="2023-01-01");
const mo = d => d ? K.util.fmtDate(d,{month:"short",year:"numeric"}) : "–";
K.trendChart(document.getElementById("metr"), {title:"METR time horizon", color:"--accent",
  history: fr.map(m=>({date:m.date, v:m.p50, lo:m.p50lo, hi:m.p50hi, name:nm(m.id)+" · 50%"})),
  projection: M.p50.projection,
  secondary: {label:"80% horizon", color:"--ink", history: fr.filter(m=>m.p80).map(m=>({date:m.date, v:m.p80, name:nm(m.id)+" · 80%"})), projection: M.p80.projection},
  thresholds: [{v:M.thresholds.workWeek, label:"1 work-week (40 hours)"},{v:M.thresholds.workMonth, label:"1 work-month (167 hours)"}]});
const lg = document.getElementById("metr-legend");
[["--accent","50% success (measured)"],["--ink","80% success (measured)"]].forEach(([c,l])=>{ const it=h("span",{class:"lg-item"}); const sw=h("span",{class:"swatch"}); sw.style.background=K.util.css(c); it.append(sw, document.createTextNode(l)); lg.append(it); });
{ const it=h("span",{class:"lg-item"}); it.append(h("span",{class:"lg-dash"}), document.createTextNode("Projection, with 95% band")); lg.append(it); }
const tb = document.getElementById("cross");
const hr=h("tr"); ["If the trend holds…","Central","Range (fast – slow)"].forEach(c=>hr.append(h("th",{},c))); tb.append(hr);
[["50% horizon reaches a work-week","p50","workWeek"],["50% horizon reaches a work-month","p50","workMonth"],["80% horizon reaches a work-week","p80","workWeek"],["80% horizon reaches a work-month (≈ our strict AGI bar)","p80","workMonth"]].forEach(([l,m,k])=>{ const c=M[m].crossings[k]; const tr=h("tr"); tr.append(h("td",{},l), h("td",{class:"num"},mo(c.mid)), h("td",{class:"num"},mo(c.fast)+" – "+mo(c.slow))); tb.append(tr); });
document.getElementById("agi-cross").textContent = mo(M.p80.crossings.workMonth.mid) + " (range " + mo(M.p80.crossings.workMonth.fast) + " – " + mo(M.p80.crossings.workMonth.slow) + ")";
document.getElementById("metr-method").textContent = M.method + " Our fit gives a 50%-horizon doubling time of " + M.p50.doublingDays + " days; METR's own fit since 2023 is " + (M.metrDoublingDays?.from_2023_on?.point_estimate?.toFixed(0) ?? "–") + " days. Data refreshed " + t.updated + " from METR.";
const last = fr[fr.length-1];
const tiles = document.getElementById("tiles");
[["Doubling time (50%)", M.p50.doublingDays.toFixed(0)+" days"],["Latest frontier, 50%", K.fmtDur(last.p50)],["80% horizon hits a work-month", mo(M.p80.crossings.workMonth.mid)],["Our strict AGI by 2030", "45%"]].forEach(([l,v])=>{ const x=h("div",{class:"tile"}); x.append(h("div",{class:"label"},l), h("div",{class:"value"},v)); tiles.append(x); });
const R = t.manual.rdShare;
document.getElementById("rd-note").textContent = R.label + ". " + R.note;
K.lineChart(document.getElementById("rd"), {title:R.label, yMax:100, endLabels:true, series:[{label:R.label, short:"AI-led", color:"--accent", values:R.points.map(p=>({x:p.date,y:p.v}))}]});
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
    <p class="prose"><strong>Status colors are reserved for tripwires</strong> and always come with an icon and a word: ○ Quiet (green), ◐ Watching (amber), ● Tripped (red). They never stand in for a hypothesis.</p>
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
      <li><strong>Forecasts vs projections.</strong> Our forecast is a solid line through the three numbers we actually state (now, end-2030, end-2035), with a shaded confidence band. A projection of a measured trend is dashed, with a 95% band. We never extrapolate our own daily probability line: a calibrated estimate shouldn't drift in a predictable direction. Outside forecasts are hollow rings.</li>
      <li><strong>Log scales for growth.</strong> Exponential trends go on a log axis labelled in human units (a workday, a work-week), so a straight line means steady doubling.</li>
      <li><strong>Type.</strong> Headings in Source Serif 4. Everything else, including big numbers, in Public Sans. Aligned columns use tabular figures.</li>
    </ul>
  </section>
  <section><h2>The Hidden AGI Index dial</h2><p class="muted">An eye whose iris has 100 ticks, one per percentage point, lit in the accent color.</p><div id="ex-dial"></div></section>
  <section><h2>Lines: change over time</h2><div class="chart-wrap"><div id="ex-line"></div></div></section>
  <section><h2>Range bars: how long something lasted</h2><div class="chart-wrap"><div id="ex-lag"></div></div></section>
  <section><h2>Meters: a probability, with market odds as a hollow ring</h2><div id="ex-fc"></div></section>
  <section><h2>Status board: tripwires</h2><div id="ex-tw"></div></section>
  <section><h2>Forecast: stated numbers, confidence band, outside forecasts</h2><div class="chart-wrap"><div id="ex-fcst"></div></div></section>
  <section><h2>Projection: measured trend on a log scale</h2><div class="chart-wrap"><div id="ex-trend"></div></div></section>
""",
    scripts_code="""
K.dial(document.getElementById("ex-dial"), 4, {size:240});
const days=["2026-09-01","2026-09-08","2026-09-15","2026-09-22","2026-09-29"];
const demo={A:[1.5,2,2,2.5,3],B:[1,1,1.5,1.5,2],C:[0.3,0.4,0.5,0.8,1],D:[0.2,0.3,0.3,0.4,0.5]};
K.lineChart(document.getElementById("ex-line"),{title:"Example (illustrative data)",series:Object.entries(demo).map(([k,v])=>({label:K.SERIES[k].label+" (example)",short:k,color:K.SERIES[k].color,values:days.map((d,i)=>({x:d,y:v[i]}))}))});
const inc = await j("data/incidents.json"); K.lagChart(document.getElementById("ex-lag"), inc.incidents.slice(0,4));
const fc = await j("data/forecasts.json"); K.forecastBars(document.getElementById("ex-fc"), fc.forecasts.filter(f=>f.market!=null).concat(fc.forecasts.slice(0,1)));
const ext = await j("data/external_forecasts.json"), tr = await j("data/trends.json");
const runs = await j("data/runs.json"); const lastRun = runs[runs.length-1];
if(lastRun.agi) K.forecastChart(document.getElementById("ex-fcst"), {title:"Strict AGI exists", today:lastRun.date, yMax:100, series:[{label:"Our forecast: strict AGI exists", color:"--ink", ...lastRun.agi}], markers:ext.forecasts});
const fr = tr.metr.models.filter(m=>m.sota && m.date>="2023-01-01");
K.trendChart(document.getElementById("ex-trend"), {title:"METR 50% horizon", history:fr.map(m=>({date:m.date,v:m.p50,name:m.id})), projection:tr.metr.p50.projection, thresholds:[{v:tr.metr.thresholds.workMonth,label:"1 work-month"}]});
K.tripwireBoard(document.getElementById("ex-tw"), (runs[runs.length-1].tripwires||[]).filter((w,i,a)=>a.findIndex(x=>x.status===w.status)===i));
""",
)


def build():
    for path, p in PAGES.items():
        root = "../" * path.count("/") or "./"
        scripts = module(root, p["scripts_code"]) if p.get("scripts_code") else p.get("scripts", "")
        html = page(path=path, title=p["title"], description=p["description"], body=p["body"],
                    active=path if path != "weekly/index.html" else "weekly/", scripts=scripts)
        out = ROOT / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html)
        print("wrote", path)


if __name__ == "__main__":
    build()
