"""Measurement ingestion pipeline - the ONLY way data enters the platform.

Real radios (hardware gateway service) and the simulation engine both call `Pipeline.handle_frame`
with raw protocol frames; they differ only in the namespace their credential maps to.

  frame -> structure + CRC -> registered & active device -> authentication tag -> routing identity
        -> replay / duplicate window -> plausibility & sensor-fault classification -> store
        -> device liveness -> threshold alerts -> local inference -> predictive alert -> live events

Outcomes that are NOT stored are still counted and logged as network events (never silently dropped).
"""
import json
import logging
import time
from collections import defaultdict, deque

from . import protocol as P
from .alert_engine import classify, effective_thresholds
from .security import unwrap
from .settings import PLAUSIBLE

log = logging.getLogger("rpm.ingest")
REPLAY_BITS = 62
CLOCK_TOLERANCE_S = 300


class Pipeline:
    def __init__(self, svc):
        self.svc = svc
        self._keys = {}
        self._auth_fail = defaultdict(lambda: deque(maxlen=20))
        self._recent_loss = defaultdict(lambda: deque(maxlen=30))   # 1 = lost, 0 = received (per device)

    # ---- helpers -------------------------------------------------------------------------------------
    @staticmethod
    def _count(c, name, n=1):
        c.execute("INSERT INTO network_counters(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=value+?", (name, n, n))

    def _event(self, ns, kind, now, device_id=None, patient_id=None, seq=None, hop=None, rssi=None, snr=None,
               latency_ms=None, detail=None, sid=None, counter=None, publish=True):
        db = self.svc.store.ns(ns)
        with db.tx() as c:
            c.execute("""INSERT INTO network_events(ts,kind,device_id,patient_id,seq_no,hop_count,rssi,snr,latency_ms,detail,sim_session_id)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (now, kind, device_id, patient_id, seq, hop, rssi, snr, latency_ms, detail, sid))
            if counter:
                self._count(c, counter)
        if publish:
            self.svc.broker.publish({"type": "network", "ns": ns, "patient_id": patient_id,
                                     "data": {"kind": kind, "device_id": device_id, "seq_no": seq, "hop_count": hop,
                                              "rssi": rssi, "snr": snr, "latency_ms": latency_ms, "detail": detail, "ts": now}})

    def device_key(self, ns, dev):
        k = (ns, dev["id"], dev["key_version"])
        if k not in self._keys:
            self._keys[k] = unwrap(self.svc.cfg.MASTER_KEY, dev["key_enc"], f"dev:{ns}:{dev['id']}".encode())
        return self._keys[k]

    # ---- entry point ---------------------------------------------------------------------------------
    def handle_frame(self, ns, raw, rssi=None, snr=None, received_at=None, sim_session_id=None, tx_time=None):
        """Process one raw v2 frame. Returns {"outcome": ..., ...}; never raises on bad input."""
        svc, now = self.svc, self.svc.clock() if received_at is None else received_at
        db = svc.store.ns(ns)
        raw = bytes(raw)
        with db.tx() as c:
            self._count(c, "frames_received")
        try:
            src = P.peek_source(raw)
        except P.CrcError:
            self._event(ns, "crc_error", now, rssi=rssi, snr=snr, sid=sim_session_id, counter="crc_errors")
            return {"outcome": "crc_error"}
        except P.FrameError as e:
            self._event(ns, "malformed", now, rssi=rssi, snr=snr, detail=str(e)[:120], sid=sim_session_id, counter="malformed")
            return {"outcome": "malformed", "detail": str(e)}
        dev = db.one("SELECT * FROM devices WHERE id=?", (src,))
        if not dev or bool(dev["is_virtual"]) != (ns == "simulation"):
            self._event(ns, "unknown_device", now, device_id=src, rssi=rssi, snr=snr, sid=sim_session_id, counter="unknown_device")
            return {"outcome": "unknown_device"}
        if dev["status"] != "active" or dev["patient_id"] is None:
            self._event(ns, "rejected", now, device_id=src, detail=f"device status {dev['status']}, not paired"
                        if dev["patient_id"] is None else f"device status {dev['status']}", sid=sim_session_id, counter="rejected")
            return {"outcome": "rejected", "detail": "device not active or not paired"}
        try:
            m = P.decode(raw, self.device_key(ns, dev))
        except P.AuthError:
            db.x("UPDATE devices SET auth_fail_count=auth_fail_count+1 WHERE id=?", (src,))
            self._event(ns, "auth_fail", now, device_id=src, patient_id=dev["patient_id"], rssi=rssi, snr=snr,
                        sid=sim_session_id, counter="auth_failures")
            fails = self._auth_fail[(ns, src)]
            fails.append(now)
            if len([t for t in fails if t > now - 60]) >= 3:
                svc.alerts.raise_alert(ns, "AUTH_FAILURES", "network", "high",
                                       f"Device {src}: repeated frames failed authentication (wrong key or injected packets)",
                                       device_id=src, sim_session_id=sim_session_id, now=now)
            return {"outcome": "auth_fail"}
        except P.FrameError as e:
            self._event(ns, "malformed", now, device_id=src, detail=str(e)[:120], sid=sim_session_id, counter="malformed")
            return {"outcome": "malformed", "detail": str(e)}
        if m["destinationId"] != svc.cfg.GATEWAY_ID or m["patientId"] != dev["patient_id"]:
            self._event(ns, "rejected", now, device_id=src, patient_id=dev["patient_id"], seq=m["seqNo"],
                        detail="routing identity mismatch (destinationId / patientId)", sid=sim_session_id, counter="rejected")
            return {"outcome": "rejected", "detail": "routing identity mismatch"}
        if m["hopCount"] > min(m["maxHopCount"], svc.cfg.MAX_HOP_COUNT):
            self._event(ns, "rejected", now, device_id=src, patient_id=dev["patient_id"], seq=m["seqNo"], hop=m["hopCount"],
                        detail="hop limit exceeded", sid=sim_session_id, counter="rejected")
            return {"outcome": "rejected", "detail": "hop limit exceeded"}
        # ---- replay / duplicate window (atomic per device) -------------------------------------------
        with db.tx() as c:
            d = c.execute("SELECT last_seq, replay_window, online FROM devices WHERE id=?", (src,)).fetchone()
            last, window, seq = d["last_seq"], d["replay_window"], m["seqNo"]
            verdict, lost, ooo = "ok", 0, 0
            if seq > last:
                shift = seq - last
                window = ((window << shift) | 1) & ((1 << REPLAY_BITS) - 1) if shift < REPLAY_BITS else 1
                lost = min(shift - 1, 10000) if last > 0 else 0
                last = seq
            elif last - seq < REPLAY_BITS:
                bit = 1 << (last - seq)
                if window & bit:
                    verdict = "duplicate"
                else:
                    window |= bit; ooo = 1; lost = -1
            else:
                verdict = "replay"
            if verdict == "ok":
                c.execute("""UPDATE devices SET last_seq=?, replay_window=?, lost_estimate=MAX(0, lost_estimate+?),
                             out_of_order_count=out_of_order_count+? WHERE id=?""", (last, window, lost, ooo, src))
                if lost > 0:
                    self._count(c, "lost_estimate", lost)
            elif verdict == "duplicate":
                c.execute("UPDATE devices SET dup_count=dup_count+1 WHERE id=?", (src,))
            else:
                c.execute("UPDATE devices SET replay_count=replay_count+1 WHERE id=?", (src,))
        hist = self._recent_loss[(ns, src)]
        if verdict != "ok":
            self._event(ns, verdict, now, device_id=src, patient_id=dev["patient_id"], seq=m["seqNo"], hop=m["hopCount"],
                        rssi=rssi, snr=snr, sid=sim_session_id, counter="duplicates" if verdict == "duplicate" else "replays")
            return {"outcome": verdict}
        hist.extend([1] * min(max(lost, 0), 30)); hist.append(0)
        if lost > 0:
            self._event(ns, "lost", now, device_id=src, patient_id=dev["patient_id"], seq=m["seqNo"],
                        detail=f"{lost} frame(s) missing before seqNo {m['seqNo']}", sid=sim_session_id)
        latency_ms = None
        if tx_time is not None:
            latency_ms = max(0.0, (now - tx_time) * 1000)
        elif m["timeSynced"] and abs(now - m["timestamp"]) <= CLOCK_TOLERANCE_S:
            latency_ms = max(0.0, (now - m["timestamp"]) * 1000)
        return self._store(ns, m, dev, now, rssi, snr, latency_ms, sim_session_id, ooo)

    # ---- validated measurement -> storage, alerts, inference -----------------------------------------
    def _store(self, ns, m, dev, now, rssi, snr, latency_ms, sid, out_of_order, data_source=None, key_epoch=None):
        svc, db = self.svc, self.svc.store.ns(ns)
        pid, src = dev["patient_id"], dev["id"]
        patient = db.one("SELECT * FROM patients WHERE id=?", (pid,))
        # timestamps: UTC internally. Device clock is trusted only when it says it is synchronized AND is plausible.
        ts, notes = now, []
        if m["timeSynced"]:
            if abs(now - m["timestamp"]) <= CLOCK_TOLERANCE_S:
                ts = float(m["timestamp"])
            else:
                notes.append("device clock outside tolerance; gateway time used")
        # plausibility: a value outside hard physical limits is a sensor problem, not a physiological reading
        quality, implausible = "ok", []
        for name in ("heartRate", "spO2", "temperature"):
            v = m[name]
            if v is not None and not PLAUSIBLE[name][0] <= v <= PLAUSIBLE[name][1]:
                implausible.append(f"{name}={v:g}"); m[name] = None
        faults = [lbl for bit, lbl in ((P.F_HRSPO2_FAULT, "HR/SpO2 sensor"), (P.F_TEMP_FAULT, "temperature sensor"),
                                       (P.F_IMU_FAULT, "motion sensor")) if m["flags"] & bit]
        if implausible:
            quality = "implausible"
        elif faults:
            quality = "sensor_fault" if m["heartRate"] is None and m["temperature"] is None else "partial"
        is_meas = m["payloadType"] in (P.PT_MEASUREMENT, P.PT_ALERT)
        mid = None
        with db.tx() as c:
            if is_meas:
                cur = c.execute("""INSERT OR IGNORE INTO measurements(patient_id,device_id,seq_no,ts,device_ts,received_at,heart_rate,
                    spo2,temperature,fall_detected,alert_level,routing_mode,source_id,destination_id,hop_count,max_hop_count,
                    payload_type,critical,flags,battery,rssi,snr,quality,data_source,sim_session_id,key_epoch)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (pid, src, m["seqNo"], ts, m["timestamp"], now, m["heartRate"], m["spO2"], m["temperature"],
                                 int(m["fallDetected"]), m["alertLevel"], m["routingMode"], src, m["destinationId"] or svc.cfg.GATEWAY_ID,
                                 m["hopCount"], m["maxHopCount"], m["payloadType"], int(m["critical"]), m["flags"], m["battery"],
                                 rssi, snr, quality, data_source or ("simulation" if ns == "simulation" else "hardware"), sid,
                                 key_epoch or dev["key_version"]))
                if cur.rowcount == 0:
                    c.execute("UPDATE devices SET dup_count=dup_count+1 WHERE id=?", (src,))
                    self._count(c, "duplicates")
                    return {"outcome": "duplicate"}
                mid = cur.lastrowid
            c.execute("""UPDATE devices SET last_seen_at=?, online=1, rx_count=rx_count+1, last_rssi=?, last_snr=?,
                         last_battery=COALESCE(?, last_battery), last_hop_count=?, last_routing_mode=?,
                         latency_ms_sum=latency_ms_sum+?, latency_n=latency_n+? WHERE id=?""",
                      (now, rssi, snr, m["battery"], m["hopCount"], m["routingMode"], latency_ms or 0.0, 1 if latency_ms is not None else 0, src))
            self._count(c, "valid")
            self._count(c, "relay_assisted" if m["hopCount"] > 0 else "direct")
            if out_of_order:
                self._count(c, "out_of_order")
        self._event(ns, "rx", now, device_id=src, patient_id=pid, seq=m["seqNo"], hop=m["hopCount"], rssi=rssi, snr=snr,
                    latency_ms=latency_ms, detail="; ".join(notes) or None, sid=sid)
        if not dev["online"]:
            self._event(ns, "online", now, device_id=src, patient_id=pid, sid=sid)
            svc.alerts.system_resolve(ns, pid, src, "DEVICE_OFFLINE", "device communication restored")
            svc.broker.publish({"type": "device", "ns": ns, "patient_id": pid, "data": {"device_id": src, "online": True, "ts": now}})
        result = {"outcome": "stored" if is_meas else "heartbeat", "measurement_id": mid, "patient_id": pid, "alerts": [], "prediction": None}
        if not is_meas:
            return result
        public = {"id": mid, "patient_id": pid, "device_id": src, "seq_no": m["seqNo"], "ts": ts, "received_at": now,
                  "heart_rate": m["heartRate"], "spo2": m["spO2"], "temperature": m["temperature"],
                  "fall_detected": int(m["fallDetected"]), "alert_level": m["alertLevel"], "routing_mode": m["routingMode"],
                  "hop_count": m["hopCount"], "critical": int(m["critical"]), "battery": m["battery"], "rssi": rssi, "snr": snr,
                  "quality": quality, "latency_ms": latency_ms}
        svc.broker.publish({"type": "measurement", "ns": ns, "patient_id": pid, "data": public})
        # ---- immediate alerts (threshold / fall / sensor / data quality) ------------------------------
        thr = effective_thresholds(svc, patient)
        conditions = classify(m, thr)
        for atype, cat, sev, msg in conditions:
            a = svc.alerts.raise_alert(ns, atype, cat, sev, msg, patient_id=pid, device_id=src, measurement_id=mid,
                                       sim_session_id=sid, now=now)
            if a: result["alerts"].append(atype)
        if faults:
            a = svc.alerts.raise_alert(ns, "SENSOR_FAULT", "sensor", "warning", "Device reports a fault on: " + ", ".join(faults),
                                       patient_id=pid, device_id=src, measurement_id=mid, sim_session_id=sid, now=now)
            if a: result["alerts"].append("SENSOR_FAULT")
        if implausible:
            a = svc.alerts.raise_alert(ns, "IMPLAUSIBLE_VALUE", "data_quality", "warning",
                                       "Physically implausible value(s) discarded: " + ", ".join(implausible),
                                       patient_id=pid, device_id=src, measurement_id=mid, sim_session_id=sid, now=now)
            if a: result["alerts"].append("IMPLAUSIBLE_VALUE")
        hist = self._recent_loss[(ns, src)]
        if len(hist) >= 20 and sum(hist) / len(hist) >= 0.3:
            svc.alerts.raise_alert(ns, "NETWORK_DEGRADED", "network", "warning",
                                   f"Device {src}: {100 * sum(hist) / len(hist):.0f} % of recent frames were lost",
                                   patient_id=pid, device_id=src, sim_session_id=sid, now=now)
        # ---- local inference --------------------------------------------------------------------------
        result["prediction"] = self._predict(ns, pid, mid, ts, now, sid, breaching=any(c[1] == "threshold" for c in conditions))
        return result

    def _predict(self, ns, pid, mid, ts, now, sid, breaching):
        svc, db = self.svc, self.svc.store.ns(ns)
        rows = db.q("""SELECT ts, heart_rate AS hr, spo2, temperature AS temp, fall_detected AS fall FROM measurements
                       WHERE patient_id=? AND ts>=? AND ts<=? ORDER BY ts""", (pid, ts - svc.cfg.PREDICT_LOOKBACK_S, ts))
        p = svc.predictor.predict(rows, ts)
        prid = db.x("""INSERT INTO predictions(patient_id,measurement_id,ts,model_name,model_version,prediction_type,status,score,
                       probability,threshold,risk_category,explanation,supporting,latency_ms,sim_session_id)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (pid, mid, ts, p["model_name"], p["model_version"], p["prediction_type"], p["status"], p["score"], p["probability"],
                     p["threshold"], p["risk_category"], json.dumps(p["explanation"]), json.dumps(p["supporting"]), p["latency_ms"], sid))
        pub = {"id": prid, "patient_id": pid, "ts": ts, "status": p["status"], "score": p["score"], "probability": p["probability"],
               "risk_category": p["risk_category"], "model_version": p["model_version"], "explanation": p["explanation"],
               "latency_ms": round(p["latency_ms"], 3)}
        svc.broker.publish({"type": "prediction", "ns": ns, "patient_id": pid, "data": pub})
        if p["status"] == "ok" and p["risk_category"] == "high" and not breaching and svc.cfg.PREDICTIVE_ALERTS:
            top = "; ".join(f"{e['label']} = {e['value']}" for e in p["explanation"][:3] if e["contribution"] > 0)
            svc.alerts.raise_alert(ns, "PREDICTED_DETERIORATION", "predictive", "warning",
                                   "Model estimates an elevated risk that a vital-sign threshold is crossed within ~10 minutes"
                                   + (f" (main factors: {top})" if top else ""),
                                   patient_id=pid, measurement_id=mid, prediction_id=prid, sim_session_id=sid, now=now)
        return pub

    # ---- legacy 16-byte v1 packets (no device id, no authentication) ---------------------------------
    def handle_v1(self, raw, rssi=None, snr=None, received_at=None):
        """Accepted only in the hardware namespace, only when RPM_ALLOW_LEGACY_V1=1, only for a patient that
        has exactly one active paired device. Stored with data_source = 'legacy_v1' (unauthenticated)."""
        svc, ns, now = self.svc, "hardware", self.svc.clock() if received_at is None else received_at
        if not svc.cfg.ALLOW_LEGACY_V1:
            return {"outcome": "rejected", "detail": "legacy v1 packets are disabled"}
        try:
            m = P.from_v1(bytes(raw))
        except P.V1.CrcError:
            self._event(ns, "crc_error", now, counter="crc_errors"); return {"outcome": "crc_error"}
        except P.V1.PacketError as e:
            self._event(ns, "malformed", now, detail=str(e)[:120], counter="malformed"); return {"outcome": "malformed"}
        db = svc.store.ns(ns)
        devs = db.q("SELECT * FROM devices WHERE patient_id=? AND status='active' AND is_virtual=0", (m["patientId"],))
        if len(devs) != 1:
            self._event(ns, "unknown_device", now, patient_id=m["patientId"], counter="unknown_device")
            return {"outcome": "unknown_device"}
        dev = devs[0]
        m.update(sourceId=dev["id"], destinationId=svc.cfg.GATEWAY_ID, seqNo=(m["timestamp"] << 16) | m["seqNo"])
        with db.tx() as c:
            self._count(c, "frames_received")
        return self._store(ns, m, dev, now, rssi, snr, None, None, 0, data_source="legacy_v1", key_epoch=0)


class Monitor:
    """Periodic housekeeping: device liveness, alert escalation, pruning. `tick()` is also called by tests."""

    def __init__(self, svc):
        self.svc = svc
        self.sim_offline_after = None      # set by the simulation engine (scaled to its sampling interval)
        self._last_prune = 0.0

    def offline_after(self, ns):
        return self.sim_offline_after if ns == "simulation" and self.sim_offline_after else self.svc.cfg.DEVICE_OFFLINE_AFTER_S

    def tick(self, now=None):
        svc, now = self.svc, self.svc.clock() if now is None else now
        changed = 0
        for ns in ("hardware", "simulation"):
            db = svc.store.ns(ns)
            for d in db.q("SELECT id, patient_id, last_seen_at FROM devices WHERE online=1 AND last_seen_at<?",
                          (now - self.offline_after(ns),)):
                db.x("UPDATE devices SET online=0 WHERE id=?", (d["id"],))
                svc.pipeline._event(ns, "offline", now, device_id=d["id"], patient_id=d["patient_id"],
                                    detail=f"no valid frame for {now - d['last_seen_at']:.0f} s", counter="offline_events")
                svc.broker.publish({"type": "device", "ns": ns, "patient_id": d["patient_id"],
                                    "data": {"device_id": d["id"], "online": False, "ts": now}})
                svc.alerts.raise_alert(ns, "DEVICE_OFFLINE", "device", "high",
                                       f"No valid communication from device {d['id']} for {now - d['last_seen_at']:.0f} s",
                                       patient_id=d["patient_id"], device_id=d["id"], now=now)
                changed += 1
            changed += svc.alerts.escalate_overdue(ns, now)
            if now - self._last_prune > 300:
                keep = svc.cfg.NETWORK_EVENT_KEEP
                db.x("DELETE FROM network_events WHERE id <= (SELECT MAX(id) FROM network_events) - ?", (keep,))
        if now - self._last_prune > 300:
            self._last_prune = now
            svc.store.system.x("DELETE FROM sessions WHERE expires_at<? OR revoked=1", (now - 86400,))
        return changed

    def run_forever(self, stop_event, interval=2.0):
        while not stop_event.wait(interval):
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("monitor tick failed")


def retention(svc, ns, now=None):
    """Delete measurements/predictions/network events older than RETENTION_DAYS. Returns rows removed."""
    now = time.time() if now is None else now
    cutoff = now - svc.cfg.RETENTION_DAYS * 86400
    db = svc.store.ns(ns)
    n = 0
    for table in ("predictions", "measurements", "network_events"):
        n += db.x(f"DELETE FROM {table} WHERE ts<?", (cutoff,)) or 0
    return n
