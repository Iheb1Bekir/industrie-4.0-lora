"""Capture real screenshots of the running RPM dashboard (http://localhost:8000) with headless Edge over CDP.

Stdlib only (minimal WebSocket client). Logs in with the local demo doctor account read from the git-ignored
data/demo_credentials.txt (the password is never printed), runs simulation scenario F so the pages show data, captures
pages, then stops the simulation and restores the previous operating mode.
usage: python capture_dashboard.py <out_dir> <demo_credentials.txt> <work_dir>
"""
import base64, json, os, socket, struct, subprocess, sys, time, urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT, BASE, W, H = 9333, "http://localhost:8000", 1280, 860
out_dir, creds_path, work = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out_dir, exist_ok=True)


class WS:
    def __init__(self, url):
        hostport, path = url[len("ws://"):].split("/", 1)
        host, port = hostport.split(":")
        self.s = socket.create_connection((host, int(port)), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        head, self.rest = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise RuntimeError(head[:200])
        self.id = 0

    def _exact(self, n):
        while len(self.rest) < n:
            chunk = self.s.recv(1 << 20)
            if not chunk:
                raise ConnectionError("socket closed")
            self.rest += chunk
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def _send(self, payload, op=0x1):
        mask, n = os.urandom(4), len(payload)
        hdr = bytes([0x80 | op]) + (bytes([0x80 | n]) if n < 126 else
                                     bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                                     bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _recv(self):
        data = b""
        while True:
            b0, b1 = self._exact(2)
            ln = b1 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._exact(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._exact(8))[0]
            if b1 & 0x80:
                self._exact(4)
            payload, op = self._exact(ln), b0 & 0x0F
            if op == 0x9:
                self._send(payload, 0xA)
                continue
            if op == 0x8:
                raise ConnectionError("websocket closed")
            data += payload
            if b0 & 0x80:
                return json.loads(data.decode())

    def call(self, method, **params):
        self.id += 1
        mid = self.id
        self._send(json.dumps({"id": mid, "method": method, "params": params}).encode())
        while True:
            m = self._recv()
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})


def ev(ws, expr):
    r = ws.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
    if r.get("exceptionDetails"):
        raise RuntimeError(json.dumps(r["exceptionDetails"])[:500])
    return r["result"].get("value")


def api(ws, csrf, method, path, body=None):
    js = (f"(async()=>{{const r=await fetch('/api/v1{path}',{{method:{json.dumps(method)},headers:{{'Content-Type':'application/json',"
          f"'X-CSRF-Token':{json.dumps(csrf)}}}{',body:' + json.dumps(json.dumps(body)) if body is not None else ''}}});"
          f"let b=null;try{{b=await r.json()}}catch(e){{}};return {{status:r.status,body:b}};}})()")
    return ev(ws, js)


def wait_load(ws, extra=3.0):
    for _ in range(100):
        if ev(ws, "document.readyState") == "complete":
            break
        time.sleep(0.2)
    time.sleep(extra)


def capture(ws, name, height=None):
    if height is None:
        height = ev(ws, "(()=>{const v=document.querySelector('#view');const a=document.documentElement.scrollHeight;"
                        "const b=v?v.getBoundingClientRect().top+v.scrollHeight:0;return Math.min(2400,Math.max(a,b));})()")
    ws.call("Emulation.setDeviceMetricsOverride", width=W, height=int(max(H, height)), deviceScaleFactor=2, mobile=False)
    time.sleep(2.0)
    data = ws.call("Page.captureScreenshot", format="png")["data"]
    with open(os.path.join(out_dir, name), "wb") as f:
        f.write(base64.b64decode(data))
    ws.call("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=2, mobile=False)
    print("captured", name, int(max(H, height)), flush=True)


def main():
    creds = {}
    with open(creds_path, encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                role, user, pw = line.split()[:3]
                creds[role] = (user, pw)
    user, pw = creds["doctor"]
    proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={os.path.join(work, 'edge-profile')}",
                             "--no-first-run", "--disable-extensions", "--hide-scrollbars", f"--window-size={W},{H}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    prev_mode, csrf, ws = None, None, None
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=2).read()
                break
            except Exception:
                time.sleep(0.2)
        pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=5))
        ws = WS(next(t for t in pages if t["type"] == "page")["webSocketDebuggerUrl"])
        ws.call("Page.enable")
        ws.call("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=2, mobile=False)
        ws.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
        ws.call("Page.navigate", url=BASE + "/")
        wait_load(ws, 1.0)
        ev(ws, "localStorage.setItem('rpm-theme','light')")
        login = ev(ws, "(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},"
                       f"body:JSON.stringify({{username:{json.dumps(user)},password:{json.dumps(pw)}}})}});const j=await r.json();"
                       "return {status:r.status,csrf:j.csrf_token,mode:j.mode,mcp:!!(j.user&&j.user.must_change_password),err:j.error||null};})()")
        csrf, prev_mode = login.get("csrf"), login.get("mode")
        print("login", login["status"], "mode", prev_mode, "must_change", login["mcp"], login["err"], flush=True)
        if login["status"] != 200:
            return
        if prev_mode != "simulation":
            print("mode->simulation", api(ws, csrf, "POST", "/system/mode", {"mode": "simulation"})["status"], flush=True)
        st = api(ws, csrf, "GET", "/simulation")["body"]["simulation"]["state"]
        if st != "stopped":
            api(ws, csrf, "POST", "/simulation/stop", {})
        r = api(ws, csrf, "POST", "/simulation/start", {"patient_count": 8, "scenario": "F", "speed": 30, "interval_s": 30})
        print("sim start", r["status"], flush=True)
        time.sleep(110)                                     # ~55 simulated minutes at speed 30
        ev(ws, "location.hash='#/overview'")
        ws.call("Page.reload", ignoreCache=True)
        wait_load(ws, 6.0)
        capture(ws, "dash_overview.png", 1100)
        pts = api(ws, csrf, "GET", "/patients")["body"]
        items = pts["patients"] if isinstance(pts, dict) else pts
        print("patients", json.dumps(items)[:1500], flush=True)
        ids = sorted(p["id"] for p in items)
        for pid in ids[:3]:
            ev(ws, f"location.hash='#/patient/{pid}'")
            time.sleep(7)
            capture(ws, f"dash_patient_{pid}.png")
        for route in ("alerts", "network", "ai", "map", "simulation"):
            ev(ws, f"location.hash='#/{route}'")
            time.sleep(8 if route == "map" else 6)
            capture(ws, f"dash_{route}.png")
    finally:
        if ws and csrf:
            try:
                print("sim stop", api(ws, csrf, "POST", "/simulation/stop", {})["status"])
                if prev_mode and prev_mode != "simulation":
                    print("mode restore", prev_mode, api(ws, csrf, "POST", "/system/mode", {"mode": prev_mode})["status"])
                api(ws, csrf, "POST", "/auth/logout", {})
            except Exception as e:  # noqa: BLE001
                print("cleanup error", e)
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
