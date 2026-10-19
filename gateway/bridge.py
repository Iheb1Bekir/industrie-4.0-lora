"""Gateway: transport -> decode/validate -> duplicate + loss tracking -> API forwarder."""
import json
import logging
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field, asdict

from . import telemetry as T
from .radio import Transport

log = logging.getLogger("gateway")


@dataclass
class Stats:
    received: int = 0
    forwarded: int = 0
    duplicates: int = 0
    crc_errors: int = 0
    malformed: int = 0
    api_rejected: int = 0
    api_errors: int = 0
    lost_estimate: int = 0   # from sequence gaps; per node, modulo 65536
    per_node: dict = field(default_factory=dict)

    def loss_rate(self):
        tot = self.received - self.duplicates - self.crc_errors - self.malformed + self.lost_estimate
        return self.lost_estimate / tot if tot > 0 else 0.0


class HttpForwarder:
    """POST payload to the Flask API. Returns (status, body_dict). Never logs the token."""
    def __init__(self, base_url, token, timeout=5):
        self.url, self.token, self.timeout = base_url.rstrip("/") + "/api/vitals", token, timeout

    def __call__(self, payload):
        req = urllib.request.Request(self.url, json.dumps(payload).encode(), {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: body = json.loads(e.read() or b"{}")
            except ValueError: body = {}
            return e.code, body
        except (urllib.error.URLError, TimeoutError) as e:
            return 0, {"error": str(e)}


class Gateway:
    def __init__(self, transport: Transport, forward, source="sim-serial", clock=time.time):
        self.transport, self.forward, self.source, self.clock = transport, forward, source, clock
        self.stats, self._last_seq, self._seen = Stats(), {}, {}

    def _track(self, t: T.Telemetry):
        """Returns True if duplicate. Updates loss estimate from sequence gaps."""
        seen = self._seen.setdefault(t.pid, deque(maxlen=64))
        key = (t.seq, t.uptime_s)
        if key in seen:
            return True
        seen.append(key)
        last = self._last_seq.get(t.pid)
        if last is not None:
            gap = (t.seq - last) & 0xFFFF
            if 1 < gap < 0x8000:
                self.stats.lost_estimate += gap - 1
            if gap >= 0x8000:   # older/out-of-order packet: do not move the pointer back
                return False
        self._last_seq[t.pid] = t.seq
        return False

    def handle(self, raw: bytes):
        """Process one raw payload. Returns outcome string."""
        s = self.stats
        s.received += 1
        try:
            t = T.decode(raw)
        except T.CrcError as e:
            s.crc_errors += 1; log.warning("dropped packet: %s", e); return "crc_error"
        except T.PacketError as e:
            s.malformed += 1; log.warning("dropped packet: %s (%s)", e, e.code); return "malformed"
        if self._track(t):
            s.duplicates += 1; return "duplicate"
        n = s.per_node.setdefault(t.pid, {"packets": 0, "last_seq": None})
        n["packets"] += 1; n["last_seq"] = t.seq
        status, body = self.forward(T.to_api_payload(t, int(self.clock()), self.source))
        if status in (200, 201):
            s.forwarded += 1; return "forwarded" if body.get("stored", True) else "api_duplicate"
        if status == 0 or status >= 500:
            s.api_errors += 1; log.error("API unreachable/error (%s)", status); return "api_error"
        s.api_rejected += 1; log.warning("API rejected packet: %s %s", status, body.get("code")); return "api_rejected"

    def run(self, max_idle=None):
        """Receive until the finite source ends (simulation) or forever (hardware)."""
        while True:
            try:
                raw = self.transport.receive(1.0)
            except EOFError:
                break
            if raw is not None:
                self.handle(raw)
        return asdict(self.stats)
