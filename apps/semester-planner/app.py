"""Cal State LA Math semester planner — server-persisted (data lives here, not the
browser) so it syncs across devices. The client mirrors its localStorage keys to
GET/POST /api/state; we store the blob atomically in static/state.json."""
import json
import os
import tempfile
from pathlib import Path
from flask import Flask, send_from_directory, abort, request, jsonify

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
STATE_PATH = STATIC_DIR / "state.json"
APPLICATION_ROOT = os.environ.get("APPLICATION_ROOT", "")

app = Flask(__name__)
app.config["APPLICATION_ROOT"] = APPLICATION_ROOT


@app.get("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "app": "semester-planner"}


@app.get("/api/state")
def get_state():
    if STATE_PATH.exists():
        try:
            return jsonify(json.loads(STATE_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return jsonify({})


@app.post("/api/state")
def post_state():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or "__ls" not in body or not isinstance(body["__ls"], dict):
        return jsonify({"error": "expected {__ls: {key: value}}"}), 400
    # cap size to avoid abuse
    ls = {str(k): str(v) for k, v in body["__ls"].items() if len(str(v)) < 500000}
    fd, tmp = tempfile.mkstemp(prefix=".state_", dir=str(STATIC_DIR))
    os.close(fd)
    Path(tmp).write_text(json.dumps({"__ls": ls}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, str(STATE_PATH))
    return jsonify({"ok": True, "keys": list(ls.keys())})


@app.get("/<path:p>")
def asset(p):
    base = STATIC_DIR.resolve()
    target = (STATIC_DIR / p).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        abort(403)
    if not target.is_file():
        abort(404)
    return send_from_directory(str(STATIC_DIR), p)


if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", "18040"))
    app.run(host="127.0.0.1", port=port, debug=False)
