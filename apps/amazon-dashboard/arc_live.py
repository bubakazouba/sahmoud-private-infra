"""Live-rendered Open-Arc System dashboard — reads chat-assistant/state/arcs.db
directly (raw SQL, ~ms) and shows the pipeline state as it fills in stage by stage.
Registered at /arcs.html on the amazon-dashboard. No pre-baked HTML."""
import os
import sqlite3
import time
from datetime import datetime

ARCS_DB = r"C:/Users/bubakazouba/chat-assistant/state/arcs.db"
CHAT_NAMES = {
    1342455443: "my DM w/ bot",
    -5072406978: "me + Preksha + bot",
    -5245872274: "me + Aya + bot",
}


def _q(con, sql, args=()):
    try:
        return con.execute(sql, args).fetchall()
    except Exception:
        return []


def render():
    con = sqlite3.connect(ARCS_DB)
    con.row_factory = sqlite3.Row

    ingest = _q(con, """SELECT chat_id, COUNT(*) n, SUM(is_out) mine,
                        SUM(CASE WHEN reply_to IS NOT NULL THEN 1 ELSE 0 END) replies,
                        MIN(ts) mn, MAX(ts) mx FROM raw_messages GROUP BY chat_id ORDER BY n DESC""")
    tot = _q(con, "SELECT COUNT(*) n, MIN(ts) mn, MAX(ts) mx FROM raw_messages")
    n_topics = (_q(con, "SELECT COUNT(*) n FROM topics") or [{"n": 0}])[0]["n"]
    n_arcs_open = (_q(con, "SELECT COUNT(*) n FROM arcs WHERE lifecycle='open'") or [{"n": 0}])[0]["n"]
    n_arcs_closed = (_q(con, "SELECT COUNT(*) n FROM arcs WHERE lifecycle='closed'") or [{"n": 0}])[0]["n"]
    arcs = _q(con, """SELECT title, goal, current_status, lifecycle, updated_at FROM arcs
                      ORDER BY (lifecycle='open') DESC, updated_at DESC LIMIT 100""")
    con.close()

    total = tot[0]["n"] if tot and tot[0]["n"] else 0
    span = ""
    if tot and tot[0]["mn"]:
        span = "%s &ndash; %s" % (datetime.fromtimestamp(tot[0]["mn"]).strftime("%m/%d %H:%M"),
                                  datetime.fromtimestamp(tot[0]["mx"]).strftime("%m/%d %H:%M"))

    def stage(done, label, detail):
        c = "#16a34a" if done else "#94a3b8"
        mark = "&#10003;" if done else "&#9711;"
        return ('<div class="stage"><span style="color:%s;font-weight:700">%s</span> '
                '<b>%s</b> <span class="muted">%s</span></div>' % (c, mark, label, detail))

    stages = "".join([
        stage(total > 0, "1. Transcript reader", "direct Telegram read, both sides + reply edges &rarr; raw_messages"),
        stage(n_topics > 0, "2. Threader", "group raw_messages into topics (both-sides, reply edges)"),
        stage(n_topics > 0, "3. Matcher", "new topic vs continuation (reply / id-overlap / entity)"),
        stage((n_arcs_open + n_arcs_closed) > 0, "4. Arc lifecycle", "create / update / reopen / sweep-close"),
    ])

    rows = ""
    for r in ingest:
        nm = CHAT_NAMES.get(r["chat_id"], str(r["chat_id"]))
        mine = r["mine"] or 0
        rows += ("<tr><td>%s</td><td class='num'>%d</td><td class='num'>%d</td>"
                 "<td class='num'>%d</td><td class='num'>%d</td></tr>"
                 % (nm, r["n"], mine, r["n"] - mine, r["replies"] or 0))

    if arcs:
        arows = "".join(
            "<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                (r["title"] or ""), (r["goal"] or "")[:120], (r["current_status"] or "")[:160],
                r["lifecycle"] or "")
            for r in arcs)
        arc_section = ("<h2>Arcs (%d open / %d closed)</h2><table><tr><th>Title</th><th>Goal</th>"
                       "<th>Current status</th><th>State</th></tr>%s</table>"
                       % (n_arcs_open, n_arcs_closed, arows))
    else:
        arc_section = ('<h2>Arcs</h2><p class="muted">No arcs yet &mdash; the threader (Stage 2) '
                       'hasn\'t run on the ingested transcript. Arcs populate here once it does.</p>')

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Open-Arc System</title><style>
:root{color-scheme:light dark}
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:1000px;margin:0 auto;padding:20px;
 background:#f8fafc;color:#0f172a}
@media(prefers-color-scheme:dark){body{background:#0b1220;color:#e2e8f0}
 table{background:#111a2e}th{background:#1e293b}tr:nth-child(even) td{background:#0f1830}}
h1{margin:0 0 2px}.muted{color:#64748b}.sub{color:#64748b;margin:0 0 18px}
.stage{padding:6px 0;font-size:15px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 16px;min-width:130px}
@media(prefers-color-scheme:dark){.card{background:#111a2e;border-color:#1e293b}}
.card .big{font-size:26px;font-weight:800}.card .lbl{color:#64748b;font-size:12px}
table{border-collapse:collapse;width:100%;margin:8px 0 22px;background:#fff;border-radius:10px;overflow:hidden}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid #e2e8f0;font-size:14px}
@media(prefers-color-scheme:dark){th,td{border-color:#1e293b}}
th{background:#f1f5f9;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.num{text-align:right;font-variant-numeric:tabular-nums}
</style></head><body>
<h1>Open-Arc System</h1>
<p class="sub">Live from arcs.db &middot; rendered """ + now + """</p>
<div class="cards">
 <div class="card"><div class="big">""" + str(total) + """</div><div class="lbl">msgs ingested</div></div>
 <div class="card"><div class="big">""" + str(n_topics) + """</div><div class="lbl">topics</div></div>
 <div class="card"><div class="big">""" + str(n_arcs_open) + """</div><div class="lbl">open arcs</div></div>
 <div class="card"><div class="big">""" + str(n_arcs_closed) + """</div><div class="lbl">closed arcs</div></div>
</div>
<h2>Pipeline</h2>""" + stages + """
<h2>Ingested transcript <span class="muted" style="font-weight:400">""" + span + """</span></h2>
<table><tr><th>Chat</th><th>Msgs</th><th>Mine</th><th>Bot/others</th><th>Reply-edges</th></tr>""" + rows + """</table>
""" + arc_section + """
</body></html>"""


if __name__ == "__main__":
    print(render()[:500])
