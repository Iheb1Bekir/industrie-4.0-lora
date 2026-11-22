"""Render the HTML design frames to PNG (and the carousel to PDF) with headless Microsoft Edge over the DevTools protocol.

Stdlib only. Usage (from the repository root):
  python site/tools/render_media.py frames site/design/media.html site/design/out
  python site/tools/render_media.py pdf site/design/carousel.html site/design/out/carousel.pdf
"""
import base64, json, os, shutil, socket, struct, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


class WS:
    def __init__(self, url):
        hostport, path = url[len("ws://"):].split("/", 1)
        host, port = hostport.split(":")
        self.s = socket.create_connection((host, int(port)), timeout=120)
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
        hdr = bytes([0x80 | op]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n)
                                     if n < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", n))
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
        raise RuntimeError(json.dumps(r["exceptionDetails"])[:400])
    return r["result"].get("value")


def open_page(ws, url, w, h, scale=1):
    ws.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=scale, mobile=False)
    ws.call("Page.navigate", url=url)
    for _ in range(200):
        time.sleep(0.1)
        if ev(ws, "document.readyState") == "complete":
            break
    ev(ws, "(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.complete?1:new Promise(r=>{i.onload=i.onerror=r})));return 1})()")
    time.sleep(0.4)


def jpeg_size(data):
    """(width, height) from the first SOF marker of a JPEG."""
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker, seg = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + seg
    raise ValueError("no SOF marker")


def write_image_pdf(path, jpgs, w_pt, h_pt, title=""):
    """Minimal PDF 1.4: one full-page DCT (JPEG) image per page, page size w_pt x h_pt points."""
    buf, offs = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), {}

    def add(oid, body):
        offs[oid] = len(buf)
        buf.extend(f"{oid} 0 obj\n".encode() + body + b"\nendobj\n")

    n = len(jpgs)
    pages = [3 + 3 * k for k in range(n)]
    add(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    add(2, f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in pages)}] /Count {n} >>".encode())
    for pid, data in zip(pages, jpgs):
        w, h = jpeg_size(data)
        add(pid, (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w_pt:g} {h_pt:g}] "
                  f"/Resources << /XObject << /Im0 {pid + 2} 0 R >> >> /Contents {pid + 1} 0 R >>").encode())
        draw = f"q {w_pt:g} 0 0 {h_pt:g} 0 0 cm /Im0 Do Q".encode()
        add(pid + 1, f"<< /Length {len(draw)} >>\nstream\n".encode() + draw + b"\nendstream")
        add(pid + 2, (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB "
                      f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(data)} >>\nstream\n").encode() + data + b"\nendstream")
    info = 3 * n + 3
    safe = "".join(c for c in title if 32 <= ord(c) < 127 and c not in "()\\")
    add(info, f"<< /Title ({safe}) /Producer (site/tools/render_media.py) >>".encode())
    xref = len(buf)
    buf.extend(f"xref\n0 {info + 1}\n0000000000 65535 f \n".encode())
    buf.extend("".join(f"{offs[k]:010d} 00000 n \n" for k in range(1, info + 1)).encode())
    buf.extend(f"trailer\n<< /Size {info + 1} /Root 1 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    Path(path).write_bytes(bytes(buf))


class Edge:
    """A private headless Edge: its own temp profile and a free DevTools port (read from DevToolsActivePort, so it never
    talks to another instance). stop() closes it, kills whatever is left of it and deletes the profile."""

    def __init__(self):
        self.prof = tempfile.mkdtemp(prefix="rpm-edge-")
        self.proc = subprocess.Popen([EDGE, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={self.prof}",
                                      "--no-first-run", "--disable-extensions", "--hide-scrollbars",
                                      "--allow-file-access-from-files", "--force-color-profile=srgb",
                                      "--disable-background-mode", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.port = self.browser_path = None

    def connect(self):
        active = Path(self.prof) / "DevToolsActivePort"
        for _ in range(150):
            try:
                port, path = active.read_text().split()[:2]
                self.port, self.browser_path = int(port), path
                break
            except (OSError, ValueError):
                if self.proc.poll() is not None:
                    raise RuntimeError(f"Edge exited with code {self.proc.returncode}")
                time.sleep(0.2)
        else:
            raise RuntimeError("Edge did not open its DevTools port")
        pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=5))
        ws = WS(next(t for t in pages if t["type"] == "page")["webSocketDebuggerUrl"])
        ws.call("Page.enable")
        return ws

    def stop(self):
        if self.port:
            try:  # Browser.close belongs to the browser target, not to a page.
                WS(f"ws://127.0.0.1:{self.port}{self.browser_path}").call("Browser.close")
            except Exception:
                pass
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True)
            else:
                self.proc.kill()
        if os.name == "nt":  # Edge can outlive the launched process: kill anything still using this profile.
            prof = self.prof.replace("'", "''")
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
                            f"Where-Object {{ $_.CommandLine -like '*{prof}*' }} | "
                            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
                           capture_output=True)
        for _ in range(20):
            shutil.rmtree(self.prof, ignore_errors=True)
            if not os.path.exists(self.prof):
                break
            time.sleep(0.5)
        else:
            print("warning: could not delete", self.prof, file=sys.stderr)


def main():
    mode, html, out = sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    url = html.as_uri()
    edge = Edge()
    try:
        ws = edge.connect()
        if mode == "frames":
            out.mkdir(parents=True, exist_ok=True)
            open_page(ws, url, 1080, 1080)
            frames = ev(ws, "window.__frames")
            only = set(sys.argv[4].split(",")) if len(sys.argv) > 4 else None
            for fid, (w, h) in frames.items():
                if only and fid not in only:
                    continue
                open_page(ws, f"{url}?f={fid}", w, h)
                png = ws.call("Page.captureScreenshot", format="png", clip={"x": 0, "y": 0, "width": w, "height": h, "scale": 1})["data"]
                (out / f"{fid}.png").write_bytes(base64.b64decode(png))
                print("frame", fid, w, h, flush=True)
        elif mode == "pdf":
            # One page at a time (?p=N): a 1080 x 1350 PNG preview, then a 2x JPEG for the PDF. The PDF is assembled
            # from those images, so it looks exactly like the previews (headless printing is not available everywhere).
            out.parent.mkdir(parents=True, exist_ok=True)
            open_page(ws, url, 1080, 1350)
            n = ev(ws, "document.querySelectorAll('.page').length")
            clip = {"x": 0, "y": 0, "width": 1080, "height": 1350, "scale": 1}
            jpgs = []
            for i in range(1, n + 1):
                open_page(ws, f"{url}?p={i}", 1080, 1350)
                png = ws.call("Page.captureScreenshot", format="png", clip=clip)["data"]
                (out.parent / f"carousel-{i:02d}.png").write_bytes(base64.b64decode(png))
                open_page(ws, f"{url}?p={i}", 1080, 1350, scale=2)
                jpgs.append(base64.b64decode(ws.call("Page.captureScreenshot", format="jpeg", quality=90, clip=clip)["data"]))
            write_image_pdf(out, jpgs, 810, 1012.5, title=ev(ws, "document.title"))
            print("pdf", out.name, n, "pages,", out.stat().st_size // 1024, "KiB", flush=True)
    finally:
        edge.stop()


if __name__ == "__main__":
    main()
