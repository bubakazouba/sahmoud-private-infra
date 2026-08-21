"""US State-to-State Air Passenger Flows — BTS T-100 Domestic Segment 2023."""
import os
from pathlib import Path
from flask import Flask, send_from_directory, abort, jsonify

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
    flows_path = STATIC_DIR / "flows.json"
    data_ok = flows_path.is_file() and flows_path.stat().st_size > 1000
    return jsonify({
        "ok": True,
        "app": "state-travel-flows",
        "data": "ok" if data_ok else "missing",
        "data_source": "BTS T-100 Domestic Segment All Carriers, 2023",
        "flows_json_bytes": flows_path.stat().st_size if flows_path.is_file() else 0,
    })


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
    port = int(os.environ.get("APP_PORT", "18024"))
    app.run(host="127.0.0.1", port=port, debug=False)
