"""LIVE conversation-topics dashboard (2026-07-10, Sahmoud's ask: a place that
shows every topic segment and the messages under it, de-interleaved).

Reads chat-assistant/state/topic_threads.json (built by topic_threads.py) + the
inbox DB, and renders each topic with its messages in chronological order. Live
on every request (raw SQL + a small JSON read, ~ms).
"""
import html
import json
import sqlite3
from datetime import datetime

CHAT = r"C:/Users/bubakazouba/chat-assistant"
THREADS = CHAT + "/state/topic_threads.json"
INBOX_DB = CHAT + "/state/pianobot_inbox.db"


def _fmt(ts, f="%m/%d %H:%M"):
    try:
        return datetime.fromtimestamp(float(ts)).strftime(f)
    except Exception:
        return "?"


def _messages(msg_ids):
    """Look up {msg_id -> {date, who, text, out}} from the inbox raw JSON."""
    out = {}
    ids = [int(m) for m in msg_ids if m is not None]
    if not ids:
        return out
    con = sqlite3.connect(f"file:{INBOX_DB}?mode=ro", uri=True, timeout=3)
    q = ",".join("?" * len(ids))
    for mid, raw in con.execute(f"SELECT message_id, raw FROM inbox WHERE message_id IN ({q})", ids):
        try:
            d = json.loads(raw)
            out[int(mid)] = {"date": d.get("date") or 0,
                             "who": d.get("from_user") or ("Bot" if d.get("out") else "Sahmoud"),
                             "text": d.get("text") or "", "out": bool(d.get("out"))}
        except Exception:
            pass
    con.close()
    return out


def render():
    import time as _t
    t0 = _t.time()
    try:
        st = json.load(open(THREADS, encoding="utf-8"))
    except Exception:
        return "<h1>Topics</h1><p>No topic_threads.json yet — run topic_threads.py --bootstrap-days 7.</p>"
    segs = st.get("segments", [])
    all_ids = [mid for s in segs for mid in s.get("message_ids", [])]
    msgs = _messages(all_ids)

    # newest-active topics first
    segs = sorted(segs, key=lambda s: -(s.get("last_ts") or 0))
    total_msgs = sum(len(s.get("message_ids", [])) for s in segs)

    def esc(x):
        return html.escape(str(x or ""))

    def who_class(m):
        if m["out"]:
            return "bot"
        w = (m["who"] or "").lower()
        return "prek" if "preksha" in w else "sah"

    cards = []
    for s in segs:
        mids = s.get("message_ids", [])
        rows = sorted((msgs[m] for m in mids if m in msgs), key=lambda r: r["date"])
        span = f'{_fmt(s.get("first_ts"), "%m/%d")} – {_fmt(s.get("last_ts"), "%m/%d")}'
        body = "\n".join(
            f'<div class="msg {who_class(m)}"><span class="t">{_fmt(m["date"])}</span>'
            f'<span class="w">{esc(m["who"])}</span>{esc(m["text"][:600])}</div>'
            for m in rows) or "<div class='meta'>(messages not found in inbox)</div>"
        cards.append(f"""<details class="seg">
<summary><span class="cnt">{len(mids)}</span> <b>{esc(s.get("title"))}</b>
<span class="span">{span}</span></summary>
<div class="msgs">{body}</div></details>""")

    ms = int((_t.time() - t0) * 1000)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Conversation topics — LIVE</title><style>
body{{background:#0d1117;color:#c9d1d9;font-family:ui-monospace,Consolas,monospace;margin:16px;font-size:14px}}
h1{{font-size:19px;color:#e6edf3}} .meta{{color:#8b949e;font-size:12px;margin-bottom:14px}}
.live{{color:#3fb950;font-weight:bold}}
.seg{{border:1px solid #21262d;border-radius:8px;margin:8px 0;background:#0f141b;max-width:900px}}
summary{{padding:10px 12px;cursor:pointer;list-style:none}}
summary::-webkit-details-marker{{display:none}}
summary:hover{{background:#161b22}}
.cnt{{display:inline-block;min-width:26px;text-align:center;background:#1f6feb;color:#fff;border-radius:10px;padding:0 6px;font-size:12px;margin-right:6px}}
.span{{color:#8b949e;font-size:12px;margin-left:8px}}
.msgs{{padding:4px 12px 12px 12px;border-top:1px solid #21262d}}
.msg{{padding:5px 8px;margin:4px 0;border-radius:6px;border-left:3px solid #30363d;white-space:pre-wrap;word-break:break-word}}
.msg.sah{{border-left-color:#1f6feb;background:#0d1b2e}}
.msg.prek{{border-left-color:#db61a2;background:#241320}}
.msg.bot{{border-left-color:#3fb950;background:#0f1f14;color:#9db8a6}}
.t{{color:#6e7681;font-size:11px;margin-right:8px}} .w{{color:#8b949e;font-weight:bold;margin-right:8px}}
</style></head><body>
<h1>Conversation topics <span class="live">&#9679; LIVE</span></h1>
<div class="meta">{len(segs)} topics, {total_msgs} messages threaded — rendered {datetime.now().strftime('%m/%d %H:%M:%S')} in {ms}ms. De-interleaved from the raw stream by topic_threads.py. Click a topic to expand its messages in order.</div>
{''.join(cards)}
</body></html>"""
