"""Demo app: Reading log (book + pages_read / total_pages with progress bar)."""
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
        c.execute("""CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, author TEXT DEFAULT '',
            pages_read INTEGER DEFAULT 0, total_pages INTEGER NOT NULL,
            created_at REAL DEFAULT (strftime('%s','now')))""")


_init()
app = Flask(__name__, template_folder=str(HERE / "templates"))
app.config["APPLICATION_ROOT"] = APPLICATION_ROOT


@app.get("/")
def index(): return render_template("index.html", base=APPLICATION_ROOT)


@app.get("/healthz")
def healthz(): return {"ok": True, "app": "reading"}


@app.get("/api/books")
def list_books():
    with _conn() as c:
        return jsonify(books=[dict(r) for r in c.execute("SELECT * FROM books ORDER BY created_at DESC").fetchall()])


@app.post("/api/books")
def add_book():
    b = request.json or {}
    title = (b.get("title") or "").strip()
    author = (b.get("author") or "").strip()
    try: total = int(b.get("total_pages") or 0)
    except (TypeError, ValueError): return {"error": "total_pages must be int"}, 400
    if not title or total <= 0: return {"error": "title + total_pages required"}, 400
    with _conn() as c:
        cur = c.execute("INSERT INTO books (title, author, total_pages) VALUES (?,?,?)", (title, author, total))
    return {"id": cur.lastrowid, "title": title, "author": author, "pages_read": 0, "total_pages": total}


@app.put("/api/books/<int:bid>")
def update_book(bid):
    b = request.json or {}
    try: pages = int(b.get("pages_read") or 0)
    except (TypeError, ValueError): return {"error": "pages_read must be int"}, 400
    with _conn() as c:
        c.execute("UPDATE books SET pages_read=? WHERE id=?", (max(0, pages), bid))
    return {"ok": True}


@app.delete("/api/books/<int:bid>")
def delete_book(bid):
    with _conn() as c: c.execute("DELETE FROM books WHERE id=?", (bid,))
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("APP_PORT", "18005")), debug=False)
