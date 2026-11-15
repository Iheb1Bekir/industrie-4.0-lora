// Application shell: authentication, role-specific navigation, router, real-time stream (Server-Sent Events).
import { $, $$, TZ, api, can, esc, fail, fmtT, icon, state, toast, ago } from './core.js';
import * as staff from './views-staff.js';
import * as ops from './views-ops.js';

const app = $('#app');
const NAV = [  // [route, label, icon, permission, section]
  ['overview', 'Overview', 'grid', 'patients.read', 'Monitoring'],
  ['patients', 'Patients', 'users', 'patients.read', 'Monitoring'],
  ['alerts', 'Alerts', 'bell', 'alerts.read', 'Monitoring'],
  ['map', 'Patient map', 'map', 'location.read', 'Monitoring'],
  ['network', 'LoRa network', 'net', 'network.read', 'Infrastructure'],
  ['devices', 'Devices', 'chip', 'devices.read', 'Infrastructure'],
  ['ai', 'AI intelligence', 'brain', 'ml.read', 'Intelligence'],
  ['reports', 'Reports', 'file', 'reports.export', 'Intelligence'],
  ['simulation', 'Simulation', 'play', 'simulation.control', 'Administration'],
  ['admin', 'Administration', 'shield', 'users.manage', 'Administration'],
  ['home', 'My family', 'heart', 'caregiver.view', 'Family'],
];
const ROUTES = {
  overview: staff.overview, patients: staff.patients, patient: staff.patient, alerts: staff.alerts, map: staff.map,
  network: ops.network, devices: ops.devices, ai: ops.ai, reports: ops.reports, simulation: ops.simulation, admin: ops.admin,
  home: ops.caregiverHome, account: ops.account,
};
const ROLE_TITLE = { doctor: 'Doctor', assistant: 'Medical assistant', caregiver: 'Family caregiver' };
let current = null, es = null, clockTimer = null;

// ---------------------------------------------------------------- theme
function applyTheme(t) { document.documentElement.dataset.theme = t; try { localStorage.setItem('rpm-theme', t); } catch { /* storage unavailable */ } }
(function initTheme() {
  let t = null;
  try { t = localStorage.getItem('rpm-theme'); } catch { /* ignore */ }
  applyTheme(t || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
})();

// ---------------------------------------------------------------- login (three role experiences)
function loginView() {
  let role = 'doctor';
  const copy = {
    doctor: ['Clinical workspace', 'Full patient overview, alerts, predictions, devices and reports.'],
    assistant: ['Monitoring workspace', 'Follow your assigned patients, acknowledge and escalate alerts.'],
    caregiver: ['Family view', 'A simple, private view of the person you care for.'],
  };
  app.innerHTML = `<div class="login">
    <section class="hero"><div class="brand"><div class="brand-mark">${icon('pulse')}</div><div>RPM LoRa<small>Remote Patient Monitoring</small></div></div>
      <div><h1>Continuous monitoring over a private LoRa network, with local early-warning intelligence.</h1>
      <ul><li>${icon('pulse')}<span>ESP32 patient nodes, application-level relays and a Raspberry Pi 5 gateway</span></li>
      <li>${icon('brain')}<span>On-device prediction model with measured, published evaluation</span></li>
      <li>${icon('shield')}<span>Role-based access, authenticated radio frames, audit trail</span></li></ul></div>
      <div class="small" style="opacity:.7">Research prototype — not a medical device. No clinical validation.</div></section>
    <section class="panel"><form id="lf" autocomplete="on">
      <h2 id="lt"></h2><div class="muted" id="ls"></div>
      <div class="roles" role="tablist" aria-label="Choose your role">
        ${['doctor', 'assistant', 'caregiver'].map((r) => `<button type="button" role="tab" data-role="${r}">${icon({ doctor: 'pulse', assistant: 'users', caregiver: 'heart' }[r])}${ROLE_TITLE[r]}</button>`).join('')}</div>
      <div class="stack">
        <label class="f">Username<input name="username" required autocomplete="username" autofocus></label>
        <label class="f">Password<input name="password" type="password" required autocomplete="current-password"></label>
        <label class="f" id="otpf" hidden>One-time code<input name="otp" inputmode="numeric" maxlength="6" autocomplete="one-time-code"></label>
        <div class="note crit" id="le" hidden></div>
        <button class="btn primary" style="width:100%;justify-content:center;padding:10px">Sign in</button>
        <div class="small muted">Forgot your password? Ask an administrator for a one-time reset token, then <a href="#" id="rs">set a new password</a>.</div>
      </div></form></section></div>`;
  const paint = () => { $('#lt').textContent = copy[role][0]; $('#ls').textContent = copy[role][1]; $$('.roles button').forEach((b) => b.classList.toggle('on', b.dataset.role === role)); };
  paint();
  $$('.roles button').forEach((b) => b.addEventListener('click', () => { role = b.dataset.role; paint(); }));
  $('#rs').addEventListener('click', async (e) => {
    e.preventDefault();
    const { formModal } = await import('./core.js');
    const v = await formModal('Set a new password', [{ name: 'token', label: 'One-time reset token', required: true, full: true },
      { name: 'new_password', label: 'New password (12+ characters)', type: 'password', required: true, full: true }], { submit: 'Change password' });
    if (!v) return;
    try { await api('/auth/reset/complete', { method: 'POST', body: v }); toast('Password changed', 'You can sign in now.', 'ok'); } catch (err) { fail(err); }
  });
  $('#lf').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = e.target, err = $('#le');
    err.hidden = true;
    try {
      const me = await api('/auth/login', { method: 'POST', body: { username: f.username.value.trim(), password: f.password.value, otp: f.otp.value || undefined } });
      if (me.user.role !== role) toast('Signed in', `This account is a ${ROLE_TITLE[me.user.role]} account — opening that workspace.`);
      await start(me);
    } catch (ex) {
      if (ex.code === 'E_OTP_REQUIRED') { $('#otpf').hidden = false; f.otp.focus(); }
      err.hidden = false; err.textContent = ex.message;
    }
  });
}

// ---------------------------------------------------------------- shell
function shell() {
  const u = state.me, items = NAV.filter((n) => can(n[3]));
  let sect = '';
  const nav = items.map(([r, label, ic, , s]) => `${s !== sect ? `<div class="sect">${esc((sect = s))}</div>` : ''}<a href="#/${r}" data-nav="${r}">${icon(ic)}<span>${esc(label)}</span>${r === 'alerts' ? '<span class="badge plain s-critical" id="navAlerts" hidden></span>' : ''}</a>`).join('');
  app.innerHTML = `<div class="shell"><nav class="nav" aria-label="Main">
      <div class="brand"><div class="brand-mark">${icon('pulse')}</div><div>RPM LoRa<small>${esc(ROLE_TITLE[u.role])} workspace</small></div></div>
      ${nav}<div class="foot">Research prototype · not a medical device<br>Times shown in ${esc(TZ)}</div></nav>
    <div class="main"><div id="modebar"></div>
      <div class="top"><div class="title" id="title"></div><span class="live" id="live"><i></i><span>connecting…</span></span>
        <div class="grow"></div><div class="clock" id="clock"></div>
        <button class="iconbtn" id="themeBtn" title="Toggle light / dark theme" aria-label="Toggle theme">${icon('sun')}</button>
        <button class="iconbtn" id="bellBtn" title="Notifications" aria-label="Notifications">${icon('bell')}<span class="dot" id="bellDot" hidden></span></button>
        <div class="userchip" id="userBtn" tabindex="0" role="button" aria-label="Account menu"><div class="avatar">${esc(u.full_name.split(' ').map((w) => w[0]).slice(0, 2).join('').toUpperCase())}</div>
          <div><div style="font-weight:600;font-size:12.5px">${esc(u.full_name)}</div><div class="small muted">${esc(ROLE_TITLE[u.role])}${u.is_admin ? ' · admin' : ''}</div></div></div>
      </div><div id="pop"></div><main class="content" id="view"></main></div></div>`;
  $('#themeBtn').addEventListener('click', () => { applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'); route(); });
  $('#bellBtn').addEventListener('click', toggleBell);
  $('#userBtn').addEventListener('click', () => {
    const p = $('#pop');
    if (p.dataset.kind === 'user') { p.innerHTML = ''; p.dataset.kind = ''; return; }
    p.dataset.kind = 'user';
    p.innerHTML = `<div class="pop"><header>${esc(u.username)}</header><button class="linkish" data-go="#/account">Account &amp; security</button><button class="linkish" id="logout">Sign out</button></div>`;
    $('[data-go]', p).addEventListener('click', () => { location.hash = '#/account'; p.innerHTML = ''; p.dataset.kind = ''; });
    $('#logout').addEventListener('click', logout);
  });
  clearInterval(clockTimer);
  const tick = () => { const c = $('#clock'); if (c) c.innerHTML = `${esc(new Date().toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }))}<br><b>${esc(fmtT(Date.now() / 1000))}</b>`; };
  tick(); clockTimer = setInterval(tick, 1000);
  paintMode();
}

function paintMode() {
  const el = $('#modebar');
  if (!el || !state.status) return;
  const sim = state.status.mode === 'simulation', s = state.status.simulation;
  el.className = 'modebar ' + (sim ? 'sim' : 'hw');
  el.innerHTML = sim
    ? `<span>⚠ SIMULATION MODE</span><span class="sub">All patients, measurements and locations on screen are synthetic. Engine: ${esc(s.state)}${s.scenario ? ` · scenario ${esc(s.scenario)}` : ''}</span>`
    : '<span>HARDWARE MODE</span><span class="sub">Showing data received from registered physical devices only. A device is online only while valid frames arrive.</span>';
}

async function refreshStatus() {
  try { state.status = await api('/system/status'); state.mode = state.status.mode; paintMode(); } catch { /* handled by api() */ }
}

async function refreshBell() {
  try {
    const d = await api('/notifications');
    const dot = $('#bellDot');
    if (dot) { dot.hidden = !d.unread; dot.textContent = d.unread > 9 ? '9+' : d.unread; }
    return d;
  } catch { return { notifications: [], unread: 0 }; }
}

async function toggleBell() {
  const p = $('#pop');
  if (p.dataset.kind === 'bell') { p.innerHTML = ''; p.dataset.kind = ''; return; }
  p.dataset.kind = 'bell';
  const d = await refreshBell();
  p.innerHTML = `<div class="pop"><header>Notifications<button class="btn sm right" id="askN">Enable browser alerts</button></header>
    ${d.notifications.length ? d.notifications.map((x) => `<div class="item ${x.read_at ? '' : 'unread'}"><b>${esc(x.title)}</b>${x.status === 'suppressed' ? ' <span class="tag">rate-limited</span>' : ''}<div class="small">${esc(x.body)}</div><div class="small muted">${esc(ago(x.ts))}</div></div>`).join('') : '<div class="empty">No notifications</div>'}</div>`;
  $('#askN').addEventListener('click', async () => {
    if (!('Notification' in window)) return toast('Not supported', 'This browser has no notification support.');
    const r = await Notification.requestPermission();
    toast('Browser notifications', r === 'granted' ? 'Enabled for this browser.' : 'Permission was not granted.');
  });
  await api('/notifications/read', { method: 'POST', body: {} }).catch(() => {});
  $('#bellDot').hidden = true;
}

async function logout() {
  try { await api('/auth/logout', { method: 'POST', body: {} }); } catch { /* session may be gone already */ }
  es?.close(); state.me = null; location.hash = ''; location.reload();
}

// ---------------------------------------------------------------- router
function defaultRoute() { return state.me.role === 'caregiver' ? 'home' : 'overview'; }

async function route() {
  if (!state.me) return;
  const [name0, arg] = location.hash.replace(/^#\//, '').split('/');
  let name = name0 || defaultRoute();
  if (name === 'patients' && arg) name = 'patient';
  const navName = name === 'patient' ? 'patients' : name;
  const entry = NAV.find((n) => n[0] === navName);
  if (!ROUTES[name] || (entry && !can(entry[3]))) { location.hash = '#/' + defaultRoute(); return; }
  if (state.me.must_change_password && name !== 'account') { location.hash = '#/account'; return; }
  current?.destroy?.();
  $$('.nav a').forEach((a) => a.classList.toggle('active', a.dataset.nav === navName));
  $('#pop').innerHTML = ''; $('#pop').dataset.kind = '';
  const view = $('#view');
  view.innerHTML = '<div class="empty">Loading…</div>';
  try {
    current = await ROUTES[name](view, arg, { setTitle: (t) => { $('#title').textContent = t; document.title = `${t} · RPM`; } });
  } catch (e) {
    current = null;
    view.innerHTML = `<div class="card"><div class="body"><div class="note crit">${esc(e.message)}</div></div></div>`;
  }
}

// ---------------------------------------------------------------- real-time stream
function connectStream() {
  es?.close();
  es = new EventSource('/api/v1/stream');
  const setLive = (on, text) => { const l = $('#live'); if (l) { l.classList.toggle('on', on); l.lastElementChild.textContent = text; } state.live = on; };
  es.addEventListener('hello', () => setLive(true, 'Live'));
  es.onerror = () => setLive(false, 'Reconnecting…');
  const forward = (type) => es.addEventListener(type, (m) => {
    const ev = JSON.parse(m.data);
    try { current?.onEvent?.(ev); } catch (e) { console.error(e); }
    if (type === 'system' || type === 'simulation') refreshStatus().then(() => { if (type === 'system') route(); });
    if (type === 'notification') {
      const d = ev.data;
      toast(d.title, d.body, d.severity === 'critical' ? 'critical' : d.severity === 'high' ? 'critical' : 'warning');
      refreshBell();
      if ('Notification' in window && Notification.permission === 'granted' && document.hidden) new Notification(d.title, { body: d.body, tag: 'rpm-' + d.alert_id });
    }
    if (type === 'alert' || type === 'alert_update') refreshAlertCount();
  });
  ['measurement', 'prediction', 'alert', 'alert_update', 'device', 'network', 'location', 'simulation', 'system', 'notification'].forEach(forward);
}

const refreshAlertCount = (() => {
  let t = null;
  return () => { if (t || !can('alerts.read')) return; t = setTimeout(async () => { t = null;
    try { const d = await api('/alerts?status=open&per_page=1'); const b = $('#navAlerts'); if (b) { b.hidden = !d.total; b.textContent = d.total; } } catch { /* ignore */ } }, 800); };
})();

async function start(me) {
  state.me = me.user; state.perms = new Set(me.permissions); state.csrf = me.csrf_token; state.mode = me.mode;
  await refreshStatus();
  shell();
  connectStream();
  refreshBell(); refreshAlertCount();
  if (!location.hash || location.hash === '#/login') location.hash = '#/' + defaultRoute();
  await route();
}

window.addEventListener('hashchange', route);
(async function boot() {
  try { await start(await api('/auth/me')); } catch { loginView(); }
})();
