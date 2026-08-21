"""Weekend-socializing dashboard: how often Sahmoud + Preksha saw people on
weekends in 2026. Static data.json (generated from their calendars) + a
per-event override store (happened / social) he toggles in the UI, so the
"weekends you saw people" count is his to calibrate (the calendar shows PLANNED
events that didn't always happen — e.g. cricket, Ojai)."""
import json
import os
import tempfile
from pathlib import Path
from flask import Flask, send_from_directory, request, jsonify, abort

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
OVERRIDES = STATIC_DIR / "overrides.json"
APPLICATION_ROOT = os.environ.get("APPLICATION_ROOT", "")

app = Flask(__name__)
app.config["APPLICATION_ROOT"] = APPLICATION_ROOT


@app.get("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "app": "weekends"}


@app.get("/api/overrides")
def get_overrides():
    if OVERRIDES.exists():
        try:
            return jsonify(json.loads(OVERRIDES.read_text(encoding="utf-8")))
        except Exception:
            pass
    return jsonify({})


@app.post("/api/overrides")
def set_override():
    """Body: {id, happened?, social?}. Merges one event's override. Atomic."""
    b = request.get_json(silent=True) or {}
    eid = b.get("id")
    if not eid or not isinstance(eid, str):
        return jsonify({"error": "id required"}), 400
    data = {}
    if OVERRIDES.exists():
        try:
            data = json.loads(OVERRIDES.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    cur = data.get(eid, {})
    if "happened" in b:
        cur["happened"] = bool(b["happened"])
    if "social" in b:
        cur["social"] = bool(b["social"])
    data[eid] = cur
    fd, tmp = tempfile.mkstemp(prefix=".ov_", dir=str(STATIC_DIR))
    os.close(fd)
    Path(tmp).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, str(OVERRIDES))
    return jsonify({"ok": True, "id": eid, "override": cur})


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
    port = int(os.environ.get("APP_PORT", "18033"))
    app.run(host="127.0.0.1", port=port, debug=False)
