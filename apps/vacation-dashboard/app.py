"""Mountain town vacation comparison dashboard."""
import json
import os
from pathlib import Path
from flask import Flask, send_from_directory, jsonify, abort

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
DATA_FILE = Path("C:/users/bubakazouba/chat-assistant/state/_vacation_mountain_towns.json")
APPLICATION_ROOT = os.environ.get("APPLICATION_ROOT", "")

app = Flask(__name__)
app.config["APPLICATION_ROOT"] = APPLICATION_ROOT


@app.get("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "app": "vacation-dashboard"}


@app.get("/data.json")
def data():
    if not DATA_FILE.exists():
        return jsonify({"towns": [], "status": "pending — subagent still researching"})
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, list):
            return jsonify({"towns": payload, "status": "ok"})
        return jsonify(payload)
    except Exception as e:
        return jsonify({"towns": [], "status": f"error reading data: {e}"})


@app.get("/<path:p>")
def asset(p):
    base = STATIC_DIR.resolve()
    target = (STATIC_DIR / p).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        abort(404)
    if not target.is_file():
        abort(404)
    return send_from_directory(str(STATIC_DIR), p)


if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", "18028"))
    app.run(host="127.0.0.1", port=port, debug=False)
