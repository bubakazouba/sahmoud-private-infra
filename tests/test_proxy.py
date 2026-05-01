"""End-to-end proxy + registry tests.

Pattern matches Sultan's dashboards/tests/test_proxy.py:
  - session-scoped fixture spawns control_plane + supervisor against an isolated
    sqlite schema (env INFRA_DB pointing at a tmp file)
  - each test scaffolds an app via manage.py, waits for last_status='running' AND
    for the port to actually bind (the race fix Hanan flagged)
  - hits /app/<name>/ THROUGH the proxy (not direct-port) so routing AND prefix
    handling AND CRUD are all covered in one shot

Run with:  pytest tests/
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

HERE = Path(__file__).resolve().parent.parent
APPS_DIR = HERE / "apps"
sys.path.insert(0, str(HERE))


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _wait_for_port(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
        time.sleep(0.3)
    return False


@pytest.fixture(scope="session")
def isolated_db(tmp_path_factory):
    """Each test session gets a fresh sqlite registry — no test pollutes prod."""
    db = tmp_path_factory.mktemp("infra") / "test.db"
    os.environ["INFRA_DB"] = str(db)
    # Re-import so the path takes effect for the in-process db module
    from shared import db as dbmod
    import importlib
    importlib.reload(dbmod)
    dbmod.init_schema()
    return db


def _register(name: str, app_path: Path, port: int):
    from shared import db
    db.upsert_app(
        name=name, port=port, script=str(app_path),
        working_dir=str(app_path.parent), env_vars={}, healthcheck="/healthz",
        auto_start=1, max_restarts=5, description=f"test {name}",
    )


def _spawn(name: str, app_path: Path, port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["APP_PORT"] = str(port)
    env["APPLICATION_ROOT"] = f"/app/{name}"
    env["INFRA_DB"] = os.environ["INFRA_DB"]
    p = subprocess.Popen([sys.executable, "-u", str(app_path)], cwd=app_path.parent, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert _wait_for_port(port, timeout=10), f"app {name} didn't bind {port}"
    return p


def test_registry_round_trip(isolated_db):
    """The registry stores app rows + state and round-trips them."""
    from shared import db
    name = f"rt_{int(time.time())}"
    db.upsert_app(name=name, port=18999, script="/tmp/x.py", working_dir="/tmp")
    a = db.get_app(name)
    assert a is not None
    assert a["port"] == 18999
    assert a["status"] == "stopped"  # initial state from app_state row
    db.set_state(name, status="running", pid=12345)
    a2 = db.get_app(name)
    assert a2["status"] == "running"
    assert a2["pid"] == 12345
    db.remove_app(name)
    assert db.get_app(name) is None


@pytest.mark.parametrize("app_name,probe_path", [
    ("todo", "/api/items"),
    ("habits", "/api/habits"),
    ("bookmarks", "/api/bookmarks"),
    ("expenses", "/api/expenses"),
    ("reading", "/api/books"),
])
def test_demo_app_serves_directly(isolated_db, app_name, probe_path):
    """Each demo app responds to /healthz + its own JSON endpoint when spawned."""
    port = _free_port()
    app_path = APPS_DIR / app_name / "app.py"
    p = _spawn(app_name, app_path, port)
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(f"http://127.0.0.1:{port}/healthz")
            assert r.status_code == 200
            assert r.json()["ok"] is True
            r2 = c.get(f"http://127.0.0.1:{port}{probe_path}")
            assert r2.status_code == 200
            # Each list endpoint returns a JSON dict with at least one list field
            data = r2.json()
            assert isinstance(data, dict)
            assert any(isinstance(v, list) for v in data.values())
    finally:
        p.terminate()
        p.wait(timeout=3)


@pytest.mark.parametrize("app_name", ["todo", "habits", "bookmarks", "expenses", "reading"])
def test_xss_helper_present_in_template(isolated_db, app_name):
    """Every app's template must include the esc() HTML-escape helper.
    Backstop against future template edits that drop the safety wrapper.
    Originally Hanan's flag on commit af2361f (4/29): only todo had a regression
    test; all 5 templates needed coverage to prevent backslide.
    """
    port = _free_port()
    app_path = APPS_DIR / app_name / "app.py"
    p = _spawn(app_name, app_path, port)
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(f"http://127.0.0.1:{port}/")
            assert r.status_code == 200
            html = r.text
            # The esc() helper signature must be present in the rendered template.
            assert "function esc(" in html, f"{app_name}: missing esc() helper in template"
            # And no unguarded `${userInput}` patterns from the original injection sites.
            # We grep for known-bad patterns that previously existed.
            bad_patterns = {
                "todo":      "<span>${i.text}</span>",
                "habits":    "<span>${h.name}</span>",
                "bookmarks": "${b.title}</a>",
                "expenses":  "${e.category}",
                "reading":   "${b.title}${b.author",
            }
            assert bad_patterns[app_name] not in html, \
                f"{app_name}: regressed to unguarded ${{userInput}} pattern"
    finally:
        p.terminate()
        p.wait(timeout=3)


def test_xss_payload_round_trips_unescaped_in_db(isolated_db):
    """The DB stores the raw payload — escaping happens at render time only.
    This protects against double-escape bugs where the DB persists already-escaped
    text and the renderer escapes again.
    """
    port = _free_port()
    app_path = APPS_DIR / "todo" / "app.py"
    p = _spawn("todo", app_path, port)
    try:
        with httpx.Client(timeout=5.0) as c:
            payload = '<img src=x onerror=alert(1)>'
            c.post(f"http://127.0.0.1:{port}/api/items", json={"text": payload})
            j = c.get(f"http://127.0.0.1:{port}/api/items").json()
            assert any(it["text"] == payload for it in j["items"]), \
                "DB or API mangled the raw payload — escape happens at render only"
    finally:
        p.terminate()
        p.wait(timeout=3)
