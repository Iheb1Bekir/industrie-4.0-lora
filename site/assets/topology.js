/* Geometry of the OMNeT++ model RPM_LoRa_Research / DistributedRPMNetwork (src/topology/DistributedRPMNetwork.ned):
   doctor gateway at the centre; 20 patients on rings of 25 m (8), 45 m (8, offset pi/8) and 80 m (4);
   3 relays on a 30 m ring at pi/6 + 2*pi*j/3. Patients 1-16 transmit directly; patients 17-20 use relays
   1, 1, 2, 3 (nextHopRelayIndex = floor((i-16)*3/4)) and relays forward along the ordered chain 1 -> 2 -> 3 -> doctor. */
(function (root) {
  const TAU = Math.PI * 2;
  function rpmTopology() {
    const patients = [];
    for (let i = 0; i < 20; i++) {
      let r, a;
      if (i < 8) { r = 25; a = (TAU * i) / 8; }
      else if (i < 16) { r = 45; a = (TAU * (i - 8)) / 8 + Math.PI / 8; }
      else { r = 80; a = (TAU * (i - 16)) / 4; }
      const relay = i < 16 ? -1 : Math.floor(((i - 16) * 3) / 4);
      patients.push({ id: i + 1, x: r * Math.cos(a), y: r * Math.sin(a), ring: r, relay });
    }
    const relays = [0, 1, 2].map((j) => {
      const a = Math.PI / 6 + (TAU * j) / 3;
      return { id: j + 1, x: 30 * Math.cos(a), y: 30 * Math.sin(a) };
    });
    // full path (list of points, gateway last) for every patient
    const path = (p) => {
      const pts = [{ x: p.x, y: p.y }];
      if (p.relay >= 0) for (let j = p.relay; j < 3; j++) pts.push(relays[j]);
      pts.push({ x: 0, y: 0 });
      return pts;
    };
    return { patients, relays, path };
  }

  /* static SVG motif (banners, cards, README): real geometry, schematic styling */
  function topologySVG(opts = {}) {
    const size = opts.size || 520, pad = opts.pad || 28, k = (size / 2 - pad) / 80, c = size / 2;
    const T = rpmTopology();
    const X = (v) => (c + v * k).toFixed(1), Y = (v) => (c + v * k).toFixed(1);
    let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="Simulated deployment: 20 patients, 3 relays, 1 doctor gateway">`;
    s += `<defs><radialGradient id="gwg" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#22d3ee" stop-opacity=".55"/><stop offset="1" stop-color="#22d3ee" stop-opacity="0"/></radialGradient>
      <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>`;
    [25, 45, 80, 30].forEach((r, i) => { s += `<circle cx="${c}" cy="${c}" r="${(r * k).toFixed(1)}" fill="none" stroke="${i === 3 ? 'rgba(139,92,246,.28)' : 'rgba(148,163,184,.16)'}" stroke-dasharray="3 6"/>`; });
    T.patients.forEach((p) => {
      if (p.relay < 0) s += `<line x1="${X(p.x)}" y1="${Y(p.y)}" x2="${c}" y2="${c}" stroke="rgba(34,211,238,.28)" stroke-width="1.2"/>`;
    });
    T.patients.filter((p) => p.relay >= 0).forEach((p) => {
      const pts = T.path(p).map((q) => `${X(q.x)},${Y(q.y)}`).join(' ');
      s += `<polyline points="${pts}" fill="none" stroke="rgba(167,139,250,.7)" stroke-width="1.4" stroke-dasharray="5 4"/>`;
    });
    s += `<circle cx="${c}" cy="${c}" r="${(16 * k).toFixed(1)}" fill="url(#gwg)"/>`;
    T.relays.forEach((r) => { s += `<rect x="${(c + r.x * k - 7).toFixed(1)}" y="${(c + r.y * k - 7).toFixed(1)}" width="14" height="14" rx="3" fill="#8b5cf6" filter="url(#glow)"/>`; });
    T.patients.forEach((p) => { s += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="${p.relay < 0 ? 4.6 : 5.2}" fill="${p.relay < 0 ? '#22d3ee' : '#a5f3fc'}" filter="url(#glow)"/>`; });
    s += `<circle cx="${c}" cy="${c}" r="9" fill="#e6edf7" filter="url(#glow)"/><circle cx="${c}" cy="${c}" r="4" fill="#22d3ee"/>`;
    if (opts.labels) {
      s += `<text x="${c}" y="${c + 26}" fill="#8b9bb4" font-family="JetBrains Mono, Consolas, monospace" font-size="11" text-anchor="middle">doctor gateway</text>`;
    }
    return s + '</svg>';
  }
  root.rpmTopology = rpmTopology;
  root.topologySVG = topologySVG;
})(typeof window !== 'undefined' ? window : globalThis);
