"""Demo app: Bookmarks (title + URL + tag). Flask + sqlite + HTML."""
import os, sqlite3
from pathlib import Path
from flask import Flask, jsonify, request, render_template

HERE = Path(__file__).resolve().parent
DB = HERE / "data.db"
APPLICATION_ROOT = os.environ.get("APPLICATION_ROOT", "")


def _conn():
    c = sqlite3.connect(str(DB)); c.row_factory = sqlite3.Row; return c


def _init():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, url TEXT NOT NULL, tag TEXT DEFAULT '',
            created_at REAL DEFAULT (strftime('%s','now')))""")


_init()
app = Flask(__name__, template_folder=str(HERE / "templates"))
app.config["APPLICATION_ROOT"] = APPLICATION_ROOT


@app.get("/")
def index(): return render_template("index.html", base=APPLICATION_ROOT)


@app.get("/healthz")
def healthz(): return {"ok": True, "app": "bookmarks"}


@app.get("/api/bookmarks")
def list_bookmarks():
    with _conn() as c:
        return jsonify(bookmarks=[dict(r) for r in c.execute("SELECT * FROM bookmarks ORDER BY created_at DESC").fetchall()])


@app.post("/api/bookmarks")
def add_bookmark():
    b = request.json or {}
    title, url, tag = b.get("title", "").strip(), b.get("url", "").strip(), b.get("tag", "").strip()
    if not title or not url: return {"error": "title and url required"}, 400
    with _conn() as c:
        cur = c.execute("INSERT INTO bookmarks (title, url, tag) VALUES (?,?,?)", (title, url, tag))
    return {"id": cur.lastrowid, "title": title, "url": url, "tag": tag}


@app.delete("/api/bookmarks/<int:bid>")
def delete_bookmark(bid):
    with _conn() as c: c.execute("DELETE FROM bookmarks WHERE id=?", (bid,))
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("APP_PORT", "18003")), debug=False)
