"""Static-dashboard wrapper for sd-things-to-do.
Mirrors https://bubakazouba.github.io/sd-things-to-do/ behind the OAuth-gated proxy.
"""
import os
from pathlib import Path
from flask import Flask, send_from_directory, abort

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
APPLICATION_ROOT = os.environ.get("APPLICATION_ROOT", "")

app = Flask(__name__)
app.config["APPLICATION_ROOT"] = APPLICATION_ROOT


@app.get("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "app": "sd-things-to-do"}


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
    port = int(os.environ.get("APP_PORT", "18011"))
    app.run(host="127.0.0.1", port=port, debug=False)
