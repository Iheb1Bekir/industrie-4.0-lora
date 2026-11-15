// Dependency-free charts. One measure per chart (never a dual axis); time axis in local time;
// crosshair tooltip; drag to zoom, double-click to reset; gaps in the data are drawn as gaps.
import { esc, fmtDT } from './core.js';

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function niceStep(span, target) {
  const raw = span / target, mag = 10 ** Math.floor(Math.log10(raw)), f = raw / mag;
  return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag;
}
const TIME_STEPS = [1, 5, 10, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 21600, 43200, 86400, 172800, 604800];

export class TimeChart {
  /** opts: {label, unit, color (css var name), decimals, yMin, yMax, bands:[{value,label,kind:'above'|'below'}]} */
  constructor(el, opts) {
    this.el = el; this.o = opts; this.points = []; this.view = null; this.domain = null; this.drag = null;
    el.classList.add('chart');
    el.innerHTML = '<canvas></canvas><div class="chart-tip"></div>';
    this.cv = el.firstChild; this.tip = el.lastChild;
    this.ro = new ResizeObserver(() => this.draw());
    this.ro.observe(el);
    this.cv.addEventListener('mousemove', (e) => this.hover(e));
    this.cv.addEventListener('mouseleave', () => { this.hx = null; this.tip.style.display = 'none'; this.draw(); });
    this.cv.addEventListener('mousedown', (e) => { this.drag = { x0: e.offsetX, x1: e.offsetX }; });
    window.addEventListener('mouseup', this.up = () => {
      if (!this.drag) return;
      const { x0, x1 } = this.drag; this.drag = null;
      if (Math.abs(x1 - x0) > 12) { const [a, b] = [this.xInv(Math.min(x0, x1)), this.xInv(Math.max(x0, x1))]; this.view = [a, b]; this.zoomed?.(this.view); }
      this.draw();
    });
    this.cv.addEventListener('dblclick', () => { this.view = null; this.zoomed?.(null); this.draw(); });
  }
  destroy() { this.ro.disconnect(); window.removeEventListener('mouseup', this.up); }
  /** points: [[ts, value|null], ...] sorted; domain: [from, to] */
  set(points, domain) { this.points = points; this.domain = domain; this.draw(); }
  push(ts, v, domain) {
    this.points.push([ts, v]);
    if (domain) { this.domain = domain; while (this.points.length && this.points[0][0] < domain[0]) this.points.shift(); }
    this.draw();
  }
  setView(v) { this.view = v; this.draw(); }
  xr() { return this.view || this.domain || [0, 1]; }
  x(t) { const [a, b] = this.xr(); return this.pl + ((t - a) / (b - a)) * this.pw; }
  xInv(px) { const [a, b] = this.xr(); return a + ((px - this.pl) / this.pw) * (b - a); }
  draw() {
    const { cv, o } = this, dpr = window.devicePixelRatio || 1, W = this.el.clientWidth, H = this.el.clientHeight;
    if (!W || !H) return;
    cv.width = W * dpr; cv.height = H * dpr;
    const g = cv.getContext('2d'); g.scale(dpr, dpr);
    const pl = (this.pl = 40), pr = 12, pt = 10, pb = 22, pw = (this.pw = W - pl - pr), ph = H - pt - pb;
    const [t0, t1] = this.xr();
    const vis = this.points.filter((p) => p[0] >= t0 && p[0] <= t1);
    const vals = vis.map((p) => p[1]).filter((v) => v !== null && v !== undefined);
    let lo = o.yMin ?? Math.min(...vals, ...(o.bands || []).map((b) => b.value)), hi = o.yMax ?? Math.max(...vals, ...(o.bands || []).map((b) => b.value));
    if (!vals.length && o.yMin === undefined) { lo = 0; hi = 1; }
    if (vals.length) { lo = Math.min(lo, Math.min(...vals)); hi = Math.max(hi, Math.max(...vals)); }
    const pad = (hi - lo) * 0.12 || 1; lo -= pad; hi += pad;
    const y = (v) => pt + ph - ((v - lo) / (hi - lo)) * ph;
    const ink3 = css('--ink-3'), grid = css('--grid'), color = css(o.color);
    g.font = '11px system-ui'; g.textBaseline = 'middle';
    const ys = niceStep(hi - lo, 4);
    g.strokeStyle = grid; g.fillStyle = ink3; g.lineWidth = 1; g.textAlign = 'right';
    for (let v = Math.ceil(lo / ys) * ys; v <= hi; v += ys) {
      g.beginPath(); g.moveTo(pl, Math.round(y(v)) + 0.5); g.lineTo(pl + pw, Math.round(y(v)) + 0.5); g.stroke();
      g.fillText(v.toFixed(ys < 1 ? 1 : 0), pl - 6, y(v));
    }
    const span = t1 - t0, ts = TIME_STEPS.find((s) => span / s <= Math.max(3, pw / 90)) || 604800;
    g.textAlign = 'center'; g.textBaseline = 'top';
    const tzOff = new Date().getTimezoneOffset() * 60;
    for (let t = Math.ceil((t0 - tzOff) / ts) * ts + tzOff; t <= t1; t += ts) {
      const d = new Date(t * 1000);
      const lbl = ts >= 86400 ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
        : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', ...(ts < 60 ? { second: '2-digit' } : {}) });
      g.fillText(lbl, this.x(t), pt + ph + 6);
    }
    for (const b of o.bands || []) {           // alert limits: dashed line + label, tinted zone beyond the limit
      if (b.value < lo || b.value > hi) continue;
      const crit = css('--critical');
      g.fillStyle = crit; g.globalAlpha = 0.06;
      if (b.kind === 'above') g.fillRect(pl, pt, pw, y(b.value) - pt); else g.fillRect(pl, y(b.value), pw, pt + ph - y(b.value));
      g.globalAlpha = 1; g.strokeStyle = crit; g.setLineDash([4, 4]);
      g.beginPath(); g.moveTo(pl, y(b.value)); g.lineTo(pl + pw, y(b.value)); g.stroke(); g.setLineDash([]);
      g.fillStyle = crit; g.textAlign = 'right'; g.textBaseline = 'bottom'; g.fillText(b.label, pl + pw - 4, y(b.value) - 2);
    }
    // line with gaps: break when a value is missing or the time gap is much larger than the usual interval
    const gaps = []; for (let i = 1; i < vis.length; i++) gaps.push(vis[i][0] - vis[i - 1][0]);
    const med = gaps.length ? gaps.slice().sort((a, b) => a - b)[gaps.length >> 1] : 0, maxGap = Math.max(med * 3.5, 1);
    g.strokeStyle = color; g.lineWidth = 2; g.lineJoin = 'round'; g.beginPath();
    let pen = false, prev = null;
    for (const [t, v] of vis) {
      if (v === null || v === undefined) { pen = false; continue; }
      if (pen && prev !== null && t - prev > maxGap) pen = false;
      if (pen) g.lineTo(this.x(t), y(v)); else g.moveTo(this.x(t), y(v));
      pen = true; prev = t;
    }
    g.stroke();
    if (vis.length && vis.length < 80) { g.fillStyle = color; for (const [t, v] of vis) if (v !== null && v !== undefined) { g.beginPath(); g.arc(this.x(t), y(v), 2.2, 0, 7); g.fill(); } }
    for (const m of this.marks || []) {         // event markers (e.g. falls)
      if (m.ts < t0 || m.ts > t1) continue;
      g.strokeStyle = css('--critical'); g.lineWidth = 1.5; g.beginPath(); g.moveTo(this.x(m.ts), pt); g.lineTo(this.x(m.ts), pt + ph); g.stroke();
      g.fillStyle = css('--critical'); g.textAlign = 'left'; g.textBaseline = 'top'; g.fillText(m.label, this.x(m.ts) + 4, pt + 2);
    }
    if (!vals.length) { g.fillStyle = ink3; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('No measurements in this period', pl + pw / 2, pt + ph / 2); }
    if (this.drag) { g.fillStyle = css('--brand'); g.globalAlpha = 0.15; g.fillRect(Math.min(this.drag.x0, this.drag.x1), pt, Math.abs(this.drag.x1 - this.drag.x0), ph); g.globalAlpha = 1; }
    if (this.hx != null && !this.drag) { g.strokeStyle = css('--ink-3'); g.lineWidth = 1; g.beginPath(); g.moveTo(this.hx, pt); g.lineTo(this.hx, pt + ph); g.stroke();
      if (this.hp) { g.fillStyle = color; g.strokeStyle = css('--surface'); g.lineWidth = 2; g.beginPath(); g.arc(this.x(this.hp[0]), y(this.hp[1]), 4.5, 0, 7); g.fill(); g.stroke(); } }
    this.yf = y;
  }
  hover(e) {
    if (this.drag) { this.drag.x1 = e.offsetX; this.draw(); return; }
    const t = this.xInv(e.offsetX);
    let best = null;
    for (const p of this.points) if (p[1] !== null && p[1] !== undefined && (!best || Math.abs(p[0] - t) < Math.abs(best[0] - t))) best = p;
    this.hx = e.offsetX; this.hp = best;
    if (best) {
      this.tip.style.display = 'block';
      this.tip.style.left = this.x(best[0]) + 'px'; this.tip.style.top = (this.yf ? this.yf(best[1]) : 0) + 'px';
      this.tip.innerHTML = `<b>${esc(Number(best[1]).toFixed(this.o.decimals ?? 0))} ${esc(this.o.unit || '')}</b> · ${esc(fmtDT(best[0]))}`;
    }
    this.draw();
  }
}

// Static XY curve (ROC / precision-recall / calibration) as SVG with hover readout.
export function xyChart(el, { curves, xlabel, ylabel, diagonal = false, points = false }) {
  const W = 420, H = 300, pl = 44, pb = 36, pt = 10, pr = 12, pw = W - pl - pr, ph = H - pt - pb;
  const X = (v) => pl + v * pw, Y = (v) => pt + ph - v * ph;
  let s = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;max-height:320px" role="img" aria-label="${esc(ylabel)} versus ${esc(xlabel)}">`;
  for (let i = 0; i <= 5; i++) {
    const v = i / 5;
    s += `<line x1="${pl}" x2="${pl + pw}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/><text x="${pl - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="var(--ink-3)">${v.toFixed(1)}</text>`;
    s += `<text x="${X(v)}" y="${pt + ph + 16}" text-anchor="middle" font-size="11" fill="var(--ink-3)">${v.toFixed(1)}</text>`;
  }
  if (diagonal) s += `<line x1="${X(0)}" y1="${Y(0)}" x2="${X(1)}" y2="${Y(1)}" stroke="var(--axis)" stroke-dasharray="4 4"/>`;
  for (const c of curves) {
    s += `<polyline fill="none" stroke="var(${c.color})" stroke-width="2" stroke-linejoin="round" points="${c.points.map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(' ')}"/>`;
    if (points) s += c.points.map((p) => `<circle cx="${X(p[0]).toFixed(1)}" cy="${Y(p[1]).toFixed(1)}" r="4" fill="var(${c.color})" stroke="var(--surface)" stroke-width="2"><title>${esc(xlabel)} ${p[0].toFixed(3)} · ${esc(ylabel)} ${p[1].toFixed(3)}${p[2] !== undefined ? ` · n=${p[2]}` : ''}</title></circle>`).join('');
  }
  s += `<text x="${pl + pw / 2}" y="${H - 4}" text-anchor="middle" font-size="12" fill="var(--ink-2)">${esc(xlabel)}</text>`;
  s += `<text transform="translate(12 ${pt + ph / 2}) rotate(-90)" text-anchor="middle" font-size="12" fill="var(--ink-2)">${esc(ylabel)}</text></svg>`;
  el.innerHTML = s;
}

// Horizontal bars with direct value labels (magnitude comparison).
export function barList(el, rows, { fmt = (v) => v.toFixed(3), color = '--hr' } = {}) {
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 1e-9);
  el.innerHTML = rows.map((r) => `<div class="bar-row" title="${esc(r.title || '')}"><span>${esc(r.label)}</span>
    <div class="bar-track"><div class="bar-fill" style="width:${Math.max(1, (Math.abs(r.value) / max) * 100).toFixed(1)}%;background:var(${r.color || color})"></div></div>
    <span class="num" style="text-align:right">${esc(fmt(r.value))}</span></div>`).join('');
}

// Two-series histogram (negative vs positive class score distribution), small multiples stacked vertically.
export function histogram(el, edges, series) {
  const W = 420, H = 110, pl = 8, pw = W - 16, n = edges.length - 1, bw = pw / n;
  el.innerHTML = series.map((s) => {
    const max = Math.max(...s.counts, 1);
    const bars = s.counts.map((c, i) => `<rect x="${(pl + i * bw + 1).toFixed(1)}" y="${(H - 22 - (c / max) * (H - 34)).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${((c / max) * (H - 34)).toFixed(1)}" rx="2" fill="var(${s.color})"><title>score ${edges[i].toFixed(2)}–${edges[i + 1].toFixed(2)}: ${c} rows</title></rect>`).join('');
    return `<div class="small muted" style="margin-top:6px"><span class="swatch" style="background:var(${s.color})"></span>${esc(s.label)} (${s.counts.reduce((a, b) => a + b, 0)} rows, own scale)</div>
      <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">${bars}<line x1="${pl}" x2="${pl + pw}" y1="${H - 22}" y2="${H - 22}" stroke="var(--axis)"/>
      ${[0, 0.25, 0.5, 0.75, 1].map((v) => `<text x="${pl + v * pw}" y="${H - 8}" font-size="10" fill="var(--ink-3)" text-anchor="${v === 0 ? 'start' : v === 1 ? 'end' : 'middle'}">${v}</text>`).join('')}
      ${s.threshold != null ? `<line x1="${pl + s.threshold * pw}" x2="${pl + s.threshold * pw}" y1="4" y2="${H - 22}" stroke="var(--critical)" stroke-dasharray="4 3"/>` : ''}</svg>`;
  }).join('');
}
