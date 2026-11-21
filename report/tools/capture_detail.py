"""Second capture: patient detail during scenario G (predictive warning), charts zoomed to the simulated period.
usage: python capture_detail.py <out_dir> <demo_credentials.txt> <work_dir>   (same args as capture_dashboard.py)"""
import json, os, subprocess, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capture_dashboard as C  # noqa: E402  (parses the same argv)


def main():
    creds = {}
    with open(C.creds_path, encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                role, user, pw = line.split()[:3]
                creds[role] = (user, pw)
    user, pw = creds["doctor"]
    proc = subprocess.Popen([C.EDGE, "--headless=new", f"--remote-debugging-port={C.PORT}", f"--user-data-dir={os.path.join(C.work, 'edge-profile')}",
                             "--no-first-run", "--disable-extensions", "--hide-scrollbars", f"--window-size={C.W},{C.H}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws, csrf = None, None
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{C.PORT}/json/version", timeout=2).read()
                break
            except Exception:
                time.sleep(0.2)
        pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{C.PORT}/json/list", timeout=5))
        ws = C.WS(next(t for t in pages if t["type"] == "page")["webSocketDebuggerUrl"])
        ws.call("Page.enable")
        ws.call("Emulation.setDeviceMetricsOverride", width=C.W, height=C.H, deviceScaleFactor=2, mobile=False)
        ws.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
        ws.call("Page.navigate", url=C.BASE + "/")
        C.wait_load(ws, 1.0)
        ev = C.ev
        ev(ws, "localStorage.setItem('rpm-theme','light')")
        login = ev(ws, "(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},"
                       f"body:JSON.stringify({{username:{json.dumps(user)},password:{json.dumps(pw)}}})}});const j=await r.json();"
                       "return {status:r.status,csrf:j.csrf_token,mode:j.mode};})()")
        csrf = login.get("csrf")
        print("login", login["status"], "mode", login["mode"], flush=True)
        if login["status"] != 200 or login["mode"] != "simulation":
            return
        if C.api(ws, csrf, "GET", "/simulation")["body"]["simulation"]["state"] != "stopped":
            C.api(ws, csrf, "POST", "/simulation/stop", {})
        t0 = time.time()
        r = C.api(ws, csrf, "POST", "/simulation/start", {"patient_count": 6, "scenario": "G", "speed": 10, "interval_s": 30})
        print("sim start", r["status"], flush=True)
        time.sleep(235)                    # 39 simulated minutes; trend starts at 4 min and ramps over 15 min
        ev(ws, "location.hash='#/patient/1'")
        ws.call("Page.reload", ignoreCache=True)
        C.wait_load(ws, 6.0)
        ok = ev(ws, "(async()=>{document.querySelector('#rangeSeg button[data-r=custom]').click();await new Promise(r=>setTimeout(r,400));"
                    "const iso=(d)=>new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,16);"
                    "const f=document.querySelector('.modal-bg form');if(!f)return false;"
                    f"f.elements.from.value=iso(new Date({int(t0 * 1000)}));f.elements.to.value=iso(new Date(Date.now()+60000));"
                    "f.requestSubmit();return true;})()")
        print("custom range", ok, flush=True)
        time.sleep(4)
        C.capture(ws, "dash_patient_G.png")
        ev(ws, "(()=>{const b=document.querySelector('#tabs button[data-t=predictions]');if(b)b.click();return !!b;})()")
        time.sleep(4)
        C.capture(ws, "dash_patient_G_pred.png")
    finally:
        if ws and csrf:
            try:
                print("sim stop", C.api(ws, csrf, "POST", "/simulation/stop", {})["status"])
                C.api(ws, csrf, "POST", "/auth/logout", {})
            except Exception as e:  # noqa: BLE001
                print("cleanup error", e)
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
