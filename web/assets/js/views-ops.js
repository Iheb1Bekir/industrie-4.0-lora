// Operations views: LoRa network / digital twin, devices, AI intelligence, simulation control, reports,
// administration, account, and the simplified family-caregiver home.
import { $, $$, ago, api, badge, can, debounce, esc, fail, fmtDT, fmtShort, fmtT, formModal, icon, infoModal, n, pct, state, toast } from './core.js';
import { barList, histogram, xyChart } from './charts.js';

const kpi = (label, value, hint = '', cls = '') => `<div class="kpi ${cls}"><div class="label">${esc(label)}</div><div class="value num">${value}</div><div class="hint">${hint}</div></div>`;
const kindTag = (k) => `<span class="tag">${esc(k)}</span>`;

// =============================================================== LoRa network + digital twin
export async function network(root, _arg, ctx) {
  ctx.setTitle('LoRa network & digital twin');
  let alive = true, research = null;
  try { research = (await api('/network/research')).runs; } catch { research = []; }
  function topo(d) {
    const W = 900, H = 440, cx = W / 2, cy = H / 2, nodes = d.topology.nodes;
    const pos = { GW: [cx, cy] };
    const relays = nodes.filter((x) => x.type === 'relay'), pats = nodes.filter((x) => x.type === 'patient');
    relays.forEach((r, i) => { const a = Math.PI / 6 + (2 * Math.PI * i) / Math.max(relays.length, 1); pos[r.id] = [cx + 120 * Math.cos(a), cy + 105 * Math.sin(a)]; });
    pats.forEach((p, i) => { const a = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(pats.length, 1); pos[p.id] = [cx + 330 * Math.cos(a), cy + 180 * Math.sin(a)]; });
    let s = `<svg class="topo" viewBox="0 0 ${W} ${H}" role="img" aria-label="Network topology">`;
    for (const l of d.topology.links) { const a = pos[l.from], b = pos[l.to]; if (a && b) s += `<line class="lnk ${l.kind}" data-link="${esc(l.from)}" x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}"/>`; }
    for (const r of relays) s += `<g><rect x="${pos[r.id][0] - 15}" y="${pos[r.id][1] - 15}" width="30" height="30" rx="7" fill="var(--predict)"/><text x="${pos[r.id][0]}" y="${pos[r.id][1] + 4}" text-anchor="middle" style="fill:#fff;font-weight:700">${esc(r.id)}</text>
      <text x="${pos[r.id][0]}" y="${pos[r.id][1] + 30}" text-anchor="middle">fwd ${r.forwarded} · drop ${r.dropped}</text><title>${esc(r.label)}: received ${r.received}, forwarded ${r.forwarded}, dropped ${r.dropped}, duplicates ${r.duplicates}</title></g>`;
    for (const p of pats) {
      const [x, y] = pos[p.id], col = p.online ? 'var(--good)' : 'var(--offline)';
      s += `<a href="#/patients/${p.patient_id}"><circle cx="${x}" cy="${y}" r="13" fill="${col}" stroke="var(--surface)" stroke-width="2"/><text x="${x}" y="${y + 4}" text-anchor="middle" style="fill:#fff;font-weight:700;font-size:9px">${esc(p.label.replace('P', ''))}</text>
        <text x="${x}" y="${y + 28}" text-anchor="middle">${p.online ? (p.rssi !== null ? `${n(p.rssi, 0)} dBm` : 'online') : 'offline'}${p.hop_count ? ` · ${p.hop_count} hop` : ''}</text>
        <title>${esc(p.label)} · device ${p.device_id} · ${p.online ? 'online' : 'offline'} · PDR ${p.pdr === null ? 'n/a' : pct(p.pdr)} · last frame ${esc(ago(p.last_seen_at))}</title></a>`;
    }
    s += `<rect x="${cx - 26}" y="${cy - 20}" width="52" height="40" rx="9" fill="var(--brand)"/><text x="${cx}" y="${cy + 4}" text-anchor="middle" style="fill:var(--brand-ink);font-weight:700">GW</text><text x="${cx}" y="${cy + 36}" text-anchor="middle">Doctor gateway</text></svg>`;
    return s;
  }
  async function load() {
    const d = await api('/network');
    if (!alive) return;
    const c = d.counters, sim = d.kind === 'simulated';
    root.innerHTML = `<div class="stack">
      <div class="note ${sim ? 'warn' : ''}"><b>${sim ? 'SIMULATED network statistics.' : 'MEASURED network statistics.'}</b> ${esc(d.note)} Protocol: ${esc(d.protocol)}.</div>
      <div class="kpis">${kpi('Frames received', c.frames_received ?? 0, `${d.frames_last_minute} valid in the last minute`)}${kpi('Valid & stored', c.valid ?? 0, `${c.direct ?? 0} direct · ${c.relay_assisted ?? 0} relay-assisted`)}
        ${kpi('Lost (sequence gaps)', c.lost_estimate ?? 0, 'estimated from seqNo')}${kpi('Delivery ratio', d.pdr === null ? '—' : pct(d.pdr), 'valid / (valid + lost)', d.pdr !== null && d.pdr < 0.9 ? 'warn' : 'ok')}
        ${kpi('Duplicates', c.duplicates ?? 0, 'dropped by (device, seqNo)')}${kpi('Rejected', (c.auth_failures ?? 0) + (c.unknown_device ?? 0) + (c.rejected ?? 0) + (c.replays ?? 0), `${c.auth_failures ?? 0} auth · ${c.unknown_device ?? 0} unknown · ${c.replays ?? 0} replay`, (c.auth_failures ?? 0) ? 'alert' : '')}
        ${kpi('Corrupted', (c.crc_errors ?? 0) + (c.malformed ?? 0), `${c.crc_errors ?? 0} CRC · ${c.malformed ?? 0} malformed`)}${kpi('Latency', d.latency_ms.avg === null ? '—' : `${n(d.latency_ms.avg, 0)}<small class="muted" style="font-size:13px"> ms</small>`, esc(d.latency_ms.note))}</div>
      <div class="card"><header><h2>Topology — live digital twin</h2>${kindTag(d.kind)}<div class="legend right"><span><span class="swatch" style="background:var(--good)"></span>patient node online</span><span><span class="swatch" style="background:var(--offline)"></span>offline</span><span><span class="swatch" style="background:var(--predict)"></span>relay</span><span>— direct · - - relay path</span></div></header>
        <div class="body" id="topo">${d.topology.nodes.length > 1 ? topo(d) : '<div class="empty">No paired device yet.</div>'}</div></div>
      <div class="grid g-main"><div class="card"><header><h2>Devices</h2>${can('reports.export') ? '<a class="btn sm right" href="/api/v1/reports/network.csv">Export CSV</a>' : ''}</header><div class="tablewrap" style="margin-top:10px"><table>
        <thead><tr><th>Device</th><th>Patient</th><th>Status</th><th>Received</th><th>Lost</th><th>Dup</th><th>PDR</th><th>RSSI</th><th>SNR</th><th>Hops</th><th>Route</th><th>Latency</th><th>Errors</th><th>Last frame</th></tr></thead><tbody>
        ${d.devices.map((v) => `<tr><td class="mono">#${v.id}</td><td>${v.patient_id ? `<a href="#/patients/${v.patient_id}">P${String(v.patient_id).padStart(3, '0')}</a>` : '—'}</td><td>${v.status !== 'active' ? badge('offline', v.status) : v.online ? badge('ok', 'online') : badge('critical', 'offline')}</td>
          <td class="num">${v.rx_count}</td><td class="num">${v.lost_estimate}</td><td class="num">${v.dup_count}</td><td class="num">${v.pdr === null ? '—' : pct(v.pdr)}</td><td class="num">${n(v.last_rssi, 0)}</td><td class="num">${n(v.last_snr, 1)}</td>
          <td class="num">${v.last_hop_count ?? '—'}</td><td>${v.last_routing_mode === 1 ? 'relay' : v.last_routing_mode === 0 ? 'direct' : '—'}</td><td class="num">${v.avg_latency_ms === null ? '—' : n(v.avg_latency_ms, 0) + ' ms'}</td>
          <td class="num small">${v.auth_fail_count + v.replay_count ? `${v.auth_fail_count} auth · ${v.replay_count} replay` : '0'}</td><td class="small">${esc(ago(v.last_seen_at))}</td></tr>`).join('') || '<tr><td colspan="14" class="empty">No device.</td></tr>'}</tbody></table></div></div>
        <div class="card"><header><h2>Network events</h2></header><div class="tablewrap" style="margin-top:10px;max-height:420px"><table><tbody id="nev">
        ${d.events.map(evRow).join('') || '<tr><td class="empty">No event yet.</td></tr>'}</tbody></table></div></div></div>
      <div class="card"><header><h2>Research scenario — OMNeT++ / FLoRa (20 patients · 3 relays · 1 gateway)</h2>${kindTag('offline simulation')}</header><div class="body">
        ${research.length ? research.map((r) => `<div class="stack"><div class="small muted">${esc(r.label)} — ${esc(r.source)} — imported ${esc(r.imported_at)}</div>
          <div class="kpis">${kpi('Patients / relays', `${r.patients} / ${r.relays}`, `${esc(r.sim_time)} simulated`)}${kpi('Generated', r.generated, 'measurements')}${kpi('Valid at doctor', r.doctor_valid, `${r.direct} direct · ${r.relay_assisted} relay-assisted`)}
            ${kpi('Delivery ratio', pct(r.pdr), 'valid / generated')}${kpi('Duplicates dropped', r.duplicates, 'at the doctor gateway')}${kpi('Alerts seen', `${r.alerts.warning + r.alerts.critical}`, `${r.alerts.warning} warning · ${r.alerts.critical} critical · ${r.alerts.fall} fall`)}</div>
          <table><thead><tr><th>Relay</th><th>Received</th><th>Forwarded</th><th>Dropped</th><th>Duplicates</th></tr></thead><tbody>${r.relay_stats.map((x) => `<tr><td>Relay ${x.index + 1}</td><td class="num">${x.received}</td><td class="num">${x.forwarded ?? '—'}</td><td class="num">${x.dropped}</td><td class="num">${x.duplicates}</td></tr>`).join('')}</tbody></table></div>`).join('<hr style="border:0;border-top:1px solid var(--line);margin:16px 0">')
          : '<div class="empty">No OMNeT++ result imported yet. Run <code>python tools/import_omnet_results.py</code> (docs/SIMULATION_GUIDE.md).</div>'}
        <div class="small muted" style="margin-top:10px">These figures come from the separate OMNeT++ 6.5.0 / INET 4.6.0 / FLoRa 1.3.2 project. They are not live and OMNeT++ does not control any physical radio.</div></div></div></div>`;
  }
  const evRow = (e) => `<tr><td class="num small">${esc(fmtT(e.ts))}</td><td>${badge({ rx: 'ok', online: 'ok', lost: 'warning', duplicate: 'warning', offline: 'critical', auth_fail: 'critical', replay: 'critical', crc_error: 'warning', malformed: 'warning', unknown_device: 'critical', rejected: 'critical' }[e.kind] || 'info', e.kind)}</td>
    <td class="small">${e.device_id ? `dev ${e.device_id}` : ''}${e.seq_no ? ` · seq ${e.seq_no}` : ''}${e.hop_count ? ` · ${e.hop_count} hop` : ''}${e.rssi !== null && e.rssi !== undefined ? ` · ${n(e.rssi, 0)} dBm` : ''}${e.latency_ms ? ` · ${n(e.latency_ms, 0)} ms` : ''}${e.detail ? `<div class="muted">${esc(e.detail)}</div>` : ''}</td></tr>`;
  const reload = debounce(() => load().catch(() => {}), 4000);
  await load();
  return {
    destroy() { alive = false; },
    onEvent(ev) {
      if (ev.type === 'network') {
        const tb = $('#nev'); if (tb) { tb.insertAdjacentHTML('afterbegin', evRow(ev.data)); while (tb.rows.length > 80) tb.deleteRow(-1); }
        const ln = $(`[data-link="D${ev.data.device_id}"]`);
        if (ln && ev.data.kind === 'rx') { ln.classList.add('active'); setTimeout(() => ln.classList.remove('active'), 500); }
        reload();
      }
      if (ev.type === 'device' || ev.type === 'simulation') reload();
    },
  };
}

// =============================================================== devices
export async function devices(root, _arg, ctx) {
  ctx.setTitle('Devices');
  function showProvisioning(pr) {
    infoModal('Device provisioning — shown once', `<div class="note crit"><b>${esc(pr.warning)}</b></div>
      <table><tbody><tr><td class="muted">Device ID (sourceId)</td><td class="mono">${pr.device_id}</td></tr><tr><td class="muted">Gateway ID (destinationId)</td><td class="mono">${pr.gateway_id}</td></tr><tr><td class="muted">Key version</td><td class="mono">${pr.key_version}</td></tr></tbody></table>
      <div><h3>Device key (256-bit, hex)</h3><div class="keybox mono">${esc(pr.device_key_hex)}</div></div>
      <div><h3>Serial provisioning command (USB, 115200 baud)</h3><div class="keybox mono">${esc(pr.serial_command)}</div></div>
      <div class="small muted">The server stores only an encrypted copy. The node stores the key in its NVS flash and signs every frame with HMAC-SHA256.</div>`);
  }
  async function load() {
    const [d, pl] = await Promise.all([api('/devices'), api('/patients')]);
    const names = Object.fromEntries(pl.patients.map((p) => [p.id, p]));
    const manage = can('devices.manage');
    root.innerHTML = `<div class="stack"><div class="row"><h2>${d.devices.length} device(s)</h2>${state.mode === 'simulation' ? kindTag('virtual devices') : ''}
        <span class="muted small">A device is <b>online</b> only while valid, authenticated frames arrive (timeout ${Math.round(d.offline_after_s)} s). A database record alone never makes it “connected”.</span>
        ${manage ? '<button class="btn primary right" id="newD">+ Register device</button>' : ''}</div>
      <div class="card"><div class="tablewrap"><table><thead><tr><th>ID</th><th>Serial / label</th><th>Hardware</th><th>Patient</th><th>Status</th><th>Connection</th><th>Last frame</th><th>Battery</th><th>Signal</th><th>Frames</th>${manage ? '<th>Actions</th>' : ''}</tr></thead><tbody>
      ${d.devices.map((v) => `<tr><td class="mono">#${v.id}</td><td><b>${esc(v.serial)}</b><div class="small muted">${esc(v.label || '')}</div></td><td class="small">${esc(v.hw_model || '—')}<div class="muted">${esc(v.radio || '')}</div></td>
        <td>${v.patient_id ? `<a href="#/patients/${v.patient_id}">${esc(names[v.patient_id]?.full_name || 'P' + v.patient_id)}</a>` : '<span class="muted">not paired</span>'}</td>
        <td>${badge(v.status === 'active' ? 'ok' : v.status === 'provisioned' ? 'warning' : 'offline', v.status)}</td><td>${v.status === 'active' ? (v.online ? badge('ok', 'online') : badge('critical', 'offline')) : '—'}</td>
        <td class="small">${esc(ago(v.last_seen_at))}</td><td class="num">${v.last_battery === null ? '<span class="muted small">n/a</span>' : v.last_battery + ' %'}</td>
        <td class="num small">${v.last_rssi === null ? '—' : `${n(v.last_rssi, 0)} dBm / ${n(v.last_snr, 1)} dB`}</td><td class="num small">${v.rx_count} rx · ${v.lost_estimate} lost</td>
        ${manage ? `<td><div class="row" style="gap:5px;flex-wrap:nowrap">${v.status === 'provisioned' || (v.status === 'active' && !v.patient_id) ? `<button class="btn sm primary" data-d="pair" data-id="${v.id}">Pair</button>` : ''}
          ${v.status === 'active' ? `<button class="btn sm" data-d="disable" data-id="${v.id}">Disable</button>` : ''}${v.status === 'disabled' ? `<button class="btn sm" data-d="enable" data-id="${v.id}">Enable</button>` : ''}
          ${v.status !== 'replaced' ? `<button class="btn sm" data-d="rotate-key" data-id="${v.id}">New key</button><button class="btn sm danger" data-d="replace" data-id="${v.id}">Retire</button>` : ''}</div></td>` : ''}</tr>`).join('') || '<tr><td colspan="11" class="empty">No device registered.</td></tr>'}</tbody></table></div></div>
      <div class="note">Enrollment: 1) register the device → a unique 256-bit key is generated; 2) enter it on the ESP32 over USB serial; 3) pair the device with a patient. To replace a broken node: <i>Retire</i> the old device, register the new one and pair it with the same patient — the history stays with the patient.</div></div>`;
    $('#newD')?.addEventListener('click', async () => {
      const v = await formModal('Register a device', [{ name: 'serial', label: 'Serial / MAC address', required: true, placeholder: 'e.g. ESP32-A4:CF:12:9B:20:10' }, { name: 'label', label: 'Label', placeholder: 'Patient node 1' },
        { name: 'hw_model', label: 'Board', placeholder: 'ESP32-S3 DevKitC-1' }, { name: 'radio', label: 'LoRa radio', placeholder: 'SX1276 868 MHz' },
        { name: 'patient_id', label: 'Pair with patient now (optional)', type: 'select', options: [['', '— later —'], ...pl.patients.filter((p) => !p.device || p.device.status !== 'active').map((p) => [p.id, `${p.code} ${p.full_name}`])], full: true }],
      { submit: 'Register', intro: state.mode === 'simulation' ? 'Simulation mode: this creates a <b>virtual</b> device in the simulation database.' : 'Hardware mode: this creates the identity of a <b>physical</b> ESP32 node.' });
      if (!v) return;
      const body = { ...v }; if (body.patient_id === '') delete body.patient_id; else body.patient_id = Number(body.patient_id);
      try { const r = await api('/devices', { method: 'POST', body }); await load(); showProvisioning(r.provisioning); } catch (e) { fail(e); }
    });
    $$('[data-d]', root).forEach((b) => b.addEventListener('click', async () => {
      const act = b.dataset.d, id = b.dataset.id;
      try {
        let body = {};
        if (act === 'pair') {
          const free = pl.patients.filter((p) => !p.device || p.device.status !== 'active');
          if (!free.length) return toast('No patient available', 'Every patient already has an active device.', 'warning');
          const v = await formModal(`Pair device #${id}`, [{ name: 'patient_id', label: 'Patient', type: 'select', options: free.map((p) => [p.id, `${p.code} ${p.full_name}`]), full: true }], { submit: 'Pair' });
          if (!v) return; body = { patient_id: Number(v.patient_id) };
        }
        const r = await api(`/devices/${id}/${act}`, { method: 'POST', body });
        toast('Device updated', `${act} — device #${id}`, 'ok');
        await load();
        if (r.provisioning) showProvisioning(r.provisioning);
      } catch (e) { fail(e); }
    }));
  }
  const reload = debounce(() => load().catch(() => {}), 5000);
  await load();
  return { onEvent(ev) { if (ev.type === 'device') reload(); } };
}

// =============================================================== AI intelligence
export async function ai(root, _arg, ctx) {
  ctx.setTitle('AI intelligence');
  let alive = true;
  async function load() {
    const [d, ph] = await Promise.all([api('/ml/model'), api('/ml/predictions')]);
    if (!alive) return;
    const rt = d.runtime, meta = d.metadata, mt = d.metrics, cv = d.curves;
    if (!meta || !mt) {
      root.innerHTML = `<div class="stack"><div class="note crit"><b>No prediction model is deployed.</b> ${esc(rt.error || '')}<br>Monitoring continues: measurements are stored and threshold alerts work independently of the model.
        Train and activate a model with <code>python ml/train.py</code> (docs/ML_PIPELINE.md).</div></div>`; return;
    }
    const sel = mt.models[meta.model_name], t = sel.test, cm = t.confusion_matrix, ds = meta.dataset, ev = t.events;
    const m4 = (v) => (v * 100).toFixed(1) + ' %';
    root.innerHTML = `<div class="stack">
      <div class="note warn"><b>Read this first.</b> ${esc(d.disclaimer)} The model is an early-warning aid; clinicians decide.</div>
      <div class="kpis">${kpi('Active model', `<span style="font-size:17px">${esc(meta.model_name.replaceAll('_', ' '))}</span>`, `version ${esc(meta.version)}`)}
        ${kpi('Deployment', rt.loaded ? 'Loaded' : 'Not loaded', `health: ${esc(rt.health)}${rt.sklearn_version_match === false ? ' · library version differs from training!' : ''}`, rt.health === 'ok' ? 'ok' : 'warn')}
        ${kpi('Trained', `<span style="font-size:17px">${esc(meta.trained_at.slice(0, 10))}</span>`, `${esc(meta.trained_at.slice(11, 19))} UTC`)}
        ${kpi('Dataset', `<span style="font-size:17px">${esc(ds.version)}</span>`, `synthetic · seed ${ds.seed} · split by patient`)}
        ${kpi('Samples train / val / test', `<span style="font-size:17px">${ds.samples.train.toLocaleString()} / ${ds.samples.val.toLocaleString()} / ${ds.samples.test.toLocaleString()}</span>`, `patients ${ds.patients.train} / ${ds.patients.val} / ${ds.patients.test}`)}
        ${kpi('Inference latency', rt.latency_ms.p50 === null ? '—' : `${n(rt.latency_ms.p50, 1)}<small class="muted" style="font-size:13px"> ms</small>`, rt.latency_ms.n ? `p95 ${n(rt.latency_ms.p95, 1)} ms · ${rt.predictions} live predictions on this host` : `no live prediction yet · ${sel.inference_latency_ms} ms on the training PC`)}</div>
      <div class="card"><header><h2>What the model predicts</h2></header><div class="body stack"><div>${esc(meta.target)}</div>
        <div class="small muted">Decision threshold (high risk): score ≥ ${n(meta.thresholds.high, 3)} — ${esc(meta.threshold_policy)}. ${esc(meta.selection_rule)}.</div></div></div>
      <div class="card"><header><h2>Held-out test set performance</h2><span class="muted small right">${t.n.toLocaleString()} rows · ${t.positives} positive (${m4(t.prevalence)})</span></header><div class="body stack">
        <div class="kpis">${kpi('Accuracy', m4(t.accuracy), 'dominated by the negative class')}${kpi('Precision', m4(t.precision), 'warnings that were followed by an event')}
          ${kpi('Recall (sensitivity)', m4(t.recall), 'pre-event rows flagged')}${kpi('Specificity', m4(t.specificity), `false-positive rate ${m4(t.fpr)}`)}${kpi('F1-score', n(t.f1, 3), `false-negative rate ${m4(t.fnr)}`)}
          ${kpi('ROC-AUC', n(t.roc_auc, 3), '')}${kpi('PR-AUC', n(t.pr_auc, 3), `chance level ${n(t.prevalence, 3)}`)}${kpi('Calibration (ECE)', n(t.ece_calibrated, 4), `Brier ${n(t.brier_calibrated, 4)} after isotonic calibration`)}</div>
        <div class="note"><b>Episode view:</b> ${ev.detected} of ${ev.events} threshold-crossing episodes in the test set were flagged in advance (${ev.event_recall === null ? '—' : m4(ev.event_recall)}),
          median lead time ${ev.median_lead_s === null ? '—' : Math.round(ev.median_lead_s / 60 * 10) / 10 + ' min'}; ${ev.false_alarm_episodes} false-alarm episodes = ${ev.false_alarms_per_patient_day} per patient-day.</div></div></div>
      <div class="grid g3">
        <div class="card"><header><h2>Confusion matrix</h2></header><div class="body"><div class="cm">
          <div></div><div class="hd">predicted: no event</div><div class="hd">predicted: event</div>
          <div class="hd">actual: no event</div><div class="cell s-ok"><b class="num">${cm.tn.toLocaleString()}</b>true negatives</div><div class="cell s-warning"><b class="num">${cm.fp.toLocaleString()}</b>false positives</div>
          <div class="hd">actual: event</div><div class="cell s-critical"><b class="num">${cm.fn.toLocaleString()}</b>false negatives</div><div class="cell s-ok"><b class="num">${cm.tp.toLocaleString()}</b>true positives</div></div>
          <div class="small muted" style="margin-top:10px">Counts on the test set at the frozen validation threshold.</div></div></div>
        <div class="card"><header><h2>ROC curve</h2><span class="muted small right">AUC ${n(t.roc_auc, 3)}</span></header><div class="body" id="roc"></div></div>
        <div class="card"><header><h2>Precision–recall curve</h2><span class="muted small right">AUC ${n(t.pr_auc, 3)}</span></header><div class="body" id="prc"></div></div></div>
      <div class="grid g2">
        <div class="card"><header><h2>Feature importance</h2><span class="muted small right">drop in PR-AUC when shuffled</span></header><div class="body" id="fi"></div></div>
        <div class="card"><header><h2>Score distribution by true class</h2></header><div class="body"><div id="hist"></div><div class="small muted">Dashed line: decision threshold. Each panel has its own vertical scale.</div></div></div></div>
      <div class="grid g2">
        <div class="card"><header><h2>Calibration</h2><span class="muted small right">isotonic, test set</span></header><div class="body" id="cal"></div></div>
        <div class="card"><header><h2>Model comparison — same protocol</h2></header><div class="tablewrap" style="margin-top:10px"><table><thead><tr><th>Model</th><th>PR-AUC</th><th>ROC-AUC</th><th>Precision</th><th>Recall</th><th>F1</th><th>Episodes</th><th>Latency</th></tr></thead><tbody>
          ${Object.entries(mt.models).map(([name, m]) => `<tr><td>${name === meta.model_name ? `<b>${esc(name.replaceAll('_', ' '))}</b> ${badge('ok', 'selected')}` : esc(name.replaceAll('_', ' '))}${m.deployable ? '' : ' <span class="muted small">(baseline)</span>'}</td>
            <td class="num">${n(m.test.pr_auc, 3)}</td><td class="num">${n(m.test.roc_auc, 3)}</td><td class="num">${m4(m.test.precision)}</td><td class="num">${m4(m.test.recall)}</td><td class="num">${n(m.test.f1, 3)}</td>
            <td class="num">${m.test.events.detected}/${m.test.events.events}</td><td class="num">${m.inference_latency_ms ? m.inference_latency_ms + ' ms' : '—'}</td></tr>`).join('')}</tbody></table></div></div></div>
      <div class="card"><header><h2>Live prediction history</h2>${state.mode === 'simulation' ? kindTag('simulation') : ''}<span class="muted small right">${Object.entries(ph.distribution).map(([k, v]) => `${esc(k.replace('_', ' '))}: ${v}`).join(' · ') || 'no prediction yet'}</span></header>
        <div class="tablewrap" style="margin-top:10px;max-height:380px"><table><thead><tr><th>Time</th><th>Patient</th><th>Risk</th><th>Score</th><th>Est. prob.</th><th>Why (top factors)</th><th>Latency</th></tr></thead><tbody>
        ${ph.predictions.slice(0, 60).map((r) => `<tr><td class="num small">${esc(fmtT(r.ts))}</td><td><a href="#/patients/${r.patient_id}">${esc(r.patient_code)}</a></td>
          <td>${r.status === 'ok' ? badge(r.risk_category === 'high' ? 'prediction' : r.risk_category, r.risk_category) : `<span class="muted small">${esc(r.status.replace('_', ' '))}</span>`}</td><td class="num">${n(r.score, 3)}</td><td class="num">${r.probability === null ? '—' : pct(r.probability)}</td>
          <td class="small">${r.explanation.slice(0, 2).map((e) => `${esc(e.label)} = <b>${esc(e.value)}</b> (${e.contribution > 0 ? '↑' : '↓'})`).join(' · ')}</td><td class="num small">${n(r.latency_ms, 1)} ms</td></tr>`).join('') || '<tr><td colspan="7" class="empty">No prediction yet — start the simulation or connect a device.</td></tr>'}</tbody></table></div></div>
      <div class="card"><header><h2>Versions & deployment</h2>${can('reports.export') ? '<a class="btn sm right" href="/api/v1/reports/model.pdf">Evaluation report (PDF)</a>' : ''}</header><div class="body stack">
        <table><thead><tr><th>Version</th><th>Model</th><th>Trained</th><th>Dataset</th><th>Status</th><th></th></tr></thead><tbody>${d.versions.map((v) => `<tr><td class="mono">${esc(v.version)}</td><td>${esc(v.model_name)}</td><td class="small">${esc(v.trained_at)}</td><td class="small">${esc(v.dataset_version)}</td>
          <td>${v.active ? badge('ok', 'active') : badge('offline', 'available')}</td><td>${!v.active && can('ml.deploy') ? `<button class="btn sm" data-deploy="${esc(v.version)}">Activate</button>` : ''}</td></tr>`).join('')}</tbody></table>
        <div class="row">${can('ml.deploy') ? '<button class="btn sm" id="rollback">Roll back to previous version</button>' : ''}<span class="small muted">Artifact SHA-256 ${esc(meta.artifact_sha256.slice(0, 16))}… · scikit-learn ${esc(meta.dependencies['scikit-learn'])} · features ${esc(meta.feature_version)} (${meta.features.length})</span></div></div></div></div>`;
    xyChart($('#roc'), { curves: [{ color: '--hr', points: cv.roc }], xlabel: 'False-positive rate', ylabel: 'True-positive rate', diagonal: true });
    xyChart($('#prc'), { curves: [{ color: '--hr', points: cv.pr }], xlabel: 'Recall', ylabel: 'Precision' });
    xyChart($('#cal'), { curves: [{ color: '--hr', points: cv.calibration.map((b) => [b.mean_predicted, b.observed_rate, b.n]) }], xlabel: 'Mean estimated probability', ylabel: 'Observed event rate', diagonal: true, points: true });
    barList($('#fi'), cv.feature_importance.slice(0, 10).map((f) => ({ label: f.label, value: f.importance, title: f.feature })));
    histogram($('#hist'), cv.score_histogram.edges, [{ label: 'No event within 10 min', counts: cv.score_histogram.negative, color: '--hr', threshold: meta.thresholds.high },
      { label: 'Event within 10 min', counts: cv.score_histogram.positive, color: '--temp', threshold: meta.thresholds.high }]);
    const deploy = async (body) => { try { await api('/ml/deploy', { method: 'POST', body }); toast('Model switched', '', 'ok'); load(); } catch (e) { fail(e); } };
    $$('[data-deploy]', root).forEach((b) => b.addEventListener('click', () => deploy({ version: b.dataset.deploy })));
    $('#rollback')?.addEventListener('click', () => deploy({ rollback: true }));
  }
  await load();
  const reload = debounce(() => load().catch(() => {}), 20000);
  return { destroy() { alive = false; }, onEvent(ev) { if (ev.type === 'prediction') reload(); } };
}

// =============================================================== simulation control
export async function simulation(root, _arg, ctx) {
  ctx.setTitle('Simulation & operating mode');
  let alive = true;
  async function load() {
    const { simulation: s, mode } = await api('/simulation');
    if (!alive) return;
    const cfg = s.config || {}, st = s.stats || {}, running = s.state === 'running', paused = s.state === 'paused', stopped = s.state === 'stopped';
    root.innerHTML = `<div class="stack">
      <div class="card"><header><h2>Operating mode</h2></header><div class="body stack">
        <div class="row"><div class="seg" id="modeSeg"><button data-m="simulation" class="${mode === 'simulation' ? 'on' : ''}">Simulation</button><button data-m="hardware" class="${mode === 'hardware' ? 'on' : ''}">Real hardware</button></div>
          <span class="muted small">Simulation and hardware data live in two separate databases. Switching mode changes what every page shows; it never copies or deletes data. Switching to hardware stops the simulation engine.</span></div></div></div>
      ${mode !== 'simulation' ? '<div class="note">The platform is in <b>hardware mode</b>. The simulation engine is stopped and cannot inject data. Switch to simulation mode to run scenarios.</div>' : `
      <div class="grid g-main">
        <div class="card"><header><h2>Scenario</h2><span class="right">${badge(running ? 'ok' : paused ? 'warning' : 'offline', s.state)}</span></header><div class="body stack">
          <div class="formgrid">
            <label class="f full">Scenario<select id="sc" ${stopped ? '' : 'disabled'}>${Object.entries(s.scenarios).map(([k, v]) => `<option value="${k}" ${cfg.scenario === k ? 'selected' : ''}>${k} — ${esc(v)}</option>`).join('')}</select></label>
            <label class="f">Patients<select id="pc" ${stopped ? '' : 'disabled'}>${[3, 5, 8, 12, 20].map((v) => `<option ${(cfg.patient_count ?? 3) === v ? 'selected' : ''}>${v}</option>`).join('')}</select><span class="small muted">3 = current physical setup · 20 = research topology</span></label>
            <label class="f">Speed<select id="sp" ${stopped ? '' : 'disabled'}>${[1, 2, 4, 10, 30].map((v) => `<option value="${v}" ${(cfg.speed ?? 4) === v ? 'selected' : ''}>×${v}</option>`).join('')}</select><span class="small muted">compresses physiology and sampling; timestamps stay real</span></label>
            <label class="f">Sampling interval<select id="iv" ${stopped ? '' : 'disabled'}>${[10, 30, 60].map((v) => `<option value="${v}" ${(cfg.interval_s ?? 30) === v ? 'selected' : ''}>${v} s</option>`).join('')}</select></label>
            <label class="f">Relays<select id="rl" ${stopped ? '' : 'disabled'}>${[1, 2, 3].map((v) => `<option ${(cfg.relay_count ?? 3) === v ? 'selected' : ''}>${v}</option>`).join('')}</select></label></div>
          <div class="row">${stopped ? '<button class="btn primary" data-sim="start">▶ Start simulation</button>' : ''}${running ? '<button class="btn" data-sim="pause">⏸ Pause</button>' : ''}${paused ? '<button class="btn primary" data-sim="resume">▶ Resume</button>' : ''}
            ${!stopped ? '<button class="btn danger" data-sim="stop">⏹ Stop</button>' : ''}${stopped ? '<button class="btn" data-sim="reset">↺ Reset scenario data</button>' : ''}</div>
          <div class="small muted">Start wipes the <b>simulation</b> database only and seeds fictional patients with virtual devices. Every frame is built, signed and validated exactly like a real LoRa frame, then goes through the same ingestion, prediction and alert pipeline.</div></div></div>
        <div class="card"><header><h2>Engine statistics</h2><span class="muted small right">session ${s.session_id ?? '—'} · sim time ${Math.round(s.sim_time_s / 60)} min</span></header><div class="body">
          <table><tbody>${[['generated', 'Measurements generated'], ['transmitted', 'Frames transmitted'], ['relay_forwards', 'Relay forwards'], ['lost_radio', 'Lost — below radio sensitivity'], ['lost_injected', 'Lost — random / injected'],
            ['duplicated', 'Duplicated in the air'], ['delayed', 'Delayed'], ['delivered_to_gateway', 'Delivered to the gateway']].map(([k, l]) => `<tr><td>${l}</td><td class="num"><b>${st[k] ?? 0}</b></td></tr>`).join('')}</tbody></table></div></div></div>
      <div class="card"><header><h2>Simulated patients — trigger an event</h2></header><div class="tablewrap" style="margin-top:10px"><table><thead><tr><th>Patient</th><th>Device</th><th>Route</th><th>Sent</th><th>Stored</th><th>Active effects</th><th>Trigger</th></tr></thead><tbody>
        ${(s.patients || []).map((p) => `<tr><td><a href="#/patients/${p.patient_id}">P${String(p.patient_id).padStart(3, '0')}</a></td><td class="mono">#${p.device_id} ${p.connected ? '' : badge('critical', 'disconnected')}</td><td>${esc(p.route)}${p.hops ? ` · ${p.hops} hop(s)` : ''}</td>
          <td class="num">${p.sent}</td><td class="num">${p.delivered}</td><td class="small">${esc(p.effects.join(', ') || '—')}</td>
          <td><div class="row" style="gap:5px"><select class="input" style="width:auto;margin:0" data-evsel="${p.patient_id}" ${stopped ? 'disabled' : ''}>${s.events.map((e) => `<option>${e}</option>`).join('')}</select><button class="btn sm" data-ev="${p.patient_id}" ${stopped ? 'disabled' : ''}>Trigger</button></div></td></tr>`).join('') || '<tr><td colspan="7" class="empty">Start a simulation to create virtual patients.</td></tr>'}</tbody></table></div></div>
      <div class="note">Follow the result live on <a href="#/overview">Overview</a>, <a href="#/alerts">Alerts</a>, <a href="#/map">Map</a>, <a href="#/network">LoRa network</a> and <a href="#/ai">AI intelligence</a>.</div>`}</div>`;
    $('#modeSeg').addEventListener('click', async (e) => {
      const m = e.target.dataset.m; if (!m || m === mode) return;
      try { await api('/system/mode', { method: 'POST', body: { mode: m } }); toast('Operating mode', `Now in ${m} mode`, 'ok'); } catch (err) { fail(err); }
    });
    $$('[data-sim]', root).forEach((b) => b.addEventListener('click', async () => {
      const body = { scenario: $('#sc').value, patient_count: Number($('#pc').value), speed: Number($('#sp').value), interval_s: Number($('#iv').value), relay_count: Number($('#rl').value) };
      try { await api(`/simulation/${b.dataset.sim}`, { method: 'POST', body }); load(); } catch (e) { fail(e); }
    }));
    $$('[data-ev]', root).forEach((b) => b.addEventListener('click', async () => {
      const pid = Number(b.dataset.ev);
      try { await api('/simulation/event', { method: 'POST', body: { patient_id: pid, event: $(`[data-evsel="${pid}"]`).value } }); toast('Event triggered', `P${String(pid).padStart(3, '0')}`, 'ok'); load(); } catch (e) { fail(e); }
    }));
  }
  await load();
  const timer = setInterval(() => { if (!document.activeElement || !['SELECT'].includes(document.activeElement.tagName)) load().catch(() => {}); }, 5000);
  return { destroy() { alive = false; clearInterval(timer); }, onEvent(ev) { if (ev.type === 'simulation' || ev.type === 'system') load().catch(() => {}); } };
}

// =============================================================== reports
export async function reports(root, _arg, ctx) {
  ctx.setTitle('Reports & export');
  const { patients } = await api('/patients');
  root.innerHTML = `<div class="stack"><div class="note">Every export is recorded in the audit trail. Files carry the data source (${state.mode === 'simulation' ? '<b>SIMULATION</b>' : 'hardware'}), the reporting period, the generation time and a disclaimer.</div>
    <div class="grid g2">
      <div class="card"><header><h2>Patient monitoring report</h2></header><div class="body stack"><div class="formgrid">
        <label class="f">Patient<select id="rp">${patients.map((p) => `<option value="${p.id}">${esc(p.code)} — ${esc(p.full_name)}</option>`).join('')}</select></label>
        <label class="f">Period<select id="rr"><option value="1h">Last hour</option><option value="24h" selected>Last 24 hours</option><option value="7d">Last 7 days</option><option value="30d">Last 30 days</option></select></label></div>
        <div class="row"><a class="btn primary" id="rPdf">Report (PDF)</a><a class="btn" id="rCsv">Measurement history (CSV)</a></div>
        <div class="small muted">PDF: measurement summary, alerts, prediction information. CSV: every stored measurement of the period.</div></div></div>
      <div class="card"><header><h2>Operational reports</h2></header><div class="body stack">
        <div class="row"><a class="btn" href="/api/v1/reports/alerts.csv?range=30d">Alert report — 30 days (CSV)</a>${can('network.read') ? '<a class="btn" href="/api/v1/reports/network.csv">Device connectivity & network performance (CSV)</a>' : ''}
          ${can('ml.read') ? '<a class="btn" href="/api/v1/reports/model.pdf">Model evaluation (PDF)</a>' : ''}</div>
        <div class="small muted">Prediction history per patient is included in the patient PDF and available on the patient profile.</div></div></div></div></div>`;
  const link = () => { const id = $('#rp').value, r = $('#rr').value; if (!id) return; $('#rPdf').href = `/api/v1/reports/patient/${id}.pdf?range=${r}`; $('#rCsv').href = `/api/v1/reports/patient/${id}.csv?range=${r}`; };
  $('#rp').addEventListener('change', link); $('#rr').addEventListener('change', link); link();
  return {};
}

// =============================================================== administration
export async function admin(root, _arg, ctx) {
  ctx.setTitle('Administration');
  let tab = 'users';
  const bytes = (b) => (b > 1e9 ? (b / 1e9).toFixed(1) + ' GB' : b > 1e6 ? (b / 1e6).toFixed(1) + ' MB' : Math.round(b / 1e3) + ' kB');
  async function load() {
    root.innerHTML = `<div class="card"><div class="body"><div class="tabs" id="at">${[['users', 'Users & roles'], ['health', 'System health'], ['limits', 'Default alert limits'], ['audit', 'Audit trail']].map((t) => `<button data-t="${t[0]}" class="${tab === t[0] ? 'on' : ''}">${t[1]}</button>`).join('')}</div><div id="ab"></div></div></div>`;
    $('#at').addEventListener('click', (e) => { if (e.target.dataset.t) { tab = e.target.dataset.t; load(); } });
    const el = $('#ab');
    if (tab === 'users') {
      const { users } = await api('/users');
      el.innerHTML = `<div class="row" style="margin-bottom:12px"><button class="btn primary sm" id="nu">+ Create account</button><span class="small muted">New accounts must change their password at first sign-in. Demo accounts are refused in production.</span></div>
        <table><thead><tr><th>User</th><th>Role</th><th>2FA</th><th>Last sign-in</th><th>Status</th><th></th></tr></thead><tbody>${users.map((u) => `<tr><td><b>${esc(u.full_name)}</b><div class="small muted mono">${esc(u.username)}</div></td>
          <td>${esc(u.role)}${u.is_admin ? ' · admin' : ''}${u.is_demo ? ' <span class="tag">demo</span>' : ''}</td><td>${u.totp_enabled ? badge('ok', 'on') : '<span class="muted small">off</span>'}</td><td class="small">${esc(u.last_login_at ? fmtShort(u.last_login_at) : 'never')}</td>
          <td>${u.is_active ? badge('ok', 'active') : badge('offline', 'disabled')}</td><td><div class="row" style="gap:5px"><button class="btn sm" data-u="reset" data-id="${u.id}">Reset token</button><button class="btn sm" data-u="unlock" data-id="${u.id}">Unlock</button>
          <button class="btn sm ${u.is_active ? 'danger' : ''}" data-u="${u.is_active ? 'disable' : 'enable'}" data-id="${u.id}">${u.is_active ? 'Disable' : 'Enable'}</button></div></td></tr>`).join('')}</tbody></table>`;
      $('#nu').addEventListener('click', async () => {
        const v = await formModal('Create account', [{ name: 'username', label: 'Username', required: true }, { name: 'full_name', label: 'Full name', required: true },
          { name: 'role', label: 'Role', type: 'select', options: [['doctor', 'Doctor'], ['assistant', 'Medical assistant'], ['caregiver', 'Family caregiver']] }, { name: 'is_admin', label: 'Administrator (doctor only)', type: 'checkbox' },
          { name: 'email', label: 'E-mail' }, { name: 'phone', label: 'Phone' }, { name: 'password', label: 'Initial password (12+ chars, mixed)', type: 'password', required: true, full: true }], { submit: 'Create' });
        if (v) try { await api('/users', { method: 'POST', body: v }); toast('Account created', v.username, 'ok'); load(); } catch (e) { fail(e); }
      });
      $$('[data-u]', el).forEach((b) => b.addEventListener('click', async () => {
        try {
          if (b.dataset.u === 'reset') { const r = await api(`/users/${b.dataset.id}/reset-token`, { method: 'POST', body: {} });
            infoModal('One-time password reset token', `<div class="note warn">${esc(r.note)} Valid for ${Math.round(r.expires_in_s / 60)} minutes.</div><div class="keybox mono">${esc(r.reset_token)}</div>`); return; }
          const body = b.dataset.u === 'unlock' ? { unlock: true } : { is_active: b.dataset.u === 'enable' };
          await api(`/users/${b.dataset.id}`, { method: 'PATCH', body }); load();
        } catch (e) { fail(e); }
      }));
    } else if (tab === 'health') {
      const h = await api('/system/health'), db = h.databases;
      el.innerHTML = `<div class="kpis">${kpi('Uptime', `${Math.floor(h.uptime_s / 3600)} h ${Math.floor((h.uptime_s % 3600) / 60)} min`, esc(h.platform))}${kpi('CPU', `${h.cpu_count} cores`, h.load_avg ? `load ${h.load_avg.map((x) => x.toFixed(2)).join(' / ')}` : `${esc(h.machine)} · load average not available on this OS`)}
        ${kpi('Process memory', h.process_rss_bytes ? bytes(h.process_rss_bytes) : 'n/a', h.process_rss_bytes ? 'resident set' : 'reported on Linux / Raspberry Pi only')}${kpi('Disk free', bytes(h.disk_free_bytes), `of ${bytes(h.disk_total_bytes)}`)}
        ${kpi('Live subscribers', h.realtime.subscribers, `${h.realtime.published} events · ${h.realtime.dropped} dropped`)}${kpi('Audit chain', h.audit_chain.ok ? 'Intact' : 'BROKEN', `${h.audit_chain.entries} entries`, h.audit_chain.ok ? 'ok' : 'alert')}
        ${kpi('Model', h.model.loaded ? 'Loaded' : 'Unavailable', esc(h.model.model_version || h.model.error || ''), h.model.loaded ? 'ok' : 'warn')}
        ${kpi('Hardware gateway', h.hardware_gateway.ingest_token_configured ? 'Enabled' : 'Disabled', h.hardware_gateway.ingest_token_configured ? `${h.hardware_gateway.online_devices} physical device(s) online · last event ${esc(ago(h.hardware_gateway.last_frame_at))}` : 'RPM_GATEWAY_INGEST_TOKEN not set', h.hardware_gateway.ingest_token_configured ? '' : 'warn')}</div>
        <table style="margin-top:14px"><thead><tr><th>Database</th><th>Size</th><th>Schema</th><th>Measurements</th></tr></thead><tbody>
          <tr><td>System (users, sessions, audit)</td><td class="num">${bytes(db.system.bytes)}</td><td class="num">v${db.system.schema}</td><td>—</td></tr>
          <tr><td>Hardware (real devices)</td><td class="num">${bytes(db.hardware.bytes)}</td><td class="num">v${db.hardware.schema}</td><td class="num">${db.hardware.measurements}</td></tr>
          <tr><td>Simulation (synthetic)</td><td class="num">${bytes(db.simulation.bytes)}</td><td class="num">—</td><td class="num">${db.simulation.measurements}</td></tr></tbody></table>
        <table style="margin-top:14px"><thead><tr><th>Notification channel</th><th>State</th></tr></thead><tbody>${Object.entries(h.notifications).map(([k, v]) => `<tr><td>${esc(k.replace('_', '-'))}</td><td>${esc(v)}</td></tr>`).join('')}</tbody></table>
        <div class="small muted" style="margin-top:8px">Python ${esc(h.python)}</div>`;
    } else if (tab === 'limits') {
      const { thresholds: t, note } = await api('/settings/thresholds');
      el.innerHTML = `<div class="note warn">${esc(note)}</div><table style="margin:12px 0"><tbody>${Object.entries(t).map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td class="num"><b>${v}</b></td></tr>`).join('')}</tbody></table><button class="btn primary sm" id="et">Edit default limits</button>`;
      $('#et').addEventListener('click', async () => {
        const v = await formModal('Default alert limits', Object.entries(t).map(([k, val]) => ({ name: k, label: k, type: 'number', step: '0.1', value: val, required: true })));
        if (v) try { await api('/settings/thresholds', { method: 'PUT', body: v }); toast('Limits saved', '', 'ok'); load(); } catch (e) { fail(e); }
      });
    } else {
      const d = await api('/audit?per_page=150');
      el.innerHTML = `<div class="small muted" style="margin-bottom:8px">${d.total} entries · append-only, hash-chained. No passwords, tokens or measurement values are recorded.</div><div class="tablewrap"><table><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Target</th><th>Mode</th><th>Outcome</th><th>Detail</th><th>IP</th></tr></thead><tbody>
        ${d.entries.map((a) => `<tr><td class="num small">${esc(fmtDT(a.ts))}</td><td>${esc(a.username || 'system')}</td><td class="mono">${esc(a.action)}</td><td class="small">${esc(a.target_type || '')} ${esc(a.target_id || '')}</td><td class="small">${esc(a.ns || '')}</td>
          <td>${a.outcome === 'ok' ? badge('ok', 'ok') : badge('critical', a.outcome)}</td><td class="small muted">${esc(a.detail || '')}</td><td class="small mono">${esc(a.ip || '')}</td></tr>`).join('')}</tbody></table></div>`;
    }
  }
  await load();
  return {};
}

// =============================================================== account & security
export async function account(root, _arg, ctx) {
  ctx.setTitle('Account & security');
  const u = state.me;
  root.innerHTML = `<div class="stack" style="max-width:720px">${u.must_change_password ? '<div class="note crit"><b>Choose a new password to continue.</b></div>' : ''}
    <div class="card"><header><h2>${esc(u.full_name)}</h2><span class="muted right mono">${esc(u.username)} · ${esc(u.role)}${u.is_admin ? ' · administrator' : ''}</span></header><div class="body">
      <form id="pw" class="stack"><h3>Change password</h3><div class="formgrid"><label class="f">Current password<input type="password" name="cur" required autocomplete="current-password"></label>
        <label class="f">New password<input type="password" name="nw" required autocomplete="new-password" minlength="12"></label></div><div class="small muted">At least 12 characters, mixing 3 of: lower case, upper case, digits, symbols. Other sessions are signed out.</div>
        <div><button class="btn primary">Change password</button></div></form></div></div>
    ${u.role === 'doctor' ? `<div class="card"><header><h2>Two-factor authentication (TOTP)</h2><span class="right">${u.totp_enabled ? badge('ok', 'enabled') : badge('offline', 'not enabled')}</span></header><div class="body stack" id="tf">
      <div class="small muted">Recommended for doctor and administrator accounts. Works with any authenticator app.</div>
      <div>${u.totp_enabled ? '<button class="btn danger sm" id="tfOff">Disable</button>' : '<button class="btn sm primary" id="tfOn">Set up</button>'}</div></div></div>` : ''}</div>`;
  $('#pw').addEventListener('submit', async (e) => {
    e.preventDefault();
    try { await api('/auth/password', { method: 'POST', body: { current_password: e.target.cur.value, new_password: e.target.nw.value } }); toast('Password changed', '', 'ok'); state.me.must_change_password = 0; location.hash = '#/'; } catch (err) { fail(err); }
  });
  $('#tfOn')?.addEventListener('click', async () => {
    try {
      const r = await api('/auth/totp/enroll', { method: 'POST', body: {} });
      const v = await formModal('Set up two-factor authentication', [{ name: 'otp', label: '6-digit code from the app', required: true, full: true }],
        { submit: 'Confirm', intro: `Add this secret to your authenticator app, then enter the current code:<div class="keybox mono" style="margin-top:8px">${esc(r.secret_base32)}</div>` });
      if (!v) return;
      await api('/auth/totp/confirm', { method: 'POST', body: v }); state.me.totp_enabled = 1; toast('Two-factor authentication enabled', '', 'ok'); account(root, _arg, ctx);
    } catch (e) { fail(e); }
  });
  $('#tfOff')?.addEventListener('click', async () => {
    const v = await formModal('Disable two-factor authentication', [{ name: 'current_password', label: 'Current password', type: 'password', required: true, full: true }], { submit: 'Disable' });
    if (v) try { await api('/auth/totp/disable', { method: 'POST', body: v }); state.me.totp_enabled = 0; account(root, _arg, ctx); } catch (e) { fail(e); }
  });
  return {};
}

// =============================================================== family caregiver home (simplified)
export async function caregiverHome(root, _arg, ctx) {
  ctx.setTitle('My family');
  let alive = true;
  const TXT = { ok: ['All is well', 'Recent measurements are within the expected range.'], attention: ['Needs attention', 'The care team has been notified of a warning.'],
    urgent: ['Urgent warning', 'The care team has been alerted. If you are with your relative and worried, call the emergency number.'],
    offline: ['Device not connected', 'No recent measurement was received. This is not a health reading.'], no_data: ['No data yet', 'No measurement has been received so far.'] };
  async function load() {
    const d = await api('/caregiver/patients');
    if (!alive) return;
    if (!d.patients.length) { root.innerHTML = '<div class="cg"><div class="card"><div class="empty">No one has shared their monitoring with you, or the authorization has ended.<br>Please contact the care team if you think this is a mistake.</div></div></div>'; return; }
    const hist = await Promise.all(d.patients.map((p) => api(`/caregiver/patients/${p.patient_id}/history`).catch(() => ({ hours: [] }))));
    root.innerHTML = `<div class="cg stack">${d.patients.map((p, i) => {
      const [t, s] = TXT[p.state], v = p.vitals;
      return `<div class="card"><div class="body stack"><div class="row"><h1>${esc(p.name)}</h1>${p.relationship ? `<span class="muted">${esc(p.relationship)}</span>` : ''}${p.is_simulation ? '<span class="tag">simulation — not a real person</span>' : ''}</div>
        <div class="state ${esc(p.state)}">${icon(p.state === 'ok' ? 'heart' : 'bell')}<div><b>${t}</b>${s}</div></div>
        ${v && p.stale ? '<div class="note warn"><b>These are the last known values, not current ones.</b> No recent measurement has been received.</div>' : ''}
        ${v ? `<div class="vit"><div><b>${n(v.heart_rate)}</b><span>Heart rate · beats/min</span></div><div><b>${n(v.spo2)}</b><span>Oxygen · %</span></div><div><b>${n(v.temperature, 1)}</b><span>Temperature · °C</span></div></div>` : ''}
        <div class="row small muted"><span>${p.last_measurement_ts ? `Last successful measurement: <b>${esc(fmtDT(p.last_measurement_ts))}</b> (${esc(ago(p.last_measurement_ts))})` : 'No measurement received yet'}</span>
          <span class="right">${p.device_connected ? badge('ok', 'device connected') : badge('offline', 'device not connected')}</span></div>
        ${p.warnings.length ? `<div><h3>Recent warnings</h3><table><tbody>${p.warnings.map((w) => `<tr><td>${badge(w.active ? w.severity : 'offline', w.active ? 'active' : 'handled')}</td><td>${esc(w.label)}</td><td class="small muted">${esc(fmtDT(w.created_at))}</td></tr>`).join('')}</tbody></table></div>` : ''}
        ${hist[i].hours.length ? `<div><h3>Last 24 hours — hourly averages</h3><div class="tablewrap" style="max-height:220px"><table><thead><tr><th>Hour</th><th>Heart rate</th><th>Oxygen</th><th>Temperature</th></tr></thead><tbody>
          ${hist[i].hours.slice().reverse().map((h) => `<tr><td>${esc(fmtShort(h.ts))}</td><td class="num">${n(h.heart_rate)}</td><td class="num">${n(h.spo2)}</td><td class="num">${n(h.temperature, 1)}</td></tr>`).join('')}</tbody></table></div></div>` : ''}
        ${p.location ? `<div class="small muted">${p.location.is_current ? 'Last known location' : 'Old location'}: recorded ${esc(ago(p.location.ts))}${p.location.source === 'simulated' ? ' (fictional, simulation)' : ''}.</div>` : ''}
        <div class="note"><b>Contact</b> — ${p.contact.doctor_name ? `Doctor: ${esc(p.contact.doctor_name)}${p.contact.doctor_phone ? ` · ${esc(p.contact.doctor_phone)}` : ''}. ` : ''}${esc(p.contact.procedure)}</div></div></div>`;
    }).join('')}<div class="small muted">You see this information because the patient (or their legal representative) authorized it. The authorization can be withdrawn at any time.</div></div>`;
  }
  const reload = debounce(() => load().catch(() => {}), 2500);
  await load();
  const timer = setInterval(reload, 30000);
  return { destroy() { alive = false; clearInterval(timer); }, onEvent(ev) { if (['measurement', 'alert', 'alert_update', 'device'].includes(ev.type)) reload(); } };
}
