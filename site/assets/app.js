/* RPM·LoRa showcase: replay of the real OMNeT++ run, architecture explorer, frame map and charts (no dependencies). */
(function () {
  'use strict';
  const D = window.RPM_DATA;
  const T = window.rpmTopology();
  const $ = (s) => document.querySelector(s);
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const NS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs = {}, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; };
  const C = { cyan: '#22d3ee', blue: '#3b82f6', violet: '#8b5cf6', lav: '#c4b5fd', text: '#e6edf7', muted: '#8b9bb4', warn: '#fbbf24', bad: '#f87171', line: 'rgba(148,163,184,.16)' };

  /* ---------------------------------------------------------------- 1. replay of OMNeT++ run r6 */
  function replay() {
    const cv = $('#net'); if (!cv) return;
    const ctx = cv.getContext('2d');
    const SPEED = 8, SIM_END = 121, HOLD = 2.5, SEG = 0.42;          // sim seconds per real second; real seconds per hop
    const pkt = D.packets.map((p) => ({ patient: p.patient, dep: p.t - p.delay_ms / 1000, hop: p.hop }));
    pkt.push({ patient: D.lost.patient, dep: 1 + 1.5 * (D.lost.patient - 1), hop: -1, lost: true });   // initialDelay = 1 s + index * 1.5 s
    pkt.sort((a, b) => a.dep - b.dep);
    let size = 560, k = 3, c = 280, t0 = performance.now(), paused = false, pausedAt = 0, visible = true;
    const fit = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2), w = cv.clientWidth || 560;
      cv.width = w * dpr; cv.height = w * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); size = w; c = w / 2; k = (w / 2 - 26) / 84;
    };
    const P = (q) => [c + q.x * k, c + q.y * k];
    function base(flash) {
      ctx.clearRect(0, 0, size, size);
      ctx.save(); ctx.setLineDash([3, 6]);
      [25, 45, 80].forEach((r) => { ctx.strokeStyle = C.line; ctx.beginPath(); ctx.arc(c, c, r * k, 0, 7); ctx.stroke(); });
      ctx.strokeStyle = 'rgba(139,92,246,.3)'; ctx.beginPath(); ctx.arc(c, c, 30 * k, 0, 7); ctx.stroke(); ctx.restore();
      ctx.lineWidth = 1;
      T.patients.forEach((p) => {
        const pts = T.path(p).map(P);
        ctx.strokeStyle = p.relay < 0 ? 'rgba(34,211,238,.16)' : 'rgba(167,139,250,.35)'; ctx.setLineDash(p.relay < 0 ? [] : [5, 4]);
        ctx.beginPath(); ctx.moveTo(...pts[0]); pts.slice(1).forEach((q) => ctx.lineTo(...q)); ctx.stroke();
      });
      ctx.setLineDash([]);
      const g = ctx.createRadialGradient(c, c, 0, c, c, 18 * k); g.addColorStop(0, 'rgba(34,211,238,.45)'); g.addColorStop(1, 'rgba(34,211,238,0)');
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(c, c, 18 * k, 0, 7); ctx.fill();
      T.relays.forEach((r, j) => { const [x, y] = P(r); ctx.shadowColor = C.violet; ctx.shadowBlur = 12; ctx.fillStyle = C.violet; ctx.fillRect(x - 7, y - 7, 14, 14); ctx.shadowBlur = 0; ctx.fillStyle = C.text; ctx.font = '600 10px Inter, sans-serif'; ctx.fillText('R' + (j + 1), x + 10, y - 8); });
      T.patients.forEach((p) => {
        const [x, y] = P(p), f = flash[p.id] || 0;
        ctx.shadowColor = C.cyan; ctx.shadowBlur = 8 + 14 * f; ctx.fillStyle = p.relay < 0 ? C.cyan : '#a5f3fc';
        ctx.beginPath(); ctx.arc(x, y, 4.5 + 3 * f, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
      });
      ctx.shadowColor = '#fff'; ctx.shadowBlur = 16; ctx.fillStyle = C.text; ctx.beginPath(); ctx.arc(c, c, 8, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
      ctx.fillStyle = C.cyan; ctx.beginPath(); ctx.arc(c, c, 3.5, 0, 7); ctx.fill();
    }
    function frame(now) {
      if (!visible) { requestAnimationFrame(frame); return; }
      const real = ((paused ? pausedAt : now) - t0) / 1000;
      const cycle = SIM_END / SPEED + HOLD, rt = reduce ? cycle - 0.01 : real % cycle, sim = Math.min(rt * SPEED, SIM_END);
      const flash = {}, live = []; let gen = 0, dir = 0, rel = 0, lost = 0;
      for (const q of pkt) {
        if (q.dep > sim) break;
        gen++;
        const age = (sim - q.dep) / SPEED;                     // real seconds since departure
        const p = T.patients[q.patient - 1], path = T.path(p);
        const segs = q.lost ? 1 : path.length - 1, dur = segs * SEG;
        if (age < 0.25) flash[q.patient] = 1 - age / 0.25;
        if (age < dur) {
          const s = Math.min(segs - 1e-6, age / SEG), i = Math.floor(s), u = s - i;
          const a = P(path[i]), b = P(path[i + 1]);
          live.push({ x: a[0] + (b[0] - a[0]) * u, y: a[1] + (b[1] - a[1]) * u, col: q.lost ? C.bad : q.hop > 0 ? C.lav : C.cyan, lost: q.lost && u > 0.82 });
        } else if (q.lost) { lost++; if (age < dur + 1.6) live.push({ x: P(T.relays[0])[0] + 14, y: P(T.relays[0])[1] + 14, col: C.bad, cross: 1 - (age - dur) / 1.6 }); }
        else if (q.hop > 0) rel++; else dir++;
      }
      base(flash);
      for (const d of live) {
        if (d.cross !== undefined) { ctx.globalAlpha = Math.max(0, d.cross); ctx.strokeStyle = C.bad; ctx.lineWidth = 2.5; ctx.beginPath(); ctx.moveTo(d.x - 6, d.y - 6); ctx.lineTo(d.x + 6, d.y + 6); ctx.moveTo(d.x + 6, d.y - 6); ctx.lineTo(d.x - 6, d.y + 6); ctx.stroke(); ctx.globalAlpha = 1; ctx.lineWidth = 1; continue; }
        ctx.shadowColor = d.col; ctx.shadowBlur = 16; ctx.fillStyle = d.col; ctx.beginPath(); ctx.arc(d.x, d.y, 4.2, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
      }
      $('#cGen').textContent = gen; $('#cDir').textContent = dir; $('#cRel').textContent = rel; $('#cLost').textContent = lost;
      if (!reduce) requestAnimationFrame(frame);
    }
    fit(); window.addEventListener('resize', () => { fit(); if (reduce) frame(performance.now()); });
    if ('IntersectionObserver' in window) new IntersectionObserver((es) => { visible = es[0].isIntersecting; }).observe(cv);
    const btn = $('#netToggle');
    if (reduce) { btn.hidden = true; } else btn.addEventListener('click', () => {
      paused = !paused; btn.setAttribute('aria-pressed', String(paused)); btn.textContent = paused ? 'Play' : 'Pause';
      if (paused) pausedAt = performance.now(); else t0 += performance.now() - pausedAt;
    });
    requestAnimationFrame(frame);
  }

  /* ---------------------------------------------------------------- 2. architecture explorer */
  const NODES = {
    patient: ['Patient node', 'warn', 'firmware written · not flashed', 'ESP32-S3 with a LoRa radio (RadioLib). Samples every 30 s from MAX30102 (HR/SpO₂, optional), DS18B20 (temperature) and MPU-6050 (fall). A missing sensor sets a fault flag instead of sending zero; the 32-bit sequence number survives reboots; a fall or critical event triggers an immediate frame, sent twice.'],
    relay: ['Relay node', 'warn', 'hardware pending · simulated', 'Checks the CRC, drops duplicates, enforces at most 4 hops, increments hopCount and recomputes the CRC. hopCount is excluded from the HMAC, so relays need no key and cannot alter other fields unnoticed.'],
    heltec: ['Heltec V3 bench receiver', 'bench', 'bench link operating', 'Heltec WiFi LoRa 32 V3 (ESP32-S3 + SX1262) receives LoRa packets and forwards them over a one-way UART (TX on GPIO2) to the Pi 5 (GPIO15 / RXD0, /dev/ttyAMA0). Reception on the Pi is still to be confirmed.'],
    radio: ['Radio input', 'sim', 'implemented · hardware pending', 'SX127x register driver over SPI, or the UART bridge: the gateway already reads one hex-encoded frame per line, so a raw v2 frame forwarded by the Heltec is accepted unchanged and stays protected by its HMAC.'],
    spool: ['Store-and-forward spool', 'ok', 'tested', 'Frames are kept in a local SQLite queue and retried in order whenever the platform API is unreachable, so a restart does not lose radio data.'],
    ingest: ['Ingestion pipeline', 'ok', 'tested', 'CRC-16 → device key lookup → HMAC-SHA256 tag (64 bit) → 62-frame replay window → plausibility limits (HR 20–250 bpm, SpO₂ 50–100 %, 25–45 °C) → quality classification.'],
    stores: ['Isolated data stores', 'ok', 'tested', 'Three SQLite (WAL) files: system (users, audit), hardware and simulation. Simulated and physical data never share a table; virtual devices use identifiers from 60001.'],
    alerts: ['Alerts + early warning', 'syn', 'model on synthetic data', 'Threshold, fall, sensor-fault and connectivity alerts with a lifecycle and automatic escalation. A gradient-boosting model predicts a sustained breach within 10 min, with a calibrated score and its main contributing features.'],
    api: ['REST API + live events', 'ok', 'tested', 'Server-side role checks and per-patient scope, CSRF tokens, scrypt passwords with lockout, optional TOTP, a SHA-256 hash-chained audit log, and server-sent events for live updates.'],
    dash: ['Web dashboard', 'ok', 'tested · demo recorded', 'Doctor, medical assistant (assigned patients) and family caregiver (one patient, recorded consent) workspaces: overview, patient views, map, LoRa digital twin, early-warning page and reports.'],
    sims: ['Simulation sources', 'sim', 'simulation', 'The web simulation engine (virtual nodes from 60001, scenarios A–G) and the imported OMNeT++ results feed the separate simulation store, never the hardware one.'],
  };
  function explorer() {
    const svg = $('#archSvg'), panel = $('#archPanel'); if (!svg) return;
    const defs = el('defs', {}, svg);
    const mk = el('marker', { id: 'ah', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' }, defs);
    el('path', { d: 'M0 0L10 5L0 10z', fill: '#8b9bb4' }, mk);
    el('rect', { x: 262, y: 22, width: 448, height: 290, rx: 16, fill: 'rgba(15,23,42,.55)', stroke: 'rgba(59,130,246,.45)', 'stroke-dasharray': '0' }, svg);
    el('text', { x: 280, y: 46, fill: '#93c5fd', 'font-size': 13, 'font-family': 'JetBrains Mono, monospace', 'letter-spacing': '1.5' }, svg).textContent = 'RASPBERRY PI 5 EDGE GATEWAY';
    const box = (id, x, y, w, h, title, sub, dashed) => {
      const g = el('g', { class: 'arch-node', tabindex: 0, role: 'button', 'data-id': id, 'aria-label': title }, svg);
      el('rect', { x, y, width: w, height: h, rx: 12, fill: 'rgba(15,23,42,.85)', stroke: dashed ? 'rgba(251,191,36,.7)' : 'rgba(148,163,184,.35)', 'stroke-dasharray': dashed ? '6 5' : '0', 'stroke-width': 1.4 }, g);
      el('text', { x: x + 14, y: y + 26, fill: '#e6edf7', 'font-size': 15, 'font-weight': 600, 'font-family': 'Space Grotesk, Inter, sans-serif' }, g).textContent = title;
      el('text', { x: x + 14, y: y + 46, fill: '#8b9bb4', 'font-size': 12, 'font-family': 'Inter, sans-serif' }, g).textContent = sub;
      return g;
    };
    const line = (x1, y1, x2, y2, col, dash) => el('path', { d: `M${x1} ${y1} L${x2} ${y2}`, stroke: col, 'stroke-width': 1.8, fill: 'none', 'stroke-dasharray': dash || '0', 'marker-end': 'url(#ah)' }, svg);
    line(222, 82, 278, 92, '#22d3ee'); line(222, 206, 278, 118, '#c4b5fd', '6 4'); line(222, 334, 278, 130, '#93c5fd', '3 4');
    line(408, 104, 422, 104, '#8b9bb4'); line(548, 104, 562, 104, '#8b9bb4'); line(632, 140, 632, 178, '#8b9bb4');
    line(562, 226, 548, 226, '#8b9bb4'); line(422, 226, 408, 226, '#8b9bb4'); line(708, 226, 742, 110, '#8b9bb4'); line(830, 290, 700, 250, '#8b9bb4', '2 4');
    box('patient', 20, 56, 202, 64, 'Patient node', 'ESP32-S3 + LoRa', true);
    box('relay', 20, 180, 202, 64, 'Relay node', '≤ 4 hops, no key needed', true);
    box('heltec', 20, 304, 202, 64, 'Heltec V3 receiver', 'bench · UART to the Pi', false);
    box('radio', 278, 76, 130, 64, 'Radio input', 'SPI or UART');
    box('spool', 422, 76, 126, 64, 'Spool', 'store and forward');
    box('ingest', 562, 76, 136, 64, 'Ingestion', 'CRC · HMAC · replay');
    box('stores', 562, 192, 136, 64, 'Data stores', '3 isolated SQLite');
    box('alerts', 422, 192, 126, 64, 'Alerts + ML', 'early warning');
    box('api', 278, 192, 130, 64, 'API + SSE', 'roles · audit');
    box('dash', 742, 70, 198, 76, 'Web dashboard', 'doctor · assistant · caregiver');
    box('sims', 742, 262, 198, 76, 'Simulation sources', 'web engine · OMNeT++');
    el('text', { x: 230, y: 74, fill: '#22d3ee', 'font-size': 11, 'font-family': 'JetBrains Mono, monospace' }, svg).textContent = 'LoRa';
    el('text', { x: 20, y: 404, fill: '#5d6b82', 'font-size': 12, 'font-family': 'Inter, sans-serif' }, svg).textContent = 'Dashed amber outline: hardware validation pending. Click a component for details.';
    const show = (id) => {
      const n = NODES[id];
      svg.querySelectorAll('.arch-node').forEach((g) => g.classList.toggle('on', g.dataset.id === id));
      panel.innerHTML = `<span class="chip ${n[1]}">${n[2]}</span><h3>${n[0]}</h3><p>${n[3]}</p>`;
    };
    svg.querySelectorAll('.arch-node').forEach((g) => {
      g.addEventListener('click', () => show(g.dataset.id));
      g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); show(g.dataset.id); } });
    });
    show('ingest');
  }

  /* ---------------------------------------------------------------- 3. frame map */
  function bytes() {
    const host = $('#bytes'); if (!host) return;
    const F = [['ver', 1, '#94a3b8'], ['type', 1, '#94a3b8'], ['patientId', 2, '#67e8f9'], ['sourceId', 2, '#67e8f9'], ['destId', 2, '#67e8f9'], ['seqNo', 4, '#93c5fd'], ['timestamp', 4, '#93c5fd'],
      ['HR', 1, '#fda4af'], ['SpO₂', 1, '#fda4af'], ['temp', 2, '#fda4af'], ['flags', 1, '#fcd34d'], ['AL<br>RM', 1, '#fcd34d'], ['HC<br>MH', 1, '#fcd34d'], ['batt', 1, '#fcd34d'],
      ['HMAC-SHA256 tag · 64 bit', 8, '#c4b5fd'], ['CRC-16', 2, '#cbd5e1']];
    let off = 0;
    for (const [name, len, col] of F) {
      const d = document.createElement('div'); d.className = 'byte-f' + (len === 1 ? ' s1' : ''); d.style.gridColumn = `span ${len}`; d.style.background = col;
      const plain = name.replace('<br>', '/');
      d.innerHTML = `<small>${off}</small>${name}`; d.title = `${plain}: ${len} byte${len > 1 ? 's' : ''} (offset ${off})`; host.appendChild(d); off += len;
    }
  }

  /* ---------------------------------------------------------------- 4. charts (plain SVG) */
  function svgBox(host, w, h) { const s = el('svg', { viewBox: `0 0 ${w} ${h}`, class: 'chart', role: 'img' }); host.appendChild(s); return s; }
  function airtime() {
    const host = $('#airChart'); if (!host) return;
    const s = svgBox(host, 520, 150); s.setAttribute('aria-label', 'Time on air: 77.1 ms for the 34-byte frame versus 379.1 ms for JSON');
    const rows = [['v2 binary frame (34 B)', D.airtime_ms.v2_34B, C.cyan], ['JSON, same fields (241 B)', D.airtime_ms.json_241B, C.bad]];
    rows.forEach(([lab, v, col], i) => {
      const y = 22 + i * 62, w = (v / 420) * 300;
      el('text', { x: 0, y: y + 22 }, s).textContent = lab;
      el('rect', { x: 180, y, width: w, height: 34, rx: 6, fill: col, opacity: 0.9 }, s);
      el('text', { x: 186 + w, y: y + 23, class: 'v' }, s).textContent = v.toFixed(1) + ' ms';
    });
  }
  function donut() {
    const host = $('#donut'); if (!host) return;
    const parts = [['direct', D.sim.direct, C.cyan], ['via relays', D.sim.relay_assisted, C.lav], ['lost', D.sim.generated - D.sim.doctor_valid, C.warn]];
    const wrap = document.createElement('div'); wrap.className = 'donut-wrap'; host.appendChild(wrap);
    const s = el('svg', { viewBox: '0 0 120 120', width: 120, height: 120, role: 'img', 'aria-label': '64 direct, 15 via relays, 1 lost of 80' }); wrap.appendChild(s);
    let a = -Math.PI / 2; const tot = D.sim.generated;
    parts.forEach(([, v, col]) => {
      const b = a + (v / tot) * Math.PI * 2, r = 48, x1 = 60 + r * Math.cos(a), y1 = 60 + r * Math.sin(a), x2 = 60 + r * Math.cos(b), y2 = 60 + r * Math.sin(b);
      el('path', { d: `M${x1} ${y1} A${r} ${r} 0 ${b - a > Math.PI ? 1 : 0} 1 ${x2} ${y2}`, stroke: col, 'stroke-width': 16, fill: 'none' }, s); a = b;
    });
    const t = el('text', { x: 60, y: 66, 'text-anchor': 'middle', fill: '#e6edf7', 'font-size': 18, 'font-weight': 700, 'font-family': 'Space Grotesk, sans-serif' }, s); t.textContent = `${D.sim.doctor_valid}/${tot}`;
    const leg = document.createElement('div'); leg.className = 'donut-legend';
    leg.innerHTML = parts.map(([l, v, col]) => `<span><i style="background:${col}"></i><b style="color:#e6edf7">${v}</b> ${l}</span>`).join('') + '<span>0 collisions · 0 duplicates</span>';
    wrap.appendChild(leg);
  }
  function delays() {
    const host = $('#delayChart'); if (!host) return;
    const s = svgBox(host, 520, 240); s.setAttribute('aria-label', 'Delay per relay hop, simulated versus analytical');
    const max = 340, H = 180, x0 = 40;
    [0, 100, 200, 300].forEach((v) => { const y = 200 - (v / max) * H; el('line', { x1: x0, x2: 515, y1: y, y2: y, class: 'grid' }, s); el('text', { x: 0, y: y + 4 }, s).textContent = v; });
    D.delay_summary.forEach((r, i) => {
      const gx = x0 + 20 + i * 118;
      [[r.sim_ms, C.cyan], [r.analytic34_ms, C.violet]].forEach(([v, col], j) => {
        const h = (v / max) * H, x = gx + j * 40;
        el('rect', { x, y: 200 - h, width: 34, height: h, rx: 5, fill: col, opacity: 0.92 }, s);
        el('text', { x: x + 17, y: 194 - h, 'text-anchor': 'middle', class: 'v' }, s).textContent = Math.round(v);
      });
      el('text', { x: gx + 37, y: 222, 'text-anchor': 'middle' }, s).textContent = r.hop === 0 ? 'direct' : `${r.hop} hop${r.hop > 1 ? 's' : ''} · n=${r.n}`;
    });
    el('rect', { x: 330, y: 6, width: 10, height: 10, rx: 2, fill: C.cyan }, s); el('text', { x: 346, y: 15 }, s).textContent = 'simulated (ms)';
    el('rect', { x: 440, y: 6, width: 10, height: 10, rx: 2, fill: C.violet }, s); el('text', { x: 456, y: 15 }, s).textContent = '34-B frame';
  }
  function relays() {
    const host = $('#relayChart'); if (!host) return;
    const s = svgBox(host, 520, 170); s.setAttribute('aria-label', 'Relay 1 forwarded 7, relay 2 forwarded 11, relay 3 forwarded 15 frames, none dropped');
    D.relay_stats.forEach((r, i) => {
      const y = 14 + i * 50, w = (r.forwarded / 16) * 250;
      el('text', { x: 0, y: y + 22 }, s).textContent = `Relay ${r.index + 1}`;
      el('rect', { x: 80, y, width: w, height: 32, rx: 6, fill: C.violet, opacity: 0.85 }, s);
      el('text', { x: 88 + w, y: y + 22, class: 'v' }, s).textContent = `${r.forwarded}/${r.received} forwarded · ${r.dropped} dropped`;
    });
  }
  function trajectory() {
    const host = $('#trajChart'); if (!host) return;
    const W = 1040, H = 260, L = 46, R = 16, Tp = 14, B = 34, s = svgBox(host, W, H);
    s.setAttribute('aria-label', 'Model score over time for one synthetic test profile, with high and medium thresholds');
    const X = (t) => L + ((t + 40) / 55) * (W - L - R), Y = (v) => Tp + (1 - v) * (H - Tp - B);
    [0, 0.5, 1].forEach((v) => { el('line', { x1: L, x2: W - R, y1: Y(v), y2: Y(v), class: 'grid' }, s); el('text', { x: 8, y: Y(v) + 4 }, s).textContent = v; });
    [-40, -30, -20, -10, 0, 10].forEach((t) => { el('text', { x: X(t), y: H - 10, 'text-anchor': 'middle' }, s).textContent = t + ' min'; });
    [[D.model.thresholds.high, C.text, '6 5', 'high'], [D.model.thresholds.medium, C.muted, '2 4', 'medium']].forEach(([v, col, d, lab]) => {
      el('line', { x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: col, 'stroke-dasharray': d, 'stroke-width': 1.2 }, s);
      el('text', { x: W - R - 4, y: Y(v) - 6, 'text-anchor': 'end' }, s).textContent = lab;
    });
    [[0, 'episode onset', 'end', -5], [7.283, 'sustained breach', 'start', 5]].forEach(([t, lab, anchor, dx]) => {
      el('line', { x1: X(t), x2: X(t), y1: Tp, y2: H - B, stroke: 'rgba(251,191,36,.6)', 'stroke-dasharray': '3 4' }, s);
      el('text', { x: X(t) + dx, y: H - B - 8, fill: '#fbbf24', 'text-anchor': anchor }, s).textContent = lab;
    });
    const pts = D.trajectory.filter((p) => p.score !== null).map((p) => `${X(p.t).toFixed(1)},${Y(p.score).toFixed(1)}`).join(' ');
    const g = el('linearGradient', { id: 'sg', x1: 0, x2: 1, y1: 0, y2: 0 }, el('defs', {}, s));
    el('stop', { offset: 0, 'stop-color': C.cyan }, g); el('stop', { offset: 1, 'stop-color': C.violet }, g);
    el('polyline', { points: pts, fill: 'none', stroke: 'url(#sg)', 'stroke-width': 2.4, 'stroke-linejoin': 'round' }, s);
  }

  /* ---------------------------------------------------------------- 5. gallery lightbox */
  function gallery() {
    const dlg = $('#lightbox'); if (!dlg || !dlg.showModal) return;
    document.querySelectorAll('#gallery button').forEach((b) => b.addEventListener('click', () => {
      dlg.querySelector('img').src = b.dataset.src; dlg.querySelector('img').alt = b.dataset.cap; dlg.querySelector('p').textContent = b.dataset.cap + ' · simulation mode, synthetic patients'; dlg.showModal();
    }));
    dlg.querySelector('button').addEventListener('click', () => dlg.close());
    dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
  }

  /* the OMNeT++ clip loops silently, but never moves for visitors who prefer reduced motion */
  if (reduce) document.querySelectorAll('video[autoplay]').forEach((v) => { v.removeAttribute('autoplay'); v.pause(); v.controls = true; });

  replay(); explorer(); bytes(); airtime(); donut(); delays(); relays(); trajectory(); gallery();
})();
