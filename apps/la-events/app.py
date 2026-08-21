"""Static-dashboard wrapper for la-events.
Mirrors https://bubakazouba.github.io/la-weekend-events/ behind the OAuth-gated proxy.
"""
import json
import os
import tempfile
from pathlib import Path
from flask import Flask, send_from_directory, abort, request, jsonify

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
PREFS_PATH = STATIC_DIR / "preferences.json"
EVENT_VOTES_PATH = STATIC_DIR / "event_votes.json"
APPLICATION_ROOT = os.environ.get("APPLICATION_ROOT", "")

app = Flask(__name__)
app.config["APPLICATION_ROOT"] = APPLICATION_ROOT


@app.get("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "app": "la-events"}


@app.post("/api/preferences")
def update_preferences():
    """Update preferences.json with new likes/dislikes lists. Atomic write."""
    body = request.get_json(silent=True) or {}
    likes = body.get("likes")
    dislikes = body.get("dislikes")
    if not isinstance(likes, list) or not isinstance(dislikes, list):
        return jsonify({"error": "likes and dislikes must be lists of strings"}), 400
    likes = [str(s).strip() for s in likes if str(s).strip()]
    dislikes = [str(s).strip() for s in dislikes if str(s).strip()]
    # dedupe (preserve order)
    likes = list(dict.fromkeys(likes))
    dislikes = list(dict.fromkeys(dislikes))
    if any(len(s) > 200 for s in likes + dislikes):
        return jsonify({"error": "preference entries must be < 200 chars"}), 400

    existing = {}
    if PREFS_PATH.exists():
        try:
            existing = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    existing["likes"] = likes
    existing["dislikes"] = dislikes
    existing.setdefault(
        "_doc",
        "Edited via the dashboard (POST /api/preferences) or by DMing PianoBot. The daily la-events refresh reads these to bias curation.",
    )

    # atomic write
    fd, tmp = tempfile.mkstemp(prefix=".preferences_", dir=str(STATIC_DIR))
    os.close(fd)
    Path(tmp).write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, str(PREFS_PATH))
    return jsonify({"ok": True, "likes": likes, "dislikes": dislikes})


def _atomic_write_json(path, obj, prefix):
    fd, tmp = tempfile.mkstemp(prefix=prefix, dir=str(STATIC_DIR))
    os.close(fd)
    Path(tmp).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, str(path))


@app.post("/api/event-vote")
def event_vote():
    """Record a per-event thumbs up/down (the EXACT event he liked/disliked).
    Body: {title, date?, vote: "like"|"dislike"|"clear"}. A vote is exclusive
    (voting like removes any prior dislike for that title and vice-versa);
    "clear" removes the event from both lists. Keyed by title (stable across
    weekly regenerations; the per-weekend `id` is reused so it isn't unique)."""
    body = request.get_json(silent=True) or {}
    title = str(body.get("title", "")).strip()
    date = str(body.get("date", "")).strip()
    vote = body.get("vote")
    if not title or vote not in ("like", "dislike", "clear"):
        return jsonify({"error": 'need title + vote ("like"|"dislike"|"clear")'}), 400
    if len(title) > 300:
        return jsonify({"error": "title too long"}), 400

    data = {"liked": [], "disliked": []}
    if EVENT_VOTES_PATH.exists():
        try:
            data = json.loads(EVENT_VOTES_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {"liked": [], "disliked": []}
    data.setdefault("liked", [])
    data.setdefault("disliked", [])
    # a vote is exclusive — drop this title from both lists first
    data["liked"] = [e for e in data["liked"] if e.get("title") != title]
    data["disliked"] = [e for e in data["disliked"] if e.get("title") != title]
    if vote == "like":
        data["liked"].append({"title": title, "date": date})
    elif vote == "dislike":
        data["disliked"].append({"title": title, "date": date})
    # "clear" => leave it removed from both
    data["_doc"] = ("Per-event thumbs from the dashboard cards. The weekly la-events refresh "
                    "NEVER re-adds a 'disliked' event (purges by title) and treats 'liked' "
                    "events as a strong signal to keep/seek-similar.")
    _atomic_write_json(EVENT_VOTES_PATH, data, ".event_votes_")
    return jsonify({"ok": True, "vote": vote, "title": title,
                    "liked": len(data["liked"]), "disliked": len(data["disliked"])})


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
    port = int(os.environ.get("APP_PORT", "18006"))
    app.run(host="127.0.0.1", port=port, debug=False)
