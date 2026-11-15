"""Administration CLI.

  python -m gateway.manage create-user --role doctor --admin --username dr.smith --name "Dr Smith"
        (password is asked interactively; it is never taken from the command line)
  python -m gateway.manage seed-demo          DEVELOPMENT ONLY: three demo accounts with random passwords,
                                              written to data/demo_credentials.txt (git-ignored)
  python -m gateway.manage set-mode simulation|hardware
  python -m gateway.manage verify-audit
  python -m gateway.manage backup DIR         consistent online copies of the three databases
  python -m gateway.manage retention          delete clinical rows older than RPM_RETENTION_DAYS
  python -m gateway.manage gen-key            print a new RPM_MASTER_KEY / gateway token
"""
import argparse
import base64
import getpass
import os
import secrets
import sqlite3
import sys
import time

from .ingest import retention
from .services import Services
from .settings import PlatformConfig

DEMO = [("dr.demo", "doctor", True, "Dr. Demo (demo account)"), ("assistant.demo", "assistant", False, "Assistant Demo (demo account)"),
        ("family.demo", "caregiver", False, "Family Demo (demo account)")]


def _gen_password():
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(3)) + "!7"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("create-user")
    cu.add_argument("--role", required=True, choices=["doctor", "assistant", "caregiver"])
    cu.add_argument("--username", required=True); cu.add_argument("--name", default="")
    cu.add_argument("--admin", action="store_true"); cu.add_argument("--email"); cu.add_argument("--phone")
    sub.add_parser("seed-demo")
    sm = sub.add_parser("set-mode"); sm.add_argument("mode", choices=["simulation", "hardware"])
    sub.add_parser("verify-audit")
    bk = sub.add_parser("backup"); bk.add_argument("dir")
    sub.add_parser("retention")
    sub.add_parser("gen-key")
    a = ap.parse_args(argv)

    if a.cmd == "gen-key":
        print("RPM_MASTER_KEY=" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
        print("RPM_GATEWAY_INGEST_TOKEN=" + secrets.token_urlsafe(32))
        return 0
    cfg = PlatformConfig.from_env()
    svc = Services(cfg)
    if a.cmd == "create-user":
        pw = getpass.getpass("Password: ")
        if pw != getpass.getpass("Repeat password: "):
            print("passwords do not match", file=sys.stderr); return 2
        try:
            uid = svc.auth.create_user(a.username, pw, a.role, a.name or a.username, is_admin=a.admin, email=a.email, phone=a.phone)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr); return 2
        svc.audit.log("user.create", None, "user", uid, detail={"role": a.role, "is_admin": a.admin, "via": "cli"}, ip="cli")
        print(f"created user {a.username} (id {uid}, role {a.role}{', administrator' if a.admin else ''})")
    elif a.cmd == "seed-demo":
        if cfg.production:
            print("refused: demo accounts cannot be created when RPM_ENV=production", file=sys.stderr); return 2
        path, lines = os.path.join(cfg.DATA_DIR, "demo_credentials.txt"), []
        for username, role, admin, name in DEMO:
            if svc.store.system.one("SELECT 1 FROM users WHERE username=?", (username,)):
                print(f"{username}: already exists (password unchanged)"); continue
            pw = _gen_password()
            uid = svc.auth.create_user(username, pw, role, name, is_admin=admin, is_demo=True)
            svc.audit.log("user.create", None, "user", uid, detail={"role": role, "demo": True, "via": "cli"}, ip="cli")
            lines.append(f"{role:<10} {username:<16} {pw}")
        if lines:
            with open(path, "a") as f:
                f.write("# DEVELOPMENT DEMO ACCOUNTS - generated %s - never use in production\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
                f.write("\n".join(lines) + "\n")
            print(f"{len(lines)} demo account(s) created. Credentials written to {path} (git-ignored).")
    elif a.cmd == "set-mode":
        svc.store.set_setting("operating_mode", a.mode)
        svc.audit.log("system.mode_switch", None, detail={"to": a.mode, "via": "cli"}, ip="cli")
        print("operating mode:", a.mode)
    elif a.cmd == "verify-audit":
        ok, n, bad = svc.audit.verify()
        print(f"audit chain {'OK' if ok else 'BROKEN at id ' + str(bad)} ({n} entries)")
        return 0 if ok else 1
    elif a.cmd == "backup":
        os.makedirs(a.dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for name, db in (("system", svc.store.system), ("hardware", svc.store.ns("hardware")), ("simulation", svc.store.ns("simulation"))):
            dst = os.path.join(a.dir, f"rpm_{name}_{stamp}.sqlite3")
            src, out = sqlite3.connect(db.path), sqlite3.connect(dst)
            with out:
                src.backup(out)
            src.close(); out.close()
            print("backup written:", dst)
    elif a.cmd == "retention":
        for ns in ("hardware", "simulation"):
            print(f"{ns}: removed {retention(svc, ns)} rows older than {cfg.RETENTION_DAYS} days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
