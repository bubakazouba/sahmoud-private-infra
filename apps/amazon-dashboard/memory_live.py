"""LIVE memory-telemetry page (2026-07-10, Sahmoud: "can this just be a live
dashboard instead of an html file?").

Replaces the pre-baked 2MB memory_telemetry.html snapshot in the SERVING path:
every request queries state/memory_telemetry.db + the mem0 chroma sqlite
directly (raw SQL, no chromadb client) and renders a lean page in ~ms. The old
builder (chat-assistant/scripts/memory_telemetry_build.py) still exists for
deep-dive/archival use but nothing depends on its staleness anymore.
"""
import html
import sqlite3
import time
from datetime import datetime

CHAT = r"C:/Users/bubakazouba/chat-assistant"
TELEM_DB = CHAT + "/state/memory_telemetry.db"
CHROMA_DB = CHAT + "/state/mem0/chroma/chroma.sqlite3"
# Curated, individually store-verified recall-failure catalog (Sahmoud 2026-07-10:
# "i want ALL examples of B and C"). Appended to whenever a new failure is caught;
# the dashboard renders whatever is here. Methodology lives in each entry.
FAILURES = CHAT + "/state/memory_failure_examples.jsonl"


def _fmt_ts(ts):
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%m/%d %H:%M")
    except Exception:
        return "?"


def _mem_texts(mem_ids):
    """mem_id (uuid) -> text snippet, via raw chroma sqlite (fast, read-only)."""
    out = {}
    ids = [m for m in set(mem_ids) if m]
    if not ids:
        return out
    try:
        con = sqlite3.connect(f"file:{CHROMA_DB}?mode=ro", uri=True, timeout=3)
        q = ",".join("?" * len(ids))
        rows = con.execute(
            f"""SELECT e.embedding_id, m.string_value
                FROM embeddings e JOIN embedding_metadata m ON m.id = e.id
                WHERE m.key='data' AND e.embedding_id IN ({q})""", ids).fetchall()
        con.close()
        for mid, txt in rows:
            out[mid] = (txt or "")[:110]
    except Exception:
        pass
    return out


def _failures_html():
    """Render the verified recall-failure catalog (Class B / C / near-miss / A-audited)."""
    import json
    cards = []
    try:
        with open(FAILURES, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f if l.strip()]
    except Exception:
        return "<div class='meta'>no failure catalog found</div>"
    LABEL = {"B": ("CLASS B — in store, NOT surfaced", "#f85149"),
             "C": ("CLASS C — proactive turn, no retrieval ran", "#f85149"),
             "C-nearmiss": ("CLASS C near-miss — no harm, but only via manual file reads", "#e6a23c"),
             "A-audited": ("audited candidates that turned out CLASS A (never extracted)", "#8b949e")}
    order = {"B": 0, "C": 1, "C-nearmiss": 2, "A-audited": 3}
    rows.sort(key=lambda r: order.get(r.get("class"), 9))
    for r in rows:
        lbl, color = LABEL.get(r.get("class"), (r.get("class", "?"), "#8b949e"))
        e = lambda k: html.escape(str(r.get(k, "")))
        cards.append(f"""<div class='card'>
<div style='color:{color};font-weight:bold'>{html.escape(lbl)} <span class='hm'>({e('date')})</span></div>
<div style='color:#e6edf3;margin:4px 0'>{e('title')}</div>
<table>
<tr><td class='hm'>trigger</td><td>{e('trigger')}</td></tr>
<tr><td class='hm'>memory that existed</td><td>{e('memory_that_existed')}</td></tr>
<tr><td class='hm'>what happened</td><td>{e('what_happened')}</td></tr>
<tr><td class='hm'>why it failed</td><td>{e('why_it_failed')}</td></tr>
<tr><td class='hm'>status</td><td>{e('status')}</td></tr>
<tr><td class='hm'>verified</td><td>{e('verified')}</td></tr>
</table></div>""")
    return "\n".join(cards)


def render():
    t0 = time.time()
    con = sqlite3.connect(f"file:{TELEM_DB}?mode=ro", uri=True, timeout=3)
    cur = con.cursor()

    n_scored = cur.execute("SELECT count(*) FROM memory_score").fetchone()[0]
    n_hit = cur.execute("SELECT count(*) FROM memory_score WHERE hits>0").fetchone()[0]
    n_ev = cur.execute("SELECT count(*) FROM scoring_event").fetchone()[0]
    last_ev = cur.execute("SELECT max(ts) FROM scoring_event").fetchone()[0]
    ev24 = cur.execute("SELECT count(*) FROM scoring_event WHERE ts>?", (time.time() - 86400,)).fetchone()[0]
    n_tr = cur.execute("SELECT count(*) FROM retrieval_trace").fetchone()[0]
    last_tr = cur.execute("SELECT max(ts) FROM retrieval_trace").fetchone()[0]

    hist = cur.execute(
        """SELECT CASE WHEN decayed_score<0.3 THEN '0.0-0.3' WHEN decayed_score<0.45 THEN '0.3-0.45'
           WHEN decayed_score<0.55 THEN '0.45-0.55' WHEN decayed_score<0.7 THEN '0.55-0.7'
           ELSE '0.7-1.0' END b, count(*) FROM memory_score GROUP BY b ORDER BY b""").fetchall()

    top = cur.execute("""SELECT mem_id, decayed_score, hits, misses FROM memory_score
                         WHERE hits>0 ORDER BY decayed_score DESC LIMIT 15""").fetchall()
    sinking = cur.execute("""SELECT mem_id, decayed_score, hits, misses FROM memory_score
                             WHERE misses>=8 ORDER BY (hits*1.0/(hits+misses)) ASC, misses DESC LIMIT 15""").fetchall()
    recent = cur.execute("""SELECT ts, mem_id, verdict, msg_id FROM scoring_event
                            ORDER BY ts DESC LIMIT 30""").fetchall()
    con.close()

    texts = _mem_texts([r[0] for r in top] + [r[0] for r in sinking] + [r[1] for r in recent])

    def esc(s):
        return html.escape(str(s or ""))

    def rows_scored(rows):
        out = []
        for mid, sc, h, m in rows:
            out.append(f"<tr><td class='sc'>{sc:.2f}</td><td class='hm'>{h}&#10003;/{m}&#10007;</td>"
                       f"<td>{esc(texts.get(mid, mid[:8] + '…'))}</td></tr>")
        return "\n".join(out) or "<tr><td colspan=3>none</td></tr>"

    hist_html = "\n".join(
        f"<tr><td class='sc'>{esc(b)}</td><td class='hm'>{n}</td>"
        f"<td><div class='bar' style='width:{min(100, n * 2)}px'></div></td></tr>" for b, n in hist)

    recent_html = "\n".join(
        f"<tr><td class='hm'>{_fmt_ts(ts)}</td><td class='{('ok' if v == 'used' else 'miss')}'>{esc(v)}</td>"
        f"<td class='hm'>{esc(msg)}</td><td>{esc(texts.get(mid, (mid or '')[:8]))}</td></tr>"
        for ts, mid, v, msg in recent)

    ms = int((time.time() - t0) * 1000)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Memory scoring — LIVE</title><style>
body{{background:#0d1117;color:#c9d1d9;font-family:ui-monospace,Consolas,monospace;margin:16px;font-size:14px}}
h1{{font-size:18px;color:#e6edf3}} h2{{font-size:15px;color:#e6a23c;margin-top:22px}}
table{{border-collapse:collapse;width:100%;max-width:860px}}
td{{padding:4px 8px;border-bottom:1px solid #21262d;vertical-align:top}}
.sc{{color:#79c0ff;white-space:nowrap}} .hm{{color:#8b949e;white-space:nowrap}}
.ok{{color:#3fb950}} .miss{{color:#f85149}}
.bar{{background:#4a5568;height:10px;border-radius:5px}}
.live{{color:#3fb950;font-weight:bold}} .meta{{color:#8b949e;font-size:12px}}
.card{{border:1px solid #21262d;border-radius:8px;padding:10px 12px;margin:10px 0;max-width:860px}}
</style></head><body>
<h1>Memory scoring <span class="live">&#9679; LIVE</span></h1>
<div class="meta">rendered {datetime.now().strftime('%m/%d %H:%M:%S')} in {ms}ms — queries the DB on every load, no cached file</div>
<h2>Pipeline health</h2>
<table>
<tr><td>scoring events (total / last 24h)</td><td class="sc">{n_ev} / {ev24}</td></tr>
<tr><td>latest scoring event</td><td class="sc">{_fmt_ts(last_ev)}</td></tr>
<tr><td>memories scored (any / with &#8805;1 hit)</td><td class="sc">{n_scored} / {n_hit}</td></tr>
<tr><td>retrieval traces (total / latest)</td><td class="sc">{n_tr} / {_fmt_ts(last_tr)}</td></tr>
</table>
<h2>&#9888; Recall failures — Class B (in store, not surfaced) &amp; Class C (no retrieval on proactive turns)</h2>
<div class="meta">Every entry individually verified against the store before inclusion (manual audit 2026-07-10; appended to as new failures are caught). Not auto-instrumented — no fabricated cases.</div>
{_failures_html()}
<h2>Score distribution</h2><table>{hist_html}</table>
<h2>&#127942; Most useful (top 15 with &#8805;1 hit)</h2><table>{rows_scored(top)}</table>
<h2>&#128201; Sinking — retrieved a lot, rarely used (top 15)</h2><table>{rows_scored(sinking)}</table>
<h2>&#9200; Last 30 scoring events</h2>
<table><tr><td class="hm">when</td><td class="hm">verdict</td><td class="hm">msg</td><td class="hm">memory</td></tr>
{recent_html}</table>
</body></html>"""
