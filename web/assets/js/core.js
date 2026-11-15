// Core helpers: API client (session cookie + CSRF header), formatting, DOM utilities, toasts, modal.
export const state = { me: null, perms: new Set(), csrf: null, mode: null, status: null, live: false };

export class ApiError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}

export async function api(path, { method = 'GET', body } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && state.csrf) headers['X-CSRF-Token'] = state.csrf;
  const r = await fetch('/api/v1' + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: 'same-origin' });
  let data = null;
  try { data = await r.json(); } catch { /* non-JSON */ }
  if (!r.ok) {
    if (r.status === 401 && state.me && !path.startsWith('/auth/login')) { state.me = null; location.hash = '#/login'; location.reload(); }
    throw new ApiError(r.status, data?.code || 'E_HTTP', data?.error || `Request failed (${r.status})`);
  }
  return data;
}

export const can = (p) => state.perms.has(p);

// ---- escaping: every dynamic string rendered into HTML goes through esc() ----
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (v) => (v === null || v === undefined ? '' : String(v).replace(/[&<>"']/g, (c) => ESC[c]));
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// ---- time: stored/transported as UTC epoch seconds, displayed in the browser's local timezone ----
export const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
const dtf = new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
const tf = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const df = new Intl.DateTimeFormat(undefined, { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
export const fmtDT = (ts) => (ts ? dtf.format(new Date(ts * 1000)) : '—');
export const fmtT = (ts) => (ts ? tf.format(new Date(ts * 1000)) : '—');
export const fmtShort = (ts) => (ts ? df.format(new Date(ts * 1000)) : '—');
export function ago(ts) {
  if (!ts) return 'never';
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 5) return 'just now';
  if (s < 90) return `${Math.round(s)} s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
export const n = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v) ? '—' : Number(v).toFixed(d));
export const pct = (v, d = 1) => (v === null || v === undefined ? '—' : (v * 100).toFixed(d) + ' %');

export const STATE_LABEL = { normal: 'Normal', warning: 'Warning', critical: 'Critical', offline: 'Offline', prediction: 'Prediction warning',
  stale: 'Stale data', no_data: 'No data yet', no_device: 'No device' };
export const badge = (cls, text) => `<span class="badge s-${esc(cls)}">${esc(text)}</span>`;
export const stateBadge = (s) => badge(s, STATE_LABEL[s] || s);

const ICONS = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/><path d="M16 4.8a3.5 3.5 0 0 1 0 6.4M18 14.8c2 .7 3.2 2.4 3.6 5.2"/>',
  bell: '<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2.5h-15z"/><path d="M10 21h4"/>',
  map: '<path d="M12 21s7-6.2 7-11.5A7 7 0 0 0 5 9.500C5 14.800 12 21 12 21z"/><circle cx="12" cy="9.500" r="2.500"/>',
  net: '<circle cx="12" cy="5" r="2.500"/><circle cx="5" cy="19" r="2.500"/><circle cx="19" cy="19" r="2.500"/><path d="M12 7.500v4M12 11.500 6.300 17M12 11.500 17.700 17"/>',
  brain: '<path d="M4 18V9M9 18V5M14 18v-7M19 18V8"/><path d="M3 21h18"/>',
  play: '<circle cx="12" cy="12" r="9"/><path d="M10 8.500v7l6-3.500z"/>',
  chip: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  file: '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5M9 13h7M9 17h7"/>',
  shield: '<path d="M12 3 4.500 6v6c0 4.500 3.200 7.700 7.500 9 4.300-1.300 7.500-4.500 7.500-9V6z"/><path d="m9 12 2.200 2.200L15.500 10"/>',
  heart: '<path d="M12 20s-7.500-4.600-7.500-10.200A4.300 4.300 0 0 1 12 7.300a4.300 4.300 0 0 1 7.500 2.500C19.500 15.400 12 20 12 20z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2.500M12 19.500V22M2 12h2.500M19.500 12H22M4.900 4.900l1.800 1.800M17.300 17.300l1.800 1.800M4.900 19.100l1.800-1.800M17.300 6.700l1.800-1.800"/>',
  pulse: '<path d="M2 12h4.500l2.500-6 4 12 2.500-6H22"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
};
export const icon = (name) => `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;

export function toast(title, body = '', kind = '') {
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  t.innerHTML = `<b>${esc(title)}</b><span class="small muted">${esc(body)}</span>`;
  $('#toasts').append(t);
  setTimeout(() => t.remove(), kind === 'critical' ? 12000 : 6000);
}
export const fail = (e) => toast('Action failed', e.message || String(e), 'critical');

// Modal with a form. fields: [{name,label,type,options,value,required,full,placeholder,help}]. Resolves with values or null.
export function formModal(title, fields, { submit = 'Save', intro = '' } = {}) {
  return new Promise((resolve) => {
    const bg = document.createElement('div');
    bg.className = 'modal-bg';
    const inputs = fields.map((f) => {
      const req = f.required ? 'required' : '';
      let ctl;
      if (f.type === 'select') ctl = `<select name="${esc(f.name)}" ${req}>${f.options.map((o) => `<option value="${esc(o[0])}" ${String(o[0]) === String(f.value ?? '') ? 'selected' : ''}>${esc(o[1])}</option>`).join('')}</select>`;
      else if (f.type === 'textarea') ctl = `<textarea name="${esc(f.name)}" rows="4" ${req} maxlength="4000">${esc(f.value || '')}</textarea>`;
      else if (f.type === 'checkbox') return `<label class="chk ${f.full ? 'full' : ''}"><input type="checkbox" name="${esc(f.name)}" ${f.value ? 'checked' : ''}> ${esc(f.label)}</label>`;
      else ctl = `<input name="${esc(f.name)}" type="${esc(f.type || 'text')}" value="${esc(f.value ?? '')}" ${req} placeholder="${esc(f.placeholder || '')}" ${f.step ? `step="${esc(f.step)}"` : ''} autocomplete="off">`;
      return `<label class="f ${f.full ? 'full' : ''}">${esc(f.label)}${ctl}${f.help ? `<span class="small muted">${esc(f.help)}</span>` : ''}</label>`;
    }).join('');
    bg.innerHTML = `<form class="modal" novalidate><header><h2>${esc(title)}</h2><button type="button" class="iconbtn right" data-x aria-label="Close">${icon('x')}</button></header>
      <div class="body stack">${intro ? `<div class="note">${intro}</div>` : ''}<div class="formgrid">${inputs}</div><div class="note crit" hidden data-err></div></div>
      <footer><button type="button" class="btn" data-x>Cancel</button><button class="btn primary">${esc(submit)}</button></footer></form>`;
    const close = (v) => { bg.remove(); resolve(v); };
    bg.addEventListener('click', (e) => { if (e.target === bg || e.target.closest('[data-x]')) close(null); });
    bg.querySelector('form').addEventListener('submit', (e) => {
      e.preventDefault();
      const out = {};
      for (const f of fields) {
        const el = e.target.elements[f.name];
        if (f.type === 'checkbox') out[f.name] = el.checked;
        else if (f.type === 'number') out[f.name] = el.value === '' ? null : Number(el.value);
        else out[f.name] = el.value.trim();
        if (f.required && (out[f.name] === '' || out[f.name] === null)) {
          const err = bg.querySelector('[data-err]'); err.hidden = false; err.textContent = `${f.label} is required`; el.focus(); return;
        }
      }
      close(out);
    });
    document.body.append(bg);
    bg.querySelector('input,select,textarea')?.focus();
  });
}

export function infoModal(title, html) {
  const bg = document.createElement('div');
  bg.className = 'modal-bg';
  bg.innerHTML = `<div class="modal"><header><h2>${esc(title)}</h2><button class="iconbtn right" data-x aria-label="Close">${icon('x')}</button></header><div class="body stack">${html}</div>
    <footer><button class="btn primary" data-x>Close</button></footer></div>`;
  bg.addEventListener('click', (e) => { if (e.target === bg || e.target.closest('[data-x]')) bg.remove(); });
  document.body.append(bg);
  return bg;
}

export function debounce(fn, ms) {
  let t = null;
  return (...a) => { if (t) return; t = setTimeout(() => { t = null; fn(...a); }, ms); };
}
