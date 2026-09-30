/* Hidden AGI watch chart kit. One style for every graph on the site.
   Rules (see style.html): hairline solid grid, 2px lines, >=8px dots with a 2px surface ring,
   bars <=24px with 4px rounded data-ends, legend for >=2 series, sparing direct labels,
   text in ink tokens (never series colors), hover tooltip on every chart, table view available. */
const NS = "http://www.w3.org/2000/svg";
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const svg = (tag, a={}) => { const e=document.createElementNS(NS,tag); for(const [k,v] of Object.entries(a)) e.setAttribute(k,v); return e; };
const h = (tag, a={}, text) => { const e=document.createElement(tag); for(const [k,v] of Object.entries(a)) e.setAttribute(k,v); if(text!=null) e.textContent=text; return e; };
const fmtPct = v => v==null||isNaN(v) ? "–" : (v===0 ? "0" : v<1 ? v.toFixed(1) : (v<10 && v%1 ? v.toFixed(1) : String(Math.round(v)))) + "%";
const parseDate = d => new Date(d + "T12:00:00");
const fmtDate = (d, opts={day:"numeric",month:"short"}) => parseDate(d).toLocaleDateString(undefined, opts);
const DAY = 864e5;

export const SERIES = {
  A:{label:"A: AGI undisclosed", color:"--sA"},
  B:{label:"B: Secret RSI", color:"--sB"},
  C:{label:"C: Covert AGI online", color:"--sC"},
  D:{label:"D: Covert govt influence", color:"--sD"},
  Dopen:{label:"D-open: Open govt influence", color:"--sE"}
};

/* ---- tooltip (one per page) ---- */
let tip;
function tooltip(){
  if(tip) return tip;
  tip = h("div",{class:"chart-tip",role:"status","aria-live":"polite"}); tip.hidden = true; document.body.append(tip); return tip;
}
function showTip(x, y, rows, title){
  const t = tooltip(); t.replaceChildren();
  if(title) t.append(h("div",{class:"tip-title"},title));
  rows.forEach(r => { const row=h("div",{class:"tip-row"}); if(r.color){ const k=h("span",{class:"tip-key"}); k.style.background=r.color; row.append(k);} row.append(h("span",{},r.label)); if(r.value!=null) row.append(h("strong",{},r.value)); t.append(row); });
  t.hidden = false;
  const pad=12, w=t.offsetWidth, hh=t.offsetHeight;
  let left = x + pad, top = y + pad;
  if(left + w > innerWidth - 8) left = x - w - pad;
  if(top + hh > innerHeight - 8) top = y - hh - pad;
  t.style.left = Math.max(8,left) + "px"; t.style.top = Math.max(8,top) + "px";
}
const hideTip = () => { if(tip) tip.hidden = true; };

/* ---- shared pieces ---- */
function legend(items){
  const lg = h("div",{class:"legend"});
  items.forEach(it => { const s=h("span",{class:"lg-item"}); const k=h("span",{class:it.line?"lg-line":"swatch"}); k.style.background=css(it.color)||it.color; s.append(k, document.createTextNode(it.label)); lg.append(s); });
  return lg;
}
function tableView(caption, head, rows){
  const d = h("details",{class:"table-view"}); d.append(h("summary",{},"Show as table"));
  const wrap=h("div",{class:"table-wrap"}); const t=h("table"); t.append(h("caption",{class:"sr-only"},caption));
  const tr=h("tr"); head.forEach(c=>tr.append(h("th",{scope:"col"},c))); t.append(tr);
  rows.forEach(r=>{ const row=h("tr"); r.forEach(c=>row.append(h("td",{},c))); t.append(row); });
  wrap.append(t); d.append(wrap); return d;
}
function niceTicks(max, n=4){
  const step = [0.25,0.5,1,2,2.5,5,10,20,25].find(st => st*n >= max) || 25;
  const top = Math.min(100, step*Math.max(1, Math.ceil(max/step)));
  const ticks=[]; for(let v=0; v<=top+1e-9; v+=step) ticks.push(+v.toFixed(2));
  return {top, ticks};
}

/* ---- line chart: several series over dates, one y axis in percent ---- */
export function lineChart(host, {series, height=280, yMax, title, endLabels=true}){
  host.replaceChildren();
  const box = h("div",{class:"chart"}); host.append(box);
  const W = Math.max(box.clientWidth || host.clientWidth || 600, 300), H = height;
  const L = 44, R = endLabels ? 118 : 16, T = 12, B = 30;
  const dates = [...new Set(series.flatMap(s => s.values.map(v => v.x)))].sort();
  const all = series.flatMap(s => s.values.map(v => v.y)).filter(v => v!=null);
  const {top:ymax, ticks} = yMax ? {top:yMax, ticks:[0,yMax/4,yMax/2,yMax*3/4,yMax]} : niceTicks(Math.max(...all, 1) * 1.1);
  const t0 = parseDate(dates[0]).getTime(), t1 = parseDate(dates[dates.length-1]).getTime();
  const x = d => dates.length < 2 || t1===t0 ? L + (W-L-R)/2 : L + (parseDate(d).getTime()-t0)/(t1-t0)*(W-L-R);
  const y = v => T + (1 - v/ymax) * (H-T-B);
  const s = svg("svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":title||"Line chart"});
  const g = svg("g",{class:"axis"}); s.append(g);
  ticks.forEach((v,i)=>{ g.append(svg("line",{x1:L,x2:W-R,y1:y(v),y2:y(v),class:i?"grid":"base"})); const tx=svg("text",{x:L-8,y:y(v)+4,"text-anchor":"end"}); tx.textContent=fmtPct(v); g.append(tx); });
  const every = Math.max(1, Math.ceil(dates.length/6));
  dates.forEach((d,i)=>{ if(i%every && i!==dates.length-1) return; const tx=svg("text",{x:x(d),y:H-8,"text-anchor":"middle"}); tx.textContent=fmtDate(d); g.append(tx); });
  const surface = css("--surface");
  const ends = [];
  series.forEach(se => {
    const col = css(se.color) || se.color;
    const pts = se.values.filter(v => v.y!=null).map(v => [x(v.x), y(v.y), v]);
    if(pts.length > 1) s.append(svg("polyline",{points:pts.map(p=>p[0]+","+p[1]).join(" "),fill:"none",stroke:col,"stroke-width":2,"stroke-linejoin":"round","stroke-linecap":"round"}));
    pts.forEach(p => s.append(svg("circle",{cx:p[0],cy:p[1],r:4,fill:col,stroke:surface,"stroke-width":2})));
    if(pts.length) ends.push({y:pts[pts.length-1][1], x:pts[pts.length-1][0], label:se.short||se.label, v:pts[pts.length-1][2].y});
  });
  // end labels only where they don't collide; the legend and tooltip carry the rest
  if(endLabels){
    ends.sort((a,b)=>a.y-b.y); let last=-99;
    ends.forEach(e => { if(e.y - last < 14) return; last = e.y; const tx=svg("text",{x:e.x+10,y:e.y+4,class:"end-label"}); tx.textContent=`${e.label} ${fmtPct(e.v)}`; s.append(tx); });
  }
  // crosshair + tooltip
  const cross = svg("line",{y1:T,y2:H-B,class:"crosshair",visibility:"hidden"}); s.append(cross);
  const hit = svg("rect",{x:L,y:T,width:W-L-R,height:H-T-B,fill:"transparent"}); s.append(hit);
  const nearest = px => dates.reduce((b,d)=>Math.abs(x(d)-px)<Math.abs(x(b)-px)?d:b, dates[0]);
  const move = ev => {
    const r = s.getBoundingClientRect(); const px = (ev.touches?ev.touches[0].clientX:ev.clientX) - r.left;
    const d = nearest(px); cross.setAttribute("x1",x(d)); cross.setAttribute("x2",x(d)); cross.setAttribute("visibility","visible");
    const rows = series.map(se => { const v = se.values.filter(p=>p.x===d).pop(); return {label:se.label, value:v?fmtPct(v.y):"–", color:css(se.color)||se.color}; });
    showTip(r.left + x(d), (ev.touches?ev.touches[0].clientY:ev.clientY), rows, fmtDate(d,{day:"numeric",month:"short",year:"numeric"}));
  };
  hit.addEventListener("mousemove", move); hit.addEventListener("touchstart", move, {passive:true});
  hit.addEventListener("mouseleave", () => { cross.setAttribute("visibility","hidden"); hideTip(); });
  box.append(s);
  if(series.length > 1) host.append(legend(series.map(se=>({label:se.label, color:se.color, line:true}))));
  host.append(tableView(title||"Data", ["Date", ...series.map(se=>se.label)], dates.map(d => [fmtDate(d,{day:"numeric",month:"short",year:"numeric"}), ...series.map(se => { const v=se.values.filter(p=>p.x===d).pop(); return v?fmtPct(v.y):"–"; })])));
}

/* ---- the Hidden AGI Index dial: an eye whose iris is 100 ticks, n lit ---- */
export function dial(host, value, {size=220, label="Hidden AGI Index"}={}){
  host.replaceChildren();
  const S = size, c = S/2, rOut = S*0.27, rIn = S*0.19;
  const s = svg("svg",{width:S,height:S*0.66,viewBox:`0 ${S*0.17} ${S} ${S*0.66}`,role:"img","aria-label":`${label}: ${fmtPct(value)}`});
  const ink = css("--ink"), rule = css("--axis"), acc = css("--accent");
  const eyeD = `M ${S*0.03} ${c} C ${S*0.26} ${S*0.1}, ${S*0.74} ${S*0.1}, ${S*0.97} ${c} C ${S*0.74} ${S*0.9}, ${S*0.26} ${S*0.9}, ${S*0.03} ${c} Z`;
  const cid = "eye-" + Math.random().toString(36).slice(2,8);
  const defs = svg("defs"); const cp = svg("clipPath",{id:cid}); cp.append(svg("path",{d:eyeD})); defs.append(cp); s.append(defs);
  const iris = svg("g",{"clip-path":`url(#${cid})`}); s.append(iris);
  const lit = Math.round(Math.min(100, Math.max(0, value)));
  for(let i=0;i<100;i++){
    const a = (i/100)*2*Math.PI - Math.PI/2;
    const on = i < lit;
    iris.append(svg("line",{x1:c+Math.cos(a)*rIn, y1:c+Math.sin(a)*rIn, x2:c+Math.cos(a)*rOut, y2:c+Math.sin(a)*rOut, stroke:on?acc:rule, "stroke-width":on?S*0.014:S*0.008, "stroke-linecap":"round"}));
  }
  s.append(svg("path",{d:eyeD,fill:"none",stroke:ink,"stroke-width":S*0.018,"stroke-linejoin":"round"}));
  s.append(svg("circle",{cx:c,cy:c,r:rIn*0.86,fill:css("--bg")}));
  const t = svg("text",{x:c,y:c+S*0.035,"text-anchor":"middle",class:"dial-value"}); t.textContent = fmtPct(value); t.style.fontSize = (S*0.1)+"px"; s.append(t);
  host.append(s);
}

/* ---- status board (tripwires): icon + label + text, never color alone ---- */
export const STATUS = {
  quiet:{label:"Quiet", icon:"○", color:"--good"},
  watching:{label:"Watching", icon:"◐", color:"--warn"},
  tripped:{label:"Tripped", icon:"●", color:"--crit"}
};
export function tripwireBoard(host, wires){
  host.replaceChildren();
  const order = {tripped:0, watching:1, quiet:2};
  const list = h("ul",{class:"tripwires"});
  [...wires].sort((a,b)=>order[a.status]-order[b.status]).forEach(w => {
    const st = STATUS[w.status] || STATUS.quiet;
    const li = h("li",{class:"tw "+w.status});
    const badge = h("span",{class:"tw-status"}); const ic=h("span",{class:"tw-icon","aria-hidden":"true"},st.icon); ic.style.color=css(st.color); badge.append(ic, document.createTextNode(st.label));
    const body = h("div",{class:"tw-body"});
    const sig = h("div",{class:"tw-signal"}); const hy=h("span",{class:"tw-hyp"}); const sw=h("span",{class:"swatch"}); sw.style.background=css(SERIES[w.hyp]?.color||"--muted"); hy.append(sw, document.createTextNode(w.hyp==="Dopen"?"D-open":w.hyp)); sig.append(hy, document.createTextNode(" " + w.signal));
    body.append(sig);
    const note = h("div",{class:"tw-note muted"}, w.note || ""); if(w.url){ note.append(" "); note.append(h("a",{href:w.url,target:"_blank",rel:"noopener"},"source")); } body.append(note);
    li.append(badge, body); list.append(li);
  });
  host.append(list);
}

/* ---- disclosure lag: horizontal range bars on a date axis, outsider-found highlighted ---- */
export function lagChart(host, incidents, {title="Days from incident to public disclosure"}={}){
  host.replaceChildren();
  const box = h("div",{class:"chart"}); host.append(box);
  const rows = incidents.map(i => ({...i, lag: Math.round((parseDate(i.disclosed)-parseDate(i.occurred))/DAY), ext: i.foundBy!=="lab"})).sort((a,b)=>b.lag-a.lag);
  const W = Math.max(box.clientWidth || 600, 300), rowH = 34, T = 8, B = 30;
  const narrow = W < 560, L = narrow ? 12 : 250, R = 56;
  const H = T + rows.length*(narrow?rowH+18:rowH) + B;
  const t0 = Math.min(...rows.map(r=>parseDate(r.occurred).getTime())) - 7*DAY, t1 = Math.max(...rows.map(r=>parseDate(r.disclosed).getTime())) + 7*DAY;
  const x = t => L + (t-t0)/(t1-t0)*(W-L-R);
  const s = svg("svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":title});
  const g = svg("g",{class:"axis"}); s.append(g);
  const m0 = new Date(t0); m0.setDate(1); m0.setMonth(m0.getMonth()+1);
  for(let d=new Date(m0); d.getTime()<=t1; d.setMonth(d.getMonth()+1)){ const px=x(d.getTime()); g.append(svg("line",{x1:px,x2:px,y1:T,y2:H-B,class:"grid"})); const tx=svg("text",{x:px,y:H-8,"text-anchor":"middle"}); tx.textContent=d.toLocaleDateString(undefined,{month:"short"}); g.append(tx); }
  const acc = css("--accent"), mute = css("--muted"), surface = css("--surface");
  rows.forEach((r,i) => {
    const yy = T + i*(narrow?rowH+18:rowH) + (narrow?18:0);
    const lab = svg("text",{x:narrow?L:L-10,y:narrow?yy-4:yy+rowH/2+4,"text-anchor":narrow?"start":"end",class:"row-label"}); lab.textContent = (r.title.length>(narrow?52:38)?r.title.slice(0,narrow?50:36)+"…":r.title); s.append(lab);
    const x0 = x(parseDate(r.occurred).getTime()), x1 = x(parseDate(r.disclosed).getTime());
    const bh = 12, by = yy + rowH/2 - bh/2;
    const col = r.ext ? acc : mute;
    s.append(svg("rect",{x:x0,y:by,width:Math.max(2,x1-x0),height:bh,rx:4,fill:col,opacity:r.occurredApprox?0.55:1}));
    s.append(svg("circle",{cx:x1,cy:by+bh/2,r:5,fill:col,stroke:surface,"stroke-width":2}));
    const v = svg("text",{x:x1+10,y:by+bh/2+4,class:"end-label"}); v.textContent = r.lag + "d"; s.append(v);
    const hit = svg("rect",{x:0,y:yy,width:W,height:rowH,fill:"transparent"});
    hit.addEventListener("mousemove", ev => showTip(ev.clientX, ev.clientY, [
      {label:"Happened", value:fmtDate(r.occurred,{day:"numeric",month:"short",year:"numeric"}) + (r.occurredApprox?" (approx.)":"")},
      {label:"Disclosed", value:fmtDate(r.disclosed,{day:"numeric",month:"short",year:"numeric"})},
      {label:"Lag", value:r.lag + " days"}, {label:"Found by", value:r.foundBy}], r.title));
    hit.addEventListener("mouseleave", hideTip); s.append(hit);
  });
  box.append(s);
  host.append(legend([{label:"Made public by someone other than the lab", color:"--accent"},{label:"Made public by the lab itself", color:"--muted"}]));
  host.append(h("p",{class:"muted small"},"Faded bars have an approximate start date."));
  host.append(tableView(title, ["Incident","Lab","Happened","Disclosed","Lag (days)","Found by"], rows.map(r=>[r.title, r.lab, fmtDate(r.occurred,{day:"numeric",month:"short",year:"numeric"})+(r.occurredApprox?" (approx.)":""), fmtDate(r.disclosed,{day:"numeric",month:"short",year:"numeric"}), String(r.lag), r.foundBy])));
  return rows;
}

/* ---- probability meters for open forecasts; market odds as a hollow marker ---- */
export function forecastBars(host, forecasts){
  host.replaceChildren();
  const list = h("div",{class:"fc-list"});
  forecasts.forEach(f => {
    const row = h("div",{class:"fc-row"});
    const q = h("div",{class:"fc-q"}); q.append(h("div",{},f.question));
    const meta = h("div",{class:"muted small"}, `Due ${fmtDate(f.deadline,{day:"numeric",month:"short",year:"numeric"})}` + (f.outcome!=null ? ` · Resolved ${f.outcome?"YES":"NO"}` : ""));
    q.append(meta);
    const m = h("div",{class:"fc-meter",role:"img","aria-label":`${f.p}%` + (f.market!=null?`, market ${f.market}%`:"")});
    const fill = h("div",{class:"fc-fill"}); fill.style.width = f.p + "%"; m.append(fill);
    if(f.market!=null){ const mk=h("div",{class:"fc-market",title:`Market: ${f.market}%`}); mk.style.left = f.market + "%"; m.append(mk); }
    const val = h("div",{class:"fc-val"}, f.p + "%");
    row.append(q, m, val);
    row.addEventListener("mousemove", ev => showTip(ev.clientX, ev.clientY, [{label:"Our probability", value:f.p+"%"}, ...(f.market!=null?[{label:"Market", value:f.market+"%"}]:[]), {label:"Resolves", value:f.resolution}], f.question));
    row.addEventListener("mouseleave", hideTip);
    list.append(row);
  });
  host.append(list);
}

/* ---- calibration: predicted bins vs observed frequency, with the diagonal ---- */
export function calibration(host, resolved){
  host.replaceChildren();
  if(resolved.length < 5){ host.append(h("p",{class:"empty"},`Calibration appears once at least 5 forecasts resolve (${resolved.length} so far).`)); return; }
  const bins = [[0,20],[20,40],[40,60],[60,80],[80,101]].map(([a,b]) => { const fs = resolved.filter(f=>f.p>=a&&f.p<b); return {a,b,n:fs.length, pred:fs.reduce((s,f)=>s+f.p,0)/(fs.length||1), obs:fs.filter(f=>f.outcome).length/(fs.length||1)*100}; }).filter(b=>b.n);
  const box = h("div",{class:"chart"}); host.append(box);
  const W = Math.min(Math.max(box.clientWidth||400,280), 420), H = W, L=40,R=12,T=12,B=30;
  const sx = v => L + v/100*(W-L-R), sy = v => T + (1-v/100)*(H-T-B);
  const s = svg("svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":"Calibration: predicted vs observed"});
  const g = svg("g",{class:"axis"}); s.append(g);
  [0,25,50,75,100].forEach(v=>{ g.append(svg("line",{x1:L,x2:W-R,y1:sy(v),y2:sy(v),class:v?"grid":"base"})); const t=svg("text",{x:L-6,y:sy(v)+4,"text-anchor":"end"}); t.textContent=v+"%"; g.append(t); const t2=svg("text",{x:sx(v),y:H-8,"text-anchor":"middle"}); t2.textContent=v+"%"; g.append(t2); });
  s.append(svg("line",{x1:sx(0),y1:sy(0),x2:sx(100),y2:sy(100),stroke:css("--axis"),"stroke-width":1}));
  bins.forEach(b => { const c=svg("circle",{cx:sx(b.pred),cy:sy(b.obs),r:4+Math.min(b.n,8),fill:css("--accent"),stroke:css("--surface"),"stroke-width":2}); c.addEventListener("mousemove",ev=>showTip(ev.clientX,ev.clientY,[{label:"Forecasts",value:String(b.n)},{label:"Average forecast",value:fmtPct(b.pred)},{label:"Came true",value:fmtPct(b.obs)}],`${b.a}–${Math.min(b.b,100)}% bin`)); c.addEventListener("mouseleave",hideTip); s.append(c); });
  box.append(s);
}
export const brier = fs => fs.length ? fs.reduce((s,f)=>s+Math.pow(f.p/100-(f.outcome?1:0),2),0)/fs.length : null;

/* ---- dot timeline: events on a date axis, one row per lane ---- */
export function dotTimeline(host, items, {lane="who", title="Timeline"}={}){
  host.replaceChildren();
  const box = h("div",{class:"chart"}); host.append(box);
  const lanes = [...new Set(items.map(i=>i[lane]))];
  const W = Math.max(box.clientWidth||600,300), rowH=40, narrow=W<560, L=narrow?12:150, R=24, T=narrow?22:10, B=30;
  const H = T + lanes.length*(rowH+(narrow?16:0)) + B;
  const ts = items.map(i=>parseDate(i.date).getTime()); const t0=Math.min(...ts)-20*DAY, t1=Math.max(...ts)+20*DAY;
  const x = t => L + (t-t0)/(t1-t0)*(W-L-R);
  const s = svg("svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":title});
  const g = svg("g",{class:"axis"}); s.append(g);
  const m0=new Date(t0); m0.setDate(1); m0.setMonth(m0.getMonth()+1);
  for(let d=new Date(m0); d.getTime()<=t1; d.setMonth(d.getMonth()+1)){ const px=x(d.getTime()); g.append(svg("line",{x1:px,x2:px,y1:T,y2:H-B,class:"grid"})); if(d.getMonth()%2===0){ const tx=svg("text",{x:px,y:H-8,"text-anchor":"middle"}); tx.textContent=d.toLocaleDateString(undefined,{month:"short"}); g.append(tx);} }
  lanes.forEach((ln,i)=>{ const yy=T+i*(rowH+(narrow?16:0))+(narrow?16:0)+rowH/2; g.append(svg("line",{x1:L,x2:W-R,y1:yy,y2:yy,class:"grid"})); const t=svg("text",{x:narrow?L:L-10,y:narrow?yy-14:yy+4,"text-anchor":narrow?"start":"end",class:"row-label"}); t.textContent=ln; s.append(t);
    items.filter(it=>it[lane]===ln).forEach(it=>{ const c=svg("circle",{cx:x(parseDate(it.date).getTime()),cy:yy,r:6,fill:css("--accent"),stroke:css("--surface"),"stroke-width":2}); c.addEventListener("mousemove",ev=>showTip(ev.clientX,ev.clientY,[{label:"When",value:fmtDate(it.date,{day:"numeric",month:"short",year:"numeric"})},{label:"Said",value:`“${it.quote}”`}],it.who)); c.addEventListener("mouseleave",hideTip); s.append(c); }); });
  box.append(s);
}

export const util = {css, h, fmtPct, fmtDate, parseDate, DAY, legend, tableView, showTip, hideTip};

/* ---- forecast: our stated probabilities (now, end-2030, end-2035) with a confidence band ----
   The band is NOT a statistical interval: it widens with our stated confidence
   (low → roughly ×0.5–×1.6 of the point; high → ×0.85–×1.15). Outside forecasts are hollow rings. */
const CONF_BAND = {"low":[0.5,1.6], "low–medium":[0.6,1.45], "medium":[0.75,1.3], "medium–high":[0.8,1.2], "high":[0.85,1.15]};
export function forecastChart(host, {series, markers=[], today, height=300, yMax, title="Forecast", compact=false}){
  host.replaceChildren();
  const box = h("div",{class:"chart"}); host.append(box);
  const W = Math.max(box.clientWidth || host.clientWidth || 600, compact?160:300), H = height;
  const L = compact?42:44, R = compact?12:(markers.length?16:96), T = 12, B = 28;
  const t0 = parseDate(today).getTime(), t1 = parseDate("2036-01-01").getTime();
  const x = d => L + (parseDate(d).getTime()-t0)/(t1-t0)*(W-L-R);
  const pts = se => [{x:today,y:se.now},{x:"2030-12-31",y:se.y2030},{x:"2035-12-31",y:se.y2035}];
  const bands = se => { const [lo,hi] = CONF_BAND[se.conf] || CONF_BAND.low; return pts(se).map(p=>({x:p.x, lo:Math.max(0,p.y*lo), hi:Math.min(100,p.y*hi)})); };
  const all = series.flatMap(se => bands(se).map(b=>b.hi)).concat(markers.map(m=>m.p));
  const {top:ymax, ticks} = yMax ? {top:yMax, ticks:[0,yMax/4,yMax/2,yMax*3/4,yMax]} : niceTicks(Math.max(...all,1)*1.05, compact?3:4);
  const y = v => T + (1 - v/ymax) * (H-T-B);
  const s = svg("svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":title});
  const g = svg("g",{class:"axis"}); s.append(g);
  ticks.forEach((v,i)=>{ g.append(svg("line",{x1:L,x2:W-R,y1:y(v),y2:y(v),class:i?"grid":"base"})); const tx=svg("text",{x:L-6,y:y(v)+4,"text-anchor":"end"}); tx.textContent=fmtPct(v); g.append(tx); });
  const years = compact ? [2028,2031,2034] : [2027,2028,2029,2030,2031,2032,2033,2034,2035];
  years.forEach(yr=>{ const px=x(`${yr}-01-01`); const tx=svg("text",{x:px,y:H-8,"text-anchor":"middle"}); tx.textContent=String(yr); g.append(tx); });
  const tl = svg("line",{x1:x(today),x2:x(today),y1:T,y2:H-B,class:"crosshair"}); s.append(tl);
  if(!compact){ const tt=svg("text",{x:x(today)+4,y:T+10,class:"row-label"}); tt.textContent="Today"; s.append(tt); }
  const surface = css("--surface");
  series.forEach(se => {
    const col = css(se.color) || se.color;
    const b = bands(se);
    s.append(svg("polygon",{points:[...b.map(p=>`${x(p.x)},${y(p.hi)}`), ...[...b].reverse().map(p=>`${x(p.x)},${y(p.lo)}`)].join(" "), fill:col, opacity:0.1}));
    const P = pts(se);
    s.append(svg("polyline",{points:P.map(p=>`${x(p.x)},${y(p.y)}`).join(" "),fill:"none",stroke:col,"stroke-width":2,"stroke-linejoin":"round"}));
    P.forEach(p => s.append(svg("circle",{cx:x(p.x),cy:y(p.y),r:4,fill:col,stroke:surface,"stroke-width":2})));
    if(!compact){ const last=P[P.length-1]; const tx=svg("text",{x:x(last.x)+8,y:y(last.y)+4,class:"end-label"}); tx.textContent=`${se.short||""} ${fmtPct(last.y)}`.trim(); if(!markers.length) s.append(tx); }
  });
  markers.forEach(m => { const c=svg("circle",{cx:x(m.date),cy:y(m.p),r:6,fill:surface,stroke:css("--ink"),"stroke-width":2}); c.addEventListener("mousemove",ev=>showTip(ev.clientX,ev.clientY,[{label:m.what},{label:"Probability",value:m.p+"%"},{label:"By",value:fmtDate(m.date,{month:"short",year:"numeric"})},{label:m.definition}],m.who)); c.addEventListener("mouseleave",hideTip); s.append(c); });
  // hover: read the three anchor points
  const hit = svg("rect",{x:L,y:T,width:W-L-R,height:H-T-B,fill:"transparent"}); s.insertBefore(hit, s.querySelector("circle"));
  hit.addEventListener("mousemove", ev => { const rows=[]; series.forEach(se=>{ rows.push({label:se.label+" now", value:fmtPct(se.now), color:css(se.color)||se.color}); rows.push({label:"by 2030", value:fmtPct(se.y2030)}); rows.push({label:"by 2035", value:fmtPct(se.y2035)}); }); showTip(ev.clientX, ev.clientY, rows, "Our forecast (confidence: "+series.map(se=>se.conf).join(", ")+")"); });
  hit.addEventListener("mouseleave", hideTip);
  box.append(s);
  if(!compact){
    const items = series.map(se=>({label:se.label, color:se.color, line:true}));
    const lg = legend(items);
    if(markers.length){ const it=h("span",{class:"lg-item"}); const ring=h("span",{class:"lg-ring"}); it.append(ring, document.createTextNode("Outside forecasts (hover for details)")); lg.append(it); }
    const band=h("span",{class:"lg-item"}); const bs=h("span",{class:"lg-band"}); band.append(bs, document.createTextNode("Shaded band: our confidence")); lg.append(band);
    host.append(lg);
    host.append(tableView(title, ["Series","Now","By end-2030","By end-2035","Confidence"], series.map(se=>[se.label, fmtPct(se.now), fmtPct(se.y2030), fmtPct(se.y2035), se.conf||"–"]).concat(markers.map(m=>[m.who+": "+m.what, "–", "", fmtDate(m.date,{month:"short",year:"numeric"})+" · "+m.p+"%", m.rating]))));
  }
}

/* ---- trend: measured history on a log scale, fitted line, dashed projection with a band, thresholds ---- */
const fmtDur = m => m < 1 ? `${Math.round(m*60)} sec` : m < 60 ? `${m<10?m.toFixed(1):Math.round(m)} min` : m < 60*24 ? `${(m/60)<10?(m/60).toFixed(1):Math.round(m/60)} hr` : `${Math.round(m/60)} hr`;
export function trendChart(host, {history, projection, thresholds=[], from="2023-01-01", to="2031-01-01", title="Trend", color="--accent", secondary, height=320}){
  host.replaceChildren();
  const box = h("div",{class:"chart"}); host.append(box);
  const W = Math.max(box.clientWidth || 600, 300), H = height, L = 86, R = 16, T = 12, B = 30;
  const t0 = parseDate(from).getTime(), t1 = parseDate(to).getTime();
  const x = d => L + (parseDate(d).getTime()-t0)/(t1-t0)*(W-L-R);
  const TICKS = [[1/6,"10 sec"],[1,"1 min"],[10,"10 min"],[60,"1 hr"],[480,"8 hr (a workday)"],[2400,"1 work-week"],[10020,"1 work-month"],[120000,"1 work-year"]];
  const vals = history.map(p=>p.v).concat(thresholds.map(t=>t.v)).concat(secondary?secondary.history.map(p=>p.v):[]).filter(v=>v>0);
  const vmin = Math.min(...vals), vmax = 120000; // cap the scale at a work-year; the projection is clipped beyond it
  const ticks = TICKS.filter(([v])=>v>=vmin/1.5 && v<=vmax);
  const lmin = Math.log10(Math.min(ticks[0][0], vmin)), lmax = Math.log10(vmax);
  const y = v => T + (1 - (Math.log10(Math.max(v,10**lmin)) - lmin)/(lmax-lmin)) * (H-T-B);
  const s = svg("svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":title});
  s.append(svg("defs"));
  const clipId = "plot-" + Math.random().toString(36).slice(2,7); const cp=svg("clipPath",{id:clipId}); cp.append(svg("rect",{x:L,y:T,width:W-L-R,height:H-T-B})); s.querySelector("defs").append(cp);
  const g = svg("g",{class:"axis"}); s.append(g);
  ticks.forEach(([v,lab],i)=>{ g.append(svg("line",{x1:L,x2:W-R,y1:y(v),y2:y(v),class:i?"grid":"base"})); const tx=svg("text",{x:L-6,y:y(v)+4,"text-anchor":"end"}); tx.textContent=lab.replace(" (a workday)",""); g.append(tx); });
  for(let yr=parseDate(from).getFullYear()+1; yr<parseDate(to).getFullYear()+1; yr++){ const px=x(`${yr}-01-01`); if(px>W-R) break; const tx=svg("text",{x:px,y:H-8,"text-anchor":"middle"}); tx.textContent=String(yr); g.append(tx); }
  const plot = svg("g",{"clip-path":`url(#${clipId})`}); s.append(plot);
  const col = css(color) || color, surface = css("--surface");
  thresholds.forEach(t => { plot.append(svg("line",{x1:L,x2:W-R,y1:y(t.v),y2:y(t.v),stroke:css("--ink"),"stroke-width":1,opacity:0.5})); const tx=svg("text",{x:L+6,y:y(t.v)-5,class:"row-label"}); tx.textContent=t.label; s.append(tx); });
  const drawProj = (proj, c) => {
    if(!proj?.length) return;
    plot.append(svg("polygon",{points:[...proj.map(p=>`${x(p.date)},${y(p.hi)}`), ...[...proj].reverse().map(p=>`${x(p.date)},${y(p.lo)}`)].join(" "), fill:c, opacity:0.1}));
    plot.append(svg("polyline",{points:proj.map(p=>`${x(p.date)},${y(p.mid)}`).join(" "),fill:"none",stroke:c,"stroke-width":2,"stroke-dasharray":"6 5"}));
  };
  if(secondary){ const c2 = css(secondary.color)||secondary.color; drawProj(secondary.projection, c2); secondary.history.filter(p=>p.date>=from).forEach(p=>{ const c=svg("circle",{cx:x(p.date),cy:y(p.v),r:4,fill:c2,stroke:surface,"stroke-width":2}); c.addEventListener("mousemove",ev=>showTip(ev.clientX,ev.clientY,[{label:secondary.label,value:fmtDur(p.v)}],p.name||fmtDate(p.date))); c.addEventListener("mouseleave",hideTip); plot.append(c); }); }
  drawProj(projection, col);
  history.filter(p=>p.date>=from).forEach(p => { const c=svg("circle",{cx:x(p.date),cy:y(p.v),r:p.faint?3:4.5,fill:col,opacity:p.faint?0.4:1,stroke:surface,"stroke-width":2}); c.addEventListener("mousemove",ev=>showTip(ev.clientX,ev.clientY,[{label:"Horizon",value:fmtDur(p.v)},{label:"Released",value:fmtDate(p.date,{day:"numeric",month:"short",year:"numeric"})}].concat(p.lo?[{label:"95% CI",value:`${fmtDur(p.lo)} – ${fmtDur(p.hi)}`}]:[]),p.name)); c.addEventListener("mouseleave",hideTip); plot.append(c); });
  box.append(s);
  return {fmtDur};
}
export {fmtDur};
