const SERIES = [
  {k:"A", short:"A: AGI undisclosed", c:"--sA"},
  {k:"B", short:"B: Secret RSI", c:"--sB"},
  {k:"C", short:"C: Covert AGI online", c:"--sC"},
  {k:"D", short:"D: Covert govt influence", c:"--sD"},
  {k:"Dopen", short:"D-open: Open govt influence", c:"--sE"}
];
const HLABEL = {now:"now", y2030:"by 2030", y2035:"by 2035"};
let runs = [];
let horizon = "now";
const hidden = new Set();

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
  s.appendChild(svgEl("polyline",{points:pts.map(p=>p.join(",")).join(" "),fill:"none",stroke:css(SERIES.find(x=>x.k===k).c),"stroke-width":1.6}));
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

function niceMax(m){ for(const s of [1,2,5,10,20,25,50,75,100]) if(m<=s) return s; return 100; }

function renderChart(){
  const host=document.getElementById("chart"); host.replaceChildren();
  const W=Math.max(host.clientWidth||600, 300), H=300, L=40, R=16, T=14, B=34;
  const vis=SERIES.filter(s=>!hidden.has(s.k));
  const all=runs.flatMap(r=>vis.map(s=>val(r,s.k,horizon))).filter(v=>v!=null);
  const ymax=niceMax(Math.max(...all,1)*1.1);
  const svg=svgEl("svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":`Probability ${HLABEL[horizon]} for each hypothesis across ${runs.length} runs`});
  const ax=svgEl("g",{class:"axis"}); svg.append(ax);
  const x = i => runs.length<2 ? L+(W-L-R)/2 : L + i*(W-L-R)/(runs.length-1);
  const y = v => T + (1-v/ymax)*(H-T-B);
  for(let i=0;i<=4;i++){ const v=ymax*i/4; ax.append(svgEl("line",{x1:L,x2:W-R,y1:y(v),y2:y(v)})); const t=svgEl("text",{x:L-6,y:y(v)+4,"text-anchor":"end"}); t.textContent=fmt(v)+"%"; ax.append(t); }
  const every=Math.max(1,Math.ceil(runs.length/6));
  runs.forEach((r,i)=>{ if(i%every && i!==runs.length-1) return; const t=svgEl("text",{x:x(i),y:H-10,"text-anchor":"middle"}); t.textContent=fmtDate(r.date).replace(/,? \d{4}$/,""); ax.append(t); });
  vis.forEach(s=>{
    const col=css(s.c);
    const pts=runs.map((r,i)=>[x(i),val(r,s.k,horizon)]).filter(p=>p[1]!=null).map(p=>[p[0],y(p[1])]);
    if(pts.length>1) svg.append(svgEl("polyline",{points:pts.map(p=>p.join(",")).join(" "),fill:"none",stroke:col,"stroke-width":2,"stroke-dasharray":s.k==="Dopen"?"5 4":"0"}));
    pts.forEach(p=>{ const c=svgEl("circle",{cx:p[0],cy:p[1],r:3.5,fill:col}); c.append(svgEl("title")); c.firstChild.textContent=`${s.short}: ${fmt(ymax*(1-(p[1]-T)/(H-T-B)))}%`; svg.append(c); });
  });
  host.append(svg);
}

function renderLegend(){
  const lg=document.getElementById("legend"); lg.replaceChildren();
  SERIES.forEach(s=>{
    const b=el("button",{"aria-pressed":String(!hidden.has(s.k))});
    const sw=el("span",{class:"swatch"}); sw.style.background=css(s.c);
    b.append(sw, document.createTextNode(s.short));
    b.onclick=()=>{ hidden.has(s.k)?hidden.delete(s.k):hidden.add(s.k); renderLegend(); renderChart(); };
    lg.append(b);
  });
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
  renderReadings(); renderLegend(); renderChart(); renderChanges(); renderRoundup(); renderTimeline(); renderHistory();
}

document.querySelectorAll(".seg button").forEach(b=>b.onclick=()=>{
  horizon=b.dataset.h;
  document.querySelectorAll(".seg button").forEach(x=>x.setAttribute("aria-pressed",String(x===b)));
  if(runs.length) renderChart();
});
let rt; addEventListener("resize",()=>{ clearTimeout(rt); rt=setTimeout(()=>runs.length&&renderChart(),150); });
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change",()=>runs.length&&renderAll());

(async()=>{
  const st=document.getElementById("status");
  try{
    const res=await fetch("data/runs.json",{cache:"no-cache"});
    runs=(await res.json()).map((r,i)=>({...r,_i:i})).sort((a,b)=>String(a.date).localeCompare(String(b.date))||a._i-b._i);
    renderAll();
  }catch(e){ st.textContent="Couldn't load data/runs.json. Reload to try again."; }
})();
