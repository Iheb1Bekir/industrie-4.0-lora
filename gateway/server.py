"""RPM platform v2 server: REST API v1 + real-time stream + web application.

Run (development):  python -m gateway.server
Run (production):   RPM_ENV=production python -m gateway.server      (served by waitress, behind an HTTPS reverse proxy)

The legacy pre-MVP API (gateway.app, bearer tokens, /api/vitals) is unchanged and still runnable on its own;
it is NOT mounted here (see docs/ARCHITECTURE.md, "Legacy compatibility").
"""
import logging
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import simulator
from .api_v1 import bp as api_bp
from .security import err
from .services import Services
from .settings import PlatformConfig

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: https://tile.openstreetmap.org https://*.tile.openstreetmap.org; "
       "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


def create_server(cfg=None, clock=time.time, background=False):
    cfg = cfg or PlatformConfig.from_env()
    app = Flask(__name__, static_folder=str(WEB / "assets"), static_url_path="/assets")
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    svc = Services(cfg, clock)
    simulator.attach(svc)
    app.config["SERVICES"] = svc
    app.register_blueprint(api_bp)

    @app.get("/")
    def index():
        return send_from_directory(str(WEB), "index.html")

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "time": svc.clock()})

    @app.errorhandler(404)
    def _404(e):
        return err("not found", "E_NOT_FOUND", 404)

    @app.errorhandler(405)
    def _405(e):
        return err("method not allowed", "E_METHOD", 405)

    @app.errorhandler(413)
    def _413(e):
        return err("request body too large", "E_TOO_LARGE", 413)

    @app.errorhandler(500)
    def _500(e):
        logging.getLogger("rpm").exception("unhandled error")
        return err("internal server error", "E_INTERNAL", 500)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        if cfg.production:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp

    if background:
        stop = threading.Event()
        app.config["STOP_EVENT"] = stop
        threading.Thread(target=svc.monitor.run_forever, args=(stop,), name="rpm-monitor", daemon=True).start()
    return app


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = PlatformConfig.from_env()
    app = create_server(cfg, background=True)
    svc = app.config["SERVICES"]
    n_users = svc.store.system.scalar("SELECT COUNT(*) FROM users")
    log = logging.getLogger("rpm")
    log.info("RPM platform starting: env=%s mode=%s model=%s users=%s", cfg.ENV, svc.store.mode(),
             svc.predictor.status()["model_version"] or "none loaded", n_users)
    if not n_users:
        log.warning("No user account exists. Create one:  python -m gateway.manage create-user --role doctor --admin   "
                    "(or, development only:  python -m gateway.manage seed-demo)")
    if cfg.production:
        from waitress import serve
        serve(app, host=cfg.HOST, port=cfg.PORT, threads=16, channel_timeout=120)
    else:
        app.run(host=cfg.HOST, port=cfg.PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
