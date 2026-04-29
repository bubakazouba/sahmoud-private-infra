"""Demo app: Expense log. Flask + sqlite + HTML with category aggregation."""
import os, sqlite3, datetime
from pathlib import Path
from flask import Flask, jsonify, request, render_template

HERE = Path(__file__).resolve().parent
DB = HERE / "data.db"
APPLICATION_ROOT = os.environ.get("APPLICATION_ROOT", "")


def _conn():
    c = sqlite3.connect(str(DB)); c.row_factory = sqlite3.Row; return c


def _init():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL, category TEXT NOT NULL DEFAULT 'misc',
            note TEXT DEFAULT '', date TEXT NOT NULL)""")


_init()
app = Flask(__name__, template_folder=str(HERE / "templates"))
app.config["APPLICATION_ROOT"] = APPLICATION_ROOT


@app.get("/")
def index(): return render_template("index.html", base=APPLICATION_ROOT)


@app.get("/healthz")
def healthz(): return {"ok": True, "app": "expenses"}


@app.get("/api/expenses")
def list_expenses():
    with _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM expenses ORDER BY date DESC, id DESC").fetchall()]
        totals = {r[0]: r[1] for r in c.execute("SELECT category, SUM(amount) FROM expenses GROUP BY category").fetchall()}
    return jsonify(expenses=rows, totals=totals)


@app.post("/api/expenses")
def add_expense():
    b = request.json or {}
    try: amount = float(b.get("amount") or 0)
    except (TypeError, ValueError): return {"error": "amount must be a number"}, 400
    if amount <= 0: return {"error": "amount must be > 0"}, 400
    cat = (b.get("category") or "misc").strip()
    note = (b.get("note") or "").strip()
    date = (b.get("date") or datetime.date.today().isoformat()).strip()
    with _conn() as c:
        cur = c.execute("INSERT INTO expenses (amount, category, note, date) VALUES (?,?,?,?)", (amount, cat, note, date))
    return {"id": cur.lastrowid, "amount": amount, "category": cat, "note": note, "date": date}


@app.delete("/api/expenses/<int:eid>")
def delete_expense(eid):
    with _conn() as c: c.execute("DELETE FROM expenses WHERE id=?", (eid,))
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("APP_PORT", "18004")), debug=False)
