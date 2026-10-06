"""hidden.html, "Could it be hidden?" (spec 7.4): the Hidden AGI Index and how it is derived, the canonical A-D
definitions under definitions v2.0, our odds to 2035, the readings over time and the hiding-conditions gauges.

Everything reads without JavaScript: the Index bar, the definitions, an odds table and the gauge values are
server-rendered. The module script then draws the forecast charts (moved here from the old homepage's
assets/app.js), the readings over time (lineChart with a "Definitions v2.0" break at the first v2.0 reading) and
the gauge row, each over its plain fallback.
"""
from sitekit import display_words

from . import common as C
from .common import as_dict, e

TITLE = "Could it be hidden? · Hidden AGI watch"
DESCRIPTION = ("How a hidden AI system would show in our numbers: the Hidden AGI Index and its parts, the four hidden "
               "scenarios and one open one, our odds to 2035, and the hiding-conditions gauges.")
HYP_ORDER = ["A", "B", "C", "D", "Dopen"]
FLOOR_CHIP = ('<a href="disclosure-lag.html#floor"><abbr class="chip" title="Incidents nobody found can\'t be counted, '
              'so this is a minimum">floor</abbr></a>')
GAUGE_NAMES = [("gap", "Capability gap"), ("rd", "AI-led R&D"), ("oversight", "Disclosure lag"), ("money", "Big Tech capex"),
               ("delegation", "Delegation")]

SCRIPTS_CODE = r"""
// hidden.html: our odds to 2035, the readings over time and the gauge row, each drawn over its plain fallback.
const $ = id => document.getElementById(id);
const num = v => v==null || v==="" || isNaN(Number(v)) ? null : Number(v);
const val = (r, k, hz) => num(k === "agi" ? r?.agi?.[hz] : r?.probs?.[k]?.[hz]);
const defsOf = r => String(r?.defs || "1.0");
const sname = k => K.SERIES[k]?.name || K.SERIES[k]?.label || k;
function published(all){   // same rule as the server: a report, not comparable:false; the last entry per report wins
  const m = new Map();
  all.filter(r => r && r.report && r.comparable !== false).forEach(r => { m.delete(r.report); m.set(r.report, r); });
  return [...m.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));
}
let pub = [], outside = [], gdefs = [];
const last = () => pub[pub.length - 1];

function drawOdds(){
  const r = last(), host = $("fc-agi"), grid = $("fc-grid");
  if(!r || !host || !grid) return;
  const today = r.date;
  // Announcement markets measure someone saying AGI is here, a looser event, so they stay off this chart.
  const markers = (outside || []).filter(m => m && m.bar !== "announcement");
  if(r.agi) K.forecastChart(host, {title: "AGI anywhere, public or hidden", today, yMax: 100,
    series: [{label: "Our forecast: AGI anywhere", short: "AGI", color: "--ink", ...r.agi}], markers});
  const list = K.SERIES_ORDER.map(k => ({k, p: r.probs?.[k]})).filter(x => x.p);
  if(!list.length) return;
  const highs = list.flatMap(({p}) => ["now", "y2030", "y2035"].map(z => { const b = p.band?.[z]; return Array.isArray(b) ? Number(b[1]) : K.confBand(p[z], p.conf)[1]; })).filter(v => !isNaN(v));
  const yMax = Math.min(100, Math.max(25, Math.ceil(Math.max(...highs, 1) / 25) * 25));
  const note = $("fc-scale"); if(note) note.textContent = `All ${list.length} panels share the same 0–${yMax}% scale.`;
  grid.replaceChildren();
  const todo = [];   // lay out every card first, then draw, so each chart measures its final width
  list.forEach(({k, p}) => {
    const s = K.SERIES[k] || {color: "--ink"};
    const m = K.util.h("div", {class: "mini"}), h3 = K.util.h("h3"), sw = K.util.h("span", {class: "swatch"});
    sw.style.background = K.util.cssVar(s.color); h3.append(sw, document.createTextNode(sname(k))); m.append(h3);
    const c = K.util.h("div"); m.append(c);
    m.append(K.util.h("p", {class: "muted"}, `${K.fmtNum(p.now)}% today → ${K.fmtNum(p.y2030)}% by end-2030 → ${K.fmtNum(p.y2035)}% by end-2035${p.conf ? " · " + p.conf + " confidence" : ""}`));
    grid.append(m);
    todo.push(() => K.forecastChart(c, {title: sname(k), today, compact: true, height: 150, yMax,
      series: [{label: sname(k), color: s.color, now: p.now, y2030: p.y2030, y2035: p.y2035, conf: p.conf, band: p.band}]}));
  });
  todo.forEach(f => f());
}

function drawOverTime(){
  const host = $("over-time-chart"); if(!host || !pub.length) return;
  const byDate = new Map(); pub.forEach(r => byDate.set(r.date, r));   // one point per day: the latest reading
  const days = [...byDate.values()];
  const breaks = [];
  days.forEach((r, i) => { if(i && defsOf(r) !== defsOf(days[i - 1])) breaks.push({x: r.date, label: "Definitions v" + defsOf(r)}); });
  K.lineChart(host, {title: "Probability true today for each scenario", breaks,
    series: K.SERIES_ORDER.map(k => ({label: sname(k), short: k === "Dopen" ? "D-open" : k, color: K.SERIES[k].color,
      values: days.map(r => ({x: r.date, y: val(r, k, "now")}))}))});
}

function drawGauges(){ const host = $("gauge-row"); if(host && gdefs.length) K.gaugeRow(host, gdefs, pub, {root: ""}); }

function drawAll(){
  [["odds", drawOdds], ["readings over time", drawOverTime], ["gauges", drawGauges]].forEach(([name, f]) => {
    try{ f(); }catch(err){ console.error(`hidden.html: the ${name} section kept its plain version:`, err); }
  });
}

(async () => {
  let runs;
  try{ runs = await j("data/runs.json"); if(!Array.isArray(runs)) throw new Error("runs.json is not a list"); }
  catch(err){
    console.error("Couldn't load data/runs.json:", err);
    const st = $("hidden-status"); if(st) st.textContent = "Couldn't load data/runs.json; the figures above are from the last build.";
    return;
  }
  pub = published(runs);
  const [ext, g] = await Promise.all(["data/external_forecasts.json", "data/gauges.json"].map(p => j(p).catch(err => { console.error(err); return null; })));
  outside = Array.isArray(ext?.forecasts) ? ext.forecasts : [];
  gdefs = Array.isArray(g?.gauges) ? g.gauges : [];
  drawAll();
  // redraw the width-dependent charts only when the width changes (phones fire resize when the address bar hides)
  let rt, lastW = innerWidth;
  addEventListener("resize", () => { if(innerWidth === lastW) return; lastW = innerWidth; clearTimeout(rt);
    rt = setTimeout(() => { [drawOdds, drawOverTime].forEach(f => { try{ f(); }catch(err){ console.error(err); } }); }, 150); });
})();
"""


def _hyp_text(data):
    hy = as_dict(as_dict(data).get("hypotheses"))
    out = {}
    for k in HYP_ORDER:
        h = as_dict(hy.get(k))
        out[k] = (h.get("name") or C.HYP_LABELS.get(k, k), h.get("text"))
    return out


def _letter(k):
    return "D-open" if k == "Dopen" else k


def odds_table(run):
    rows = [("AGI anywhere, public or hidden", as_dict(run.get("agi")))] + [
        (f"{_letter(k)} · {C.HYP_LABELS[k]}", as_dict(as_dict(run.get("probs")).get(k))) for k in HYP_ORDER]
    body = "".join(f'<tr><td>{e(n)}</td><td class="num">{C.fmt(v.get("now"))}%</td><td class="num">{C.fmt(v.get("y2030"))}%</td>'
                   f'<td class="num">{C.fmt(v.get("y2035"))}%</td><td>{e(v.get("conf"))}</td></tr>' for n, v in rows)
    return ('<div class="table-wrap"><table><caption class="sr-only">Our odds, today and by end-2030 and end-2035</caption>'
            '<tr><th>Scenario</th><th>Today</th><th>By end-2030</th><th>By end-2035</th><th>Confidence</th></tr>'
            f'{body}</table></div>')


def gauge_values(run):
    g = as_dict(run.get("gauges"))
    bits = []
    for k, name in GAUGE_NAMES:
        d = C._gauge_display(run, k)
        if d:
            bits.append(f"{e(name)} {e(d)}" + (f" {FLOOR_CHIP}" if k == "oversight" else ""))
    return " · ".join(bits) if bits and g else ""


def render(root_dir=None):
    runs = C.load_json("data/runs.json", root_dir)
    run = C.newest(runs) or {}
    prev = C.prev_published(runs, run) if run else None
    data = C.load_components(root_dir)
    chip = C.pending_chip(run, data) if data else ""
    pr = as_dict(run.get("probs"))
    parts = C.index_parts_text(run)
    delta = C.delta_text(run, prev, "index")
    glance = (f"Hidden AGI Index {C.fmt(run.get('index'))}%: {e(parts)} · {e(delta)}" if parts else
              f"Hidden AGI Index {C.fmt(run.get('index'))}% · {e(delta)} · breakdown from the next reading")
    note = display_words(run.get("indexNote")) if run.get("indexNote") else None   # "secret RSI" etc. retired (3.1)
    hyps = []
    for k, (name, text) in _hyp_text(data).items():
        p = as_dict(pr.get(k))
        extra = ""   # D-open's own text says it is outside the Index (R1-13)
        body = f"<p>{e(text)}</p>" if text else ""
        hyps.append(f'<li><details><summary><strong>{_letter(k)} · {e(name)}</strong>: {C.fmt(p.get("now"))}% today · '
                    f'{C.fmt(p.get("y2030"))}% by end-2030 · {C.fmt(p.get("y2035"))}% by end-2035{extra}</summary>'
                    f'{body}</details></li>')
    gv = gauge_values(run)
    oversight = C._gauge_display(run, "oversight")
    money = C._gauge_display(run, "money")
    as_of = f" Reading of {C.day(run.get('date'))}." if run.get("date") else ""
    return f"""  <h1>Could it be hidden?</h1>
  <p class="hq-a">{glance}{chip}</p>
  <p class="muted small" id="hidden-status">{e(as_of.strip())}</p>
  {C.method_banner(run, prev)}
  <section id="index" aria-labelledby="index-h"><h2 id="index-h">The Index</h2>
    {C.index_block(run)}
    <p>The chance that at least one of A–D is true today. B needs no AGI; A, C and D do.</p>
    {f'<details><summary>How today&#39;s figure is derived</summary><p>{e(note)}</p></details>' if note else ''}
  </section>
  <section id="hypotheses" aria-labelledby="hyp-h"><h2 id="hyp-h">The four hidden scenarios, and one open one</h2>
    <p class="small muted">Definitions v{e(as_dict(data).get('definitionsVersion') or '2.0')}: "AGI" means AGI as defined on <a href="agi.html#definition">Is AGI here?</a> The Index counts A to D only; D-open is open by definition.{chip}</p>
    <ul class="plain am-hyp">{''.join(hyps)}</ul>
  </section>
  <section id="odds" aria-labelledby="odds-h"><h2 id="odds-h">Our odds to 2035</h2>
    <p class="muted small">Our probabilities that each is true today, and that it becomes true by the end of 2030 and of 2035. They are our stated forecast, not a projection of the daily line; the shaded band is a judgment range, not a statistical interval. Hollow rings are outside forecasts.{chip}</p>
    <div class="chart-wrap"><div id="fc-agi"><p class="muted small">AGI anywhere, public or hidden: {C.fmt(as_dict(run.get('agi')).get('now'))}% today · {C.fmt(as_dict(run.get('agi')).get('y2030'))}% by end-2030 · {C.fmt(as_dict(run.get('agi')).get('y2035'))}% by end-2035.</p></div></div>
    <p class="muted small" id="fc-scale"></p>
    <div class="forecast-grid" id="fc-grid">{odds_table(run)}</div>
    <p class="small"><a href="money.html#prediction-markets">Prediction markets, for comparison →</a> · <a href="trends.html">What the measured trends say →</a></p>
  </section>
  <section id="over-time" aria-labelledby="ot-h"><h2 id="ot-h">Readings over time</h2>
    <p class="muted small">The probability that each scenario is true today, one point per daily reading. A dashed line marks a change of definitions; no line joins across it.</p>
    <div class="chart-wrap"><div id="over-time-chart"><p class="muted small">Every reading is listed in the <a href="archive.html">archive</a>.</p></div></div>
  </section>
  <section id="gauges" aria-labelledby="g-h"><h2 id="g-h">Hiding conditions</h2>
    <p class="small muted">{e(C.GAUGE_SENTENCE)}</p>
    <div id="gauge-row">{f'<p class="small">{gv}</p>' if gv else ''}</div>
  </section>
  <section aria-labelledby="more-h"><h2 id="more-h">More on hiding</h2>
    <div class="cards">
      <a class="card" href="disclosure-lag.html"><strong>Disclosure lag</strong><span>{e(('Median ' + oversight + ' from incident to disclosure; a floor.') if oversight else 'How long AI incidents stay secret.')}</span></a>
      <a class="card" href="money.html"><strong>Follow the money</strong><span>{e(('Big Tech capex ' + money + '; context only (X4 is the test).') if money else 'Money as context for hiding.')}</span></a>
    </div>
    <p class="small"><a href="start-here.html#pieces">How our numbers fit together →</a></p>
  </section>"""


PAGE = dict(title=TITLE, description=DESCRIPTION, body=render, scripts_code=SCRIPTS_CODE, head_extra="")
