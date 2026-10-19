(() => {
  const $ = (id) => document.getElementById(id);
  let token = sessionStorage.getItem("rpm_token") || "", sel = null, timer = null;
  const el = (tag, props = {}, ...kids) => {
    const e = Object.assign(document.createElement(tag), props);
    kids.forEach((k) => e.append(k)); return e;
  };
  const setStatus = (msg, err) => { const s = $("status"); s.textContent = msg; s.className = "status" + (err ? " err" : ""); };

  async function api(path, opts = {}) {
    const r = await fetch(path, { ...opts, headers: { Authorization: "Bearer " + token, ...(opts.headers || {}) } });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || ("HTTP " + r.status));
    return body;
  }

  function chart(target, rows, key, unit) {
    target.replaceChildren();
    const pts = rows.filter((r) => r[key] !== null && r[key] !== undefined);
    if (pts.length < 2) { target.append(el("div", { className: "muted", textContent: pts.length ? "Only one reading so far." : "No history yet." })); return; }
    const W = 300, H = 120, P = 24, xs = pts.map((p) => p.ts), ys = pts.map((p) => p[key]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const sx = (x) => P + ((x - x0) / (x1 - x0 || 1)) * (W - P - 4), sy = (y) => H - 14 - ((y - y0) / (y1 - y0 || 1)) * (H - 28);
    const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const path = document.createElementNS(NS, "polyline");
    path.setAttribute("points", pts.map((p) => `${sx(p.ts).toFixed(1)},${sy(p[key]).toFixed(1)}`).join(" "));
    path.setAttribute("fill", "none"); path.setAttribute("stroke", "#1f6feb"); path.setAttribute("stroke-width", "2");
    svg.append(path);
    [[y1, 10], [y0, H - 4]].forEach(([v, y]) => { const t = document.createElementNS(NS, "text"); t.setAttribute("x", 2); t.setAttribute("y", y); t.setAttribute("font-size", 9); t.setAttribute("fill", "currentColor"); t.textContent = v.toFixed(key === "temp" ? 1 : 0) + unit; svg.append(t); });
    target.append(svg);
  }

  async function loadPatients() {
    const { patients } = await api("/api/patients");
    const ul = $("patients"); ul.replaceChildren();
    if (!patients.length) ul.append(el("li", { textContent: "No patients yet" }));
    patients.forEach((p) => {
      const li = el("li", { className: p.pid === sel ? "sel" : "", textContent: p.pid });
      if (p.active_alerts) li.append(el("span", { className: "badge", textContent: p.active_alerts }));
      li.append(el("div", { className: "muted", textContent: `${p.n_readings} readings` }));
      li.onclick = () => { sel = p.pid; refresh(); };
      ul.append(li);
    });
    if (!sel && patients.length) sel = patients[0].pid;
  }

  const fmt = (v, d = 0) => (v === null || v === undefined ? "n/a" : Number(v).toFixed(d));
  function card(label, val, unit, bad) { return el("div", { className: "card" + (bad ? " bad" : "") }, el("span", { className: "muted", textContent: label }), el("b", { textContent: val + unit })); }

  async function loadDetail() {
    $("detail").hidden = !sel; if (!sel) return;
    $("pname").textContent = "Patient " + sel;
    const [lat, hist, al] = await Promise.all([api(`/api/patient/${sel}/latest`), api(`/api/patient/${sel}/history?hours=24`), api(`/api/alerts?pid=${sel}`)]);
    const r = lat.latest, fl = r.flags | 0;
    const f = $("fresh"); f.replaceChildren(`Last reading ${r.age_s} s ago (${new Date(r.ts * 1000).toLocaleString()}) · source: ${r.source} · seq ${r.seq ?? "n/a"} `);
    if (r.synthetic) f.append(el("span", { className: "synth", textContent: "SYNTHETIC" }));
    if (r.age_s > 180) f.append(el("b", { textContent: " · STALE", style: "color:var(--bad)" }));
    const faults = [fl & 4 ? "HR/SpO2" : null, fl & 8 ? "temperature" : null, fl & 16 ? "IMU" : null].filter(Boolean);
    const cards = $("cards"); cards.replaceChildren(
      card("Heart rate", fmt(r.hr), " bpm", r.hr !== null && (r.hr > 120 || r.hr < 40)),
      card("SpO2", fmt(r.spo2), " %", r.spo2 !== null && r.spo2 < 92),
      card("Temperature", fmt(r.temp, 1), " °C", r.temp !== null && (r.temp >= 38 || r.temp < 35)),
      card("Fall", r.fall ? "YES" : "no", "", !!r.fall),
      card("Sensor quality", faults.length ? "FAULT" : "OK", "", faults.length > 0));
    if (faults.length) cards.append(el("div", { className: "muted", textContent: "Faulty: " + faults.join(", ") }));
    chart($("c_hr"), hist.readings, "hr", ""); chart($("c_spo2"), hist.readings, "spo2", ""); chart($("c_temp"), hist.readings, "temp", "");
    const ul = $("alerts"); ul.replaceChildren();
    if (!al.alerts.length) ul.append(el("li", { textContent: "No active alerts" }));
    al.alerts.forEach((a) => {
      const b = el("button", { textContent: "Acknowledge" });
      b.onclick = async () => { try { await api(`/api/alerts/${a.id}/ack`, { method: "POST" }); refresh(); } catch (e) { setStatus(e.message, true); } };
      ul.append(el("li", { className: a.severity }, el("span", { textContent: `[${a.severity}] ${a.kind}: ${a.message} — ${new Date(a.created_ts * 1000).toLocaleString()}` }), b));
    });
    await loadPrediction();
  }

  async function loadPrediction() {
    const box = $("prediction"); box.replaceChildren();
    try {
      const p = await api(`/api/patient/${sel}/predict?horizon=${$("horizon").value}`);
      box.append(el("div", {}, "Risk: ", el("span", { className: "risk " + p.risk, textContent: p.risk.toUpperCase() }), ` — ${p.reason}`));
      box.append(el("div", { className: "muted", textContent: `Model: ${p.model} · status: ${p.status} · samples: ${p.samples_used}${p.synthetic_input ? " · SYNTHETIC input" : ""}` }));
      if (p.pred) Object.entries(p.pred).forEach(([k, v]) => box.append(el("div", { textContent: `${k}: ${v.join(" → ")} (every ${p.step_minutes} min)` })));
      box.append(el("div", { className: "muted", textContent: p.disclaimer }));
    } catch (e) { box.append(el("div", { className: "muted", textContent: "Prediction unavailable: " + e.message })); }
  }

  async function refresh() {
    if (!token) return;
    try { await loadPatients(); await loadDetail(); setStatus("Updated " + new Date().toLocaleTimeString()); }
    catch (e) { setStatus("Error: " + e.message, true); }
  }

  async function init() {
    try {
      const h = await (await fetch("/api/health")).json();
      $("horizon").replaceChildren(...h.allowed_horizons.map((m) => el("option", { value: m, textContent: m + " min" })));
    } catch (e) { setStatus("API unreachable", true); }
    $("horizon").onchange = loadPrediction;
    $("tokenForm").onsubmit = (ev) => { ev.preventDefault(); token = $("token").value.trim(); sessionStorage.setItem("rpm_token", token); $("token").value = ""; sel = null; refresh(); };
    if (token) refresh();
    clearInterval(timer); timer = setInterval(refresh, 10000);
  }
  init();
})();
