"""CLI for the multi-app infra.

Usage:
  python manage.py list
  python manage.py register <name> <script> [--port N] [--working-dir DIR] [--no-auto-start]
  python manage.py start <name>
  python manage.py stop <name>
  python manage.py restart <name>
  python manage.py reset <name>          # clear crashloop state
  python manage.py logs <name> [N]
  python manage.py rm <name>
  python manage.py supervisor start|stop|status
  python manage.py console start|stop|status
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from shared import db

STATE = HERE / "state"
STATE.mkdir(parents=True, exist_ok=True)


def cmd_list(args):
    db.init_schema()
    apps = db.list_apps()
    if not apps:
        print("(no apps registered)")
        return
    print(f"{'name':20s} {'port':>6s} {'status':12s} {'restart':>7s} {'description'}")
    for a in apps:
        print(f"{a['name']:20s} {a['port']:>6d} {(a.get('status') or '-'):12s} "
              f"{a.get('restart_count') or 0:>7d} {a.get('description') or ''}")


def cmd_register(args):
    db.init_schema()
    port = args.port or db.next_free_port()
    abs_script = str(Path(args.script).resolve())
    wd = args.working_dir or str(Path(abs_script).parent)
    db.upsert_app(
        name=args.name, port=port, script=abs_script, working_dir=wd,
        env_vars={}, healthcheck=args.healthcheck, auto_start=0 if args.no_auto_start else 1,
        max_restarts=args.max_restarts, description=args.description or "",
    )
    print(f"[registered] {args.name} on port {port}, script={abs_script}")


def cmd_start(args):
    db.set_auto_start(args.name, True)
    print(f"[start] auto_start enabled for {args.name}; supervisor will spawn within 10s")


def cmd_stop(args):
    db.set_auto_start(args.name, False)
    a = db.get_app(args.name)
    if a and a.get("pid"):
        try:
            import psutil
            psutil.Process(a["pid"]).terminate()
            print(f"[stop] killed pid {a['pid']}")
        except Exception as e:
            print(f"[stop] could not kill pid {a['pid']}: {e}")
    db.set_state(args.name, status="stopped")


def cmd_restart(args):
    a = db.get_app(args.name)
    if a and a.get("pid"):
        try:
            import psutil
            psutil.Process(a["pid"]).terminate()
            print(f"[restart] killed pid {a['pid']}; supervisor will respawn within 10s")
        except Exception as e:
            print(f"[restart] could not kill pid {a['pid']}: {e}")
    db.set_state(args.name, status="stopped", restart_count=0)


def cmd_reset(args):
    db.set_state(args.name, status="stopped", restart_count=0, last_error=None)
    print(f"[reset] {args.name} crashloop cleared")


def cmd_logs(args):
    log = STATE / f"{args.name}.log"
    if not log.exists():
        print(f"(no logs for {args.name})")
        return
    n = args.n or 50
    text = log.read_text(encoding="utf-8", errors="replace")
    print("\n".join(text.splitlines()[-n:]))


def cmd_rm(args):
    db.remove_app(args.name)
    print(f"[removed] {args.name}")


# --- service helpers (supervisor + control plane themselves) ---------------

def _svc_pidfile(svc):
    return STATE / f"{svc}.pid"


def _read_pid(svc):
    f = _svc_pidfile(svc)
    if not f.exists():
        return None
    try:
        return int(f.read_text().strip())
    except Exception:
        return None


def _is_alive(pid):
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except Exception:
        return False


def _svc_start(svc, script):
    pid = _read_pid(svc)
    if _is_alive(pid):
        print(f"[{svc}] already running pid={pid}")
        return
    log = STATE / f"{svc}.log"
    fp = open(log, "ab")
    p = subprocess.Popen(
        [sys.executable, "-u", str(HERE / script)],
        cwd=str(HERE), stdout=fp, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    _svc_pidfile(svc).write_text(str(p.pid))
    print(f"[{svc}] started pid={p.pid}, log={log}")


def _svc_stop(svc):
    pid = _read_pid(svc)
    if not _is_alive(pid):
        print(f"[{svc}] not running")
        return
    try:
        import psutil
        psutil.Process(pid).terminate()
        print(f"[{svc}] terminated pid={pid}")
    except Exception as e:
        print(f"[{svc}] kill failed: {e}")


def _svc_status(svc):
    pid = _read_pid(svc)
    if _is_alive(pid):
        print(f"[{svc}] running pid={pid}")
    else:
        print(f"[{svc}] not running")


def cmd_supervisor(args):
    {"start": lambda: _svc_start("supervisor", "supervisor.py"),
     "stop":  lambda: _svc_stop("supervisor"),
     "status": lambda: _svc_status("supervisor"),
     "restart": lambda: (_svc_stop("supervisor"), time.sleep(1), _svc_start("supervisor", "supervisor.py")),
     }[args.action]()


def cmd_console(args):
    {"start": lambda: _svc_start("console", "control_plane.py"),
     "stop":  lambda: _svc_stop("console"),
     "status": lambda: _svc_status("console"),
     "restart": lambda: (_svc_stop("console"), time.sleep(1), _svc_start("console", "control_plane.py")),
     }[args.action]()


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    r = sub.add_parser("register"); r.set_defaults(func=cmd_register)
    r.add_argument("name"); r.add_argument("script")
    r.add_argument("--port", type=int); r.add_argument("--working-dir")
    r.add_argument("--no-auto-start", action="store_true")
    r.add_argument("--max-restarts", type=int, default=5)
    r.add_argument("--healthcheck", default="/healthz")
    r.add_argument("--description", default="")

    for cmd in ("start", "stop", "restart", "reset", "rm"):
        c = sub.add_parser(cmd); c.set_defaults(func=globals()[f"cmd_{cmd}"])
        c.add_argument("name")

    l = sub.add_parser("logs"); l.set_defaults(func=cmd_logs)
    l.add_argument("name"); l.add_argument("n", type=int, nargs="?")

    for svc in ("supervisor", "console"):
        s = sub.add_parser(svc); s.set_defaults(func=globals()[f"cmd_{svc}"])
        s.add_argument("action", choices=["start", "stop", "status", "restart"])

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
