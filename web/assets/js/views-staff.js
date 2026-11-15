// Clinical views: overview, patient list, patient profile, alert centre, map.
import { $, $$, STATE_LABEL, ago, api, badge, can, debounce, esc, fail, fmtDT, fmtShort, fmtT, formModal, icon, infoModal, n, pct, state, stateBadge, toast } from './core.js';
import { TimeChart } from './charts.js';

const simTag = () => (state.mode === 'simulation' ? '<span class="tag">SIM</span>' : '');
const vitCell = (label, v, unit, bad, d = 0) => `<div class="${v === null || v === undefined ? 'na' : bad ? 'bad' : ''}"><b>${n(v, d)}</b><span>${esc(label)} ${esc(unit)}</span></div>`;

function tile(p) {
  const m = p.latest, t = p.thresholds_hint || {};
  return `<a class="tile ${esc(p.state)}" href="#/patients/${p.id}" data-pid="${p.id}">
    <div class="row"><b>${esc(p.full_name)}</b><span class="muted small">${esc(p.code)}</span><span class="right">${stateBadge(p.state)}</span></div>
    <div class="vit">${vitCell('HR', m?.heart_rate, 'bpm', m && m.heart_rate > 120)}${vitCell('SpO₂', m?.spo2, '%', m && m.spo2 !== null && m.spo2 < 92)}${vitCell('Temp', m?.temperature, '°C', m && m.temperature >= 38, 1)}</div>
    <div class="row small muted" style="margin-top:9px"><span data-age>${m ? `Updated ${esc(ago(m.ts))}` : 'No measurement received'}</span>
      <span class="right">${p.device ? (p.device.online ? '● device online' : '○ device offline') : 'no device'}</span></div>
    ${p.prediction && p.prediction.status === 'ok' && p.prediction.risk_category !== 'low' ? `<div class="small" style="margin-top:6px">${badge(p.prediction.risk_category === 'high' ? 'prediction' : 'medium', `AI risk: ${p.prediction.risk_category}`)}</div>` : ''}
    ${m?.fall_detected ? `<div class="small" style="margin-top:6px">${badge('critical', 'Fall flag')}</div>` : ''}</a>`;
}

function alertRow(a, actions = true) {
  const btn = (act, label, perm, cls = '') => (can(perm) ? `<button class="btn sm ${cls}" data-act="${act}" data-id="${a.id}">${label}</button>` : '');
  const open = ['new', 'acknowledged', 'assigned', 'escalated'].includes(a.status);
  return `<tr data-alert="${a.id}"><td>${badge(a.severity, a.severity)}</td><td><b>${esc(a.label)}</b><div class="small muted">${esc(a.message)}</div></td>
    <td>${a.patient_id ? `<a href="#/patients/${a.patient_id}">${esc(a.patient_name)}</a><div class="small muted">${esc(a.patient_code)}</div>` : '<span class="muted">system</span>'}</td>
    <td>${badge(a.category === 'predictive' ? 'predictive' : 'info', a.category)}</td><td class="num">${esc(fmtShort(a.created_at))}<div class="small muted">${esc(ago(a.created_at))}${a.trigger_count > 1 ? ` · ×${a.trigger_count}` : ''}</div></td>
    <td>${badge(a.status, a.status.replace('_', ' '))}</td>
    <td>${actions ? `<div class="row" style="gap:5px;flex-wrap:nowrap">${open && ['new', 'escalated'].includes(a.status) ? btn('acknowledge', 'Acknowledge', 'alerts.acknowledge', 'primary') : ''}
      ${open && a.status !== 'escalated' ? btn('escalate', 'Escalate', 'alerts.escalate') : ''}${open ? btn('resolve', 'Resolve', 'alerts.resolve') : ''}
      <button class="btn sm" data-act="detail" data-id="${a.id}">Details</button></div>` : ''}</td></tr>`;
}

async function alertAction(id, act, reload) {
  try {
    if (act === 'detail') return alertDetail(id, reload);
    let note;
    if (act === 'resolve' || act === 'false_positive' || act === 'escalate') {
      const v = await formModal(`${act.replace('_', ' ')} alert`, [{ name: 'note', label: 'Note (optional)', type: 'textarea', full: true }], { submit: 'Confirm' });
      if (!v) return;
      note = v.note || undefined;
    }
    await api(`/alerts/${id}/action`, { method: 'POST', body: { action: act, note } });
    toast('Alert updated', `Action: ${act.replace('_', ' ')}`, 'ok');
    reload();
  } catch (e) { fail(e); }
}

async function alertDetail(id, reload) {
  const { alert: a } = await api(`/alerts/${id}`);
  const m = a.measurement, pr = a.prediction;
  const bg = infoModal(`${a.label} — alert #${a.id}`, `
    <div class="row">${badge(a.severity, a.severity)}${badge(a.status, a.status.replace('_', ' '))}${badge('info', a.category)}<span class="muted small right">${esc(fmtDT(a.created_at))}</span></div>
    <div>${esc(a.message)}</div>
    ${m ? `<div class="note"><b>Triggering measurement</b> (${esc(fmtT(m.ts))}): HR ${n(m.heart_rate)} bpm · SpO₂ ${n(m.spo2)} % · Temp ${n(m.temperature, 1)} °C${m.fall_detected ? ' · fall flag' : ''}</div>` : ''}
    ${pr ? `<div class="note"><b>Triggering prediction</b> — model ${esc(pr.model_version)}, risk ${esc(pr.risk_category)}, score ${n(pr.score, 3)}
      <div class="small">${pr.explanation.map((e) => `${esc(e.label)} = ${esc(e.value)} (${esc(e.direction)})`).join('<br>')}</div></div>` : ''}
    ${a.note ? `<div><h3>Note</h3>${esc(a.note)}</div>` : ''}
    <div><h3>History</h3><table><tbody>${a.events.map((e) => `<tr><td class="num small">${esc(fmtDT(e.ts))}</td><td>${esc(e.action.replace('_', ' '))}</td><td>${esc(e.user_name)}</td><td class="small muted">${esc(e.note || '')}</td></tr>`).join('')}</tbody></table></div>
    ${can('alerts.false_positive') && !['resolved', 'false_positive'].includes(a.status) ? '<button class="btn danger" data-fp>Mark as false positive</button>' : ''}`);
  bg.querySelector('[data-fp]')?.addEventListener('click', () => { bg.remove(); alertAction(id, 'false_positive', reload); });
}

const bindAlertActions = (root, reload) => root.addEventListener('click', (e) => {
  const b = e.target.closest('[data-act]');
  if (b) { e.preventDefault(); alertAction(Number(b.dataset.id), b.dataset.act, reload); }
});

// =============================================================== overview
export async function overview(root, _arg, ctx) {
  ctx.setTitle(state.me.role === 'assistant' ? 'Monitoring overview' : 'Clinical overview');
  let alive = true;
  async function load() {
    const d = await api('/overview');
    if (!alive) return;
    const k = d.kpi, net = d.network, sim = d.mode === 'simulation';
    const kpi = (label, value, hint, cls = '') => `<div class="kpi ${cls}"><div class="label">${esc(label)}</div><div class="value num">${value}</div><div class="hint">${hint}</div></div>`;
    root.innerHTML = `<div class="stack">
      ${state.me.role === 'assistant' ? '<div class="note">You see the patients assigned to you. You can acknowledge and escalate alerts and add observations; resolving alerts, clinical notes, devices and registration are reserved for doctors.</div>' : ''}
      <div class="kpis">
        ${kpi('Registered patients', k.patients_total, sim ? 'synthetic profiles' : 'in your scope')}
        ${kpi('Connected now', `${k.patients_connected}<small class="muted" style="font-size:14px"> / ${k.patients_total}</small>`, 'valid frames within timeout', k.patients_connected === k.patients_total && k.patients_total ? 'ok' : 'warn')}
        ${kpi('Abnormal readings', k.patients_abnormal, 'latest value beyond a limit', k.patients_abnormal ? 'warn' : 'ok')}
        ${kpi('Critical alerts', k.alerts_critical, `${k.alerts_open} open alerts in total`, k.alerts_critical ? 'alert' : 'ok')}
        ${kpi('Need attention', k.patients_attention, 'patients with an open alert', k.patients_attention ? 'warn' : 'ok')}
        ${kpi('Devices offline', k.devices_offline, 'no valid communication', k.devices_offline ? 'alert' : 'ok')}
        ${kpi('Delivery ratio', net.pdr === null ? '—' : pct(net.pdr), `${net.valid} received · ${net.lost_estimate} lost · ${esc(net.kind)}`)}
        ${kpi('AI predictions (5 min)', k.predictions_5min, d.model.loaded ? `${k.predictions_high_5min} high risk · model ${esc(d.model.version)}` : '<b>model not loaded</b> — threshold alerts still active', d.model.loaded ? '' : 'warn')}
      </div>
      <div class="card"><header><h2>Data flow — from sensor to response</h2><span class="muted small right">Last measurement ${esc(k.last_measurement_ts ? ago(k.last_measurement_ts) : '—')} · source: ${esc(d.data_source)}</span></header><div class="body">
        <div class="flow"><div class="step"><b class="num">${k.patients_connected}</b><span>patient nodes transmitting</span></div>
          <div class="step"><b class="num">${net.valid + net.lost_estimate}</b><span>frames sent over LoRa (est.)</span></div>
          <div class="step"><b class="num">${net.valid}</b><span>validated by the gateway</span></div>
          <div class="step"><b class="num">${k.predictions_5min}</b><span>AI inferences (last 5 min)</span></div>
          <div class="step"><b class="num">${k.alerts_open}</b><span>open alerts</span></div>
          <div class="step"><b class="num">${d.alerts.filter((a) => a.status !== 'new').length}</b><span>being handled by staff</span></div></div></div></div>
      <div class="grid g-main">
        <div class="stack"><div class="row"><h2>Patients</h2>${simTag()}<span class="muted small">live — updates as frames arrive</span></div>
          <div class="tiles" id="tiles">${d.patients.length ? d.patients.map(tile).join('') : '<div class="empty card">No patient in your scope yet.</div>'}</div></div>
        <div class="card"><header><h2>Active alerts</h2><a class="right small" href="#/alerts">All alerts →</a></header>
          <div class="body" id="ovAlerts" style="padding:8px 0 0">${d.alerts.length ? d.alerts.slice(0, 8).map((a) => `<div class="pop-item" style="padding:10px 16px;border-top:1px solid var(--line)">
            <div class="row">${badge(a.severity, a.severity)}<b>${esc(a.label)}</b><span class="small muted right">${esc(ago(a.created_at))}</span></div>
            <div class="small">${a.patient_id ? `<a href="#/patients/${a.patient_id}">${esc(a.patient_name)}</a> · ` : ''}${esc(a.message)}</div>
            <div class="row" style="margin-top:6px">${badge(a.status, a.status)}${['new', 'escalated'].includes(a.status) && can('alerts.acknowledge') ? `<button class="btn sm primary" data-act="acknowledge" data-id="${a.id}">Acknowledge</button>` : ''}<button class="btn sm" data-act="detail" data-id="${a.id}">Details</button></div></div>`).join('') : '<div class="empty">No open alert.</div>'}</div></div>
      </div></div>`;
  }
  const reload = debounce(() => load().catch(() => {}), 3000);
  bindAlertActions(root, reload);
  await load();
  const ageTimer = setInterval(reload, 15000);
  return {
    destroy() { alive = false; clearInterval(ageTimer); },
    onEvent(ev) {
      if (ev.type === 'measurement') {
        const el = $(`.tile[data-pid="${ev.patient_id}"]`, root), d = ev.data;
        if (el) {
          $('.vit', el).innerHTML = vitCell('HR', d.heart_rate, 'bpm', d.heart_rate > 120) + vitCell('SpO₂', d.spo2, '%', d.spo2 !== null && d.spo2 < 92) + vitCell('Temp', d.temperature, '°C', d.temperature >= 38, 1);
          $('[data-age]', el).textContent = 'Updated just now';
          el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
        }
      }
      if (['alert', 'alert_update', 'device', 'simulation', 'prediction'].includes(ev.type)) reload();
    },
  };
}

// =============================================================== patients list + registration
export async function patients(root, _arg, ctx) {
  ctx.setTitle('Patients');
  async function load() {
    const d = await api('/patients');
    root.innerHTML = `<div class="stack"><div class="row"><h2>${d.patients.length} patient(s) in your scope</h2>${simTag()}
        ${can('patients.register') ? '<button class="btn primary right" id="newP">+ Register patient</button>' : ''}</div>
      <div class="card"><div class="tablewrap"><table><thead><tr><th>ID</th><th>Patient</th><th>Status</th><th>HR</th><th>SpO₂</th><th>Temp</th><th>Last measurement</th><th>Device</th><th>Open alerts</th><th>AI risk</th></tr></thead>
      <tbody>${d.patients.map((p) => `<tr><td class="mono">${esc(p.code)}</td><td><a href="#/patients/${p.id}"><b>${esc(p.full_name)}</b></a></td><td>${stateBadge(p.state)}</td>
        <td class="num">${n(p.latest?.heart_rate)}</td><td class="num">${n(p.latest?.spo2)}</td><td class="num">${n(p.latest?.temperature, 1)}</td>
        <td>${p.latest ? `${esc(ago(p.latest.ts))}${p.latest.stale ? ' <span class="tag">stale</span>' : ''}` : '<span class="muted">none</span>'}</td>
        <td>${p.device ? `<span class="mono">#${p.device.id}</span> ${p.device.online ? badge('ok', 'online') : badge('offline', 'offline')}` : '<span class="muted">not paired</span>'}</td>
        <td class="num">${p.open_alerts || '—'}</td><td>${p.prediction?.status === 'ok' ? badge(p.prediction.risk_category === 'high' ? 'prediction' : p.prediction.risk_category, p.prediction.risk_category) : '<span class="muted small">' + esc(p.prediction?.status?.replace('_', ' ') || '—') + '</span>'}</td></tr>`).join('') || '<tr><td colspan="10" class="empty">No patient yet.</td></tr>'}</tbody></table></div></div></div>`;
    $('#newP')?.addEventListener('click', register);
  }
  async function register() {
    const v = await formModal('Register a patient', [
      { name: 'full_name', label: 'Full name', required: true, full: true }, { name: 'date_of_birth', label: 'Date of birth', type: 'date' },
      { name: 'sex', label: 'Sex', type: 'select', options: [['', '—'], ['F', 'Female'], ['M', 'Male'], ['X', 'Other']] },
      { name: 'phone', label: 'Phone' }, { name: 'address', label: 'Address' },
      { name: 'id', label: 'Patient ID (optional)', type: 'number', help: 'Numeric ID carried in LoRa frames (1–65535). Leave empty for the next free ID.' },
    ], { submit: 'Register', intro: state.mode === 'simulation' ? 'You are in <b>simulation mode</b>: this patient is created in the simulation database only.' : 'This patient is created in the <b>hardware</b> database. Pair a physical device afterwards (Devices page).' });
    if (!v) return;
    if (v.id === null) delete v.id;
    try { const r = await api('/patients', { method: 'POST', body: v }); toast('Patient registered', r.patient.code, 'ok'); location.hash = `#/patients/${r.patient.id}`; } catch (e) { fail(e); }
  }
  await load();
  const reload = debounce(() => load().catch(() => {}), 2500);
  return { onEvent(ev) { if (['measurement', 'alert', 'alert_update', 'device'].includes(ev.type)) reload(); } };
}

// =============================================================== patient profile
const RANGES = [['15m', '15 min', 900], ['1h', '1 hour', 3600], ['24h', '24 hours', 86400], ['7d', '7 days', 604800], ['30d', '30 days', 2592000]];

export async function patient(root, arg, ctx) {
  const pid = Number(arg);
  let p = (await api(`/patients/${pid}`)).patient, range = '1h', custom = null, tab = 'alerts', charts = {}, alive = true, zoom = null;
  ctx.setTitle(`${p.full_name} · ${p.code}`);
  const thr = () => p.thresholds;

  function header() {
    const m = p.latest, t = thr();
    const big = (label, v, unit, bad, d, color) => `<div class="kpi ${v === null || v === undefined ? '' : bad ? 'alert' : 'ok'}"><div class="label"><span class="swatch" style="background:var(${color})"></span>${label}</div>
      <div class="value num">${n(v, d)}<small>${unit}</small></div></div>`;
    return `<div class="row"><a href="#/patients" class="btn sm">← Patients</a><h1>${esc(p.full_name)}</h1><span class="mono muted">${esc(p.code)}</span>${stateBadge(p.state)}${simTag()}
        <span class="right row">${can('reports.export') ? `<a class="btn sm" id="expCsv">Export CSV</a><a class="btn sm" id="expPdf">Report PDF</a>` : ''}</span></div>
      <div class="bigvit">${big('Heart rate', m?.heart_rate, 'bpm', m && (m.heart_rate > t.hr_high || m.heart_rate < t.hr_low), 0, '--hr')}
        ${big('SpO₂', m?.spo2, '%', m && m.spo2 !== null && m.spo2 < t.spo2_low, 0, '--spo2')}
        ${big('Temperature', m?.temperature, '°C', m && m.temperature !== null && (m.temperature >= t.temp_high || m.temperature < t.temp_low), 1, '--temp')}
        <div class="kpi ${m?.fall_detected ? 'alert' : ''}"><div class="label">Fall detection</div><div class="value" style="font-size:20px;margin-top:10px">${m ? (m.fall_detected ? 'FALL FLAG' : 'No fall') : '—'}</div>
          <div class="hint">${m ? `Last measurement ${esc(fmtT(m.ts))} (${esc(ago(m.ts))})${m.stale ? ' — <b>stale</b>' : ''}${m.quality !== 'ok' ? ` — quality: ${esc(m.quality)}` : ''}` : 'No measurement received yet'}</div></div></div>
      <div class="row small muted"><span>Device: ${p.device ? `<b class="mono">#${p.device.id}</b> ${esc(p.device.serial)} · ${p.device.online ? 'online' : '<b>offline</b>'} · last frame ${esc(ago(p.device.last_seen_at))}${p.device.last_battery !== null && p.device.last_battery !== undefined ? ` · battery ${p.device.last_battery} %` : ' · battery: not reported by hardware'}${p.device.last_rssi !== null ? ` · RSSI ${n(p.device.last_rssi, 0)} dBm` : ''}` : 'none paired'}</span>
        <span>Doctor: ${esc(p.primary_doctor?.full_name || '—')}</span>
        ${p.prediction ? `<span>AI: ${p.prediction.status === 'ok' ? `${badge(p.prediction.risk_category === 'high' ? 'prediction' : p.prediction.risk_category, 'risk ' + p.prediction.risk_category)} model ${esc(p.prediction.model_version)}` : esc(p.prediction.status.replace('_', ' '))}</span>` : ''}</div>`;
  }

  function frame() {
    root.innerHTML = `<div class="stack"><div id="phead" class="stack">${header()}</div>
      <div class="card"><header><h2>Physiological trends</h2><span class="muted small">drag to zoom · double-click to reset</span>
        <span class="right row"><div class="seg" id="rangeSeg">${RANGES.map((r) => `<button data-r="${r[0]}" class="${range === r[0] ? 'on' : ''}">${r[1]}</button>`).join('')}<button data-r="custom" class="${range === 'custom' ? 'on' : ''}">Custom…</button></div></span></header>
        <div class="body grid g3"><div><div class="legend"><span><span class="swatch" style="background:var(--hr)"></span>Heart rate (bpm)</span></div><div id="cHr"></div></div>
          <div><div class="legend"><span><span class="swatch" style="background:var(--spo2)"></span>SpO₂ (%)</span></div><div id="cSp"></div></div>
          <div><div class="legend"><span><span class="swatch" style="background:var(--temp)"></span>Temperature (°C)</span></div><div id="cTe"></div></div>
          <div class="small muted" id="chartNote" style="grid-column:1/-1"></div></div></div>
      <div class="card"><div class="body"><div class="tabs" id="tabs">${[['alerts', 'Alerts'], ['predictions', 'Predictions', 'predictions.read'], ['history', 'Readings'], ['notes', 'Notes'],
        ['profile', 'Profile & device'], ['caregivers', 'Caregivers', 'caregivers.manage'], ['location', 'Location', 'location.read']]
        .filter((t) => !t[2] || can(t[2])).map((t) => `<button data-t="${t[0]}" class="${tab === t[0] ? 'on' : ''}">${t[1]}</button>`).join('')}</div><div id="tab"></div></div></div></div>`;
    const t = thr();
    charts.hr = new TimeChart($('#cHr'), { color: '--hr', unit: 'bpm', bands: [{ value: t.hr_high, label: `limit ${t.hr_high}`, kind: 'above' }] });
    charts.sp = new TimeChart($('#cSp'), { color: '--spo2', unit: '%', bands: [{ value: t.spo2_low, label: `limit ${t.spo2_low}`, kind: 'below' }] });
    charts.te = new TimeChart($('#cTe'), { color: '--temp', unit: '°C', decimals: 1, bands: [{ value: t.temp_high, label: `limit ${t.temp_high}`, kind: 'above' }] });
    for (const c of Object.values(charts)) c.zoomed = (v) => { zoom = v; for (const o of Object.values(charts)) if (o !== c) o.setView(v); };
    $('#rangeSeg').addEventListener('click', async (e) => {
      const r = e.target.dataset.r; if (!r) return;
      if (r === 'custom') {
        const now = new Date(), iso = (d) => new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
        const v = await formModal('Custom time range', [{ name: 'from', label: 'From (local time)', type: 'datetime-local', value: iso(new Date(now - 6 * 3600e3)), required: true },
          { name: 'to', label: 'To (local time)', type: 'datetime-local', value: iso(now), required: true }], { submit: 'Apply' });
        if (!v) return;
        custom = [new Date(v.from).getTime() / 1000, new Date(v.to).getTime() / 1000];
        if (!(custom[0] < custom[1])) return toast('Invalid range', '"From" must be before "To".', 'warning');
      }
      range = r; $$('#rangeSeg button').forEach((b) => b.classList.toggle('on', b.dataset.r === r)); loadSeries();
    });
    $('#tabs').addEventListener('click', (e) => { if (e.target.dataset.t) { tab = e.target.dataset.t; $$('#tabs button').forEach((b) => b.classList.toggle('on', b === e.target)); loadTab(); } });
    bindExports();
  }
  const q = () => (range === 'custom' ? `from=${custom[0]}&to=${custom[1]}` : `range=${range}`);
  function bindExports() {
    const a = $('#expCsv'), b = $('#expPdf');
    if (a) a.href = `/api/v1/reports/patient/${pid}.csv?${q()}`;
    if (b) b.href = `/api/v1/reports/patient/${pid}.pdf?${q()}`;
  }
  async function loadSeries() {
    const d = await api(`/patients/${pid}/measurements?${q()}`);
    if (!alive) return;
    const dom = [d.from, d.to]; zoom = null;
    charts.hr.view = charts.sp.view = charts.te.view = null;
    charts.hr.marks = d.points.filter((x) => x.fall_detected).map((x) => ({ ts: x.ts, label: 'fall' }));
    charts.hr.set(d.points.map((x) => [x.ts, x.heart_rate]), dom);
    charts.sp.set(d.points.map((x) => [x.ts, x.spo2]), dom);
    charts.te.set(d.points.map((x) => [x.ts, x.temperature]), dom);
    $('#chartNote').textContent = `${d.count} measurement(s) from ${fmtDT(d.from)} to ${fmtDT(d.to)}` + (d.aggregated ? ` — shown as ${d.bucket_s}-second averages` : '') + '. Gaps in the line are missing data (never interpolated as normal).';
    bindExports();
  }
  async function loadTab() {
    const el = $('#tab'); if (!el) return;
    el.innerHTML = '<div class="empty">Loading…</div>';
    try {
      if (tab === 'alerts') {
        const d = await api(`/alerts?status=all&patient_id=${pid}&per_page=100`);
        el.innerHTML = d.alerts.length ? `<div class="tablewrap"><table><thead><tr><th>Severity</th><th>Alert</th><th>Patient</th><th>Category</th><th>Created</th><th>Status</th><th></th></tr></thead><tbody>${d.alerts.map((a) => alertRow(a)).join('')}</tbody></table></div>` : '<div class="empty">No alert recorded for this patient.</div>';
      } else if (tab === 'predictions') {
        const d = await api(`/patients/${pid}/predictions?${q()}`);
        el.innerHTML = `<div class="note">Prediction type <b>threshold_breach_10min</b>: estimated risk that a configured limit is crossed (sustained) within ~10 minutes. Decision support from a model trained on synthetic data — it assists and never replaces clinical judgement.</div>
          <div class="tablewrap" style="margin-top:12px"><table><thead><tr><th>Time</th><th>Risk</th><th>Score</th><th>Est. probability</th><th>Model</th><th>Main contributing factors</th><th>Latency</th></tr></thead><tbody>
          ${d.predictions.map((r) => `<tr><td class="num">${esc(fmtT(r.ts))}</td><td>${r.status === 'ok' ? badge(r.risk_category === 'high' ? 'prediction' : r.risk_category, r.risk_category) : `<span class="muted small">${esc(r.status.replace('_', ' '))}</span>`}</td>
            <td class="num">${n(r.score, 3)}</td><td class="num">${r.probability === null ? '—' : pct(r.probability)}</td><td class="mono small">${esc(r.model_version || '—')}</td>
            <td class="small">${r.explanation.slice(0, 3).map((e) => `${esc(e.label)} = <b>${esc(e.value)}</b> <span class="muted">(${e.contribution > 0 ? '↑' : '↓'} ${esc(e.direction)})</span>`).join('<br>') || '<span class="muted">—</span>'}</td>
            <td class="num small">${n(r.latency_ms, 1)} ms</td></tr>`).join('') || '<tr><td colspan="7" class="empty">No prediction in this period.</td></tr>'}</tbody></table></div>`;
      } else if (tab === 'history') {
        const d = await api(`/patients/${pid}/measurements?${q()}`);
        const rows = d.points.slice(-300).reverse();
        el.innerHTML = `<div class="small muted" style="margin-bottom:8px">Latest ${rows.length} of ${d.count} row(s)${d.aggregated ? ` (averaged per ${d.bucket_s} s)` : ''}. Use “Export CSV” for the complete period.</div><div class="tablewrap"><table><thead><tr><th>Time</th><th>HR</th><th>SpO₂</th><th>Temp</th><th>Fall</th>${d.aggregated ? '<th>Samples</th>' : '<th>Seq</th><th>Quality</th><th>Hops</th><th>RSSI</th>'}</tr></thead><tbody>
          ${rows.map((r) => `<tr><td class="num">${esc(fmtDT(r.ts))}</td><td class="num">${n(r.heart_rate)}</td><td class="num">${n(r.spo2)}</td><td class="num">${n(r.temperature, 1)}</td><td>${r.fall_detected ? badge('critical', 'fall') : ''}</td>
            ${d.aggregated ? `<td class="num">${r.n}</td>` : `<td class="num mono">${r.seq_no}</td><td>${r.quality === 'ok' ? '' : badge('warning', r.quality)}</td><td class="num">${r.hop_count}</td><td class="num">${n(r.rssi, 0)}</td>`}</tr>`).join('') || '<tr><td colspan="9" class="empty">No measurement in this period.</td></tr>'}</tbody></table></div>`;
      } else if (tab === 'notes') {
        const d = await api(`/patients/${pid}/notes`);
        el.innerHTML = `<div class="row">${can('notes.clinical.write') ? '<button class="btn primary sm" data-note="clinical">+ Clinical note</button>' : ''}${can('notes.observation.write') ? '<button class="btn sm" data-note="observation">+ Observation</button>' : ''}
          ${can('notes.clinical.read') ? '' : '<span class="small muted">Clinical notes are visible to doctors only.</span>'}</div>
          <div class="stack" style="margin-top:12px">${d.notes.map((x) => `<div class="note ${x.kind === 'clinical' ? '' : 'warn'}"><div class="row small"><b>${esc(x.author_name)}</b><span class="muted">${esc(x.author_role)} · ${esc(x.kind)}</span><span class="right muted">${esc(fmtDT(x.ts))}</span></div><div style="white-space:pre-wrap">${esc(x.body)}</div></div>`).join('') || '<div class="empty">No note yet.</div>'}</div>`;
        $$('[data-note]', el).forEach((b) => b.addEventListener('click', async () => {
          const v = await formModal(b.dataset.note === 'clinical' ? 'Clinical note' : 'Observation', [{ name: 'body', label: 'Text', type: 'textarea', required: true, full: true }]);
          if (v) try { await api(`/patients/${pid}/notes`, { method: 'POST', body: { kind: b.dataset.note, body: v.body } }); loadTab(); } catch (e) { fail(e); }
        }));
      } else if (tab === 'profile') {
        const t = p.thresholds, ov = p.threshold_overrides;
        el.innerHTML = `<div class="grid g2"><div class="stack"><h3>Identification</h3>
          <table><tbody><tr><td class="muted">Patient ID (LoRa)</td><td class="mono">${p.id} · ${esc(p.code)}</td></tr><tr><td class="muted">Date of birth</td><td>${esc(p.date_of_birth || '—')}</td></tr><tr><td class="muted">Sex</td><td>${esc(p.sex || '—')}</td></tr>
            <tr><td class="muted">Phone</td><td>${esc(p.phone || '—')}</td></tr><tr><td class="muted">Address</td><td>${esc(p.address || '—')}</td></tr><tr><td class="muted">Assigned doctor</td><td>${esc(p.primary_doctor?.full_name || '—')}</td></tr>
            <tr><td class="muted">Care team</td><td>${p.staff.map((s) => `${esc(s.full_name)} <span class="muted small">(${esc(s.role)})</span>${can('patients.assign') ? ` <button class="btn sm" data-unstaff="${s.user_id}">remove</button>` : ''}`).join('<br>') || '—'}</td></tr>
            <tr><td class="muted">Record type</td><td>${p.is_synthetic ? 'Synthetic (simulation)' : 'Real patient record'}</td></tr></tbody></table>
          <div class="row">${can('patients.write') ? '<button class="btn sm" id="editP">Edit profile</button>' : ''}${can('patients.assign') ? '<button class="btn sm" id="addStaff">Assign staff member</button>' : ''}</div></div>
          <div class="stack"><h3>Alert limits for this patient</h3>
          <table><tbody>${[['hr_high', 'Heart rate above', 'bpm'], ['hr_low', 'Heart rate below', 'bpm'], ['spo2_low', 'SpO₂ below', '%'], ['temp_high', 'Temperature at/above', '°C'], ['temp_low', 'Temperature below', '°C']]
            .map(([k, l, u]) => `<tr><td class="muted">${l}</td><td class="num"><b>${t[k]}</b> ${u} ${k in ov ? '<span class="tag">patient-specific</span>' : ''}</td></tr>`).join('')}</tbody></table>
          <div class="small muted">Configurable engineering limits, not universal medical rules.</div>${can('thresholds.write') ? '<button class="btn sm" id="editThr">Configure limits</button>' : ''}
          <h3>Device history</h3><table><tbody>${p.devices.map((d) => `<tr><td class="mono">#${d.id} ${esc(d.serial)}</td><td>${badge(d.status === 'active' ? 'ok' : 'offline', d.status)}</td><td class="small muted">paired ${esc(fmtShort(d.assigned_at))}${d.unassigned_at ? ` → ${esc(fmtShort(d.unassigned_at))}` : ''}</td></tr>`).join('') || '<tr><td class="muted">No device was ever paired. Use the Devices page.</td></tr>'}</tbody></table></div></div>`;
        $('#editP')?.addEventListener('click', async () => {
          const v = await formModal('Edit profile', [{ name: 'full_name', label: 'Full name', value: p.full_name, required: true, full: true }, { name: 'date_of_birth', label: 'Date of birth', type: 'date', value: p.date_of_birth },
            { name: 'sex', label: 'Sex', type: 'select', value: p.sex, options: [['', '—'], ['F', 'Female'], ['M', 'Male'], ['X', 'Other']] }, { name: 'phone', label: 'Phone', value: p.phone }, { name: 'address', label: 'Address', value: p.address, full: true }]);
          if (v) try { p = (await api(`/patients/${pid}`, { method: 'PATCH', body: v })).patient; refreshHead(); loadTab(); } catch (e) { fail(e); }
        });
        $('#editThr')?.addEventListener('click', async () => {
          const v = await formModal('Patient-specific alert limits', [['hr_high', 'Heart rate above (bpm)'], ['hr_low', 'Heart rate below (bpm)'], ['spo2_low', 'SpO₂ below (%)'], ['temp_high', 'Temperature at/above (°C)'], ['temp_low', 'Temperature below (°C)']]
            .map(([k, l]) => ({ name: k, label: l, type: 'number', step: '0.1', value: t[k], required: true })), { intro: 'These limits apply to this patient only and override the defaults.' });
          if (v) try { await api(`/patients/${pid}/thresholds`, { method: 'PUT', body: v }); p = (await api(`/patients/${pid}`)).patient; toast('Limits saved', '', 'ok'); loadTab(); } catch (e) { fail(e); }
        });
        $('#addStaff')?.addEventListener('click', async () => {
          const { staff } = await api('/staff');
          const v = await formModal('Assign staff member', [{ name: 'user_id', label: 'Doctor or assistant', type: 'select', options: staff.filter((s) => s.role !== 'caregiver').map((s) => [s.id, `${s.full_name} (${s.role})`]), full: true }]);
          if (v) try { await api(`/patients/${pid}/staff`, { method: 'POST', body: { user_id: Number(v.user_id) } }); p = (await api(`/patients/${pid}`)).patient; loadTab(); } catch (e) { fail(e); }
        });
        $$('[data-unstaff]', el).forEach((b) => b.addEventListener('click', async () => { try { await api(`/patients/${pid}/staff/${b.dataset.unstaff}`, { method: 'DELETE' }); p = (await api(`/patients/${pid}`)).patient; loadTab(); } catch (e) { fail(e); } }));
      } else if (tab === 'caregivers') {
        el.innerHTML = `<div class="note">A family caregiver sees only this patient's simplified status, and only while an explicit, recorded consent is active. Revoking takes effect immediately.</div>
          <div class="row" style="margin:12px 0"><button class="btn primary sm" id="addCg">+ Authorize a caregiver</button></div>
          <table><thead><tr><th>Caregiver</th><th>Relationship</th><th>Consent given by</th><th>Access</th><th>Granted</th><th>Status</th><th></th></tr></thead><tbody>
          ${p.caregivers.map((c) => `<tr><td><b>${esc(c.full_name)}</b></td><td>${esc(c.relationship || '—')}</td><td>${esc(c.consent_given_by)}</td>
            <td class="small">${c.can_view_vitals ? 'vitals' : 'status only'}${c.can_view_location ? ' · location' : ''}${c.notify ? ' · notifications' : ''}</td><td class="small">${esc(fmtShort(c.granted_at))}${c.expires_at ? `<br>expires ${esc(fmtShort(c.expires_at))}` : ''}</td>
            <td>${c.active ? badge('ok', 'active') : badge('offline', c.revoked_at ? 'revoked' : 'expired')}</td><td>${c.active ? `<button class="btn sm danger" data-revoke="${c.link_id}">Revoke</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="7" class="empty">No caregiver is authorized.</td></tr>'}</tbody></table>`;
        $('#addCg').addEventListener('click', async () => {
          const { staff } = await api('/staff');
          const cgs = staff.filter((s) => s.role === 'caregiver');
          if (!cgs.length) return toast('No caregiver account', 'An administrator must create a caregiver account first.', 'warning');
          const v = await formModal('Authorize a family caregiver', [{ name: 'user_id', label: 'Caregiver account', type: 'select', options: cgs.map((s) => [s.id, `${s.full_name} (${s.username})`]), full: true },
            { name: 'relationship', label: 'Relationship', placeholder: 'e.g. daughter' }, { name: 'consent_given_by', label: 'Consent given by', required: true, help: 'Name of the patient or legal representative' },
            { name: 'days', label: 'Valid for (days, empty = until revoked)', type: 'number' }, { name: 'can_view_vitals', label: 'May see selected vital signs', type: 'checkbox', value: true },
            { name: 'can_view_location', label: 'May see last known location', type: 'checkbox' }, { name: 'notify', label: 'Receives emergency notifications', type: 'checkbox', value: true }], { submit: 'Record consent & authorize' });
          if (!v) return;
          const body = { ...v, user_id: Number(v.user_id), expires_at: v.days ? Date.now() / 1000 + v.days * 86400 : undefined }; delete body.days;
          try { await api(`/patients/${pid}/caregivers`, { method: 'POST', body }); p = (await api(`/patients/${pid}`)).patient; loadTab(); } catch (e) { fail(e); }
        });
        $$('[data-revoke]', el).forEach((b) => b.addEventListener('click', async () => { try { await api(`/patients/${pid}/caregivers/${b.dataset.revoke}`, { method: 'DELETE' }); p = (await api(`/patients/${pid}`)).patient; toast('Access revoked', '', 'ok'); loadTab(); } catch (e) { fail(e); } }));
      } else if (tab === 'location') {
        const l = p.location;
        el.innerHTML = `<div class="stack">${l ? `<div class="note ${l.is_current ? '' : 'warn'}"><b>${l.is_current ? 'Last known location' : 'Old location — not the current position'}</b>: ${l.lat.toFixed(5)}, ${l.lon.toFixed(5)}
            · recorded ${esc(fmtDT(l.ts))} (${esc(ago(l.ts))}) · accuracy ${l.accuracy_m ? `±${Math.round(l.accuracy_m)} m` : 'unknown'} · source: <b>${esc(l.source)}</b>${l.source === 'simulated' ? ' (fictional coordinates)' : ''}</div>
            <a class="btn sm" href="#/map">Show on map</a>` : '<div class="empty">No authorized location is available for this patient.</div>'}
          ${can('location.write') && state.mode === 'hardware' ? `<div class="note">The ESP32 node has no GPS module. A location can be registered manually, with the patient's explicit consent. A future GPS adapter would use the same store (source “gps”).</div>
            <div class="row"><button class="btn sm primary" id="setLoc">Register location manually</button><button class="btn sm danger" id="revLoc">Revoke location consent</button></div>` : ''}</div>`;
        $('#setLoc')?.addEventListener('click', async () => {
          const v = await formModal('Register a location (with consent)', [{ name: 'lat', label: 'Latitude', type: 'number', step: 'any', required: true, placeholder: '35.5047' }, { name: 'lon', label: 'Longitude', type: 'number', step: 'any', required: true, placeholder: '11.0622' },
            { name: 'accuracy_m', label: 'Accuracy (m)', type: 'number' }, { name: 'consent_given_by', label: 'Consent given by', required: true, help: 'Patient or legal representative' }]);
          if (v) try { await api(`/patients/${pid}/location`, { method: 'POST', body: v }); p = (await api(`/patients/${pid}`)).patient; loadTab(); } catch (e) { fail(e); }
        });
        $('#revLoc')?.addEventListener('click', async () => { try { await api(`/patients/${pid}/location-consent`, { method: 'DELETE' }); p = (await api(`/patients/${pid}`)).patient; toast('Location consent revoked', 'The location is no longer shown.', 'ok'); loadTab(); } catch (e) { fail(e); } });
      }
    } catch (e) { el.innerHTML = `<div class="note crit">${esc(e.message)}</div>`; }
  }
  const refreshHead = debounce(async () => { try { p = (await api(`/patients/${pid}`)).patient; if (alive && $('#phead')) { $('#phead').innerHTML = header(); bindExports(); } } catch { /* ignore */ } }, 1500);
  frame();
  bindAlertActions(root, () => { loadTab(); refreshHead(); });
  await loadSeries(); await loadTab();
  return {
    destroy() { alive = false; Object.values(charts).forEach((c) => c.destroy()); },
    onEvent(ev) {
      if (ev.patient_id !== pid) return;
      if (ev.type === 'measurement') {
        const d = ev.data, r = RANGES.find((x) => x[0] === range);
        if (r && r[2] <= 86400 && !zoom) {
          const dom = [Date.now() / 1000 - r[2], Date.now() / 1000];
          charts.hr.push(d.ts, d.heart_rate, dom); charts.sp.push(d.ts, d.spo2, dom); charts.te.push(d.ts, d.temperature, dom);
          if (d.fall_detected) { (charts.hr.marks ||= []).push({ ts: d.ts, label: 'fall' }); }
        }
        p.latest = { ...p.latest, ...d, stale: false, quality: d.quality };
        if ($('#phead')) { $('#phead').innerHTML = header(); bindExports(); }
      }
      if (['alert', 'alert_update', 'device'].includes(ev.type)) { refreshHead(); if (tab === 'alerts') loadTab(); }
      if (ev.type === 'prediction') { refreshHead(); if (tab === 'predictions') loadTab(); }
    },
  };
}

// =============================================================== alert centre
export async function alerts(root, _arg, ctx) {
  ctx.setTitle('Alerts');
  let status = 'open', category = '', page = 1;
  async function load() {
    const d = await api(`/alerts?status=${status}&per_page=50&page=${page}${category ? `&category=${category}` : ''}`);
    root.innerHTML = `<div class="stack"><div class="row"><div class="seg" id="st">${[['open', 'Open'], ['closed', 'Closed'], ['all', 'All']].map((s) => `<button data-s="${s[0]}" class="${status === s[0] ? 'on' : ''}">${s[1]}</button>`).join('')}</div>
        <select class="input" id="cat" style="width:auto;margin:0"><option value="">All categories</option>${['threshold', 'fall', 'predictive', 'device', 'sensor', 'network', 'data_quality'].map((c) => `<option ${category === c ? 'selected' : ''}>${c}</option>`).join('')}</select>
        <span class="muted small">${d.total} alert(s)</span>${can('reports.export') ? '<a class="btn sm right" href="/api/v1/reports/alerts.csv?range=30d">Export CSV (30 days)</a>' : ''}</div>
      <div class="card"><div class="tablewrap"><table><thead><tr><th>Severity</th><th>Alert</th><th>Patient</th><th>Category</th><th>Created</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>${d.alerts.map((a) => alertRow(a)).join('') || '<tr><td colspan="7" class="empty">Nothing here.</td></tr>'}</tbody></table></div></div>
      <div class="row">${page > 1 ? '<button class="btn sm" id="prev">← Newer</button>' : ''}${d.total > page * 50 ? '<button class="btn sm" id="next">Older →</button>' : ''}</div>
      <div class="small muted">Lifecycle: new → acknowledged → assigned → escalated → resolved / false positive. Critical and high alerts that nobody acknowledges are escalated automatically. Repeated triggers of the same condition update the existing alert instead of creating duplicates.</div></div>`;
    $('#st').addEventListener('click', (e) => { if (e.target.dataset.s) { status = e.target.dataset.s; page = 1; load(); } });
    $('#cat').addEventListener('change', (e) => { category = e.target.value; page = 1; load(); });
    $('#prev')?.addEventListener('click', () => { page--; load(); }); $('#next')?.addEventListener('click', () => { page++; load(); });
  }
  const reload = debounce(() => load().catch(() => {}), 1000);
  bindAlertActions(root, reload);
  await load();
  return { onEvent(ev) { if (ev.type === 'alert' || ev.type === 'alert_update') reload(); } };
}

// =============================================================== map (Mahdia)
export async function map(root, _arg, ctx) {
  ctx.setTitle('Patient map — Mahdia');
  const sim = state.mode === 'simulation';
  root.innerHTML = `<div class="stack">
    <div class="note ${sim ? 'warn' : ''}">${sim ? '<b>Demonstration area — fictional coordinates.</b> Positions are generated by the simulation engine around Mahdia and do not correspond to any real person.'
      : 'Only locations registered with the patient’s consent are shown. The patient nodes have no GPS: a marker is the <b>last known</b> registered location, not live tracking.'}</div>
    <div class="card"><header><h2>Mahdia, Tunisia</h2><div class="legend right">${['normal', 'warning', 'critical', 'prediction', 'offline'].map((s) => `<span>${badge(s, STATE_LABEL[s])}</span>`).join('')}</div></header>
      <div class="body" style="padding:12px 0 0"><div id="map"></div></div></div>
    <div class="small muted" id="mapNote"></div></div>`;
  if (!window.L) { $('#map').innerHTML = '<div class="empty">Map library could not be loaded.</div>'; return {}; }
  const m = L.map('map', { zoomControl: true }).setView([35.5047, 11.0622], 14);
  const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(m);
  tiles.on('tileerror', () => { $('#mapNote').textContent = 'Background map tiles are unavailable (no internet access). Markers remain correct; only the background is missing.'; });
  const markers = new Map();
  const iconFor = (p) => L.divIcon({ className: '', html: `<div class="pin ${esc(p.state)}"><span>${esc(p.code.replace('P', ''))}</span></div>`, iconSize: [30, 30], iconAnchor: [15, 30], popupAnchor: [0, -28] });
  const popup = (p) => {
    const l = p.location, v = p.latest;
    return `<b>${esc(p.full_name)}</b> <span class="muted">${esc(p.code)}</span><br>${stateBadge(p.state)}
      <div style="margin:6px 0">${v ? `HR <b>${n(v.heart_rate)}</b> · SpO₂ <b>${n(v.spo2)}</b> · T <b>${n(v.temperature, 1)}</b><br><span class="muted small">measured ${esc(ago(v.ts))}</span>` : '<span class="muted">no measurement</span>'}</div>
      ${p.open_alerts ? `<div class="small"><b>${p.open_alerts} open alert(s):</b> ${esc(p.open_alert_types.join(', '))}</div>` : ''}
      <div class="small muted">${l.is_current ? 'Last known location' : '<b>Old location</b>'} · ${esc(fmtDT(l.ts))} · ${l.accuracy_m ? `±${Math.round(l.accuracy_m)} m` : 'accuracy unknown'} · ${esc(l.source)}</div>
      <div style="margin-top:6px"><a href="#/patients/${p.id}">Open full profile →</a> · <a href="geo:${l.lat.toFixed(5)},${l.lon.toFixed(5)}">Navigate</a></div>`;
  };
  let first = true;
  async function load() {
    const d = await api('/patients');
    const seen = new Set();
    for (const p of d.patients) {
      if (!p.location) continue;
      seen.add(p.id);
      let mk = markers.get(p.id);
      if (!mk) { mk = L.marker([p.location.lat, p.location.lon], { icon: iconFor(p) }).addTo(m); markers.set(p.id, mk); }
      mk.setLatLng([p.location.lat, p.location.lon]).setIcon(iconFor(p)).bindPopup(popup(p)).setZIndexOffset(p.state === 'critical' ? 1000 : 0);
      mk._rpm = p;
    }
    for (const [id, mk] of markers) if (!seen.has(id)) { mk.remove(); markers.delete(id); }
    if (first && markers.size) { m.fitBounds(L.featureGroup([...markers.values()]).getBounds().pad(0.25), { maxZoom: 15 }); first = false; }
    const without = d.patients.length - markers.size;
    if (!$('#mapNote').textContent || without) $('#mapNote').textContent = `${markers.size} patient(s) with an authorized location` + (without ? `; ${without} without location (no consented location registered).` : '.');
  }
  const reload = debounce(() => load().catch(() => {}), 1500);
  await load();
  setTimeout(() => m.invalidateSize(), 50);
  return {
    destroy() { m.remove(); },
    onEvent(ev) {
      if (ev.type === 'location') { const mk = markers.get(ev.patient_id); if (mk) mk.setLatLng([ev.data.lat, ev.data.lon]); else reload(); }
      if (['alert', 'alert_update', 'device', 'measurement'].includes(ev.type)) reload();
      if (ev.type === 'alert' && ev.data.severity === 'critical') {   // geographic alert: highlight and open the marker
        setTimeout(() => { const mk = markers.get(ev.patient_id); if (mk) { m.panTo(mk.getLatLng()); mk.openPopup(); } }, 1800);
      }
    },
  };
}
