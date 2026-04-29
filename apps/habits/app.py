"""Demo app: Habit streak tracker. Flask + sqlite + HTML."""
import os, sqlite3, time
from pathlib import Path
from flask import Flask, jsonify, request, render_template

HERE = Path(__file__).resolve().parent
DB = HERE / "data.db"
APPLICATION_ROOT = os.environ.get("APPLICATION_ROOT", "")


def _conn():
    c = sqlite3.connect(str(DB)); c.row_factory = sqlite3.Row; return c


def _init():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            streak INTEGER DEFAULT 0,
            last_done REAL DEFAULT 0)""")


_init()
app = Flask(__name__, template_folder=str(HERE / "templates"))
app.config["APPLICATION_ROOT"] = APPLICATION_ROOT


@app.get("/")
def index(): return render_template("index.html", base=APPLICATION_ROOT)


@app.get("/healthz")
def healthz(): return {"ok": True, "app": "habits"}


@app.get("/api/habits")
def list_habits():
    with _conn() as c:
        return jsonify(habits=[dict(r) for r in c.execute("SELECT * FROM habits ORDER BY name").fetchall()])


@app.post("/api/habits")
def add_habit():
    name = (request.json or {}).get("name", "").strip()
    if not name: return {"error": "name required"}, 400
    with _conn() as c:
        try: cur = c.execute("INSERT INTO habits (name) VALUES (?)", (name,))
        except sqlite3.IntegrityError: return {"error": "already exists"}, 409
    return {"id": cur.lastrowid, "name": name, "streak": 0}


@app.post("/api/habits/<int:hid>/check")
def check_habit(hid):
    now = time.time()
    with _conn() as c:
        h = c.execute("SELECT * FROM habits WHERE id=?", (hid,)).fetchone()
        if not h: return {"error": "not found"}, 404
        gap = now - (h["last_done"] or 0)
        # If checked within 36h, streak continues; otherwise reset to 1
        new_streak = (h["streak"] + 1) if 0 < gap < 60*60*36 else 1
        c.execute("UPDATE habits SET streak=?, last_done=? WHERE id=?", (new_streak, now, hid))
    return {"ok": True, "streak": new_streak}


@app.delete("/api/habits/<int:hid>")
def delete_habit(hid):
    with _conn() as c: c.execute("DELETE FROM habits WHERE id=?", (hid,))
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("APP_PORT", "18002")), debug=False)
