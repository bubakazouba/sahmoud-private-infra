"""Demo app: Todo list. Flask backend + sqlite DB + minimal HTML frontend."""
import os
import sqlite3
from pathlib import Path
from flask import Flask, jsonify, request, render_template

HERE = Path(__file__).resolve().parent
DB = HERE / "data.db"
APPLICATION_ROOT = os.environ.get("APPLICATION_ROOT", "")


def _conn():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    return c


def _init():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL, done INTEGER DEFAULT 0,
            created_at REAL DEFAULT (strftime('%s','now')))""")


_init()
app = Flask(__name__, template_folder=str(HERE / "templates"))
app.config["APPLICATION_ROOT"] = APPLICATION_ROOT


@app.get("/")
def index():
    return render_template("index.html", base=APPLICATION_ROOT)


@app.get("/healthz")
def healthz():
    return {"ok": True, "app": "todo"}


@app.get("/api/items")
def list_items():
    with _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM items ORDER BY created_at DESC").fetchall()]
    return jsonify(items=rows)


@app.post("/api/items")
def add_item():
    text = (request.json or {}).get("text", "").strip()
    if not text:
        return {"error": "text required"}, 400
    with _conn() as c:
        cur = c.execute("INSERT INTO items (text) VALUES (?)", (text,))
        new_id = cur.lastrowid
    return {"id": new_id, "text": text, "done": 0}


@app.put("/api/items/<int:item_id>")
def update_item(item_id):
    body = request.json or {}
    with _conn() as c:
        c.execute("UPDATE items SET done = ? WHERE id = ?", (1 if body.get("done") else 0, item_id))
    return {"ok": True}


@app.delete("/api/items/<int:item_id>")
def delete_item(item_id):
    with _conn() as c:
        c.execute("DELETE FROM items WHERE id = ?", (item_id,))
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", "18001"))
    app.run(host="127.0.0.1", port=port, debug=False)
