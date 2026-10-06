/* Hidden AGI watch chart kit. One style for every graph on the site.
   Rules (see style.html): hairline solid grid, 2px lines, >=8px dots with a 2px surface ring,
   bars <=24px with 4px rounded data-ends, legend for >=2 series, sparing direct labels,
   text in ink tokens (never series colors), hover tooltip on every chart, and a "Show as table"
   view (or a visible table on the page) for every chart. */
const NS = "http://www.w3.org/2000/svg";
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
// For inline HTML styles: a token name becomes var(--token), so swatches follow the theme without a redraw.
const cssVar = c => (c && String(c).startsWith("--")) ? `var(${c})` : c;
const svg = (tag, a={}) => { const e=document.createElementNS(NS,tag); for(const [k,v] of Object.entries(a)) e.setAttribute(k,v); return e; };
const h = (tag, a={}, text) => { const e=document.createElement(tag); for(const [k,v] of Object.entries(a)) e.setAttribute(k,v); if(text!=null) e.textContent=text; return e; };
const has = (o, k) => o != null && Object.prototype.hasOwnProperty.call(o, k);

/* Numbers, matching fmt() in scripts/build_feed.py: half-up rounding to 2 decimals below 1,
   1 decimal below 10 and whole numbers above, trailing zeros dropped, with rollover at the
   boundaries (0.996 -> "1", 9.96 -> "10"). A change counts only if the formatted values differ. */
const roundHalfUp = (v, d) => { const a = Math.abs(v), r = Number(Math.round(Number(a + "e" + d)) + "e-" + d); return Math.sign(v) * (isNaN(r) ? Number(a.toFixed(d)) : r); };
const places = a => a < 1 ? 2 : a < 10 ? 1 : 0;
export const fmtNum = v => {
  if(v==null || v==="" || isNaN(v)) return "–";
  v = Number(v); if(v===0) return "0";
  let r = roundHalfUp(v, places(Math.abs(v)));
  if(places(Math.abs(r)) < places(Math.abs(v))) r = roundHalfUp(r, places(Math.abs(r)));
  return String(r);
};
export const fmtPct = v => { const s = fmtNum(v); return s==="–" ? s : s + "%"; };
const parseDate = d => new Date(d + "T12:00:00");
const fmtDate = (d, opts={day:"numeric",month:"short"}) => { const t = parseDate(d); return isNaN(t) ? String(d ?? "") : t.toLocaleDateString(undefined, opts); };
const fullDate = d => fmtDate(d,{day:"numeric",month:"short",year:"numeric"});
const validDate = d => d != null && d !== "" && !isNaN(parseDate(d));
const DAY = 864e5;

/* Links built from data: only http(s) URLs or site-relative paths, never javascript: or data:.
   Returns the href to use (root-prefixed when relative), or null to skip the link. */
export const safeHref = (u, root="") => {
  u = String(u ?? "").trim(); if(!u) return null;
  try { const p0 = new URL(u).protocol; if(p0!=="https:" && p0!=="http:") return null; } catch(e){ /* no scheme: a relative path */ }
  const s = /^https?:\/\//i.test(u) ? u : root + u;
  try { const p = new URL(s, document.baseURI).protocol; return (p==="https:" || p==="http:") ? s : null; }
  catch(e){ return null; }
};
const isAbsolute = u => /^https?:\/\//i.test(String(u));
// a data-driven link, or null; a new tab only for absolute URLs
function dataLink(u, text, root=""){
  const href = safeHref(u, root); if(!href) return null;
  return h("a", isAbsolute(href) ? {href, target:"_blank", rel:"noopener"} : {href}, text);
}

/* label: the original display name. It never changes, because frozen pages (weekly/2026-10-02.html) draw
   their legends from it live. name: the redesign v2 display name (sitekit.HYP_LABELS with the same letter
   prefix), which new pages use in its place. */
export const SERIES = {
  A:{label:"A: AGI undisclosed", name:"A: Hidden AGI", color:"--sA"},
  B:{label:"B: Secret RSI", name:"B: Hidden self-improvement", color:"--sB"},
  C:{label:"C: Covert AGI online", name:"C: Covert AGI actor", color:"--sC"},
  D:{label:"D: Covert govt influence", name:"D: Covert government influence", color:"--sD"},
  Dopen:{label:"D-open: Open govt influence", name:"D-open: Open government influence", color:"--sE"}
};
export const SERIES_ORDER = ["A","B","C","D","Dopen"];

/* ---- tooltip (one per page) ---- */
let tip, onHide = null;
function tooltip(){
  if(tip) return tip;
  tip = h("div",{class:"chart-tip",role:"status","aria-live":"polite"}); tip.hidden = true; document.body.append(tip);
  // The tip is position:fixed, so it goes stale once the page moves. Touch scrolls never fire mouseleave.
  addEventListener("scroll", hideTip, {passive:true, capture:true});
  addEventListener("resize", hideTip, {passive:true});
  addEventListener("keydown", e => { if(e.key==="Escape") hideTip(); });
  return tip;
}
/* cleanup (optional) runs when the tip hides, e.g. to clear a chart's crosshair. */
function showTip(x, y, rows, title, cleanup){
  const t = tooltip(); t.replaceChildren();
  if(onHide && onHide!==cleanup){ const f = onHide; onHide = null; f(); }
  onHide = cleanup || null;
  if(title) t.append(h("div",{class:"tip-title"},title));
  rows.forEach(r => { const row=h("div",{class:"tip-row"}); if(r.color){ const k=h("span",{class:"tip-key"}); k.style.background=r.color; row.append(k);} row.append(h("span",{},r.label)); if(r.value!=null) row.append(h("strong",{},r.value)); t.append(row); });
  t.hidden = false;
  const pad=12, w=t.offsetWidth, hh=t.offsetHeight;
  let left = x + pad, top = y + pad;
  if(left + w > innerWidth - 8) left = x - w - pad;
  if(top + hh > innerHeight - 8) top = y - hh - pad;
  t.style.left = Math.max(8,left) + "px"; t.style.top = Math.max(8,top) + "px";
}
function hideTip(){ if(tip) tip.hidden = true; if(onHide){ const f = onHide; onHide = null; f(); } }

/* ---- shared pieces ---- */
function legend(items){
  const lg = h("div",{class:"legend"});
  items.forEach(it => { const s=h("span",{class:"lg-item"}); const k=h("span",{class:it.line?"lg-line":(it.cls||"swatch")}, it.glyph); if(it.color) k.style.background=cssVar(it.color); s.append(k, document.createTextNode(it.label)); lg.append(s); });
  return lg;
}
function tableView(caption, head, rows, summary="Show as table"){
  const d = h("details",{class:"table-view"}); d.append(h("summary",{},summary));
  const wrap=h("div",{class:"table-wrap"}); const t=h("table"); t.append(h("caption",{class:"sr-only"},caption));
  const tr=h("tr"); head.forEach(c=>tr.append(h("th",{scope:"col"},c))); t.append(tr);
  rows.forEach(r=>{ const row=h("tr"); r.forEach(c=>row.append(h("td",{},c))); t.append(row); });
  wrap.append(t); d.append(wrap); return d;
}
/* Axis ticks for data up to max: clean steps at any magnitude (1, 2, 2.5 or 5 × 10^k).
   cap limits the top, e.g. 100 for probabilities; money charts stay uncapped. */
function niceTicks(max, n=4, cap=Infinity){
  max = Math.min(cap, max);
  const raw = max / n, mag = 10 ** Math.floor(Math.log10(raw || 1));
  const step = [1,2,2.5,5,10].map(m=>m*mag).find(st => st*n >= max) || 10*mag;
  const top = Math.min(cap, step*Math.max(1, Math.ceil(max/step)));
  const ticks=[]; for(let v=0; v<=top+1e-9; v+=step) ticks.push(+v.toFixed(6));
  if(top - ticks[ticks.length-1] > 1e-9) ticks.push(top);
  return {top, ticks};
}
/* Ticks for a fixed top: a clean step that divides it, close to n intervals. */
function fixedTicks(top, n=4){
  const mag = 10 ** Math.floor(Math.log10(top || 1));
  const steps = [0.1,0.2,0.25,0.5,1,2,2.5,5,10].map(m=>m*mag).filter(st => { const k = top/st; return Math.abs(k-Math.round(k)) < 1e-9 && k >= 2 && k <= 6; });
  if(!steps.length) return {top, ticks:[0,top/4,top/2,top*3/4,top]};
  const step = steps.reduce((b,st) => Math.abs(top/st-n) < Math.abs(top/b-n) - 1e-9 ? st : b);
  const ticks=[]; for(let v=0; v<=top+1e-9; v+=step) ticks.push(+v.toFixed(6));
  return {top, ticks};
}
/* Month gridlines with labels: every month when they are at least 40px apart, otherwise every
   other month. The year is shown on the first label and whenever it changes. Labels near the
   edges are anchored inward, and a label that would overlap the previous one is skipped. */
function monthAxis(g, t0, t1, x, T, H, B, W){
  const months = [];
  const m0 = new Date(t0); m0.setDate(1); m0.setHours(12,0,0,0); m0.setMonth(m0.getMonth()+1);
  for(let d=new Date(m0); d.getTime()<=t1; d.setMonth(d.getMonth()+1)) months.push(new Date(d));
  const every = months.length > 1 && x(months[1].getTime()) - x(months[0].getTime()) < 40 ? 2 : 1;
  let lastYear = null, prevRight = -Infinity;
  months.forEach((d,i) => {
    const px = x(d.getTime()); g.append(svg("line",{x1:px,x2:px,y1:T,y2:H-B,class:"grid"}));
    if(i % every) return;
    const text = d.toLocaleDateString(undefined, d.getFullYear() !== lastYear ? {month:"short",year:"numeric"} : {month:"short"});
    const w = text.length * 6.4, anchor = px < w/2 ? "start" : (W && px > W - w/2) ? "end" : "middle";
    const left = anchor==="start" ? px : anchor==="end" ? px - w : px - w/2;
    if(left < prevRight + 6) return;
    prevRight = left + w; lastYear = d.getFullYear();
    const tx = svg("text",{x:px,y:H-8,"text-anchor":anchor}); tx.textContent = text; g.append(tx);
  });
}
/* A dot with a 2px surface ring. Tied values share one split marker, a slice per series,
   so no series hides another. */
function dot(parent, cx, cy, cols, surface){
  if(cols.length < 2){ parent.append(svg("circle",{cx,cy,r:4,fill:cols[0],stroke:surface,"stroke-width":2})); return; }
  const r = 5, n = cols.length;
  cols.forEach((c,i) => {
    const a0 = -Math.PI/2 + i*2*Math.PI/n, a1 = a0 + 2*Math.PI/n;
    parent.append(svg("path",{d:`M${cx},${cy} L${cx+r*Math.cos(a0)},${cy+r*Math.sin(a0)} A${r},${r} 0 ${a1-a0>Math.PI?1:0} 1 ${cx+r*Math.cos(a1)},${cy+r*Math.sin(a1)} Z`, fill:c}));
  });
  parent.append(svg("circle",{cx,cy,r,fill:"none",stroke:surface,"stroke-width":2}));
}
/* Width of each string as SVG text in the given class (falls back to an estimate). */
function textWidth(host, strings, cls){
  const m = svg("svg",{width:0,height:0,style:"position:absolute;visibility:hidden"}); host.append(m);
  const ws = strings.map(t => { const e = svg("text",{class:cls}); e.textContent = t; m.append(e); let w = 0; try{ w = e.getComputedTextLength(); }catch(err){} return w || t.length*6.6; });
  m.remove(); return ws;
}

/* ---- redraw on width and theme changes ----
   Calls draw() now and returns its result. Redraws (debounced) only when the host's width
   changes, so opening "Show as table" doesn't redraw and close it, and when the color scheme flips. */
export function live(host, draw){
  const out = draw();
  let w = Math.round(host.clientWidth), t;
  const redo = () => { clearTimeout(t); t = setTimeout(() => { try{ draw(); }catch(e){ console.error("Chart redraw failed:", e); } }, 150); };
  if(typeof ResizeObserver !== "undefined") new ResizeObserver(entries => { const nw = Math.round(entries[0].contentRect.width); if(nw && nw !== w){ w = nw; redo(); } }).observe(host);
  if(typeof matchMedia === "function") matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", redo);
  return out;
}

/* ---- sparkline: a tiny text-free trend; the number next to it carries the value ---- */
export function sparkline(values, {color="--accent", zeroBased=false, width=120, height=24, cls}={}){
  const W = width, H = height, s = svg("svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`,"aria-hidden":"true"});
  if(cls) s.setAttribute("class", cls);
  const v = (values||[]).filter(x => x!=null && x!=="" && !isNaN(x)).map(Number);
  if(v.length < 2){ s.append(svg("line",{x1:0,x2:W,y1:H-4,y2:H-4,stroke:css("--grid"),"stroke-width":1})); return s; }
  const mx = zeroBased ? Math.max(...v, 1) : Math.max(...v), mn = zeroBased ? 0 : Math.min(...v), rg = (mx-mn) || 1;
  s.append(svg("polyline",{points:v.map((x,i)=>`${2+i*(W-4)/(v.length-1)},${H-3-(x-mn)/rg*(H-6)}`).join(" "),fill:"none",stroke:css(color)||color,"stroke-width":2,"stroke-linejoin":"round","stroke-linecap":"round"}));
  return s;
}

/* lineChart breaks: a dashed muted hairline at each break, labelled at the top (inward near the right edge) */
function breakLines(s, box, brks, x, {T, bottom, right}){
  const muted = css("--muted"), bw = textWidth(box, brks.map(b => b.label), "row-label");
  brks.forEach((b,i) => {
    const px = x(b.x);
    s.append(svg("line",{x1:px,x2:px,y1:T,y2:bottom,stroke:muted,"stroke-width":1,"stroke-dasharray":"4 3"}));
    if(!b.label) return;
    const flip = px + 4 + bw[i] > right;
    const tx = svg("text",{x:flip ? px-4 : px+4, y:T+10, "text-anchor":flip ? "end" : "start", class:"row-label"}); tx.textContent = b.label; s.append(tx);
  });
}
/* Consecutive points on the same side of every break, so no line joins across one. */
function splitRuns(vals, pts, seg){
  const runs = []; let k0 = null;
  vals.forEach((v,i) => { const k = seg(String(v.x)); if(!runs.length || k !== k0){ runs.push([]); k0 = k; } runs[runs.length-1].push(pts[i]); });
  return runs;
}
/* ---- line chart: several series over dates, one y axis (percent unless yFormat says otherwise) ----
   breaks: [{x:"YYYY-MM-DD", label}] marks a method change: a dashed vertical hairline at x, labelled,
   and no series is joined across it (points before x and points from x on are drawn as separate lines).
   With no breaks the chart is drawn exactly as before. */
export function lineChart(host, {series, height=280, yMax, title, endLabels=true, yFormat=fmtPct, log=false, percent, breaks=[]}){
  host.replaceChildren();
  const box = h("div",{class:"chart"}); host.append(box);
  const W = Math.max(box.clientWidth || host.clientWidth || 600, 300), H = height;
  const pct = percent ?? (yFormat===fmtPct);
  const dates = [...new Set(series.flatMap(s => s.values.map(v => v.x)))].filter(validDate).sort();
  const all = series.flatMap(s => s.values.map(v => v.y)).filter(v => v!=null && !isNaN(v));
  if(!dates.length || !all.length){ host.append(h("p",{class:"empty"},"No data yet.")); return; }
  const L = 44, T = 12, B = 30;
  let {top:ymax, ticks} = yMax ? fixedTicks(pct ? Math.min(100, yMax) : yMax) : niceTicks(Math.max(...all, 1) * 1.1, 4, pct ? 100 : Infinity);
  let lmin = 0;
  if(log){ const pos = all.filter(v=>v>0); lmin = Math.floor(Math.log10(Math.min(...pos))); const lmax = Math.ceil(Math.log10(Math.max(...pos))); ymax = 10**lmax; ticks = []; for(let e=lmin;e<=lmax;e++) ticks.push(10**e); }
  const y = v => log ? T + (1 - (Math.log10(Math.max(v,10**lmin)) - lmin)/(Math.log10(ymax)-lmin)) * (H-T-B) : T + (1 - v/ymax) * (H-T-B);
  // End labels: off for multi-series charts on narrow screens (the legend carries them there).
  // Labels within 14px form one group; tied values merge into one label ("C, D-open 1%").
  const showEnds = endLabels && !(W < 480 && series.length > 1);
  let groups = [];
  if(showEnds){
    const ends = series.map(se => { const v = se.values.filter(p => p.y!=null && !isNaN(p.y) && validDate(p.x)); if(!v.length) return null; const p = v[v.length-1]; return {d:p.x, y:y(p.y), v:p.y, label:se.short||se.label}; }).filter(Boolean).sort((a,b)=>a.y-b.y);
    ends.forEach(e => { const gp = groups[groups.length-1]; if(gp && e.y - gp[0].y < 14) gp.push(e); else groups.push([e]); });
    groups = groups.map(gp => ({d:gp[0].d, y:gp[0].y, text:`${gp.filter(e => yFormat(e.v)===yFormat(gp[0].v)).map(e=>e.label).join(", ")} ${yFormat(gp[0].v)}`}));
  }
  const R = groups.length ? Math.min(118, Math.ceil(16 + Math.max(...textWidth(box, groups.map(gp=>gp.text), "end-label")))) : 16;
  const t0 = parseDate(dates[0]).getTime(), t1 = parseDate(dates[dates.length-1]).getTime();
  const x = d => dates.length < 2 || t1===t0 ? L + (W-L-R)/2 : L + (parseDate(d).getTime()-t0)/(t1-t0)*(W-L-R);
  const brks = (Array.isArray(breaks) ? breaks : []).filter(b => b && validDate(b.x)).map(b => ({x:String(b.x), label:String(b.label ?? "")})).sort((a,b) => a.x.localeCompare(b.x));
  const seg = d => brks.filter(b => d >= b.x).length;               // which side of each break a date falls on
  const shownBrks = brks.filter(b => { const t = parseDate(b.x).getTime(); return t >= t0 && t <= t1 && dates.length > 1; });
  const brkAt = d => shownBrks.filter(b => d >= b.x && !dates.some(e => e >= b.x && e < d));   // the breaks a date is the first reading on or after
  const aria = (title||"Line chart") + shownBrks.map(b => `; dashed line on ${fullDate(b.x)}: ${b.label}`).join("");
  const s = svg("svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":aria});
  const g = svg("g",{class:"axis"}); s.append(g);
  ticks.forEach((v,i)=>{ g.append(svg("line",{x1:L,x2:W-R,y1:y(v),y2:y(v),class:i?"grid":"base"})); const tx=svg("text",{x:L-8,y:y(v)+4,"text-anchor":"end"}); tx.textContent=yFormat(v); g.append(tx); });
  // x ticks by measured spacing; the latest date always keeps its label. Spans of more than
  // ~10 months are labelled by month and year ("Mar 2024"), one label per month; shorter spans
  // that cross a new year carry the full date, so a tick never reads as a year ("Jan 26").
  const long = t1 - t0 > 300*DAY, crossYear = parseDate(dates[0]).getFullYear() !== parseDate(dates[dates.length-1]).getFullYear();
  const tickFmt = long ? (d => { const t = parseDate(d); return t.toLocaleDateString(undefined,{month:"short"}) + " " + t.getFullYear(); }) : crossYear ? fullDate : (d => fmtDate(d));
  const MIN_GAP = long ? 64 : crossYear ? 84 : 56, halfW = long ? 30 : crossYear ? 40 : 22, shown = [];
  dates.forEach(d => { const prev = shown[shown.length-1]; if(!prev || (x(d) - x(prev) >= MIN_GAP && tickFmt(d) !== tickFmt(prev))) shown.push(d); });
  const lastD = dates[dates.length-1];
  if(shown[shown.length-1] !== lastD){ const prev = shown[shown.length-1]; if(shown.length > 1 && (x(lastD) - x(prev) < MIN_GAP || tickFmt(lastD) === tickFmt(prev))) shown.pop(); shown.push(lastD); }
  shown.forEach(d => { const tx=svg("text",{x:x(d),y:H-8,"text-anchor":x(d)+halfW > W ? "end" : x(d)-halfW < 0 ? "start" : "middle"}); tx.textContent=tickFmt(d); g.append(tx); });
  if(shownBrks.length) breakLines(s, box, shownBrks, x, {T, bottom:H-B, right:W-R});
  const surface = css("--surface");
  // dense series (points under 14px apart) keep only the latest dot; the tooltip gives every day
  const dense = dates.length > 1 && (W-L-R)/(dates.length-1) < 14;
  const dots = new Map();
  series.forEach(se => {
    const col = css(se.color) || se.color;
    const vals = se.values.filter(v => v.y!=null && !isNaN(v.y) && validDate(v.x));
    const pts = vals.map(v => [x(v.x), y(v.y)]);
    splitRuns(vals, pts, seg).forEach(run => { if(run.length > 1) s.append(svg("polyline",{points:run.map(p=>p[0]+","+p[1]).join(" "),fill:"none",stroke:col,"stroke-width":2,"stroke-linejoin":"round","stroke-linecap":"round"})); });
    (dense ? pts.slice(-1) : pts).forEach(p => { const k = p[0].toFixed(1)+","+p[1].toFixed(1); if(!dots.has(k)) dots.set(k, {x:p[0], y:p[1], cols:[]}); dots.get(k).cols.push(col); });
  });
  dots.forEach(d => dot(s, d.x, d.y, d.cols, surface));
  groups.forEach(gp => { const tx=svg("text",{x:x(gp.d)+10,y:gp.y+4,class:"end-label"}); tx.textContent=gp.text; s.append(tx); });
  // crosshair + tooltip
  const cross = svg("line",{y1:T,y2:H-B,class:"crosshair",visibility:"hidden"}); s.append(cross);
  const clear = () => cross.setAttribute("visibility","hidden");
  const hit = svg("rect",{x:L,y:T,width:W-L-R,height:H-T-B,fill:"transparent"}); s.append(hit);
  const nearest = px => dates.reduce((b,d)=>Math.abs(x(d)-px)<Math.abs(x(b)-px)?d:b, dates[0]);
  hit.addEventListener("mousemove", ev => {
    const r = s.getBoundingClientRect(), k = W / (r.width || W);
    const d = nearest((ev.clientX - r.left) * k); cross.setAttribute("x1",x(d)); cross.setAttribute("x2",x(d)); cross.setAttribute("visibility","visible");
    const rows = series.map(se => { const v = se.values.filter(p=>p.x===d).pop(); return {label:se.label, value:v&&v.y!=null?yFormat(v.y):"–", color:css(se.color)||se.color}; });
    brkAt(d).forEach(b => { if(b.label) rows.push({label:b.label}); });
    showTip(r.left + x(d)/k, ev.clientY, rows, fullDate(d), clear);
  });
  hit.addEventListener("mouseleave", hideTip);
  box.append(s);
  if(series.length > 1) host.append(legend(series.map(se=>({label:se.label, color:se.color, line:true}))));
  host.append(tableView(title||"Data", ["Date", ...series.map(se=>se.label)], dates.map(d => [fullDate(d) + brkAt(d).filter(b => b.label).map(b => ` (${b.label})`).join(""), ...series.map(se => { const v=se.values.filter(p=>p.x===d).pop(); return v&&v.y!=null?yFormat(v.y):"–"; })])));
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

/* ---- status board (tripwires): icon + label + text, never color alone ----
   Display words: Quiet / Open / Confirmed (redesign v2). The data keys (quiet, watching, tripped) never change.
   ◔ marks Open, so ◐ only ever means the alarm's Watch level. */
export const STATUS = {
  quiet:{label:"Quiet", icon:"○", color:"--good"},
  watching:{label:"Open", icon:"◔", color:"--warn"},
  tripped:{label:"Confirmed", icon:"●", color:"--crit"}
};
// A status we don't recognise fails closed: it is flagged and sorted first, never shown as Quiet.
const UNKNOWN_STATUS = {label:"Unknown status", icon:"?", color:"--crit"};
const statusKey = w => String(w?.status ?? "").trim().toLowerCase();
function triggerMet(alarm, id){
  for(const g of (Array.isArray(alarm?.groups) ? alarm.groups : [])) for(const t of (Array.isArray(g?.triggers) ? g.triggers : [])) if(t && t.id === id) return t.met === true;
  return Array.isArray(alarm?.current?.met) && alarm.current.met.includes(id);
}
/* The alarm level a trigger belongs to (1 Watch, 2 Warning, 3 Alarm): from alarm.json's groups,
   else from the id's letter (W, X, Y). null for no trigger or one we can't place. */
const LEVEL_BY_LETTER = {W:1, X:2, Y:3}, LEVEL_NAMES = ["Normal","Watch","Warning","Alarm"];
export function triggerLevel(alarm, id){
  id = String(id ?? "").trim(); if(!id) return null;
  for(const g of (Array.isArray(alarm?.groups) ? alarm.groups : [])) if((Array.isArray(g?.triggers) ? g.triggers : []).some(t => t && t.id === id)) { const n = Number(g.level); if(Number.isInteger(n)) return n; }
  const n = LEVEL_BY_LETTER[id[0].toUpperCase()]; return n == null ? null : n;
}
const levelName = (alarm, n) => (Array.isArray(alarm?.levels) ? alarm.levels : []).find(l => l && l.level === n)?.name || LEVEL_NAMES[n] || `Level ${n}`;
/* A status for display. A status colour never outranks the alarm condition it feeds: a confirmed signal
   is red only when it feeds a Warning- or Alarm-level condition (X, Y). One that feeds a Watch-level
   condition (W), or none, shows amber with a capped label (key "observed", kept for the CSS and the sort
   order). Unknown statuses fail closed (red, flagged). */
export function statusView(status, trigger, alarm=null){
  const k = String(status ?? "").trim().toLowerCase();
  if(!has(STATUS,k)) return {key:"unknown", known:false, ...UNKNOWN_STATUS, label:`Unknown status: "${status ?? ""}"`};
  if(k === "tripped"){
    const lv = triggerLevel(alarm, trigger);
    if(lv == null || lv < 2) return {key:"observed", known:true, icon:STATUS.tripped.icon, color:"--warn", capped:true,
      label: lv === 1 ? `Confirmed · counts toward ${levelName(alarm, 1)}` : "Confirmed · no alarm condition"};
  }
  return {key:k, known:true, ...STATUS[k]};
}
export function tripwireBoard(host, wires, {root="", alarm=null}={}){
  host.replaceChildren();
  const order = {tripped:1, observed:2, watching:3, quiet:4};
  const view = w => statusView(w?.status, w?.trigger, alarm);
  const rank = w => { const k = view(w).key; return has(order,k) ? order[k] : 0; };
  const list = h("ul",{class:"tripwires"});
  [...(wires||[])].sort((a,b)=>rank(a)-rank(b)).forEach(w => {
    const st = view(w);
    const li = h("li",{class:"tw "+st.key});
    const badge = h("span",{class:"tw-status"}); const ic=h("span",{class:"tw-icon","aria-hidden":"true"},st.icon); ic.style.color=cssVar(st.color);
    badge.append(ic, document.createTextNode(st.label));
    const body = h("div",{class:"tw-body"});
    const sig = h("div",{class:"tw-signal"}); const hy=h("span",{class:"tw-hyp"}); const sw=h("span",{class:"swatch"}); sw.style.background=cssVar(has(SERIES,w.hyp)?SERIES[w.hyp].color:"--muted"); hy.append(sw, document.createTextNode(w.hyp==="Dopen"?"D-open":(w.hyp||"?"))); sig.append(hy, document.createTextNode(" " + (w.signal||"")));
    if(w.trigger){
      const id = String(w.trigger).trim();
      sig.append(" ", h("a",{class:"chip tw-trigger", href:root+"alarm.html#"+encodeURIComponent(id)}, `Alarm condition ${id}` + (alarm && triggerMet(alarm, id) ? " · met" : "")));
    }
    body.append(sig);
    const note = h("div",{class:"tw-note muted"}, w.note || ""); const a = dataLink(w.url, "source", root); if(a){ note.append(" ", a); } body.append(note);
    li.append(badge, body); list.append(li);
  });
  host.append(list);
}

/* ---- escape watch (hypothesis C): resource-chokepoint indicators, from data/escape.json ----
   The overall line, then one tile per indicator: status (icon + word), name and a one-line reason,
   each linking to its section on the escape page. Tripped tiles follow the same colour cap as
   tripwires, using the indicator's main alarm trigger (alarmTriggers[0]). compact:false adds the
   full reason and the linked alarm triggers, for a page that shows the board without the detail. */
// One line from the reason: a short "short" field if the data has one, else the first sentence
// (plus the next when the first only restates the status, e.g. "Watching, at the high end.").
function oneLine(ind){
  const s = String(ind?.short ?? "").trim(); if(s) return s;
  const t = String(ind?.statusReason ?? "").trim(); if(!t) return "";
  const ends = []; const re = /[.!?]["”’)]?(?=\s+["“‘(]?[A-Z0-9])/g; let m;
  while((m = re.exec(t)) && ends.length < 2){ const head = t.slice(0, m.index+1); if(!/(?:\b[A-Z]\.|\b(?:vs|etc|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|Inc|Corp|Co|Ltd|No)\.)$/.test(head)) ends.push(m.index + m[0].length); }
  if(!ends.length) return t;
  return t.slice(0, ends[0] < 40 && ends[1] ? ends[1] : ends[0]).trim();
}
export function escapeBoard(host, data, {root="", alarm=null, compact=true, page="escape.html"}={}){
  host.replaceChildren();
  const inds = Array.isArray(data?.indicators) ? data.indicators.filter(i => i && typeof i === "object") : null;
  const pageLink = (text, frag="") => h("a",{href:root+page+(frag ? "#"+encodeURIComponent(frag) : "")}, text);
  if(!inds || !inds.length){
    const p = h("p",{class:"muted"},"Escape watch data is unavailable right now. ");
    p.append(pageLink("See the escape watch page")); host.append(p); return;
  }
  const view = i => statusView(i.status, Array.isArray(i.alarmTriggers) ? i.alarmTriggers[0] : null, alarm);
  const order = {unknown:0, tripped:1, observed:2, watching:3, quiet:4};
  const rows = inds.map((ind, n) => ({ind, st:view(ind), n})).sort((a,b) => (order[a.st.key] ?? 0) - (order[b.st.key] ?? 0) || a.n - b.n);
  // display words Confirmed / Open / Quiet; a capped confirmed signal ("observed") counts as confirmed here
  const count = {}; rows.forEach(r => { const k = r.st.key === "observed" ? "tripped" : r.st.key; count[k] = (count[k]||0) + 1; });
  const parts = [["tripped","confirmed"],["watching","open"],["quiet","quiet"],["unknown","with an unrecognized status (data error)"]]
    .filter(([k]) => count[k] || k==="tripped" || k==="watching" || k==="quiet").map(([k,w]) => `${count[k]||0} ${w}`);
  const top = rows[0].st;
  const head = h("div",{class:"esc-overall"});
  const badge = h("span",{class:"esc-status esc-status-lg"}); const ic = h("span",{class:"esc-icon","aria-hidden":"true"},top.icon); ic.style.color = cssVar(top.color);
  badge.append(ic, document.createTextNode(top.key === "unknown" ? "Status unknown" : top.label));
  const cnt = h("span",{class:"muted small"}, `${rows.length} indicator${rows.length===1?"":"s"}: ${parts.join(", ")}.` + (validDate(data.updated) ? ` Updated ${fullDate(data.updated)}.` : ""));
  head.append(badge, cnt);
  host.append(head);
  if(data.overall) host.append(h("p",{class:"esc-line"}, String(data.overall)));
  const list = h("ul",{class:"esc-grid"});
  rows.forEach(({ind, st}) => {
    const li = h("li",{class:"esc "+st.key});
    const s = h("div",{class:"esc-status"}); const i2 = h("span",{class:"esc-icon","aria-hidden":"true"},st.icon); i2.style.color = cssVar(st.color);
    s.append(i2, document.createTextNode(st.label));
    const name = h("h3",{class:"esc-name"}); const key = String(ind.key ?? "").trim();
    name.append(key ? pageLink(String(ind.name || key), key) : document.createTextNode(String(ind.name || "")));
    li.append(s, name, h("p",{class:"esc-why small"}, oneLine(ind)));
    if(!compact){
      const trig = (Array.isArray(ind.alarmTriggers) ? ind.alarmTriggers : []).map(t => String(t).trim()).filter(Boolean);
      if(trig.length){
        const p = h("p",{class:"esc-trig small muted"},"Feeds alarm condition" + (trig.length > 1 ? "s " : " "));
        trig.forEach((id,n) => { if(n) p.append(" "); p.append(h("a",{class:"chip tw-trigger", href:root+"alarm.html#"+encodeURIComponent(id)}, id + (alarm && triggerMet(alarm, id) ? " · met" : ""))); });
        li.append(p);
      }
      if(ind.statusReason && oneLine(ind) !== String(ind.statusReason).trim()){
        const d = h("details",{class:"esc-more small"}); d.append(h("summary",{},"Full reason"), h("p",{}, String(ind.statusReason))); li.append(d);
      }
    }
    list.append(li);
  });
  host.append(list);
}

/* ---- disclosure lag: horizontal range bars on a date axis, outsider-found highlighted ----
   Returns the rows, each with lag (from the occurred midpoint), lagMin and lagMax (from the
   occurredTo / occurredFrom window when an approximate date has one), ext and labFirst. */
export function lagChart(host, incidents, {title="Days from incident to public disclosure"}={}){
  host.replaceChildren();
  const box = h("div",{class:"chart"}); host.append(box);
  const days = (a,b) => Math.round((parseDate(b)-parseDate(a))/DAY);
  const rows = (incidents||[]).filter(i => i && validDate(i.occurred) && validDate(i.disclosed)).map(i => {
    const lag = days(i.occurred, i.disclosed);
    const lo = validDate(i.occurredTo) ? days(i.occurredTo, i.disclosed) : lag, hi = validDate(i.occurredFrom) ? days(i.occurredFrom, i.disclosed) : lag;
    const ext = i.foundBy !== "lab";
    return {...i, lag, lagMin:Math.min(lo, hi, lag), lagMax:Math.max(lo, hi, lag), ext, labFirst: ext && i.detectedBy === "lab"};
  }).sort((a,b)=>b.lag-a.lag);
  if(!rows.length){ host.append(h("p",{class:"empty"},"No dated incidents yet.")); return rows; }
  const W = Math.max(box.clientWidth || 600, 300), rowH = 34, T = 8, B = 30;
  const narrow = W < 560, L = narrow ? 12 : Math.min(380, Math.round(W*0.38)), R = 64;
  // Row labels are fitted to measured widths: above the bar on narrow screens (one line), beside it
  // on wide ones (up to two lines), with an ellipsis only when a title still doesn't fit.
  const titles = rows.map(r => String(r.title||r.id||"")), tw = textWidth(box, titles, "row-label");
  const fitLabel = (i, w, maxLines) => {
    const t = titles[i], per = (tw[i] || t.length*6.6) / Math.max(1, t.length), cap = Math.max(8, Math.floor(w / per));
    const lines = []; let rest = t;
    while(rest && lines.length < maxLines){
      if(rest.length <= cap){ lines.push(rest); break; }
      if(lines.length === maxLines-1){ lines.push(rest.slice(0, cap-1).trimEnd() + "…"); break; }
      let cut = rest.lastIndexOf(" ", cap); if(cut < cap*0.5) cut = cap;
      lines.push(rest.slice(0, cut).trimEnd()); rest = rest.slice(cut).trimStart();
    }
    return lines;
  };
  const H = T + rows.length*(narrow?rowH+18:rowH) + B;
  const starts = rows.map(r=>parseDate(validDate(r.occurredFrom)?r.occurredFrom:r.occurred).getTime());
  const ends = rows.map(r=>Math.max(parseDate(r.disclosed).getTime(), validDate(r.detected)?parseDate(r.detected).getTime():0));
  const t0 = Math.min(...starts) - 7*DAY, t1 = Math.max(...ends) + 7*DAY;
  const x = t => L + (t-t0)/(t1-t0)*(W-L-R);
  const s = svg("svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":title});
  const g = svg("g",{class:"axis"}); s.append(g);
  monthAxis(g, t0, t1, x, T, H, B, W);
  const acc = css("--accent"), mute = css("--muted"), surface = css("--surface"), ink = css("--ink");
  const rangeTxt = r => r.lagMin!==r.lagMax ? ` (range ${r.lagMin}–${r.lagMax})` : "";
  rows.forEach((r,i) => {
    const yy = T + i*(narrow?rowH+18:rowH) + (narrow?18:0);
    const ttl = titles[i], lines = fitLabel(i, narrow ? W - L - 8 : L - 18, narrow ? 1 : 2);
    const lab = svg("text",{x:narrow?L:L-10,y:narrow?yy-4:yy+rowH/2+(lines.length > 1 ? -3 : 4),"text-anchor":narrow?"start":"end",class:"row-label"});
    lines.forEach((ln,k) => { const ts = svg("tspan",{x:narrow?L:L-10, dy:k ? 13 : 0}); ts.textContent = ln; lab.append(ts); });
    if(lines.join(" ") !== ttl){ const tt = svg("title"); tt.textContent = ttl; lab.append(tt); }
    s.append(lab);
    const x0 = x(parseDate(r.occurred).getTime()), x1 = x(parseDate(r.disclosed).getTime());
    const bh = 12, by = yy + rowH/2 - bh/2;
    const col = r.ext ? acc : mute;
    // the window an approximate start date falls in, as a thin line
    if(validDate(r.occurredFrom) && validDate(r.occurredTo)) s.append(svg("line",{x1:x(parseDate(r.occurredFrom).getTime()),x2:x(parseDate(r.occurredTo).getTime()),y1:by+bh/2,y2:by+bh/2,stroke:col,"stroke-width":2,opacity:0.55}));
    s.append(svg("rect",{x:x0,y:by,width:Math.max(2,x1-x0),height:bh,rx:4,fill:col,opacity:r.occurredApprox?0.55:1}));
    if(r.labFirst && validDate(r.detected)){ const xd = x(parseDate(r.detected).getTime()); s.append(svg("line",{x1:xd,x2:xd,y1:by-4,y2:by+bh+4,stroke:ink,"stroke-width":2})); }
    s.append(svg("circle",{cx:x1,cy:by+bh/2,r:5,fill:col,stroke:surface,"stroke-width":2}));
    const v = svg("text",{x:x1+10,y:by+bh/2+4,class:"end-label"}); v.textContent = r.lag + "d" + (r.labFirst ? " ◆" : ""); s.append(v);
    const hit = svg("rect",{x:0,y:yy,width:W,height:rowH,fill:"transparent"});
    hit.addEventListener("mousemove", ev => showTip(ev.clientX, ev.clientY, [
      {label:"Happened", value:fullDate(r.occurred) + (r.occurredApprox?" (approx.)":"")},
      ...(validDate(r.occurredFrom) && validDate(r.occurredTo) ? [{label:"Window", value:`${fullDate(r.occurredFrom)} – ${fullDate(r.occurredTo)}`}] : []),
      ...(r.detectedBy || validDate(r.detected) ? [{label:"Detected by", value:(r.detectedBy||"–") + (validDate(r.detected) ? ", " + fullDate(r.detected) : "")}] : []),
      {label:"Made public", value:fullDate(r.disclosed)},
      {label:"Lag", value:r.lag + " days" + rangeTxt(r)}, {label:"Made public by", value:r.foundBy||"–"}], ttl));
    hit.addEventListener("mouseleave", hideTip); s.append(hit);
  });
  box.append(s);
  const items = [{label:"Made public by someone other than the lab", color:"--accent"},{label:"Made public by the lab itself", color:"--muted"}];
  if(rows.some(r=>r.labFirst)) items.push({label:"The lab itself detected it first; someone else made it public", cls:"lg-glyph", glyph:"◆"});
  if(rows.some(r=>r.labFirst && validDate(r.detected))) items.push({label:"When the lab detected it", cls:"lg-tick"});
  host.append(legend(items));
  host.append(h("p",{class:"muted small"},"Faded bars have an approximate start date" + (rows.some(r=>validDate(r.occurredFrom)&&validDate(r.occurredTo)) ? "; the thin line shows the window it falls in, and the lag is measured from its midpoint." : ".")));
  const withDet = rows.some(r=>r.detectedBy);
  host.append(tableView(title, ["Incident","Lab","Happened","Made public","Lag (days)","Made public by", ...(withDet?["Detected by"]:[])], rows.map(r=>[String(r.title||r.id||""), r.lab||"–", fullDate(r.occurred)+(r.occurredApprox?" (approx.)":""), fullDate(r.disclosed), String(r.lag)+rangeTxt(r), r.foundBy||"–", ...(withDet?[(r.detectedBy||"–")+(validDate(r.detected)?", "+fullDate(r.detected):"")]:[])])));
  return rows;
}

/* ---- probability meters for forecasts; market odds as a hollow marker ----
   Each row shows when it was made, its deadline, the resolution rule and any dated corrections,
   with the reasoning and source behind "Why this number". */
/* compact (opt-in; the scorecard uses it, the frozen weekly page does not): the resolution rule and corrections move
   into the "Why this number" details, so the list stays short (V11). */
export function forecastBars(host, forecasts, {compact=false}={}){
  host.replaceChildren();
  const list = h("div",{class:"fc-list"});
  (forecasts||[]).forEach(f => {
    const row = h("div",{class:"fc-row"});
    const q = h("div",{class:"fc-q"}); q.append(h("div",{},f.question));
    const out = f.outcome===true ? " · Resolved YES" : f.outcome===false ? " · Resolved NO" : (f.outcome==="void" || f.void===true) ? " · Withdrawn" : "";
    q.append(h("div",{class:"muted small"}, (validDate(f.made) ? `Made ${fullDate(f.made)} · ` : "") + `Due ${fullDate(f.deadline)}` + out));
    const extra = [];   // compact: these go into "Why this number"
    if(f.resolution){ const r = h("div",{class:"muted small fc-res"}, `Resolves YES if: ${f.resolution}`); if(compact) extra.push(r); else q.append(r); }
    (Array.isArray(f.corrections) ? f.corrections : []).forEach(c => {
      const text = typeof c === "string" ? c : (c?.text || ""); if(!text) return;
      const line = h("div",{class:"muted small fc-corr"}, (validDate(c?.date) ? `Corrected ${fullDate(c.date)}: ` : "Corrected: ") + text);
      const a = dataLink(c?.url, "source"); if(a) line.append(" ", a);
      if(compact) extra.push(line); else q.append(line);
    });
    if(compact && extra.some(x => x.classList.contains("fc-corr"))) q.append(h("div",{class:"muted small"}, "Corrected since it was made: see below."));
    /* The reasoning behind a scored probability stays visible: a corrected forecast shows its
       reasoning as made (original_context, or context when it was never rewritten), then any update. */
    const corrected = Array.isArray(f.corrections) && f.corrections.length > 0;
    const asMade = f.original_context || (corrected ? f.context : "");
    if(f.context || f.url || asMade || extra.length){
      const why = h("details",{class:"fc-why small"}); why.append(h("summary",{}, compact ? "Why this number, and how it resolves" : "Why this number"));
      const para = (label, text, url) => {
        const p = h("p",{}); if(label) p.append(h("strong",{},label + " "));
        p.append(text || ""); const a = dataLink(url, "source"); if(a) p.append(text ? " " : "", a);
        return p;
      };
      const madeLbl = validDate(f.made) ? `As made (${fmtDate(f.made,{day:"numeric",month:"short"})}):` : "As made:";
      if(f.original_context){
        why.append(para(madeLbl, f.original_context, f.original_url));
        if(f.context || f.url) why.append(para("Since then:", f.context, f.url));
      } else {
        why.append(para(corrected ? madeLbl : "", f.context, f.url));
      }
      extra.forEach(x => why.append(x));
      q.append(why);
    }
    const mkt = f.market!=null && !isNaN(f.market);
    const mkLabel = validDate(f.marketAsOf) ? `Market (${fmtDate(f.marketAsOf,{day:"numeric",month:"short"})})` : "Market";
    const pv = Math.min(100, Math.max(0, Number(f.p) || 0));
    const m = h("div",{class:"fc-meter",role:"img","aria-label":`Our probability ${f.p}%` + (mkt?`; ${mkLabel.toLowerCase()} ${f.market}%`:"")});
    const fill = h("div",{class:"fc-fill"}); fill.style.width = pv + "%"; m.append(fill);
    if(mkt){ const mk=h("div",{class:"fc-market",title:`${mkLabel}: ${f.market}%`}); mk.style.left = Math.min(100, Math.max(0, Number(f.market))) + "%"; m.append(mk); }
    const val = h("div",{class:"fc-val"}, f.p + "%");
    row.append(q, m, val);
    row.addEventListener("mousemove", ev => showTip(ev.clientX, ev.clientY, [{label:"Our probability", value:f.p+"%"}, ...(mkt?[{label:mkLabel, value:f.market+"%"}]:[]), ...(f.resolution?[{label:"Resolves YES if", value:f.resolution}]:[])], f.question));
    row.addEventListener("mouseleave", hideTip);
    list.append(row);
  });
  host.append(list);
}

/* ---- scoring: only outcomes true or false count; "void" (withdrawn) and open forecasts don't ---- */
const scoredOnly = fs => (fs||[]).filter(f => f && (f.outcome===true || f.outcome===false) && f.p!=null && f.p!=="" && !isNaN(f.p));
export const brier = fs => { const r = scoredOnly(fs); return r.length ? r.reduce((s,f)=>s+Math.pow(Number(f.p)/100-(f.outcome===true?1:0),2),0)/r.length : null; };
/* Brier skill score against always forecasting the resolved set's base rate: 1 − BS/(ȳ(1−ȳ)).
   Above 0 beats the base rate. null when nothing has resolved or every outcome was the same. */
export const brierSkill = fs => { const r = scoredOnly(fs); if(!r.length) return null; const yb = r.filter(f=>f.outcome===true).length/r.length, ref = yb*(1-yb); return ref > 0 ? 1 - brier(r)/ref : null; };
/* Our Brier score and the market's on the same resolved forecasts that carry a market price. */
export const marketPaired = fs => { const r = scoredOnly(fs).filter(f => f.market!=null && f.market!=="" && !isNaN(f.market)); return r.length ? {ours:brier(r), market:brier(r.map(f=>({...f, p:Number(f.market)}))), n:r.length} : {ours:null, market:null, n:0}; };
// Wilson score interval for k successes in n, as percentages (z = 1.645 gives 90%).
function wilson(k, n, z=1.645){ const p = k/n, z2 = z*z, den = 1 + z2/n, c = (p + z2/(2*n))/den, hw = z*Math.sqrt(p*(1-p)/n + z2/(4*n*n))/den; return [Math.max(0,c-hw)*100, Math.min(1,c+hw)*100]; }

/* ---- calibration: predicted bins vs observed frequency, with the diagonal ----
   Shown from 15 resolved forecasts; 3 bins until 40 have resolved, then 5. Each bin shows its n
   and a Wilson 90% interval, because a bin of a few forecasts reads 0% or 100% by chance. */
export function calibration(host, resolved, {min=15}={}){
  host.replaceChildren();
  const fs = scoredOnly(resolved);
  if(fs.length < min){ host.append(h("p",{class:"empty"},`Calibration appears once at least ${min} forecasts resolve (${fs.length} so far). Before that, a bin of one or two forecasts would read 0% or 100% by chance.`)); return; }
  const edges = fs.length < 40 ? [[0,100/3],[100/3,200/3],[200/3,101]] : [[0,20],[20,40],[40,60],[60,80],[80,101]];
  const bins = edges.map(([a,b]) => { const bf = fs.filter(f=>Number(f.p)>=a && Number(f.p)<b), n = bf.length, k = bf.filter(f=>f.outcome===true).length; return {name:`${Math.round(a)}–${Math.min(100,Math.round(b))}%`, n, k, pred: n ? bf.reduce((s,f)=>s+Number(f.p),0)/n : null, obs: n ? k/n*100 : null, ci: n ? wilson(k,n) : null}; });
  const box = h("div",{class:"chart"}); host.append(box);
  const W = Math.min(Math.max(box.clientWidth||400,280), 420), H = W, L=40,R=12,T=12,B=30;
  const sx = v => L + v/100*(W-L-R), sy = v => T + (1-v/100)*(H-T-B);
  const s = svg("svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":"Calibration: predicted vs observed, with 90% intervals"});
  const g = svg("g",{class:"axis"}); s.append(g);
  [0,25,50,75,100].forEach(v=>{ g.append(svg("line",{x1:L,x2:W-R,y1:sy(v),y2:sy(v),class:v?"grid":"base"})); const t=svg("text",{x:L-6,y:sy(v)+4,"text-anchor":"end"}); t.textContent=v+"%"; g.append(t); const t2=svg("text",{x:sx(v),y:H-8,"text-anchor":"middle"}); t2.textContent=v+"%"; g.append(t2); });
  s.append(svg("line",{x1:sx(0),y1:sy(0),x2:sx(100),y2:sy(100),stroke:css("--axis"),"stroke-width":1}));
  const ink = css("--ink"), acc = css("--accent"), surface = css("--surface");
  bins.filter(b=>b.n).forEach(b => {
    const cx = sx(b.pred);
    s.append(svg("line",{x1:cx,x2:cx,y1:sy(b.ci[0]),y2:sy(b.ci[1]),stroke:ink,"stroke-width":2,opacity:0.5,"stroke-linecap":"round"}));
    const c = svg("circle",{cx,cy:sy(b.obs),r:4+Math.min(b.n,8),fill:acc,stroke:surface,"stroke-width":2});
    c.addEventListener("mousemove",ev=>showTip(ev.clientX,ev.clientY,[{label:"Forecasts",value:String(b.n)},{label:"Average forecast",value:fmtPct(b.pred)},{label:"Came true",value:fmtPct(b.obs)},{label:"90% interval",value:`${fmtPct(b.ci[0])} – ${fmtPct(b.ci[1])}`}],`${b.name} bin`));
    c.addEventListener("mouseleave",hideTip); s.append(c);
    const lab = svg("text",{x:cx+10+Math.min(b.n,8),y:sy(b.obs)+4,class:"row-label"}); lab.textContent = "n=" + b.n; s.append(lab);
  });
  box.append(s);
  host.append(h("p",{class:"muted small"},"Vertical lines are 90% intervals (Wilson). The diagonal is perfect calibration."));
  host.append(tableView("Calibration by bin", ["Bin","Forecasts","Average forecast","Came true","90% interval"], bins.map(b=>[b.name, String(b.n), b.n?fmtPct(b.pred):"–", b.n?`${fmtPct(b.obs)} (${b.k} of ${b.n})`:"–", b.n?`${fmtPct(b.ci[0])} – ${fmtPct(b.ci[1])}`:"–"])));
}

/* ---- dot timeline: events on a date axis, one row per lane ---- */
export function dotTimeline(host, items, {lane="who", title="Timeline"}={}){
  host.replaceChildren();
  const box = h("div",{class:"chart"}); host.append(box);
  const its = (items||[]).filter(i => i && validDate(i.date));
  if(!its.length){ host.append(h("p",{class:"empty"},"Nothing to show yet.")); return; }
  const lanes = [...new Set(its.map(i=>i[lane]))];
  const W = Math.max(box.clientWidth||600,300), rowH=40, narrow=W<560, L=narrow?12:150, R=24, T=narrow?22:10, B=30;
  const H = T + lanes.length*(rowH+(narrow?16:0)) + B;
  const ts = its.map(i=>parseDate(i.date).getTime()); const t0=Math.min(...ts)-20*DAY, t1=Math.max(...ts)+20*DAY;
  const x = t => L + (t-t0)/(t1-t0)*(W-L-R);
  const s = svg("svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":title});
  const g = svg("g",{class:"axis"}); s.append(g);
  monthAxis(g, t0, t1, x, T, H, B, W);
  const acc = css("--accent"), surface = css("--surface");
  lanes.forEach((ln,i)=>{ const yy=T+i*(rowH+(narrow?16:0))+(narrow?16:0)+rowH/2; g.append(svg("line",{x1:L,x2:W-R,y1:yy,y2:yy,class:"grid"})); const t=svg("text",{x:narrow?L:L-10,y:narrow?yy-14:yy+4,"text-anchor":narrow?"start":"end",class:"row-label"}); t.textContent=ln; s.append(t);
    its.filter(it=>it[lane]===ln).forEach(it=>{ const c=svg("circle",{cx:x(parseDate(it.date).getTime()),cy:yy,r:6,fill:acc,stroke:surface,"stroke-width":2}); c.addEventListener("mousemove",ev=>showTip(ev.clientX,ev.clientY,[{label:"When",value:fullDate(it.date)},{label:"Said",value:`“${it.quote}”`}],it.who)); c.addEventListener("mouseleave",hideTip); s.append(c); }); });
  box.append(s);
  host.append(tableView(title, ["Date", lane==="who" ? "Who" : lane, "Quote"], [...its].sort((a,b)=>String(a.date).localeCompare(String(b.date))).map(it=>[fullDate(it.date), String(it[lane] ?? "–"), it.quote ? `“${it.quote}”` : "–"])));
}

export const fmtUSDb = v => v==null ? "–" : (v>=1000 ? `$${(v/1000).toFixed(v>=10000?0:1)}T` : `$${v>=100?Math.round(v):v>=10?v.toFixed(0):v.toFixed(1)}B`);
export const util = {css, cssVar, h, svg, fmtPct, fmtNum, fmtDate, parseDate, DAY, legend, tableView, showTip, hideTip, safeHref, sparkline};

/* ---- forecast: our stated probabilities (now, end-2030, end-2035) with a judgment band ----
   The band is NOT a statistical interval. It is a judgment range: roughly how far our number
   could plausibly move as evidence arrives. It is drawn in log-odds, ± a half-width set by our
   stated confidence, so it never reaches 0% or 100% and stays sensible at high probabilities.
   A run can supply explicit bounds instead (band: {now:[lo,hi], y2030:[lo,hi], y2035:[lo,hi]}).
   Outside forecasts are hollow rings. */
export const CONF_W = {"low":1.0, "low–medium":0.8, "medium":0.6, "medium–high":0.45, "high":0.3};
const confKey = c => String(c || "low").trim().toLowerCase().replace(/\s*[-‐‑‒—–]\s*/g, "–");
export function confBand(p, conf){
  p = Number(p); if(!(p > 0)) return [0, 0];
  const k = confKey(conf), w = has(CONF_W,k) ? CONF_W[k] : CONF_W.low;
  const q = Math.min(Math.max(p, 0.1), 99.9)/100, lg = Math.log(q/(1-q)), ex = z => 100/(1+Math.exp(-z));
  return [ex(lg - w), ex(lg + w)];
}
export function forecastChart(host, {series, markers=[], today, height=300, yMax, title="Forecast", compact=false}){
  host.replaceChildren();
  const box = h("div",{class:"chart"}); host.append(box);
  if(!series?.length || !validDate(today)){ host.append(h("p",{class:"empty"},"No forecast yet.")); return; }
  const W = Math.max(box.clientWidth || host.clientWidth || 600, compact?160:300), H = height;
  const L = compact?42:44, R = compact?12:(markers.length?16:96), T = 12, B = 28;
  const t0 = parseDate(today).getTime(), t1 = parseDate("2036-01-01").getTime();
  const x = d => L + (parseDate(d).getTime()-t0)/(t1-t0)*(W-L-R);
  const num = v => v!=null && v!=="" && !isNaN(v);
  const pts = se => [{x:today,y:se.now,k:"now"},{x:"2030-12-31",y:se.y2030,k:"y2030"},{x:"2035-12-31",y:se.y2035,k:"y2035"}].filter(p=>num(p.y)).map(p=>({...p, y:Number(p.y)}));
  const bands = se => pts(se).map(p => { const b = se.band?.[p.k]; const [lo,hi] = Array.isArray(b) && b.length===2 && b.every(num) ? b.map(Number) : confBand(p.y, se.conf); return {x:p.x, k:p.k, lo:Math.max(0,Math.min(lo,hi)), hi:Math.min(100,Math.max(lo,hi))}; });
  const ms = (markers||[]).filter(m => m && validDate(m.date) && num(m.p) && parseDate(m.date).getTime() >= t0 && parseDate(m.date).getTime() <= t1);
  const all = series.flatMap(se => bands(se).map(b=>b.hi)).concat(ms.map(m=>Number(m.p)));
  const {top:ymax, ticks} = yMax ? fixedTicks(Math.min(100, yMax), compact?3:4) : niceTicks(Math.max(...all,1)*1.05, compact?3:4, 100);
  const y = v => T + (1 - v/ymax) * (H-T-B);
  const s = svg("svg",{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":title});
  const g = svg("g",{class:"axis"}); s.append(g);
  ticks.forEach((v,i)=>{ g.append(svg("line",{x1:L,x2:W-R,y1:y(v),y2:y(v),class:i?"grid":"base"})); const tx=svg("text",{x:L-6,y:y(v)+4,"text-anchor":"end"}); tx.textContent=fmtPct(v); g.append(tx); });
  if(compact){
    // name the three anchors; Jan-1 year ticks would put "2031" under the end-2030 point
    [[today,"Now","start"],["2030-12-31","End 2030","middle"],["2035-12-31","End 2035","end"]].forEach(([d,lab,anc]) => { const tx=svg("text",{x:x(d),y:H-8,"text-anchor":anc}); tx.textContent=lab; g.append(tx); });
  } else {
    const every = (W-L-R) * (365.25*DAY) / (t1-t0) < 40 ? 2 : 1;   // year labels are ~31px wide
    for(let yr = parseDate(today).getFullYear()+1; yr <= 2035; yr++){ if(every===2 && yr%2) continue; const tx=svg("text",{x:x(`${yr}-01-01`),y:H-8,"text-anchor":"middle"}); tx.textContent=String(yr); g.append(tx); }
    // mark the two forecast anchors, so the end-2030 point never reads as "2031"
    [["2030-12-31","End 2030"],["2035-12-31","End 2035"]].forEach(([d,lab]) => { g.append(svg("line",{x1:x(d),x2:x(d),y1:T,y2:H-B,class:"grid","stroke-dasharray":"2 3"})); const tx=svg("text",{x:x(d)-4,y:T+10,"text-anchor":"end",class:"row-label"}); tx.textContent=lab; s.append(tx); });
  }
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
    if(!compact && !ms.length && P.length){ const last=P[P.length-1]; const tx=svg("text",{x:x(last.x)+8,y:y(last.y)+4,class:"end-label"}); tx.textContent=`${se.short||""} ${fmtPct(last.y)}`.trim(); s.append(tx); }
  });
  // outside forecasts: rings that would sit within 8px of each other are nudged apart
  const placed = [], ink = css("--ink");
  ms.forEach(m => {
    let cx = x(m.date); const cy = y(Number(m.p));
    for(let i=0; i<4 && placed.some(([px,py]) => Math.hypot(px-cx, py-cy) < 8); i++) cx += 7;
    placed.push([cx,cy]);
    const c=svg("circle",{cx,cy,r:6,fill:surface,stroke:ink,"stroke-width":2});
    c.addEventListener("mousemove",ev=>showTip(ev.clientX,ev.clientY,[{label:m.what},{label:"Probability",value:fmtPct(m.p)},{label:"By",value:fmtDate(m.date,{month:"short",year:"numeric"})},...(m.gap||m.definition?[{label:m.gap||m.definition}]:[])],m.who));
    c.addEventListener("mouseleave",hideTip); s.append(c);
  });
  // hover: read the three anchor points and their bands
  const hit = svg("rect",{x:L,y:T,width:W-L-R,height:H-T-B,fill:"transparent"}); s.insertBefore(hit, s.querySelector("circle"));
  const withBand = (v, b) => b ? `${fmtPct(v)} (band ${fmtNum(b.lo)}–${fmtPct(b.hi)})` : fmtPct(v);
  hit.addEventListener("mousemove", ev => { const rows=[]; series.forEach(se=>{ const b = k => bands(se).find(x=>x.k===k); rows.push({label:se.label+" now", value:withBand(se.now, b("now")), color:css(se.color)||se.color}); rows.push({label:"by end-2030", value:withBand(se.y2030, b("y2030"))}); rows.push({label:"by end-2035", value:withBand(se.y2035, b("y2035"))}); }); showTip(ev.clientX, ev.clientY, rows, "Our forecast (confidence: "+series.map(se=>se.conf||"–").join(", ")+")"); });
  hit.addEventListener("mouseleave", hideTip);
  box.append(s);
  if(!compact){
    const lg = legend(series.map(se=>({label:se.label, color:se.color, line:true})));
    if(ms.length){ const it=h("span",{class:"lg-item"}); it.append(h("span",{class:"lg-ring"}), document.createTextNode("Outside forecasts: none uses our exact definition (see the table)")); lg.append(it); }
    const band=h("span",{class:"lg-item"}); band.append(h("span",{class:"lg-band"}), document.createTextNode("Shaded band: how far our number could plausibly move")); lg.append(band);
    host.append(lg);
    host.append(tableView(title, ["Series","Now","By end-2030","By end-2035","Confidence"], series.map(se=>[se.label, fmtPct(se.now), fmtPct(se.y2030), fmtPct(se.y2035), se.conf||"–"])));
    if(ms.length) host.append(tableView("Outside forecasts", ["Who","What","By","Probability","How it differs from our bar","Source rating"], ms.map(m=>[m.who||"–", m.what||"–", fmtDate(m.date,{month:"short",year:"numeric"}), fmtPct(m.p), m.gap||m.definition||"–", m.rating||"–"]), "Show the outside forecasts as a table"));
  }
}

/* ---- trend: measured history on a log scale, fitted line, dashed projection with a band, thresholds ----
   Points above 16 hours (960 min), or flagged excluded, are faded: METR says they are unreliable
   and the fit leaves them out. A projection with predLo/predHi also gets a lighter band showing
   where an individual new model should land. */
const fmtDur = m => m < 1 ? `${Math.round(m*60)} sec` : m < 60 ? `${m<10?m.toFixed(1):Math.round(m)} min` : m < 60*24 ? `${(m/60)<10?(m/60).toFixed(1):Math.round(m/60)} hr` : `${Math.round(m/60)} hr`;
const outOfRange = p => p.excluded===true || Number(p.v) > 960;
export function trendChart(host, {history, projection, thresholds=[], from="2023-01-01", to="2031-01-01", title="Trend", color="--accent", secondary, height=320, rate="50%"}){
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
  // year labels are ~31px wide: on narrow charts label every other year so they never run together
  const yrW = x("2025-01-01") - x("2024-01-01"), yStep = yrW < 40 ? 2 : 1;
  for(let yr=parseDate(from).getFullYear()+1; yr<parseDate(to).getFullYear()+1; yr++){ const px=x(`${yr}-01-01`); if(px>W-R) break; if(yr % yStep) continue; const tx=svg("text",{x:px,y:H-8,"text-anchor":"middle"}); tx.textContent=String(yr); g.append(tx); }
  const plot = svg("g",{"clip-path":`url(#${clipId})`}); s.append(plot);
  const col = css(color) || color, surface = css("--surface");
  thresholds.forEach(t => { plot.append(svg("line",{x1:L,x2:W-R,y1:y(t.v),y2:y(t.v),stroke:css("--ink"),"stroke-width":1,opacity:0.5})); const tx=svg("text",{x:L+6,y:y(t.v)-5,class:"row-label"}); tx.textContent=t.label; s.append(tx); });
  const drawProj = (proj, c) => {
    if(!proj?.length) return;
    if(proj.every(p=>p.predLo!=null && p.predHi!=null)) plot.append(svg("polygon",{points:[...proj.map(p=>`${x(p.date)},${y(p.predHi)}`), ...[...proj].reverse().map(p=>`${x(p.date)},${y(p.predLo)}`)].join(" "), fill:c, opacity:0.05}));
    plot.append(svg("polygon",{points:[...proj.map(p=>`${x(p.date)},${y(p.hi)}`), ...[...proj].reverse().map(p=>`${x(p.date)},${y(p.lo)}`)].join(" "), fill:c, opacity:0.1}));
    plot.append(svg("polyline",{points:proj.map(p=>`${x(p.date)},${y(p.mid)}`).join(" "),fill:"none",stroke:c,"stroke-width":2,"stroke-dasharray":"6 5"}));
  };
  const outLine = {label:"Above 16 hours: METR says this is unreliable; not used in the fit"};
  const point = (p, c, rows) => { const faded = p.faint || outOfRange(p); const e=svg("circle",{cx:x(p.date),cy:y(p.v),r:faded?3:4.5,fill:c,opacity:faded?0.4:1,stroke:surface,"stroke-width":2}); e.addEventListener("mousemove",ev=>showTip(ev.clientX,ev.clientY,rows.concat(outOfRange(p)?[outLine]:[]),p.name||fmtDate(p.date))); e.addEventListener("mouseleave",hideTip); plot.append(e); };
  if(secondary){ const c2 = css(secondary.color)||secondary.color; drawProj(secondary.projection, c2); secondary.history.filter(p=>p.date>=from).forEach(p=>point(p, c2, [{label:secondary.label,value:fmtDur(p.v)}])); }
  drawProj(projection, col);
  history.filter(p=>p.date>=from).forEach(p => point(p, col, [{label:"Horizon",value:fmtDur(p.v)},{label:"Released",value:fullDate(p.date)}].concat(p.lo?[{label:"95% CI",value:`${fmtDur(p.lo)} – ${fmtDur(p.hi)}`}]:[])));
  box.append(s);
  const inFit = p => p.inFit!=null ? !!p.inFit : !outOfRange(p);
  const rate2 = secondary ? (secondary.rate || (String(secondary.label||"").match(/\d+%/)||[])[0] || secondary.label || "–") : null;
  const rows = history.filter(p=>p.date>=from).map(p=>({p, rate})).concat(secondary ? secondary.history.filter(p=>p.date>=from).map(p=>({p, rate:rate2})) : [])
    .sort((a,b)=>String(a.p.date).localeCompare(String(b.p.date)) || String(a.rate).localeCompare(String(b.rate)));
  host.append(tableView(title, ["Model","Released","Success rate","Horizon","95% CI","Used in fit?"], rows.map(({p, rate}) => [String(p.name||"–").replace(/\s*·\s*\d+%\s*$/,""), fullDate(p.date), rate, fmtDur(p.v), p.lo!=null && p.hi!=null ? `${fmtDur(p.lo)} – ${fmtDur(p.hi)}` : "–", inFit(p) ? "Yes" : (outOfRange(p) ? "No (above 16 hours)" : "No")])));
  return {fmtDur};
}
export {fmtDur};

/* ---- gauge row: the measured quantities under the dial ----
   Each tile: label, the question, the reading, change vs the previous reading, a kind tag
   (measured / estimated / assessed), a sparkline of past readings, the evidence, and a
   "How it's measured" disclosure (with the scale, where there is one). */
export function gaugeRow(host, defs, runs, {root=""}={}){
  host.replaceChildren();
  const withG = (runs||[]).filter(r=>r && r.gauges);
  const last = withG[withG.length-1], prev = withG[withG.length-2];
  if(!last){ host.append(h("p",{class:"muted"},"No gauge readings yet.")); return; }
  const row = h("div",{class:"gauges"});
  (defs||[]).forEach(d => {
    const g = last.gauges[d.key]; if(!g) return;
    const p = prev?.gauges?.[d.key];
    const tile = h("div",{class:"gauge"});
    const top = h("div",{class:"g-top"}); top.append(h("span",{class:"g-label"},d.label), h("span",{class:"tag g-kind"},d.kind)); tile.append(top);
    tile.append(h("div",{class:"g-q muted small"}, d.question));
    // "Level" is the fire alarm's word only: delegation is read in rungs (display only; data unchanged)
    tile.append(h("div",{class:"g-value"}, d.key === "delegation" ? String(g.display ?? "").replace(/\bLevel\s+(\d)\s+of\s+(\d)\b/i, "rung $1 of $2") : g.display));
    let delta = "first reading";
    if(p && p.value!=null && g.value!=null){ delta = fmtNum(g.value)===fmtNum(p.value) ? "no change" : (Number(g.value)>Number(p.value)?"▲ up ":"▼ down ") + fmtNum(Math.round(Math.abs(g.value-p.value)*1e6)/1e6); }
    const rg = Array.isArray(g.range) ? `${fmtNum(g.range[0])}–${fmtNum(g.range[1])}` : g.range;
    tile.append(h("div",{class:"g-delta muted small"}, (rg && !String(g.display||"").includes(rg) ? `range ${rg} · ` : "") + delta));
    tile.append(sparkline(withG.map(r=>r.gauges[d.key]?.value), {color:"--accent", cls:"g-spark"}));
    const parts = String(g.note || "").split(/(?<=[.!?])\s+(?=[A-Z0-9"“(])/);
    const note = h("div",{class:"g-note small"}, parts[0] + " ");
    const a = dataLink(g.url, "evidence", root); if(a) note.append(a);
    tile.append(note);
    if(parts.length > 1){ const more = h("details",{class:"g-more small"}); more.append(h("summary",{},"More"), h("p",{}, parts.slice(1).join(" "))); tile.append(more); }
    tile.append(h("div",{class:"g-feeds muted small"}, d.key === "gap" ? "In A's formula" : "Context for our odds"));
    const how = h("details",{class:"g-how small"}); how.append(h("summary",{},"How it's measured"), h("p",{}, d.how || ""));
    if(Array.isArray(d.scale) && d.scale.length){
      const ol = h("ol",{class:"g-scale"}), cur = Math.round(Number(g.value));
      d.scale.forEach((st,i) => { const txt = String(st).replace(/^\s*\d+\s*[:.)]\s*/,""), li = h("li"); if(i+1===cur) li.append(h("strong",{},txt), document.createTextNode(" (current)")); else li.textContent = txt; ol.append(li); });
      how.append(ol);
    }
    tile.append(how);
    tile.addEventListener("mousemove", ev => showTip(ev.clientX, ev.clientY, [{label:d.how}].concat(d.scale?d.scale.map(x=>({label:x})):[]), d.label + " · " + d.unit));
    tile.addEventListener("mouseleave", hideTip);
    row.append(tile);
  });
  host.append(row);
}

/* ---- fire alarm: the current level, with icon + word (never color alone) ----
   Bad or missing data shows a neutral "unavailable" box, never a red one: a typo must not look
   like an alarm. */
export function alarmIndicator(host, alarm, {root="", compact=false}={}){
  host.replaceChildren();
  const cur = alarm?.current || {}, levels = Array.isArray(alarm?.levels) ? alarm.levels : [];
  const lv = levels.find(l => l && l.level === cur.level);
  if(!lv){
    const box = h("div",{class:"alarm alarm-unknown",role:"status"});
    box.append(h("span",{class:"muted"},"Fire alarm status unavailable. "), h("a",{href:root+"alarm.html"},"See the criteria"));
    host.append(box); return;
  }
  const met = Array.isArray(cur.met) ? cur.met.map(String) : (cur.met == null ? [] : null);   // null: malformed list
  const box = h("div",{class:`alarm alarm-${lv.level}`,role:"status"});
  const scale = h("div",{class:"alarm-scale","aria-hidden":"true"});
  levels.forEach(l => { const seg=h("span",{class:"alarm-seg"+(l.level===lv.level?" on":"")}); if(l.level<=lv.level) seg.style.background=cssVar("--"+l.status); scale.append(seg); });
  const head = h("div",{class:"alarm-head"});
  const ic = h("span",{class:"alarm-icon"}, lv.icon); ic.style.color = cssVar("--" + lv.status);
  head.append(h("span",{class:"alarm-kicker"},"Fire alarm"), ic, h("strong",{class:"alarm-name"},`Level ${lv.level}: ${lv.name}`));
  box.append(head, scale);
  box.append(h("div",{class:"alarm-meaning"}, lv.meaning || ""));
  if(!compact){
    const det = h("div",{class:"muted small alarm-detail"});
    if(validDate(cur.since)) det.append(`Since ${fullDate(cur.since)} · `);
    det.append("triggers met: ");
    if(met === null) det.append("unavailable");
    else if(met.length) met.forEach((id,i) => { if(i) det.append(", "); det.append(h("a",{href:root+"alarm.html#"+encodeURIComponent(id)},id)); });
    else det.append("none");
    det.append("." + (cur.note ? " " + cur.note : ""));
    box.append(det);
  }
  box.append(h("a",{href:root+"alarm.html",class:"small"},"How the alarm works and what would raise it →"));
  host.append(box);
}
/* A banner on every page, shown only at Warning (2) or Alarm (3). */
export async function alarmBanner(root=""){
  try{
    const res = await fetch(root+"data/alarm.json",{cache:"no-cache"}); if(!res.ok) return;
    const alarm = await res.json();
    const lv = (Array.isArray(alarm?.levels) ? alarm.levels : []).find(l => l && l.level === alarm?.current?.level);
    if(!lv || !(lv.level >= 2)) return;
    const b = h("div",{class:"alarm-banner",role:"alert"});
    b.append(h("strong",{},`${lv.icon} Fire alarm: Level ${lv.level}, ${lv.name}. `), document.createTextNode((alarm.current.note||"")+" "), h("a",{href:root+"alarm.html"},"Details"));
    document.body.prepend(b);
  }catch(e){}
}

/* ---- AGI parts tracker (agi.html; FINAL_SPEC.md section 6) ----
   agiMap(host, data, {today, trends, root}): data = data/agi_components.json, trends = data/trends.json (projection
   dates are read from it, never copied), today = {date} of the newest published run (the "Now" line; never the
   browser clock). It replaces the server-rendered fallback inside host; if anything throws, the fallback is put
   back with a muted note. Status is ink pips plus a word, never a status or hypothesis colour; meters are linear on
   the measure's own scale; projections are ink and drawn only where a published trend supports them. */
const AM_RT = {"verified fact":"fact", "credible report":"report", "expert opinion":"opinion", "forecast aggregate":"agg", "our inference":"ours", "speculation":"spec"};
const AM_PS = {pass:["✓","Passed"], aggregate:["≈","Overall figure only"], no:["–","Not yet"], unmeasured:["?","Not measured"]};
const AM_MARK_LABEL = {workWeek:"work-week (40 h)", workMonth:"work-month (167 h)"};
const AM_MARK_SHORT = {workWeek:"wk", workMonth:"mo"};
const AM_RANGES = {all:["2019-01-01","2031-01-01"], recent:["2024-01-01","2031-01-01"]};
const AM_MY = {month:"short", year:"numeric"};
// element builder with children: attrs with null/false are skipped, {text} sets textContent
const el = (tag, attrs={}, ...kids) => { const e = document.createElement(tag); for(const [k,v] of Object.entries(attrs)){ if(v == null || v === false) continue; if(k === "text") e.textContent = v; else e.setAttribute(k, v === true ? "" : v); } kids.flat().forEach(k => { if(k != null && k !== "") e.append(k); }); return e; };
const amTime = d => { const s = String(d ?? ""); return /^\d{4}-\d{2}-\d{2}$/.test(s) ? parseDate(s).getTime() : Date.parse(s); };
const amOk = d => d != null && d !== "" && !isNaN(amTime(d));
const amDate = (d, o={day:"numeric", month:"short", year:"numeric"}) => fmtDate(d, o);
// a measurement's "as of" text: every ISO date in it reads like the rest of the site ("May 8, 2026"), the rest stays;
// in the table cell the leading date is kept on one line
const amAsOf = s => String(s ?? "").replace(/\b\d{4}-\d{2}-\d{2}\b/g, d => amDate(d));
const amAsOfCell = s => { const t = amAsOf(s), m = String(s ?? "").match(/^\d{4}-\d{2}-\d{2}\b/); if(!m) return t || "–"; const d = amDate(m[0]); return [el("span",{class:"am-day", text:d}), t.slice(d.length)]; };
const getPath = (o, path) => String(path || "").split(".").filter(Boolean).reduce((a,k) => a != null && typeof a === "object" ? a[k] : undefined, o);

export function agiMap(host, data, {today, trends, root=""}={}){
  if(!host) return null;
  const fallback = [...host.childNodes];
  const fail = err => {
    console.error("agiMap failed:", err);
    host.replaceChildren(...fallback);
    if(!host.querySelector(".am-fail")) host.prepend(el("p",{class:"muted am-fail", text:"The interactive view could not be drawn; the plain version is below."}));
    return null;
  };
  try{ return agiMapDraw(host, data, {today, trends, root}); }
  catch(err){ return fail(err); }
}

function agiMapDraw(host, D, {today, trends, root=""}){
  if(!D || !Array.isArray(D.components) || !D.components.length || !Array.isArray(D.statusScale)) throw new Error("agiMap: no components");
  const nowDate = typeof today === "string" ? today : today?.date;
  if(!validDate(nowDate)) throw new Error("agiMap: today.date is required");
  const SC = Object.fromEntries(D.statusScale.map(x => [x.key, x]));
  const RM = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const link = (u, txt="source") => dataLink(u, txt, root) || "";
  const tag = (r, note, qual) => r ? [el("span",{class:"tag " + (AM_RT[r] || ""), title:note || null, text:r}), qual ? el("span",{class:"tag-q", text:`(${qual})`}) : ""] : "";
  const rtag = x => x ? tag(x.rating, x.ratingNote, x.ratingQual) : "";
  const pips = (st, wcls="am-word") => { const sc = SC[st] || {word:String(st ?? "?"), pips:0}; return el("span",{class:"am-status"},
    el("span",{class:"am-pips","aria-hidden":"true"}, [0,1,2,3].map(i => el("span",{class:"pip" + (i < sc.pips ? " on" : "")}))),
    el("span",{class:wcls,"aria-hidden":"true", text:sc.word}), el("span",{class:"sr-only", text:`, status ${sc.word}, step ${sc.pips} of 4`})); };
  const word = st => (SC[st] || {word:String(st ?? "?")}).word;
  const hookTip = (node, title, body, rating) => {
    node.addEventListener("pointermove", ev => showTip(ev.clientX, ev.clientY, [{label:body}, ...(rating ? [{label:rating}] : [])], title));
    node.addEventListener("pointerleave", hideTip);
  };

  /* state */
  const q = new URLSearchParams(location.search);
  let range = innerWidth < 560 ? "recent" : "all", view = q.get("view") === "timeline" ? "timeline" : "parts", openId = null;
  const xScale = w => { const [a,b] = AM_RANGES[range].map(amTime); return d => (amTime(d) - a)/(b - a)*w; };
  const counts = () => { const c = {met:0, close:0, partial:0, far:0}; D.components.forEach(x => { if(has(c, x.status)) c[x.status]++; }); return c; };
  /* a refit can leave a crossing null (a bound that never crosses before 2045): such a mark draws nothing and reads "beyond 2030" */
  const crossings = c => { const tr = c.projection?.trend; if(!tr || !trends) return null; return getPath(trends, tr.path || "metr.p80.crossings") || trends.crossings || null; };
  const trendMarks = c => { const tr = c.projection?.trend, cr = crossings(c); if(!tr || !cr || !Array.isArray(tr.marks)) return [];
    return tr.marks.filter(k => cr[k]).map(k => ({key:k, label:AM_MARK_LABEL[k] || k, short:AM_MARK_SHORT[k] || k, mid:cr[k].mid, fast:cr[k].fast, slow:cr[k].slow})); };
  const markText = m => amOk(m.mid) ? amDate(m.mid, AM_MY) + (amOk(m.fast) && amOk(m.slow) ? ` (95% band ${amDate(m.fast, AM_MY)} to ${amDate(m.slow, AM_MY)})` : " (band beyond 2030)") : "beyond 2030";
  const doublings = H => H.growth && H.value > 0 ? Math.log2(H.target / H.value) : null;
  const partsLine = c => { const ps = c.parts || [], met = ps.filter(p => p.state === "pass").length, agg = ps.filter(p => p.state === "aggregate").length;
    return `${met} of ${ps.length} parts of the test met` + (agg ? ` (${agg} on the overall figure only, which doesn't count)` : ""); };
  const arr = v => Array.isArray(v) ? v : [];

  /* distance meter: linear on the measure's own scale, with the bar, the test's Partial and Close marks and secondary rings.
     Everything sits inside the row <button>, so only phrasing content (spans styled display:block). */
  function progress(c){
    const H = c.headline, lo = H.min || 0, hi = H.max;
    const pos = v => Math.max(0, Math.min(100, (v - lo)/(hi - lo)*100));
    const db = doublings(H);
    const box = el("span",{class:"am-prog"});
    const txt = el("span",{class:"pg-txt"}, el("b",{text:H.display}), ` · bar ${H.targetDisplay}` + (db ? ` · ${db.toFixed(1)} doublings short` : ""));
    const pg = el("span",{class:"pg","aria-hidden":"true"}, el("span",{class:"pg-fill", style:`width:${pos(H.value).toFixed(2)}%`}));
    if(H.scale === "count") for(let i = 1; i < H.max; i++) pg.append(el("span",{class:"pg-seg", style:`left:${(i/H.max*100).toFixed(2)}%`}));
    if(H.partialAt != null) pg.append(el("span",{class:"pg-partial", style:`left:${pos(H.partialAt).toFixed(2)}%`}));
    if(H.closeAt != null) pg.append(el("span",{class:"pg-close", style:`left:${pos(H.closeAt).toFixed(2)}%`}));
    pg.append(el("span",{class:"pg-bar", style:`left:${pos(H.target).toFixed(2)}%`}));
    arr(H.markers).forEach(m => pg.append(el("span",{class:"pg-mark", style:`left:${pos(m.value).toFixed(2)}%`})));
    const sub = el("span",{class:"pg-sub"}, el("span",{text:partsLine(c)}));
    const glyph = g => el("span",{"aria-hidden":"true", text:g + " "});
    arr(H.markers).forEach(m => sub.append(el("span",{}, glyph("○"), String(m.label || "").split(" (")[0] + (m.counts === "partial" ? " (counts toward Partial)" : ""))));
    if(H.partialAt != null) sub.append(el("span",{}, glyph("╎"), "partial at " + H.partialDisplay));
    if(H.closeAt != null) sub.append(el("span",{}, glyph("┆"), "close at " + H.closeDisplay));
    box.append(txt, pg, sub);
    return box;
  }
  /* growth measures get a labelled log axis in the drill-down only, so the row never shows a misleading "% of the way" */
  function logStrip(c){
    const H = c.headline, tk = arr(H.logTicks); if(tk.length < 2 || !(H.value > 0)) return "";
    const lo = Math.log(tk[0][0]), hi = Math.log(tk[tk.length-1][0]);
    const pos = v => Math.max(0, Math.min(100, (Math.log(v) - lo)/(hi - lo)*100));
    const tr = el("div",{class:"pg","aria-hidden":"true"}, el("div",{class:"pg-fill", style:`width:${pos(H.value).toFixed(1)}%`}),
      H.closeAt != null ? el("div",{class:"pg-close", style:`left:${pos(H.closeAt).toFixed(1)}%`}) : "",
      el("div",{class:"pg-bar", style:`left:${pos(H.target).toFixed(1)}%`}));
    /* the last two ticks (work-week, work-month) sit two doublings apart, so the last label drops to a second row */
    const ticks = el("div",{class:"pg-ticks","aria-hidden":"true"}, tk.map(([v,l],i) => el("span",{class:(pos(v) > 97 ? "end" : (pos(v) < 3 ? "start" : "")) + (i === tk.length-1 && tk.length > 2 ? " low" : "") + (i === tk.length-3 && tk.length > 3 && pos(tk[i+1][0]) - pos(v) < 20 ? " low-n" : ""), style:`left:${pos(v).toFixed(1)}%`, text:l})));
    return el("div",{class:"am-log"}, el("p",{class:"small", text:`On a log scale, where each step is a doubling: ${H.display} now, about ${doublings(H).toFixed(1)} doublings short of ${H.targetDisplay}.`}), tr, ticks);
  }

  /* timeline lane: 2019 (or 2024) to 2030, Now line, milestones, trend projection, coming-up marks */
  function slotPlace(items, x, ys){
    const rows = ys.map(() => []);
    return items.map(it => { const px = x(it.date); let r = rows.findIndex(row => row.every(q => Math.abs(q - px) > 10)); if(r < 0) r = 0; rows[r].push(px); return {it, px, py:ys[r]}; });
  }
  function lane(c, w, {tall=false, years=false}={}){
    const LH = tall ? 46 : 34, H = LH + (years ? 13 : 0), mid = LH/2;
    const x = xScale(w), g = svg("svg",{viewBox:`0 0 ${w} ${H}`, height:H, "aria-hidden":"true", focusable:"false"});
    const [A, B] = AM_RANGES[range], y0 = +A.slice(0,4), y1 = +B.slice(0,4), nx = x(nowDate);
    g.append(svg("rect",{x:nx, y:0, width:Math.max(0, w - nx), height:LH, class:"tl-future"}));
    for(let y = y0; y <= y1; y++){
      const gx = x(`${y}-01-01`); g.append(svg("line",{x1:gx, x2:gx, y1:0, y2:LH, class:"tl-grid"}));
      if(years && y < y1 && (range === "recent" || (y - y0) % 2 === 0)){ const tx = svg("text",{x:gx+2, y:H-2, class:"tl-yr"}); tx.textContent = range === "recent" ? "'" + String(y).slice(2) : String(y); g.append(tx); }
    }
    g.append(svg("line",{x1:0, x2:w, y1:LH, y2:LH, class:"tl-base"}));
    const ys = tall ? [mid, mid-12, mid+12] : [mid, mid-9, mid+9];
    const inLane = d => amOk(d) && x(d) >= 0 && x(d) <= w;
    const drawn = trendMarks(c).filter(mk => inLane(mk.mid));
    if(drawn.length){
      const last = drawn[drawn.length-1], tr = c.projection.trend;
      if(amOk(last.fast) && amOk(last.slow)){ const bx = Math.max(0, x(last.fast)), bw = Math.min(w, x(last.slow)) - bx; if(bw > 0) g.append(svg("rect",{x:bx, y:mid-7, width:Math.max(2, bw), height:14, rx:2, class:"tl-band"})); }
      g.append(svg("line",{x1:nx, x2:x(last.mid), y1:mid, y2:mid, class:"tl-proj"}));
      drawn.forEach(mk => {
        const px = x(mk.mid), d = svg("path",{d:`M${px} ${mid-6} L${px+6} ${mid} L${px} ${mid+6} L${px-6} ${mid} Z`, class:"tl-pmark"});
        hookTip(d, `On trend: ${mk.label}`, `${markText(mk)}. A measured trend extended, not a forecast; METR's current suite can't yet measure that far.` + (tr.note ? " " + tr.note : ""), "our inference · our METR 80% horizon fit (Trend watch)");
        g.append(d);
        if(drawn.length > 1){ const lb = svg("text",{x:px, y:mid-9, class:"tl-plabel", "text-anchor":"middle"}); lb.textContent = mk.short; g.append(lb); }
      });
    }
    const ups = arr(c.upcoming).filter(u => amOk(u.date) && x(u.date) >= 0 && x(u.date) <= w);
    slotPlace(ups, x, [ys[2]+1, ys[1]-1]).forEach(({it:u, px, py:yb}) => { const p = svg("path",{d:`M${px-5} ${yb+4} L${px+5} ${yb+4} L${px} ${yb-5} Z`, class:"tl-up"}); hookTip(p, "Coming up: " + (u.approx || amDate(u.date)), u.text); g.append(p); });
    const ms = arr(c.milestones).filter(m => amOk(m.date));
    const inRange = ms.filter(m => { const px = x(m.date); return px >= -2 && px <= w + 2; });
    const earlier = ms.filter(m => x(m.date) < -2).length;
    if(earlier > 0){ const tx = svg("text",{x:2, y:10, class:"tl-more"}); tx.textContent = "‹" + earlier; hookTip(tx, `${earlier} earlier milestone${earlier > 1 ? "s" : ""}`, `Before ${A.slice(0,4)}. Choose "Since 2019", or open the part for the full list.`); g.append(tx); }
    slotPlace(inRange, x, ys).forEach(({it, px, py}) => {
      const mk = it.kind === "yardstick" ? svg("rect",{x:px-4, y:py-4, width:8, height:8, class:"tl-yard"}) : svg("circle",{cx:px, cy:py, r:4.5, class:it.kind === "internal" ? "tl-int" : "tl-dot"});
      hookTip(mk, amDate(it.date) + (it.kind === "internal" ? " · unreleased model" : it.kind === "yardstick" ? " · new test" : ""), it.text, it.rating);
      g.append(mk);
    });
    g.append(svg("line",{x1:nx, x2:nx, y1:0, y2:LH, class:"tl-now"}));
    return g;
  }
  function axis(w){
    const x = xScale(w), g = svg("svg",{viewBox:`0 0 ${w} 22`, height:22, "aria-hidden":"true"});
    const [A, B] = AM_RANGES[range], y0 = +A.slice(0,4), y1 = +B.slice(0,4), step = (w/(y1 - y0)) < 34 ? 2 : 1;
    for(let y = y0; y < y1; y++){ if((y - y0) % step) continue; const tx = svg("text",{x:x(`${y}-01-01`)+2, y:20, class:"tl-yr"}); tx.textContent = y; g.append(tx); }
    const nx = x(nowDate), lb = svg("text",{x:nx, y:9, class:"tl-nowlabel", "text-anchor":"middle"}); lb.textContent = "Now"; g.append(lb);
    g.append(svg("line",{x1:nx, x2:nx, y1:11, y2:22, class:"tl-now"}));
    return g;
  }

  /* drill-down panel: why this status, the parts of the test, the bar and the headline first; then seven closed details */
  function panel(c){
    const H = c.headline;
    const p = el("div",{class:"am-panel", id:"am-panel-" + c.id, role:"region", "aria-label":c.name + ": details", hidden:true});
    const parts = el("ul",{class:"am-parts"}, arr(c.parts).map(pt => { const ps = AM_PS[pt.state] || ["?", String(pt.state ?? "")]; return el("li",{}, el("span",{class:"mk","aria-hidden":"true", text:ps[0]}), el("strong",{text:ps[1] + ": "}), pt.name, el("span",{class:"muted", text:` (${pt.value})`})); }));
    const left = el("div",{}, el("p",{class:"am-basis-p"}, el("strong",{text:c.statusBasis})), el("p",{}, el("strong",{text:"Where it stands. "}), c.statusNote), el("p",{}, el("strong",{text:partsLine(c) + "."})), parts);
    /* one line each for the hardest part, who is working on it and what to watch next; the full lists stay collapsed */
    const who = arr(c.who), ch = arr(c.challenges), watch = arr(c.watching), nxt = arr(c.upcoming)[0];
    const hard = ch.length ? String(ch[0].text || "").split(". ")[0].replace(/\.$/, "") + "." : "";
    const fs = el("div",{class:"am-fs small"},
      el("p",{}, el("strong",{text:"Hardest: "}), hard),
      el("p",{}, el("strong",{text:"Who: "}), who.slice(0,3).map(x => x.name).join(", ") + (who.length > 3 ? ` and ${who.length - 3} more` : "") + "."),
      el("p",{}, el("strong",{text:"Next to watch: "}), (() => { const sg = watch[0] ? String(watch[0].signal || "") : "", when = nxt ? (nxt.approx || amDate(nxt.date)) : ""; return sg + (when && !sg.includes(when) ? ` (${when})` : "") + "."; })()));
    const right = el("div",{},
      el("p",{}, el("strong",{text:"Bar. "}), c.bar),
      el("p",{class:"small"}, el("strong",{text:"Headline measure: "}), `${H.label}: ${H.display} (${H.system}, ${amAsOf(H.asOf)}) `, rtag(H), " ", link(H.url)),
      H.growth ? logStrip(c) : "",
      c.also ? el("p",{class:"small"}, el("strong",{text:"Also: "}), c.also.text, " ", rtag(c.also), " ", link(c.also.url)) : "",
      c.sharedWith ? el("p",{class:"small muted", text:c.sharedWith}) : "",
      el("p",{class:"small muted"}, c.v1Test ? "Part of the v1.0 remote-work test, kept in v2.0. " : "Added in v2.0: the v1.0 test did not require it. ", el("a",{href:"#v1", text:"How v2.0 relates to v1.0"})));
    const det = (title, body) => el("details",{}, el("summary",{text:title}), el("div",{class:"body"}, body));
    const cur = arr(c.current);
    const curT = el("table",{class:"am-meas"}, el("tr",{}, ["Measure","Result","System","As of","Source"].map(x => el("th",{scope:"col", text:x}))),
      cur.map(x => el("tr",{}, el("td",{text:x.metric}), el("td",{"data-label":"Result", text:x.value}), el("td",{"data-label":"System", text:x.system || "–"}), el("td",{"data-label":"As of"}, amAsOfCell(x.asOf)), el("td",{"data-label":"Source"}, rtag(x), " ", link(x.url), x.ratingNote ? el("span",{class:"small muted", text:" " + x.ratingNote}) : ""))));
    const msl = arr(c.milestones);
    const ms = el("ul",{class:"timeline-list"}, msl.map(m => el("li",{}, el("span",{class:"when", text:amDate(m.date)}), el("span",{}, m.text, " ", m.kind === "internal" ? el("span",{class:"chip", text:"unreleased model"}) : "", m.kind === "yardstick" ? el("span",{class:"chip", text:"new test"}) : "", " ", rtag(m), " ", link(m.url)))));
    const proj = c.projection, marks = trendMarks(c), ahead = [];
    if(marks.length) ahead.push(el("p",{}, el("strong",{text:"On trend. "}), marks.map(m => `${m.label}: ${markText(m)}`).join("; ") + ". ", tag("our inference"), " ", link("trends.html", "Trend watch")));
    if(proj?.text) ahead.push(el("p",{}, el("strong",{text:"Ahead. "}), proj.text, " ", rtag(proj), " ", link(proj.url)));
    arr(c.upcoming).forEach(u => ahead.push(el("p",{}, el("strong",{text:"Coming up, " + (u.approx || amDate(u.date)) + ". "}), u.text, " ", link(u.url))));
    const t = c.test || {};
    p.append(
      el("p",{class:"q", text:c.question}),
      el("div",{class:"am-kv"}, left, right),
      fs,
      det("The full test", [el("p",{}, el("strong",{text:"Measure. "}), t.measure), el("p",{}, el("strong",{text:"Marks. "}), t.threshold), t.detail ? el("p",{class:"small muted"}, el("strong",{text:"Details. "}), t.detail) : "", t.why ? el("p",{}, el("strong",{text:"Why this test. "}), t.why) : "", el("p",{class:"muted"}, el("strong",{text:"Definition clause. "}), c.clause || "")]),
      det(`Latest measurements (${cur.length})`, [el("p",{text:c.statusDetail}), el("div",{class:"table-wrap"}, curT)]),
      det(`Timeline (${msl.length} milestones) and what lies ahead`, [ms, ...ahead]),
      det(`Hard parts (${ch.length})`, el("ul",{class:"plain"}, ch.map(x => el("li",{}, x.text, " ", rtag(x), " ", link(x.url))))),
      det(`Who is working on it (${who.length})`, el("ul",{class:"plain"}, who.map(x => el("li",{}, el("strong",{text:x.name}), ": ", x.what, " ", link(x.url))))),
      det(`What we watch (${watch.length})`, el("ul",{class:"plain"}, watch.map(x => el("li",{}, el("strong",{text:x.signal}), ". ", x.threshold || "", x.why ? el("span",{class:"muted", text:" Why: " + x.why}) : "", el("span",{class:"muted", text:" Source: " + (x.sourceName || "") + " "}), link(x.url))))),
      c.hiddenAngle ? det("Could it be hidden?", el("p",{text:c.hiddenAngle})) : "",
      el("p",{class:"small muted am-foot"}, `${word(c.status)} since ${amDate(c.since)} · reviewed ${amDate(c.lastReviewed)}.`, el("a",{href:"#" + c.id, text:"Link to this part"}), el("button",{class:"am-close", type:"button", "data-close":c.id, text:"Close"})));
    return p;
  }

  /* "Show as table": everything the picture shows, as text */
  function tables(){
    const mk = (caption, head, rows) => el("table",{}, el("caption",{class:"sr-only", text:caption}), el("tr",{}, head.map(x => el("th",{scope:"col", text:x}))), rows.map(r => el("tr",{}, r.map(x => el("td",{text:x})))));
    const status = mk("The eight parts of AGI: status, best public result, bar and on-trend dates", ["Part","Status","Best public result","Bar","On-trend date"],
      D.components.map(c => [c.name, word(c.status), `${c.headline.display} (${c.headline.label}; ${c.headline.system}, ${amAsOf(c.headline.asOf)})`, c.bar,
        trendMarks(c).map(m => `${m.label}: ${markText(m)}`).join("; ") || "No published trend"]));
    const all = D.components.flatMap(c => arr(c.milestones).map(m => [m.date, c.short, m.kind === "internal" ? "unreleased model" : m.kind === "yardstick" ? "new test" : "public result", m.text, m.rating || ""])).sort((a,b) => String(a[0]).localeCompare(String(b[0])));
    const ms = mk("Every milestone, by date", ["Date","Part","Kind","What happened","Rating"], all.map(r => [amDate(r[0]), r[1], r[2], r[3], r[4]]));
    return el("details",{class:"table-view"}, el("summary",{text:"Show as table"}), el("div",{class:"table-wrap"}, status), el("div",{class:"table-wrap", style:"margin-top:12px"}, ms));
  }

  /* the widget */
  function render(){
    const c = counts();
    const seg = (key, label, opts, cur) => el("span",{class:"am-seg", role:"group", "aria-label":label}, opts.map(([k,l]) => el("button",{type:"button", "aria-pressed":String(cur === k), ["data-" + key]:k, text:l})));
    const glyph = (inner) => { const g = svg("svg",{width:12, height:12, viewBox:"0 0 12 12", "aria-hidden":"true"}); g.append(inner); return g; };
    const top = el("div",{class:"am-top"},
      el("p",{class:"am-sum", text:`${c.met} of ${D.components.length} met · ${c.close} close · ${c.partial} partial · ${c.far} far`}),
      el("div",{class:"am-legend", role:"list", "aria-label":"Status scale"}, [...D.statusScale].reverse().map(sc => el("span",{role:"listitem", title:sc.meaning}, pips(sc.key)))));
    const tools = el("div",{class:"am-tools"},
      el("span",{class:"am-tool"}, el("span",{class:"muted", text:"View"}), seg("view", "View", [["parts","Parts"],["timeline","Timeline"]], view)),
      el("span",{class:"am-tool"}, el("span",{class:"muted", text:"From"}), seg("range", "Timeline range", [["all","Since 2019"],["recent","2024 on"]], range)),
      el("span",{class:"am-glyphs"},
        el("span",{}, glyph(svg("circle",{cx:6, cy:6, r:4.5, class:"tl-dot"})), " public result"),
        el("span",{}, glyph(svg("circle",{cx:6, cy:6, r:4, class:"tl-int"})), " unreleased model"),
        el("span",{}, glyph(svg("rect",{x:2, y:2, width:8, height:8, class:"tl-yard"})), " new test"),
        el("span",{}, glyph(svg("path",{d:"M6 1 L11 6 L6 11 L1 6 Z", class:"tl-pmark"})), " on-trend date"),
        el("span",{}, glyph(svg("path",{d:"M1 10 L11 10 L6 2 Z", class:"tl-up"})), " coming up")));
    const axisRow = el("div",{class:"am-grid am-axisrow"}, el("div",{class:"h", text:"Part · status"}), el("div",{class:"h hp", text:"Best public result vs the bar"}), el("div",{class:"am-axis"}));
    const ul = el("ul",{class:"am-rows"});
    D.components.forEach(cm => {
      const li = el("li",{class:"am-row" + (openId === cm.id ? " open" : ""), id:cm.id, "data-id":cm.id});
      const pr = progress(cm); pr.id = `am-p-${cm.id}`;
      /* APG accordion: each row's button sits in an h3; the button holds only spans (styled display:block) */
      const btn = el("button",{class:"am-btn am-grid", type:"button", "aria-expanded":String(openId === cm.id), "aria-controls":"am-panel-" + cm.id, "aria-labelledby":`am-n-${cm.id} am-s-${cm.id}`, "aria-describedby":`am-g-${cm.id} am-p-${cm.id}`, "data-id":cm.id},
        el("span",{class:"am-c1"}, el("span",{class:"am-name", id:`am-n-${cm.id}`}, el("span",{class:"am-chev","aria-hidden":"true", text:"▶"}), cm.name), el("span",{class:"am-st", id:`am-s-${cm.id}`}, pips(cm.status), el("span",{class:"am-basis", id:`am-b-${cm.id}`, text:" · " + (cm.basisShort || "")})), el("span",{class:"am-glance", id:`am-g-${cm.id}`, text:cm.glance})),
        pr, el("span",{class:"am-lane", "data-lane":cm.id}));
      const pn = panel(cm); if(openId === cm.id) pn.hidden = false;
      li.append(el("h3",{class:"am-h"}, btn), pn); ul.append(li);
    });
    host.replaceChildren(top, tools, el("div",{class:"am" + (view === "timeline" ? " tl-mode" : "")}, axisRow, ul), tables());
    drawLanes();
  }
  function drawLanes(){
    const rows = host.querySelector(".am-rows"); if(!rows || !host.isConnected) return;
    const narrow = rows.clientWidth < 729, tall = view === "timeline";
    host.querySelectorAll("[data-lane]").forEach(e => { const w = Math.max(120, Math.floor(e.clientWidth)); e.replaceChildren(lane(D.components.find(x => x.id === e.dataset.lane), w, {tall, years:narrow})); });
    const ax = host.querySelector(".am-axis"); if(ax){ const w = Math.max(120, Math.floor(ax.clientWidth)); ax.replaceChildren(narrow ? "" : axis(w)); }
  }
  const byId = id => D.components.some(c => c.id === id);
  const rowEl = id => [...host.querySelectorAll(".am-row")].find(li => li.dataset.id === id);
  const btnEl = id => rowEl(id)?.querySelector(".am-btn");
  function setOpen(id, {scroll=true}={}){
    openId = openId === id ? null : id;
    host.querySelectorAll(".am-row").forEach(li => { const on = li.dataset.id === openId; li.classList.toggle("open", on); li.querySelector(".am-btn").setAttribute("aria-expanded", String(on)); li.querySelector(".am-panel").hidden = !on; });
    if(openId){ history.replaceState(null, "", location.pathname + location.search + "#" + openId); if(scroll) rowEl(openId)?.scrollIntoView({block:"nearest", behavior:RM ? "auto" : "smooth"}); }
    else history.replaceState(null, "", location.pathname + location.search);
  }
  function openFromHash(){
    let id = ""; try{ id = decodeURIComponent(location.hash.slice(1)); }catch(e){ return; }
    if(byId(id) && openId !== id){ setOpen(id, {scroll:false}); rowEl(id)?.scrollIntoView({block:"start", behavior:"auto"}); }
  }
  function wire(){
    host.addEventListener("click", ev => {
      const v = ev.target.closest("[data-view]"); if(v){ view = v.dataset.view; host.querySelectorAll("[data-view]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.view === view))); host.querySelector(".am").classList.toggle("tl-mode", view === "timeline"); drawLanes(); return; }
      const r = ev.target.closest("[data-range]"); if(r){ range = r.dataset.range; host.querySelectorAll("[data-range]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.range === range))); drawLanes(); return; }
      const cl = ev.target.closest("[data-close]"); if(cl){ const id = cl.dataset.close; setOpen(id); btnEl(id)?.focus(); return; }
      const b = ev.target.closest(".am-btn"); if(b) setOpen(b.dataset.id);
    });
    host.addEventListener("keydown", ev => {
      if(ev.key === "Escape" && openId){ const id = openId; setOpen(id, {scroll:false}); btnEl(id)?.focus(); ev.preventDefault(); return; }
      const b = ev.target.closest(".am-btn"); if(!b) return;
      const all = [...host.querySelectorAll(".am-btn")], i = all.indexOf(b), go = j => { all[(j + all.length) % all.length].focus(); ev.preventDefault(); };
      if(ev.key === "ArrowDown") go(i+1); else if(ev.key === "ArrowUp") go(i-1); else if(ev.key === "Home") go(0); else if(ev.key === "End") go(all.length-1);
    });
    /* in-page links that name a part (a[data-open="<id>"]) open it without a page jump; plain #<id> links go through hashchange */
    document.addEventListener("click", ev => { const a = ev.target.closest?.("a[data-open]"); if(!a || !byId(a.dataset.open)) return; ev.preventDefault(); const id = a.dataset.open; if(openId !== id) setOpen(id, {scroll:false}); rowEl(id)?.scrollIntoView({block:"start", behavior:RM ? "auto" : "smooth"}); });
    addEventListener("hashchange", openFromHash);
    let lastW = innerWidth, tmr; addEventListener("resize", () => { if(innerWidth === lastW) return; lastW = innerWidth; clearTimeout(tmr); tmr = setTimeout(() => { try{ drawLanes(); }catch(e){ console.error("agiMap redraw failed:", e); } }, 150); });
  }

  render(); wire(); openFromHash();
  const o = q.get("open"); if(o && byId(o) && openId !== o) setOpen(o, {scroll:q.get("scroll") !== "0"});
  if(document.fonts?.ready) document.fonts.ready.then(() => { try{ drawLanes(); }catch(e){} });
  host.dataset.ready = "1";
  return {open: id => { if(byId(id) && openId !== id) setOpen(id); }, redraw: drawLanes};
}

/* ---- open the <details> a URL fragment points at ----
   alarm.html#W3, #rules, #proof and the like are <details>, or sit inside one. Chrome opens them on a fragment
   navigation; Safari and Firefox don't. Every frozen report imports this module for alarmBanner, so this runs
   after DOMContentLoaded, never throws, and looks the id up with getElementById, never a selector built from
   the hash (#2026 or #a:b would make querySelector throw). */
function openHashTarget(){
  try{
    if(!location.hash || location.hash.length < 2) return;
    let id; try{ id = decodeURIComponent(location.hash.slice(1)); }catch(e){ id = location.hash.slice(1); }
    const target = document.getElementById(id); if(!target) return;
    let opened = false;
    for(let e = target; e; e = e.parentElement) if(e.tagName === "DETAILS" && !e.open){ e.open = true; opened = true; }
    if(opened) target.scrollIntoView({block:"start"});
  }catch(e){ /* never break the page */ }
}
if(typeof document !== "undefined" && typeof addEventListener === "function"){
  try{
    let ran = false; const once = () => { if(ran) return; ran = true; openHashTarget(); };
    if(document.readyState === "complete") once();
    else { document.addEventListener("DOMContentLoaded", once, {once:true}); addEventListener("load", once, {once:true}); }
    addEventListener("hashchange", openHashTarget);
  }catch(e){}
}

/* ---- scroll hint: a table wider than its .table-wrap fades at the right edge until it's scrolled
   to the end (phones hide the scrollbar). Every page imports this module, so it runs site-wide,
   including on tables that are built after the page loads. */
function scrollHint(w){
  const upd = () => w.classList.toggle("more-right", w.scrollWidth - w.clientWidth - w.scrollLeft > 4);
  if(!w.dataset.scrollHint){
    w.dataset.scrollHint = "1";
    w.addEventListener("scroll", upd, {passive:true});
    if(typeof ResizeObserver !== "undefined"){ const ro = new ResizeObserver(upd); ro.observe(w); if(w.firstElementChild) ro.observe(w.firstElementChild); }
  }
  upd();
}
export function scrollHints(root=document){ root.querySelectorAll(".table-wrap").forEach(scrollHint); }
if(typeof document !== "undefined" && document.body){
  scrollHints();
  if(typeof MutationObserver !== "undefined"){
    let queued = false;
    new MutationObserver(() => { if(queued) return; queued = true; requestAnimationFrame(() => { queued = false; scrollHints(); }); })
      .observe(document.body, {childList:true, subtree:true});
  }
}
