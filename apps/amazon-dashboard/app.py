"""Amazon expense dashboard — drill into all Amazon-related spending."""
import os
from pathlib import Path
from flask import Flask, send_from_directory, abort

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
APPLICATION_ROOT = os.environ.get("APPLICATION_ROOT", "")

app = Flask(__name__)
app.config["APPLICATION_ROOT"] = APPLICATION_ROOT

# --- LIVE memory-telemetry dashboard (2026-07-10, Sahmoud: "can this just be a
# live dashboard instead of an html file?"). Every request renders fresh from
# the telemetry DB via memory_live.py (raw SQL, ~ms). The old pre-baked
# memory_telemetry.html snapshot is no longer in the serving path — this route
# shadows it; the deep-dive static build remains at memory_telemetry_full.html
# if ever rebuilt manually.
import memory_live


@app.get("/memory_telemetry.html")
@app.get("/memory_telemetry")
def memory_telemetry():
    try:
        return memory_live.render()
    except Exception as e:
        return f"<pre>memory_live render failed: {e}</pre>", 500


# LIVE conversation-topics dashboard (2026-07-10) — renders topic_threads.json
import topics_live


@app.get("/topics.html")
@app.get("/topics")
def topics():
    try:
        return topics_live.render()
    except Exception as e:
        return f"<pre>topics_live render failed: {e}</pre>", 500


# LIVE Open-Arc System dashboard (2026-07-12) — renders arcs.db
import arc_live


@app.get("/arcs.html")
@app.get("/arcs")
def arcs_page():
    try:
        return arc_live.render()
    except Exception as e:
        return f"<pre>arc_live render failed: {e}</pre>", 500


# Arc REVIEW dashboard (2026-07-12) — the deduped golden set, per-arc full thread
import arc_review


@app.get("/arc_review.html")
@app.get("/arc_review")
def arc_review_page():
    try:
        return arc_review.render()
    except Exception as e:
        return f"<pre>arc_review render failed: {e}</pre>", 500


@app.get("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "app": "amazon-dashboard"}


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
    port = int(os.environ.get("APP_PORT", "18003"))
    app.run(host="127.0.0.1", port=port, debug=False)
