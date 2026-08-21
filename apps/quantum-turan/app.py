"""Major Football Tournaments timeline (2022-2026). Static dashboard."""
import os
from pathlib import Path
from flask import Flask, send_from_directory, abort, jsonify

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
app = Flask(__name__)
app.config["APPLICATION_ROOT"] = os.environ.get("APPLICATION_ROOT", "")


@app.get("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.get("/healthz")
def healthz():
    idx = STATIC_DIR / "index.html"
    return jsonify({"ok": True, "app": "quantum-turan",
                    "data": "ok" if idx.is_file() else "missing"})


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
    port = int(os.environ.get("APP_PORT", "18051"))
    app.run(host="127.0.0.1", port=port, debug=False)
