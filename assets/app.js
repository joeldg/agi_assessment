import {lineChart, dial, tripwireBoard, forecastChart, gaugeRow, alarmIndicator, alarmBanner} from "./charts.js";

const SERIES = [
  {k:"A", short:"A: AGI undisclosed", c:"--sA"},
  {k:"B", short:"B: Secret RSI", c:"--sB"},
  {k:"C", short:"C: Covert AGI online", c:"--sC"},
  {k:"D", short:"D: Covert govt influence", c:"--sD"},
  {k:"Dopen", short:"D-open: Open govt influence", c:"--sE"}
];
let runs = [];

const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const el = (tag, attrs={}, text) => { const e=document.createElement(tag); for(const [a,v] of Object.entries(attrs)) e.setAttribute(a,v); if(text!=null) e.textContent=text; return e; };
const svgEl = (tag, attrs={}) => { const e=document.createElementNS("http://www.w3.org/2000/svg",tag); for(const [a,v] of Object.entries(attrs)) e.setAttribute(a,v); return e; };
const fmt = v => (v==null||isNaN(v)) ? "–" : v===0 ? "0" : (v<1 ? v.toFixed(1) : (v<10 && v%1 ? v.toFixed(1) : Math.round(v).toString()));
const val = (run,k,h) => { const p = run?.probs?.[k]; return p ? Number(p[h]) : null; };
const fmtDate = d => { const t=new Date(d+"T12:00:00"); return isNaN(t) ? d : t.toLocaleDateString(undefined,{day:"numeric",month:"short",year:"numeric"}); };
const link = (href, text) => el("a",{href}, text);

function deltaNode(cur, prev){
  if(cur==null || prev==null) return el("span",{class:"delta flat"},"first run");
  const d = cur-prev;
  if(Math.abs(d)<0.05) return el("span",{class:"delta flat"},"no change");
  return el("span",{class:"delta "+(d>0?"up":"down")}, (d>0?"▲ +":"▼ −")+fmt(Math.abs(d))+" pts since last run");
}

function sparkline(k){
  const w=140,h=28, vals=runs.map(r=>val(r,k,"now")).filter(v=>v!=null);
  const s=svgEl("svg",{width:w,height:h,viewBox:`0 0 ${w} ${h}`,"aria-hidden":"true"});
  if(vals.length<2){ s.appendChild(svgEl("line",{x1:0,x2:w,y1:h-4,y2:h-4,stroke:css("--rule")})); return s; }
  const max=Math.max(...vals,1);
  const pts=vals.map((v,i)=>[i*(w-4)/(vals.length-1)+2, h-3-v/max*(h-6)]);
  s.appendChild(svgEl("polyline",{points:pts.map(p=>p.join(",")).join(" "),fill:"none",stroke:css(SERIES.find(x=>x.k===k).c),"stroke-width":2,"stroke-linejoin":"round","stroke-linecap":"round"}));
  return s;
}

function renderReadings(){
  const box=document.getElementById("readings"); box.replaceChildren();
  const last=runs[runs.length-1], prev=runs[runs.length-2];
  SERIES.forEach(s=>{
    const r=el("div",{class:"reading"});
    const n=el("div",{class:"name"}); const sw=el("span",{class:"swatch"}); sw.style.background=css(s.c); n.append(sw, document.createTextNode(s.short)); r.append(n);
    const f=el("div",{class:"fig"}); f.append(document.createTextNode(fmt(val(last,s.k,"now")))); f.append(el("small",{},"%")); r.append(f);
    r.append(deltaNode(val(last,s.k,"now"), val(prev,s.k,"now")));
    const conf = last?.probs?.[s.k]?.conf;
    r.append(el("div",{class:"horizons"}, `By 2030 ${fmt(val(last,s.k,"y2030"))}%, by 2035 ${fmt(val(last,s.k,"y2035"))}%${conf?". Confidence: "+conf:""}`));
    r.append(sparkline(s.k));
    box.append(r);
  });
}

function renderChart(){
  const byDate=new Map(); runs.forEach(r=>byDate.set(r.date,r)); // one point per day: the latest run
  const days=[...byDate.values()];
  lineChart(document.getElementById("chart"), {
    title:"Probability true now for each hypothesis",
    series: SERIES.map(s=>({label:s.short, short:s.k==="Dopen"?"D-open":s.k, color:s.c, values:days.map(r=>({x:r.date, y:val(r,s.k,"now")}))}))
  });
}

let outside = [], gaugeDefs = [], alarm = null;
function renderGauges(){ gaugeRow(document.getElementById("gauge-row"), gaugeDefs, runs); }
function renderForecast(){
  const last=runs[runs.length-1]; if(!last) return;
  const today=last.date;
  if(last.agi) forecastChart(document.getElementById("fc-agi"), {title:"Strict AGI exists, public or hidden", today, yMax:100,
    series:[{label:"Our forecast: strict AGI exists", short:"AGI", color:"--ink", ...last.agi}], markers:outside});
  const grid=document.getElementById("fc-grid"); grid.replaceChildren();
  const todo=[]; // lay out every card first, then draw, so each chart measures its final width
  SERIES.forEach(s=>{
    const p=last.probs?.[s.k]; if(!p) return;
    const m=el("div",{class:"mini"}); const h3=el("h3"); const sw=el("span",{class:"swatch"}); sw.style.background=css(s.c); h3.append(sw, document.createTextNode(s.short)); m.append(h3);
    const c=el("div"); m.append(c);
    m.append(el("p",{class:"muted"},`${fmt(p.now)}% now → ${fmt(p.y2030)}% by 2030 → ${fmt(p.y2035)}% by 2035 · ${p.conf} confidence`));
    grid.append(m);
    todo.push(()=>forecastChart(c, {title:s.short, today, compact:true, height:150, series:[{label:s.short, color:s.c, now:p.now, y2030:p.y2030, y2035:p.y2035, conf:p.conf}]}));
  });
  todo.forEach(f=>f());
}

function renderHero(){
  const last=runs[runs.length-1], prev=runs[runs.length-2];
  if(last?.index==null) return;
  dial(document.getElementById("dial"), last.index, {size:220});
  document.getElementById("index-value").replaceChildren(document.createTextNode(fmt(last.index)), el("small",{},"%"));
  const d=document.getElementById("index-delta"); d.replaceChildren(deltaNode(last.index, prev?.index));
  if(last.indexNote) document.getElementById("index-note").textContent=last.indexNote;
  const n=last.needle, box=document.getElementById("needle"); box.replaceChildren();
  if(!n){ box.hidden=true; return; }
  box.className="needle"+(n.quiet?" quiet":"");
  box.append(el("div",{class:"kicker"}, n.quiet?"Quiet day":"What moved the needle"));
  box.append(el("div",{class:"headline"}, n.headline));
  if(n.detail){ const p=el("p",{},n.detail+" "); if(n.url) p.append(el("a",{href:n.url,target:"_blank",rel:"noopener"},"source")); box.append(p); }
}

function renderTripwires(){
  const last=runs[runs.length-1];
  const host=document.getElementById("tripwires");
  if(!last?.tripwires?.length){ host.append(el("p",{class:"muted"},"No tripwires recorded.")); return; }
  tripwireBoard(host, last.tripwires);
  const c={tripped:0,watching:0,quiet:0}; last.tripwires.forEach(w=>c[w.status]++);
  document.getElementById("tripwire-count").textContent=`${c.tripped} tripped, ${c.watching} watching, ${c.quiet} quiet.`;
}

function renderChanges(){
  const last=runs[runs.length-1], prev=runs[runs.length-2];
  const c=document.getElementById("changes"); c.replaceChildren();
  if(last?.summary) c.append(el("p",{},String(last.summary)));
  const list=Array.isArray(last?.changes)?last.changes:[];
  if(list.length){ const ul=el("ul",{class:"plain"}); list.forEach(t=>ul.append(el("li",{},String(t)))); c.append(ul); }
  if(last?.report){ const p=el("p"); p.append(link(last.report,"Read the full report for "+fmtDate(last.date)+" →")); c.append(p); }

  const d=document.getElementById("deltas"); d.replaceChildren();
  if(!prev){ d.append(el("p",{class:"muted"},"This is the baseline run. Movement appears from the second run onward.")); return; }
  const tb=el("table"); const hr=el("tr"); ["Hypothesis","Now","By 2030","By 2035"].forEach(h=>hr.append(el("th",{},h))); tb.append(hr);
  SERIES.forEach(s=>{
    const tr=el("tr"); tr.append(el("td",{},s.short));
    ["now","y2030","y2035"].forEach(h=>{
      const a=val(prev,s.k,h), b=val(last,s.k,h); const td=el("td",{class:"num"});
      td.append(document.createTextNode(`${fmt(a)} → ${fmt(b)} `));
      if(a!=null&&b!=null&&Math.abs(b-a)>=0.05) td.append(el("span",{class:"delta "+(b>a?"up":"down")},(b>a?"▲":"▼")));
      tr.append(td);
    });
    tb.append(tr);
  });
  d.append(tb);
  d.append(el("p",{class:"muted"},`Comparing ${fmtDate(prev.date)} with ${fmtDate(last.date)}. Figures in percent.`));
}

function renderTimeline(){
  const last=runs[runs.length-1]; const t=document.getElementById("timeline"); t.replaceChildren();
  if(!last?.timeline){ t.append(el("p",{class:"muted"},"No timeline notes yet.")); return; }
  String(last.timeline).split(/\n\n+/).forEach(p=>t.append(el("p",{},p)));
  if(Array.isArray(last.signals)&&last.signals.length){
    t.append(el("h3",{},"Signals to watch"));
    const ul=el("ul",{class:"plain"}); last.signals.forEach(s=>ul.append(el("li",{},String(s)))); t.append(ul);
  }
}

function renderRoundup(){
  const last=runs[runs.length-1]; const box=document.getElementById("roundup"); box.replaceChildren();
  const groups=Array.isArray(last?.roundup)?last.roundup:[];
  document.getElementById("roundup-note").textContent=last?.roundupWindow?`Covering ${last.roundupWindow}. Each item links to its source.`:"";
  if(!groups.length){ box.append(el("p",{class:"muted"},"No roundup for the latest run.")); return; }
  const wrap=el("div",{class:"roundup"});
  groups.forEach(g=>{
    const sec=el("div",{class:"rgroup"}); sec.append(el("h3",{},String(g.topic||"")));
    const ul=el("ul",{class:"plain"});
    (g.items||[]).forEach(it=>{
      const li=el("li");
      if(it.date) li.append(el("span",{class:"rdate"},String(it.date)+" "));
      li.append(document.createTextNode(String(it.text||"")+" "));
      const url=String(it.url||""); if(/^https?:\/\//.test(url)) li.append(el("a",{href:url,target:"_blank",rel:"noopener noreferrer"},"source"));
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
    d.append(el("summary",{},fmtDate(r.date)+(r.label?" · "+r.label:"")+(i===0?" (latest)":"")));
    const b=el("div",{class:"body"});
    const line=SERIES.map(s=>`${s.k==="Dopen"?"D-open":s.k} ${fmt(val(r,s.k,"now"))}/${fmt(val(r,s.k,"y2030"))}/${fmt(val(r,s.k,"y2035"))}`).join("   ");
    b.append(el("p",{class:"muted"},"Now / 2030 / 2035, in percent: "+line));
    if(r.summary) b.append(el("p",{},String(r.summary)));
    if(Array.isArray(r.changes)&&r.changes.length){ const ul=el("ul",{class:"plain"}); r.changes.forEach(c=>ul.append(el("li",{},String(c)))); b.append(ul); }
    if(r.report){ const p=el("p"); p.append(link(r.report,"Full report")); b.append(p); }
    if(Array.isArray(r.sources)&&r.sources.length){
      b.append(el("p",{class:"muted",style:"margin-top:8px"},"Key sources"));
      const ul=el("ul",{class:"plain"});
      r.sources.forEach(s=>{ const li=el("li"); const url=String(s.url||""); if(/^https?:\/\//.test(url)){ li.append(el("a",{href:url,target:"_blank",rel:"noopener noreferrer"},String(s.title||url))); } else li.textContent=String(s.title||""); ul.append(li); });
      b.append(ul);
    }
    d.append(b); h.append(d);
  });
}

function renderAll(){
  const st=document.getElementById("status");
  if(!runs.length){ st.textContent="No runs stored yet."; return; }
  const last=runs[runs.length-1];
  st.textContent=`${runs.length} run${runs.length>1?"s":""} recorded. Latest: ${fmtDate(last.date)}.`;
  if(alarm) alarmIndicator(document.getElementById("alarm"), alarm); renderHero(); renderGauges(); renderTripwires(); renderReadings(); renderChart(); renderForecast(); renderChanges(); renderRoundup(); renderTimeline(); renderHistory();
}

let rt; addEventListener("resize",()=>{ clearTimeout(rt); rt=setTimeout(()=>{ if(runs.length){ renderChart(); renderForecast(); } },150); });
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change",()=>{ if(runs.length){ document.getElementById("tripwires").replaceChildren(); renderAll(); } });

(async()=>{
  const st=document.getElementById("status");
  try{
    const res=await fetch("data/runs.json",{cache:"no-cache"});
    runs=(await res.json()).map((r,i)=>({...r,_i:i})).sort((a,b)=>String(a.date).localeCompare(String(b.date))||a._i-b._i);
    try{ outside=(await (await fetch("data/external_forecasts.json",{cache:"no-cache"})).json()).forecasts; }catch(e){ outside=[]; }
    try{ gaugeDefs=(await (await fetch("data/gauges.json",{cache:"no-cache"})).json()).gauges; }catch(e){ gaugeDefs=[]; }
    try{ alarm=await (await fetch("data/alarm.json",{cache:"no-cache"})).json(); }catch(e){ alarm=null; }
    alarmBanner("");
    renderAll();
  }catch(e){ st.textContent="Couldn't load data/runs.json. Reload to try again."; }
})();
