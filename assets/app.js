import {lineChart, dial, tripwireBoard, forecastChart, gaugeRow, alarmIndicator, alarmBanner, confBand, safeHref, SERIES as KSERIES, SERIES_ORDER, util} from "./charts.js";

const {h:el, fmtNum:fmt, sparkline} = util;   // fmt has no "%": the big figures put it in a <small>
const SERIES = SERIES_ORDER.map(k => ({k, short:KSERIES[k].label, c:KSERIES[k].color, letter:k==="Dopen"?"D-open":k}));
const fmtDate = d => util.fmtDate(d,{day:"numeric",month:"short",year:"numeric"});
const val = (run,k,hz) => { const p = run?.probs?.[k]; if(!p || p[hz]==null || p[hz]==="") return null; const v = Number(p[hz]); return isNaN(v) ? null : v; };
// a link from run data: http(s) or a site-relative path only; a new tab only for absolute URLs
const link = (href, text) => { const u = safeHref(href); if(!u) return null; return el("a", /^https?:/i.test(u) ? {href:u,target:"_blank",rel:"noopener"} : {href:u}, text); };

let runs = [];
let corrections = [];   // data/corrections.json entries, for the notice on a corrected reading
/* Comparisons use published readings only: runs with a report and not marked comparable:false
   (the same-morning chat estimate is kept in the history but never used for change figures).
   If one report path appears twice, the last entry wins. */
let pub = [], lastRun = null, prevRun = null;
function published(all){
  const byReport = new Map();
  all.filter(r => r.report && r.comparable !== false).forEach(r => { byReport.delete(r.report); byReport.set(r.report, r); });
  return [...byReport.values()];
}

// A change counts only if the displayed numbers differ.
function deltaNode(cur, prev, since="since last reading"){
  if(cur==null || prev==null) return el("span",{class:"delta flat"},"first reading");
  if(fmt(cur)===fmt(prev)) return el("span",{class:"delta flat"},"no change");
  const n = fmt(Math.round(Math.abs(cur-prev)*1e6)/1e6), up = cur > prev;
  return el("span",{class:"delta "+(up?"up":"down")}, `${up?"▲ +":"▼ −"}${n} ${n==="1"?"pt":"pts"} ${since}`);
}
const sinceText = () => prevRun && lastRun && prevRun.date===lastRun.date && prevRun.label ? `since the ${prevRun.label}` : "since last reading";

function renderReadings(){
  const box=document.getElementById("readings"); box.replaceChildren();
  const last=lastRun, prev=prevRun, src=pub.length?pub:runs;
  SERIES.forEach(s=>{
    const r=el("div",{class:"reading"});
    const n=el("div",{class:"name"}); const sw=el("span",{class:"swatch"}); sw.style.background=util.cssVar(s.c); n.append(sw, document.createTextNode(s.short)); r.append(n);
    const f=el("div",{class:"fig"}); f.append(document.createTextNode(fmt(val(last,s.k,"now")))); f.append(el("small",{},"%")); r.append(f);
    r.append(deltaNode(val(last,s.k,"now"), val(prev,s.k,"now"), sinceText()));
    const conf = last?.probs?.[s.k]?.conf;
    r.append(el("div",{class:"horizons"}, `By end-2030 ${fmt(val(last,s.k,"y2030"))}%, by end-2035 ${fmt(val(last,s.k,"y2035"))}%${conf?". Confidence: "+conf:""}`));
    r.append(sparkline(src.map(x=>val(x,s.k,"now")), {color:s.c, zeroBased:true, width:140, height:28}));
    box.append(r);
  });
}

function renderChart(){
  const byDate=new Map(); (pub.length?pub:runs).forEach(r=>byDate.set(r.date,r)); // one point per day: the latest reading
  const days=[...byDate.values()];
  lineChart(document.getElementById("chart"), {
    title:"Probability true now for each hypothesis",
    series: SERIES.map(s=>({label:s.short, short:s.letter, color:s.c, values:days.map(r=>({x:r.date, y:val(r,s.k,"now")}))}))
  });
}

let outside = [], gaugeDefs = [], alarm = null;
function renderGauges(){ gaugeRow(document.getElementById("gauge-row"), gaugeDefs, pub.length?pub:runs); }
const WORDS = {2:"two",3:"three",4:"four",5:"five",6:"six"};
function renderForecast(){
  const last=lastRun; if(!last) return;
  const today=last.date;
  // Announcement markets measure a different event (someone saying AGI is here), so they stay off
  // the strict-AGI chart; that comparison lives on the scorecard.
  const markers = (outside||[]).filter(m => m && m.bar !== "announcement");
  if(last.agi) forecastChart(document.getElementById("fc-agi"), {title:"Strict AGI exists, public or hidden", today, yMax:100,
    series:[{label:"Our forecast: strict AGI exists", short:"AGI", color:"--ink", ...last.agi}], markers});
  const grid=document.getElementById("fc-grid"); grid.replaceChildren();
  const list = SERIES.map(s=>({s, p:last.probs?.[s.k]})).filter(x=>x.p);
  // one shared y scale, so the panels can be compared at a glance
  const highs = list.flatMap(({p}) => ["now","y2030","y2035"].map(k => { const b = p.band?.[k]; return Array.isArray(b) ? Number(b[1]) : confBand(p[k], p.conf)[1]; })).filter(v => !isNaN(v));
  const yMax = Math.min(100, Math.max(25, Math.ceil(Math.max(...highs, 1)/25)*25));
  const note = document.getElementById("fc-scale");
  if(note) note.textContent = list.length ? `All ${WORDS[list.length]||list.length} panels share the same 0–${yMax}% scale.` : "";
  const todo=[]; // lay out every card first, then draw, so each chart measures its final width
  list.forEach(({s,p})=>{
    const m=el("div",{class:"mini"}); const h3=el("h3"); const sw=el("span",{class:"swatch"}); sw.style.background=util.cssVar(s.c); h3.append(sw, document.createTextNode(s.short)); m.append(h3);
    const c=el("div"); m.append(c);
    m.append(el("p",{class:"muted"},`${fmt(p.now)}% now → ${fmt(p.y2030)}% by end-2030 → ${fmt(p.y2035)}% by end-2035${p.conf?" · "+p.conf+" confidence":""}`));
    grid.append(m);
    todo.push(()=>forecastChart(c, {title:s.short, today, compact:true, height:150, yMax, series:[{label:s.short, color:s.c, now:p.now, y2030:p.y2030, y2035:p.y2035, conf:p.conf, band:p.band}]}));
  });
  todo.forEach(f=>f());
}

function renderHero(){
  const last=lastRun, prev=prevRun;
  const box=document.getElementById("needle");
  if(last?.index!=null){
    dial(document.getElementById("dial"), last.index, {size:220});
    document.getElementById("index-value").replaceChildren(document.createTextNode(fmt(last.index)), el("small",{},"%"));
    document.getElementById("index-delta").replaceChildren(deltaNode(last.index, prev?.index, sinceText()));
    if(last.indexNote) document.getElementById("index-note").textContent=last.indexNote;
  }
  const n=last?.needle; box.replaceChildren();
  if(!n){ box.hidden=true; return; }
  box.className="needle"+(n.quiet?" quiet":"");
  box.append(el("div",{class:"kicker"}, n.quiet?"Quiet day":"What moved the needle"));
  box.append(el("div",{class:"headline"}, n.headline));
  if(n.detail){ const p=el("p",{},n.detail+" "); const a=link(n.url,"source"); if(a) p.append(a); box.append(p); }
  box.hidden=false;
}

function renderTripwires(){
  const last=lastRun;
  const host=document.getElementById("tripwires"), count=document.getElementById("tripwire-count");
  host.replaceChildren(); count.textContent="";
  if(!last?.tripwires?.length){ host.append(el("p",{class:"muted"},"No tripwires recorded.")); return; }
  tripwireBoard(host, last.tripwires, {root:"", alarm});
  const c={tripped:0,watching:0,quiet:0}; let unknown=0;
  last.tripwires.forEach(w=>{ const k=String(w?.status??"").trim().toLowerCase(); if(Object.prototype.hasOwnProperty.call(c,k)) c[k]++; else unknown++; });
  count.textContent=`${c.tripped} tripped, ${c.watching} watching, ${c.quiet} quiet.` + (unknown?` ${unknown} with an unrecognized status (data error).`:"");
}

function renderChanges(){
  const last=lastRun, prev=prevRun;
  const c=document.getElementById("changes"); c.replaceChildren();
  // A reading corrected after publication says so, and points to the dated log.
  const fixed = last?.report ? corrections.filter(x => x && x.page === last.report) : [];
  if(fixed.length){
    const when = fixed.map(x => String(x.date||"")).filter(Boolean).sort().pop();
    const p = el("p",{class:"muted small"}, `Corrected${when ? " " + fmtDate(when) : ""}: ${fixed.length} ${fixed.length===1?"item":"items"} in this reading and its report. `);
    const a = link("about.html#corrections", "See the corrections log"); if(a) p.append(a, ".");
    c.append(p);
  }
  if(last?.summary) c.append(el("p",{},String(last.summary)));
  const list=Array.isArray(last?.changes)?last.changes:[];
  if(list.length){ const ul=el("ul",{class:"plain"}); list.forEach(t=>ul.append(el("li",{},String(t)))); c.append(ul); }
  const rep=link(last?.report,"Read the full report for "+fmtDate(last?.date)+" →"); if(rep){ const p=el("p"); p.append(rep); c.append(p); }

  const d=document.getElementById("deltas"); d.replaceChildren();
  if(!prev){
    const earlier = runs.filter(r=>!pub.includes(r) && String(r.date)<=String(last?.date));
    const quick = earlier.length ? (earlier.some(r=>/chat/i.test(String(r.label||""))) ? " (an earlier quick chat estimate is in the run history)." : " (an earlier quick estimate is in the run history).") : ".";
    d.append(el("p",{class:"muted"},"This is the first full reading; movement appears from the next reading"+quick));
    return;
  }
  const tb=el("table"); const hr=el("tr"); ["Hypothesis","Now","By end-2030","By end-2035"].forEach(t=>hr.append(el("th",{},t))); tb.append(hr);
  SERIES.forEach(s=>{
    const tr=el("tr"); tr.append(el("td",{},s.short));
    ["now","y2030","y2035"].forEach(hz=>{
      const a=val(prev,s.k,hz), b=val(last,s.k,hz); const td=el("td",{class:"num"});
      td.append(document.createTextNode(`${fmt(a)} → ${fmt(b)} `));
      if(a!=null&&b!=null&&fmt(a)!==fmt(b)) td.append(el("span",{class:"delta "+(b>a?"up":"down")},(b>a?"▲":"▼")));
      tr.append(td);
    });
    tb.append(tr);
  });
  d.append(tb);
  const same = prev.date===last.date && prev.label && last.label;
  d.append(el("p",{class:"muted"}, same ? `Comparing the ${prev.label} with the ${last.label}, both on ${fmtDate(last.date)}. Figures in percent.` : `Comparing ${fmtDate(prev.date)} with ${fmtDate(last.date)}. Figures in percent.`));
}

function renderTimeline(){
  const last=lastRun; const t=document.getElementById("timeline"); t.replaceChildren();
  if(!last?.timeline){ t.append(el("p",{class:"muted"},"No timeline notes yet.")); return; }
  String(last.timeline).split(/\n\n+/).forEach(p=>t.append(el("p",{},p)));
  if(Array.isArray(last.signals)&&last.signals.length){
    t.append(el("h3",{},"Signals to watch"));
    const ul=el("ul",{class:"plain"}); last.signals.forEach(s=>ul.append(el("li",{},String(s)))); t.append(ul);
  }
}

function renderRoundup(){
  const last=lastRun; const box=document.getElementById("roundup"); box.replaceChildren();
  const groups=Array.isArray(last?.roundup)?last.roundup:[];
  document.getElementById("roundup-note").textContent=last?.roundupWindow?`Covering ${last.roundupWindow}. Each item links to its source.`:"";
  if(!groups.length){ box.append(el("p",{class:"muted"},"No roundup for the latest reading.")); return; }
  const wrap=el("div",{class:"roundup"});
  groups.forEach(g=>{
    const sec=el("div",{class:"rgroup"}); sec.append(el("h3",{},String(g.topic||"")));
    const ul=el("ul",{class:"plain"});
    (Array.isArray(g.items)?g.items:[]).forEach(it=>{
      const li=el("li");
      if(it.date) li.append(el("span",{class:"rdate"},String(it.date)+" "));
      li.append(document.createTextNode(String(it.text||"")+" "));
      const a=link(it.url,"source"); if(a) li.append(a);
      ul.append(li);
    });
    sec.append(ul); wrap.append(sec);
  });
  box.append(wrap);
}

function renderHistory(){
  const h=document.getElementById("history"); h.replaceChildren();
  [...runs].reverse().forEach((r,i)=>{
    const d=el("details");
    d.append(el("summary",{},fmtDate(r.date)+(r.label?" · "+r.label:"")+(i===0?" (latest)":"")+(r.comparable===false||!r.report?" (quick estimate, not used for change figures)":"")));
    const b=el("div",{class:"body"});
    if(r.note) b.append(el("p",{class:"muted"},String(r.note)));
    const line=SERIES.map(s=>`${s.letter} ${fmt(val(r,s.k,"now"))}/${fmt(val(r,s.k,"y2030"))}/${fmt(val(r,s.k,"y2035"))}`).join("   ");
    b.append(el("p",{class:"muted"},"Now / end-2030 / end-2035, in percent: "+line));
    if(r.summary) b.append(el("p",{},String(r.summary)));
    if(Array.isArray(r.changes)&&r.changes.length){ const ul=el("ul",{class:"plain"}); r.changes.forEach(c=>ul.append(el("li",{},String(c)))); b.append(ul); }
    const rep=link(r.report,"Full report"); if(rep){ const p=el("p"); p.append(rep); b.append(p); }
    if(Array.isArray(r.sources)&&r.sources.length){
      b.append(el("p",{class:"muted",style:"margin-top:8px"},"Key sources"));
      const ul=el("ul",{class:"plain"});
      r.sources.forEach(s=>{ const li=el("li"); const a=link(s?.url, String(s?.title||s?.url||"")); if(a) li.append(a); else li.textContent=String(s?.title||""); ul.append(li); });
      b.append(ul);
    }
    d.append(b); h.append(d);
  });
}

// The first sentence of the summary, as the page's bottom line (initialisms and month
// abbreviations don't end a sentence).
function firstSentence(t){
  const s = String(t||"").trim(); if(!s) return "";
  const re = /[.!?]["”’)]?(?=\s+["“‘(]?[A-Z])/g; let m;
  while((m = re.exec(s))){ const head = s.slice(0, m.index+1); if(!/(?:(?:\b[A-Z]\.){2,}|\b(?:Mr|Mrs|Ms|Dr|St|vs|etc|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|Inc|Corp|Co|Ltd)\.)$/.test(head)) return s.slice(0, m.index+m[0].length); }
  return s;
}

function renderAll(){
  const st=document.getElementById("status");
  if(!runs.length){ st.textContent="No readings stored yet."; return; }
  pub = published(runs);
  lastRun = pub.length ? pub[pub.length-1] : runs[runs.length-1];
  prevRun = pub.length > 1 ? pub[pub.length-2] : null;
  const n = pub.length || runs.length, lead = firstSentence(lastRun.summary);
  st.replaceChildren();
  if(lead) st.append(el("span",{class:"status-lead"},lead), " ");
  st.append(`${n} reading${n>1?"s":""} · latest ${fmtDate(lastRun.date)}.`);
  const sections = [
    // full detail (trigger codes, note) once the level is Warning or higher; alarm.html always has it
    ["fire alarm", () => { if(alarm) alarmIndicator(document.getElementById("alarm"), alarm, {compact: !(Number(alarm?.current?.level) >= 2)}); }],
    ["index", renderHero], ["gauges", renderGauges], ["tripwires", renderTripwires], ["readings", renderReadings],
    ["readings chart", renderChart], ["forecast", renderForecast], ["latest reading", renderChanges],
    ["news roundup", renderRoundup], ["timeline", renderTimeline], ["history", renderHistory]
  ];
  let bad = 0;
  sections.forEach(([name, f]) => { try{ f(); }catch(e){ bad++; console.error(`Couldn't draw the ${name} section:`, e); } });
  if(bad) st.append(` (${bad} section${bad>1?"s":""} could not be drawn.)`);
}

// Redraw the width-dependent charts only when the width changes: phones fire resize when the
// address bar hides, and a redraw would close an open "Show as table".
let rt, lastW = innerWidth;
addEventListener("resize",()=>{ if(innerWidth===lastW) return; lastW=innerWidth; clearTimeout(rt); rt=setTimeout(()=>{ if(!runs.length) return; [renderChart, renderForecast].forEach(f=>{ try{ f(); }catch(e){ console.error(e); } }); },150); });
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change",()=>{ if(runs.length) renderAll(); });

(async()=>{
  const st=document.getElementById("status");
  try{
    const res=await fetch("data/runs.json",{cache:"no-cache"});
    if(!res.ok) throw new Error("HTTP "+res.status);
    const data=await res.json();
    if(!Array.isArray(data)) throw new Error("runs.json is not a list");
    runs=data.map((r,i)=>({...r,_i:i})).sort((a,b)=>String(a.date).localeCompare(String(b.date))||a._i-b._i);
  }catch(e){ console.error("Couldn't load data/runs.json:", e); st.textContent="Couldn't load data/runs.json. Reload to try again."; return; }
  const getJSON = async p => { const r=await fetch(p,{cache:"no-cache"}); if(!r.ok) throw new Error(p+": HTTP "+r.status); return r.json(); };
  const [ext, gdefs, al, corr] = await Promise.all(["data/external_forecasts.json","data/gauges.json","data/alarm.json","data/corrections.json"].map(p => getJSON(p).catch(e => { console.error(e); return null; })));
  corrections = Array.isArray(corr?.corrections) ? corr.corrections : [];
  outside = Array.isArray(ext?.forecasts) ? ext.forecasts : [];
  gaugeDefs = Array.isArray(gdefs?.gauges) ? gdefs.gauges : [];
  alarm = al;
  alarmBanner("");
  renderAll();
})();
