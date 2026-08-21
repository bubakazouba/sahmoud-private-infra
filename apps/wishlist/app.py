"""Wishlist app — Sahmoud + Preksha shared 'things we want to do' list,
with the ability to pull items from the todo app DB via a searchable dropdown.
Served behind the OAuth-gated proxy."""
import json, os, tempfile, urllib.request
from pathlib import Path
from flask import Flask, send_from_directory, request, jsonify

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
WISHLIST = STATIC / "wishlist.json"
TODO_API = "https://solutionbanks.com/api/items?token=aKuGNU4WiERVR6Acpp--Q1FycR0jXR4rdE0vT9JYn_0"

app = Flask(__name__)

@app.get("/")
def index():
    return send_from_directory(str(STATIC), "index.html")

@app.get("/healthz")
def healthz():
    return {"ok": True, "app": "wishlist"}

@app.get("/api/todo-items")
def todo_items():
    """Proxy the todo app's items (server-side, avoids CORS) for the dropdown."""
    try:
        with urllib.request.urlopen(TODO_API, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        items = data if isinstance(data, list) else data.get("items", [])
        slim = [{"id": it.get("id"), "name": it.get("name", ""),
                 "folder": it.get("folder_path", "")} for it in items if it.get("name")]
        return jsonify(slim)
    except Exception as e:
        return jsonify({"error": str(e)[:120]}), 502

@app.get("/api/wishlist")
def get_wishlist():
    if WISHLIST.exists():
        return send_from_directory(str(STATIC), "wishlist.json")
    return jsonify({"items": []})

@app.post("/api/wishlist")
def save_wishlist():
    body = request.get_json(silent=True) or {}
    items = body.get("items")
    if not isinstance(items, list):
        return jsonify({"error": "items must be a list"}), 400
    payload = {"items": items}
    fd, tmp = tempfile.mkstemp(dir=str(STATIC), suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, str(WISHLIST))
    return jsonify(payload)

@app.get("/<path:p>")
def static_files(p):
    return send_from_directory(str(STATIC), p)

if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", "18030"))
    app.run(host="127.0.0.1", port=port, debug=False)
