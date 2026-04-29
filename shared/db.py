"""SQLite-backed registry for the multi-app infrastructure.

Mirrors the shape of Sultan's claude-assistant/dashboards/shared/db.py but
adapted for Flask demo apps (working_dir, env_vars, healthcheck_url columns
that streamlit-only setups don't need).
"""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("INFRA_DB", HERE / "state" / "infra.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _conn():
    c = sqlite3.connect(str(DB_PATH), timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


@contextmanager
def conn():
    c = _conn()
    try:
        yield c
    finally:
        c.close()


def init_schema():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS apps (
            name           TEXT PRIMARY KEY,
            port           INTEGER NOT NULL UNIQUE,
            script         TEXT    NOT NULL,
            working_dir    TEXT    NOT NULL,
            env_vars       TEXT    NOT NULL DEFAULT '{}',  -- JSON
            healthcheck    TEXT    NOT NULL DEFAULT '/healthz',
            auto_start     INTEGER NOT NULL DEFAULT 1,
            max_restarts   INTEGER NOT NULL DEFAULT 5,
            description    TEXT    NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS app_state (
            name           TEXT PRIMARY KEY REFERENCES apps(name) ON DELETE CASCADE,
            pid            INTEGER,
            started_at     REAL,
            last_heartbeat REAL,
            status         TEXT NOT NULL DEFAULT 'stopped',  -- stopped|starting|running|crashloop
            restart_count  INTEGER NOT NULL DEFAULT 0,
            last_error     TEXT
        );
        """)


def list_apps():
    with conn() as c:
        rows = c.execute("""
            SELECT a.*, s.pid, s.started_at, s.last_heartbeat, s.status, s.restart_count, s.last_error
            FROM apps a LEFT JOIN app_state s ON a.name = s.name
            ORDER BY a.name
        """).fetchall()
        return [dict(r) for r in rows]


def get_app(name):
    with conn() as c:
        r = c.execute("""
            SELECT a.*, s.pid, s.started_at, s.last_heartbeat, s.status, s.restart_count, s.last_error
            FROM apps a LEFT JOIN app_state s ON a.name = s.name
            WHERE a.name = ?
        """, (name,)).fetchone()
        return dict(r) if r else None


def upsert_app(name, port, script, working_dir, env_vars=None, healthcheck="/healthz",
               auto_start=1, max_restarts=5, description=""):
    env_json = json.dumps(env_vars or {})
    with conn() as c:
        c.execute("""
            INSERT INTO apps (name, port, script, working_dir, env_vars, healthcheck, auto_start, max_restarts, description)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
                port=excluded.port, script=excluded.script, working_dir=excluded.working_dir,
                env_vars=excluded.env_vars, healthcheck=excluded.healthcheck,
                auto_start=excluded.auto_start, max_restarts=excluded.max_restarts,
                description=excluded.description
        """, (name, port, script, working_dir, env_json, healthcheck, auto_start, max_restarts, description))
        c.execute("INSERT OR IGNORE INTO app_state (name) VALUES (?)", (name,))


def remove_app(name):
    with conn() as c:
        c.execute("DELETE FROM apps WHERE name = ?", (name,))


def set_state(name, **kw):
    if not kw:
        return
    cols = ",".join(f"{k}=?" for k in kw)
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO app_state (name) VALUES (?)", (name,))
        c.execute(f"UPDATE app_state SET {cols} WHERE name = ?", (*kw.values(), name))


def heartbeat(name):
    set_state(name, last_heartbeat=time.time())


def set_auto_start(name, on: bool):
    with conn() as c:
        c.execute("UPDATE apps SET auto_start = ? WHERE name = ?", (1 if on else 0, name))


def next_free_port(start=18000, end=18999):
    """Pick a port in [start, end] not already used by a registered app."""
    with conn() as c:
        used = {r[0] for r in c.execute("SELECT port FROM apps").fetchall()}
    for p in range(start, end + 1):
        if p not in used:
            return p
    raise RuntimeError(f"no free ports in [{start}, {end}]")


if __name__ == "__main__":
    init_schema()
    print(f"[db init] {DB_PATH}")
    for a in list_apps():
        print(f"  {a['name']:20s} port={a['port']} status={a.get('status')}")
