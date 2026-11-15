"""In-process publish/subscribe used for Server-Sent Events (real-time dashboard updates).

Every subscriber supplies a `view(event) -> event | None` function built from the user's server-side
permissions; an event is delivered only if the view returns something (possibly a reduced copy).
"""
import json
import queue
import threading


class Broker:
    def __init__(self, max_queue=1000):
        self._subs, self._lock, self._max = {}, threading.Lock(), max_queue
        self._next = 0
        self.published = self.dropped = 0

    def subscribe(self, view):
        q = queue.Queue(self._max)
        with self._lock:
            self._next += 1
            sid = self._next
            self._subs[sid] = (q, view)
        return sid, q

    def unsubscribe(self, sid):
        with self._lock:
            self._subs.pop(sid, None)

    def publish(self, event):
        """event: {"type": str, "ns": "hardware"|"simulation"|None, "patient_id": int|None, "user_id": int|None, "data": {...}}"""
        self.published += 1
        with self._lock:
            subs = list(self._subs.values())
        for q, view in subs:
            try:
                out = view(event)
            except Exception:  # noqa: BLE001 - a broken view must never block publishing
                out = None
            if out is None:
                continue
            try:
                q.put_nowait(out)
            except queue.Full:
                self.dropped += 1

    def subscriber_count(self):
        with self._lock:
            return len(self._subs)


def sse_format(event):
    return f"event: {event['type']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"
