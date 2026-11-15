"""Simulation engine (SIMULATION MODE).

Generates synthetic physiology for virtual patient devices, builds REAL protocol-v2 frames signed with each
virtual device's key, pushes them through a model of the raw-LoRa network (direct links, application-level
relays, loss, duplicates, delay) and hands the surviving frames to `Pipeline.handle_frame("simulation", ...)`
- the same code path a real radio uses. Nothing here writes measurements directly.

Network model: mirrors the OMNeT++/FLoRa project (DistributedRPMNetwork): ring geometry 25/45/80 m around the
doctor gateway, 3 relays in an ordered chain, 14 dBm, SF7/125 kHz sensitivity -124 dBm, log-normal shadowing
(d0 = 40 m, gamma = 2.08, sigma = 3.57). It is a lightweight statistical twin, NOT a replacement for OMNeT++.

Speed factor: compresses physiology and sampling in wall-clock time; stored timestamps are always real UTC.
All records carry sim_session_id and live in the separate simulation database.
"""
import heapq
import json
import math
import random
import threading
import time

from . import protocol as P
from .alert_engine import device_alert_level, effective_thresholds
from .services import DomainError

MAHDIA = (35.5047, 11.0622)                 # city reference point (public knowledge)
DEMO_AREA_CENTER = (35.5060, 11.0450)       # centre of the fictional demonstration area
GATEWAY_POS = (35.5052, 11.0478)
SCENARIOS = {
    "A": "Normal operation", "B": "Gradual deterioration", "C": "Sudden fall", "D": "SpO2 decline",
    "E": "Network failure", "F": "Multi-patient emergency", "G": "Predictive warning",
}
EVENTS = ("deterioration", "spo2_decline", "hr_rise", "fever", "fall", "sensor_fault", "disconnect", "reconnect",
          "packet_loss", "recover", "predictive_trend")
FIRST_NAMES = ["Amira", "Youssef", "Salma", "Karim", "Leila", "Hedi", "Ines", "Mehdi", "Rania", "Sami",
               "Nour", "Walid", "Hana", "Tarek", "Dorra", "Anis", "Mouna", "Fares", "Sonia", "Nabil"]
SF7_SENSITIVITY_DBM, TX_POWER_DBM = -124.0, 14.0
PL_D0_DB, D0_M, GAMMA, SIGMA = 127.41, 40.0, 2.08, 3.57
NOISE_FLOOR_DBM = -117.0


def _rssi(distance_m, rng):
    pl = PL_D0_DB + 10 * GAMMA * math.log10(max(distance_m, 1.0) / D0_M) + rng.gauss(0, SIGMA)
    return TX_POWER_DBM - pl


class _Effect:
    """Additive physiological deviation: ramps to `delta` over `ramp` sim-seconds, holds, then optionally recovers."""

    def __init__(self, kind, start, ramp, delta, hold=None, recover=300):
        self.kind, self.start, self.ramp, self.delta, self.hold, self.recover = kind, start, ramp, delta, hold, recover

    def value(self, t):
        if t < self.start:
            return {}
        x = min(1.0, (t - self.start) / self.ramp) if self.ramp > 0 else 1.0
        if self.hold is not None and t > self.start + self.ramp + self.hold:
            x = max(0.0, 1.0 - (t - self.start - self.ramp - self.hold) / self.recover)
        x = x * x * (3 - 2 * x)   # smoothstep
        return {k: v * x for k, v in self.delta.items()}

    def finished(self, t):
        return self.hold is not None and t > self.start + self.ramp + self.hold + self.recover


class _VPatient:
    def __init__(self, index, patient_id, device_id, key, rng, n_total, n_relays):
        self.index, self.patient_id, self.device_id, self.key, self.rng = index, patient_id, device_id, key, rng
        self.base = {"hr": 68 + (index % 7) * 2, "spo2": 95 + (index % 5) * 0.8, "temp": 36.4 + (index % 6) * 0.1}  # FLoRa profile
        self.noise = {"hr": 0.0, "spo2": 0.0, "temp": 0.0}
        self.effects, self.seq, self.connected, self.extra_loss = [], 0, True, 0.0
        self.fall_pending, self.fault_until, self.next_tx, self.next_loc = False, -1.0, 0.0, 0.0
        # route: the outer ~20 % of patients are relay-assisted, as in DistributedRPMNetwork.ned
        n_relayed = max(1, round(n_total * 0.2))
        first_relayed = n_total - n_relayed
        if index >= first_relayed:
            self.relay_entry = min(n_relays - 1, (index - first_relayed) * n_relays // n_relayed)
            self.distance = 80.0
        else:
            self.relay_entry = None
            self.distance = 25.0 if index < first_relayed / 2 else 45.0
        ang, rad = rng.uniform(0, 2 * math.pi), rng.uniform(250, 1800)
        self.lat = DEMO_AREA_CENTER[0] + rad * math.cos(ang) / 111_320
        self.lon = DEMO_AREA_CENTER[1] + rad * math.sin(ang) / (111_320 * math.cos(math.radians(DEMO_AREA_CENTER[0])))
        self.sent = self.delivered = 0

    def sample(self, t):
        for k, sd, rho in (("hr", 1.6, 0.6), ("spo2", 0.35, 0.5), ("temp", 0.04, 0.8)):
            self.noise[k] = rho * self.noise[k] + self.rng.gauss(0, sd)
        v = {k: self.base[k] + self.noise[k] for k in self.base}
        v["hr"] += 2.5 * math.sin(2 * math.pi * t / 1800 + self.index)       # slow normal variation
        for e in self.effects:
            for k, d in e.value(t).items():
                v[k] += d
        self.effects = [e for e in self.effects if not e.finished(t)]
        v["hr"], v["spo2"], v["temp"] = min(220, max(30, v["hr"])), min(100, max(60, v["spo2"])), min(42, max(34, v["temp"]))
        fault = t < self.fault_until
        fall, self.fall_pending = self.fall_pending, False
        return (None if fault else round(v["hr"])), (None if fault else round(v["spo2"])), round(v["temp"], 2), fall


class Simulator:
    def __init__(self, svc):
        self.svc = svc
        self._lock = threading.RLock()
        self.state, self.session_id, self.config = "stopped", None, {}
        self.patients, self.relays, self._queue, self._schedule = [], [], [], []
        self.t_sim, self._last_real, self._thread, self._stop = 0.0, None, None, threading.Event()
        self.stats = {}
        self.rng = random.Random(1)

    # ---- public control surface ----------------------------------------------------------------------
    def status(self):
        with self._lock:
            return {"state": self.state, "session_id": self.session_id, "config": self.config, "sim_time_s": round(self.t_sim, 1),
                    "scenarios": SCENARIOS, "events": EVENTS, "stats": dict(self.stats),
                    "relays": [dict(r) for r in self.relays],
                    "patients": [{"patient_id": p.patient_id, "device_id": p.device_id, "connected": p.connected,
                                  "route": "direct" if p.relay_entry is None else f"relay {p.relay_entry + 1}",
                                  "hops": 0 if p.relay_entry is None else len(self.relays) - p.relay_entry,
                                  "sent": p.sent, "delivered": p.delivered, "effects": [e.kind for e in p.effects]}
                                 for p in self.patients]}

    def reset(self, config, user):
        """Wipe ONLY the simulation database and seed fictional patients + virtual devices."""
        with self._lock:
            if self.state != "stopped":
                self.stop(user)
            cfg = self._validate(config)
            db, svc = self.svc.store.ns("simulation"), self.svc
            with db.tx() as c:
                for t in ("notifications", "alert_events", "alerts", "predictions", "measurements", "locations", "clinical_notes",
                          "device_assignments", "caregiver_links", "consent_records", "staff_assignments", "devices", "patients",
                          "network_events", "network_counters"):
                    c.execute(f"DELETE FROM {t}")
            svc.pipeline._keys = {k: v for k, v in svc.pipeline._keys.items() if k[0] != "simulation"}
            svc.pipeline._recent_loss.clear()
            self.rng = random.Random(cfg["seed"])
            sysdb = svc.store.system
            doctor = user if user and user["role"] == "doctor" else sysdb.one("SELECT * FROM users WHERE role='doctor' AND is_active=1 ORDER BY id")
            assistants = sysdb.q("SELECT id FROM users WHERE role='assistant' AND is_active=1")
            caregivers = sysdb.q("SELECT id FROM users WHERE role='caregiver' AND is_active=1 AND is_demo=1")
            self.patients, n, now = [], cfg["patient_count"], svc.clock()
            for i in range(n):
                p = svc.register_patient("simulation", {"id": i + 1, "full_name": f"{FIRST_NAMES[i % 20]} {chr(65 + (i * 7) % 26)}. (SIM)",
                                                        "date_of_birth": f"{1940 + (i * 3) % 30}-0{1 + i % 9}-1{i % 9}",
                                                        "sex": "FM"[i % 2], "primary_doctor_id": doctor["id"] if doctor else None},
                                         doctor, synthetic=True)
                dev, key = svc.register_device("simulation", {"id": 60000 + i + 1, "serial": f"SIM-ESP32-{i + 1:03d}",   # id range reserved for virtual devices
                                                              "label": f"Virtual patient node {i + 1}", "hw_model": "virtual ESP32",
                                                              "radio": "simulated SX127x (raw LoRa)", "firmware_version": "sim"},
                                               doctor, virtual=True)
                svc.pair_device("simulation", dev["id"], p["id"], doctor)
                vp = _VPatient(i, p["id"], dev["id"], key, random.Random(cfg["seed"] * 1000 + i), n, cfg["relay_count"])
                self.patients.append(vp)
                db.x("INSERT INTO locations(patient_id,ts,lat,lon,accuracy_m,source) VALUES(?,?,?,?,?,?)",
                     (p["id"], now, vp.lat, vp.lon, 25.0, "simulated"))
                if i < math.ceil(n / 2):      # assistants see only the first half -> demonstrates restricted access
                    for a in assistants:
                        db.x("INSERT OR IGNORE INTO staff_assignments(patient_id,user_id,role,assigned_at,assigned_by) VALUES(?,?,?,?,?)",
                             (p["id"], a["id"], "assistant", now, doctor["id"] if doctor else None))
            if caregivers and self.patients:
                cid = db.x("""INSERT INTO consent_records(patient_id,kind,granted_by_name,recorded_by,scope,granted_at,note)
                              VALUES(?,?,?,?,?,?,?)""", (1, "caregiver_access", "SIMULATED CONSENT (fictional patient)",
                                                         doctor["id"] if doctor else None, json.dumps({"vitals": True, "location": True}),
                                                         now, "Created by the simulation engine for demonstration"))
                db.x("""INSERT INTO caregiver_links(patient_id,user_id,relationship,consent_id,can_view_vitals,can_view_location,notify,granted_at)
                        VALUES(?,?,?,?,?,?,?,?)""", (1, caregivers[0]["id"], "family (demo)", cid, 1, 1, 1, now))
            self.relays = [{"index": r, "received": 0, "forwarded": 0, "dropped": 0, "duplicates": 0} for r in range(cfg["relay_count"])]
            self._relay_seen = [set() for _ in self.relays]
            self.config, self.t_sim, self._queue, self._schedule = cfg, 0.0, [], []
            self.stats = {"generated": 0, "transmitted": 0, "lost_radio": 0, "lost_injected": 0, "duplicated": 0, "delayed": 0,
                          "delivered_to_gateway": 0, "relay_forwards": 0}
            svc.audit.log("simulation.reset", user, ns="simulation", detail={"patients": n, "scenario": cfg["scenario"]})
            return self.status()

    def start(self, config, user, threaded=True):
        with self._lock:
            if self.svc.store.mode() != "simulation":
                raise DomainError("switch the platform to simulation mode first", "E_STATE", 409)
            if self.state != "stopped":
                raise DomainError("simulation already running; stop it first", "E_STATE", 409)
            self.reset(config, user)
            cfg, db, now = self.config, self.svc.store.ns("simulation"), self.svc.clock()
            self.session_id = db.x("INSERT INTO sim_sessions(started_at,scenario,config,started_by,status) VALUES(?,?,?,?,?)",
                                   (now, cfg["scenario"], json.dumps(cfg), user["id"] if user else None, "running"))
            db.x("UPDATE patients SET sim_session_id=?", (self.session_id,))
            interval_real = cfg["interval_s"] / cfg["speed"]
            self.svc.monitor.sim_offline_after = max(8.0, 3.5 * interval_real)
            for i, p in enumerate(self.patients):
                p.next_tx = now + 0.5 + (i * interval_real / max(1, len(self.patients)))
            self._apply_scenario(cfg["scenario"])
            self.state, self._last_real = "running", now
            self.svc.audit.log("simulation.start", user, ns="simulation", target_type="sim_session", target_id=self.session_id,
                               detail={"scenario": cfg["scenario"], "patients": cfg["patient_count"], "speed": cfg["speed"]})
            self._publish()
            if threaded:
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, name="rpm-simulator", daemon=True)
                self._thread.start()
            return self.status()

    def pause(self, user):
        with self._lock:
            if self.state != "running":
                raise DomainError("simulation is not running", "E_STATE", 409)
            self.state = "paused"
            self.svc.audit.log("simulation.pause", user, ns="simulation", target_id=self.session_id)
            self._publish()
            return self.status()

    def resume(self, user):
        with self._lock:
            if self.state != "paused":
                raise DomainError("simulation is not paused", "E_STATE", 409)
            now = self.svc.clock()
            shift = now - self._last_real
            for p in self.patients:
                p.next_tx += shift
            self._queue = [(t + shift, n, item) for t, n, item in self._queue]
            heapq.heapify(self._queue)
            self.state, self._last_real = "running", now
            self.svc.audit.log("simulation.resume", user, ns="simulation", target_id=self.session_id)
            self._publish()
            return self.status()

    def stop(self, user=None):
        with self._lock:
            if self.state == "stopped":
                return self.status()
            self.state = "stopped"
            self._stop.set()
            self._queue = []                 # undelivered frames are discarded: nothing enters after stop
            self.svc.store.ns("simulation").x("UPDATE sim_sessions SET stopped_at=?, status='stopped' WHERE id=?",
                                              (self.svc.clock(), self.session_id))
            self.svc.audit.log("simulation.stop", user, ns="simulation", target_id=self.session_id)
            self._publish()
            return self.status()

    def trigger(self, patient_id, event, user=None):
        with self._lock:
            if self.state == "stopped":
                raise DomainError("start the simulation first", "E_STATE", 409)
            p = next((x for x in self.patients if x.patient_id == patient_id), None)
            if not p:
                raise DomainError("unknown simulated patient", "E_NOT_FOUND", 404)
            if event not in EVENTS:
                raise DomainError(f"unknown event; allowed: {', '.join(EVENTS)}")
            self._apply_event(p, event, self.t_sim)
            self.svc.audit.log("simulation.event", user, ns="simulation", target_type="patient", target_id=patient_id, detail=event)
            return self.status()

    # ---- internals -----------------------------------------------------------------------------------
    @staticmethod
    def _validate(config):
        c = dict(config or {})
        out = {"patient_count": c.get("patient_count", 3), "speed": c.get("speed", 4), "scenario": c.get("scenario", "A"),
               "interval_s": c.get("interval_s", 30), "relay_count": c.get("relay_count", 3), "seed": c.get("seed", 20261114),
               "base_loss": c.get("base_loss", 0.02), "duplicate_rate": c.get("duplicate_rate", 0.01), "delay_rate": c.get("delay_rate", 0.02)}
        for k, lo, hi, typ in (("patient_count", 1, 20, int), ("speed", 1, 60, (int, float)), ("interval_s", 5, 300, (int, float)),
                               ("relay_count", 1, 3, int), ("seed", 0, 2 ** 31, int), ("base_loss", 0, 0.9, (int, float)),
                               ("duplicate_rate", 0, 0.5, (int, float)), ("delay_rate", 0, 0.5, (int, float))):
            v = out[k]
            if isinstance(v, bool) or not isinstance(v, typ) or not lo <= v <= hi:
                raise DomainError(f"{k} must be in {lo}..{hi}")
        if out["scenario"] not in SCENARIOS:
            raise DomainError(f"scenario must be one of {', '.join(SCENARIOS)}")
        return out

    def _apply_scenario(self, s):
        P_ = self.patients
        at = lambda i: P_[min(i, len(P_) - 1)]  # noqa: E731
        plan = {"A": [], "B": [(60, at(0), "deterioration")], "C": [(45, at(1), "fall")], "D": [(60, at(0), "spo2_decline")],
                "E": [(40, at(1), "packet_loss"), (240, at(1), "disconnect")],
                "F": [(45, at(0), "deterioration"), (90, at(1), "fall"), (60, at(2), "spo2_decline")]
                     + [(120, p, "fever") for p in P_[3:5]],
                "G": [(240, at(0), "predictive_trend")]}[s]
        self._schedule = sorted(((t, p.index, p, e) for t, p, e in plan), key=lambda x: x[:2])

    def _apply_event(self, p, event, t):
        r = p.rng
        if event == "deterioration":
            p.effects.append(_Effect(event, t, 600, {"hr": r.uniform(55, 70), "spo2": -r.uniform(7, 10), "temp": r.uniform(1.4, 2.0)}))
        elif event == "spo2_decline":
            p.effects.append(_Effect(event, t, 480, {"spo2": -r.uniform(9, 12), "hr": r.uniform(10, 18)}))
        elif event == "hr_rise":
            p.effects.append(_Effect(event, t, 480, {"hr": r.uniform(60, 75)}))
        elif event == "predictive_trend":
            p.effects.append(_Effect(event, t, 900, {"hr": r.uniform(62, 72), "spo2": -r.uniform(2.0, 3.0)}))
        elif event == "fever":
            p.effects.append(_Effect(event, t, 900, {"temp": r.uniform(2.0, 2.8), "hr": r.uniform(15, 25)}))
        elif event == "fall":
            p.fall_pending = True
            p.effects.append(_Effect("post_fall", t, 5, {"hr": r.uniform(18, 28)}, hold=60, recover=240))
            p.next_tx = min(p.next_tx, self.svc.clock())          # event-triggered transmission
        elif event == "sensor_fault":
            p.fault_until = t + 120
        elif event == "disconnect":
            p.connected = False
        elif event == "reconnect":
            p.connected, p.extra_loss = True, 0.0
        elif event == "packet_loss":
            p.extra_loss = 0.5
        elif event == "recover":
            for e in p.effects:               # start the recovery phase of every active effect now
                if e.hold is not None and t > e.start + e.ramp + e.hold:
                    continue                  # already recovering
                e.delta = e.value(t)          # freeze at the current deviation ...
                e.start, e.ramp, e.hold, e.recover = t, 0, 0.0, 240   # ... and decay from there
            p.fault_until, p.extra_loss, p.connected = -1.0, 0.0, True

    def _publish(self):
        self.svc.broker.publish({"type": "simulation", "ns": "simulation", "patient_id": None,
                                 "data": {"state": self.state, "session_id": self.session_id, "sim_time_s": round(self.t_sim, 1)}})

    def _run(self):
        while not self._stop.wait(0.2):
            try:
                self.step()
            except Exception:  # noqa: BLE001
                import logging
                logging.getLogger("rpm.sim").exception("simulation step failed")

    def step(self, now=None):
        """Advance the simulation to wall-clock `now` (called by the engine thread, or directly by tests)."""
        with self._lock:
            if self.state != "running":
                return 0
            now = self.svc.clock() if now is None else now
            cfg = self.config
            self.t_sim += max(0.0, now - self._last_real) * cfg["speed"]
            self._last_real = now
            while self._schedule and self._schedule[0][0] <= self.t_sim:
                _, _, p, e = self._schedule.pop(0)
                self._apply_event(p, e, self.t_sim)
            interval_real = cfg["interval_s"] / cfg["speed"]
            n = 0
            for p in self.patients:
                if now >= p.next_tx:
                    p.next_tx = max(p.next_tx + interval_real, now) if now - p.next_tx < interval_real else now + interval_real
                    self._transmit(p, now)
                    n += 1
                if self.t_sim >= p.next_loc:
                    p.next_loc = self.t_sim + 120
                    self._move(p, now)
            while self._queue and self._queue[0][0] <= now:
                _, _, (raw, rssi, snr, tx_time, p) = heapq.heappop(self._queue)
                self._deliver(raw, rssi, snr, tx_time, p, now)
            return n

    def _move(self, p, now):
        """Small bounded random walk; coordinates are fictional and flagged source='simulated'."""
        step = p.rng.uniform(0, 12)
        ang = p.rng.uniform(0, 2 * math.pi)
        p.lat += step * math.cos(ang) / 111_320
        p.lon += step * math.sin(ang) / (111_320 * math.cos(math.radians(p.lat)))
        self.svc.store.ns("simulation").x("INSERT INTO locations(patient_id,ts,lat,lon,accuracy_m,source) VALUES(?,?,?,?,?,?)",
                                          (p.patient_id, now, p.lat, p.lon, 25.0, "simulated"))
        self.svc.broker.publish({"type": "location", "ns": "simulation", "patient_id": p.patient_id,
                                 "data": {"patient_id": p.patient_id, "lat": p.lat, "lon": p.lon, "ts": now, "source": "simulated",
                                          "accuracy_m": 25.0}})

    def _transmit(self, p, now):
        svc, cfg = self.svc, self.config
        hr, spo2, temp, fall = p.sample(self.t_sim)
        self.stats["generated"] += 1
        if not p.connected:
            return                                  # device is off: nothing is sent (the backend must notice by itself)
        p.seq += 1
        m = {"patientId": p.patient_id, "sourceId": p.device_id, "destinationId": svc.cfg.GATEWAY_ID, "seqNo": p.seq,
             "timestamp": int(now), "heartRate": hr, "spO2": spo2, "temperature": temp, "fallDetected": fall,
             "routingMode": P.ROUTE_DIRECT if p.relay_entry is None else P.ROUTE_RELAY, "hopCount": 0,
             "maxHopCount": svc.cfg.MAX_HOP_COUNT, "payloadType": P.PT_ALERT if fall else P.PT_MEASUREMENT,
             "flags": P.F_SYNTH | P.F_TIME_SYNCED, "battery": None}
        thr = effective_thresholds(svc, None)
        m["alertLevel"] = device_alert_level(m, thr)
        m["critical"] = m["alertLevel"] >= 2
        raw = P.encode(m, p.key)
        p.sent += 1
        self.stats["transmitted"] += 1
        rng = p.rng
        # hop chain: patient -> [relay r -> ... -> last relay] -> gateway
        hops = [] if p.relay_entry is None else list(range(p.relay_entry, len(self.relays)))
        delay, rssi = 0.0, None
        distances = [p.distance] if not hops else [45.0] + [52.0] * (len(hops) - 1) + [30.0]
        for h, dist in enumerate(distances):
            rssi = _rssi(dist, rng)
            if rssi < SF7_SENSITIVITY_DBM:
                self.stats["lost_radio"] += 1; return
            if rng.random() < cfg["base_loss"] + (p.extra_loss if h == 0 else 0.0):
                self.stats["lost_injected"] += 1; return
            delay += rng.uniform(0.06, 0.12)       # ~70 ms time on air for 34 bytes at SF7/125 kHz + processing
            if h < len(hops):                       # frame arrived at relay hops[h]
                relay, seen = self.relays[hops[h]], self._relay_seen[hops[h]]
                relay["received"] += 1
                key = P.dedup_key(raw)
                if key in seen:
                    relay["duplicates"] += 1; relay["dropped"] += 1; return
                try:
                    raw = P.relay_forward(raw, svc.cfg.MAX_HOP_COUNT)
                except P.FrameError:
                    relay["dropped"] += 1; return
                seen.add(key)
                if len(seen) > 4096:
                    seen.clear()
                relay["forwarded"] += 1
                self.stats["relay_forwards"] += 1
        snr = rssi - NOISE_FLOOR_DBM
        if rng.random() < cfg["delay_rate"]:
            delay += rng.uniform(1.0, 3.0) * max(1.0, cfg["interval_s"] / cfg["speed"])
            self.stats["delayed"] += 1
        copies = 2 if rng.random() < cfg["duplicate_rate"] else 1
        if copies == 2:
            self.stats["duplicated"] += 1
        for k in range(copies):
            self._n = getattr(self, "_n", 0) + 1
            heapq.heappush(self._queue, (now + delay + 0.05 * k, self._n, (raw, round(rssi, 1), round(snr, 1), now, p)))

    def _deliver(self, raw, rssi, snr, tx_time, p, now):
        self.stats["delivered_to_gateway"] += 1
        res = self.svc.pipeline.handle_frame("simulation", raw, rssi=rssi, snr=snr, received_at=now,
                                             sim_session_id=self.session_id, tx_time=tx_time)
        if res["outcome"] == "stored":
            p.delivered += 1


def attach(svc):
    svc.simulator = Simulator(svc)
    return svc.simulator
