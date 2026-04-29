"""Long-running supervisor: spawns + monitors child apps registered in db.

Loop (every 10s):
  1. Pull all apps with auto_start=1 from db.
  2. For each: check if its pid is alive AND its port is bound.
  3. If not: spawn it via subprocess.Popen with env vars + working_dir.
  4. Track restart_count + last restart time. After max_restarts within 60s,
     mark status='crashloop' and stop respawning until manually reset.
  5. Update last_heartbeat on success.

Run:  python supervisor.py
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from shared import db

POLL_INTERVAL = 10
CRASHLOOP_WINDOW = 60  # seconds
HEARTBEAT_PORT_TIMEOUT = 1.0


def _port_bound(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(HEARTBEAT_PORT_TIMEOUT)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except Exception:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def spawn(a: dict) -> int:
    """Launch a child app. Returns the spawned PID."""
    env = os.environ.copy()
    env_extra = json.loads(a.get("env_vars") or "{}")
    env.update(env_extra)
    env["APP_NAME"] = a["name"]
    env["APP_PORT"] = str(a["port"])
    env["APPLICATION_ROOT"] = f"/app/{a['name']}"
    env["INFRA_DB"] = str(db.DB_PATH)

    log_path = HERE / "state" / f"{a['name']}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(log_path, "ab")

    cmd = [sys.executable, "-u", a["script"]]
    p = subprocess.Popen(
        cmd,
        cwd=a["working_dir"],
        env=env,
        stdout=log_fp, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    return p.pid


def tick():
    apps = [a for a in db.list_apps() if a.get("auto_start")]
    for a in apps:
        name, port, status = a["name"], a["port"], a.get("status")
        pid = a.get("pid")
        alive = _pid_alive(pid) and _port_bound(port)

        if alive:
            db.set_state(name, status="running", last_heartbeat=time.time(), last_error=None)
            continue

        if status == "crashloop":
            continue  # operator must reset

        max_restarts = a.get("max_restarts") or 5
        restart_count = a.get("restart_count") or 0
        now = time.time()
        last_started = a.get("started_at") or 0
        # Reset restart counter if last start was > CRASHLOOP_WINDOW ago
        if now - last_started > CRASHLOOP_WINDOW:
            restart_count = 0

        if restart_count >= max_restarts:
            db.set_state(name, status="crashloop",
                         last_error=f"exceeded {max_restarts} restarts within {CRASHLOOP_WINDOW}s")
            print(f"[crashloop] {name}: giving up after {restart_count} restarts")
            continue

        try:
            new_pid = spawn(a)
            db.set_state(name, pid=new_pid, started_at=now, status="starting",
                         restart_count=restart_count + 1, last_error=None)
            print(f"[spawn] {name} pid={new_pid} (restart {restart_count + 1}/{max_restarts})")
        except Exception as e:
            db.set_state(name, status="stopped", last_error=str(e),
                         restart_count=restart_count + 1)
            print(f"[spawn-failed] {name}: {e}")


def main():
    db.init_schema()
    print(f"[supervisor] up. polling every {POLL_INTERVAL}s. db={db.DB_PATH}")
    while True:
        try:
            tick()
        except Exception as e:
            print(f"[tick error] {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
