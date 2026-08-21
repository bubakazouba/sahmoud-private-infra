"""Arc REVIEW dashboard — the deduped GOLDEN arc set for review. Reads
chat-assistant/state/arcs_golden.db. Each arc is an expandable card showing title,
lifecycle (open/closed), domain tags, goal, summary, current_status, and the FULL message
thread (timestamp / sender / text|media) for that arc's topic. Registered at /arc_review.html.
Has a domain-tag filter + a 'hide bot-dev' toggle + open/closed filter (client-side)."""
import sqlite3
import html
from datetime import datetime

GOLDEN_DB = r"C:/Users/bubakazouba/chat-assistant/state/arcs_golden.db"


def _q(con, sql, args=()):
    try:
        return con.execute(sql, args).fetchall()
    except Exception:
        return []


def _esc(s):
    return html.escape(str(s or ""))


def render():
    con = sqlite3.connect(GOLDEN_DB)
    con.row_factory = sqlite3.Row
    arcs = _q(con, """SELECT id, topic_id, title, goal, summary, current_status, lifecycle, updated_at
                      FROM arcs ORDER BY (lifecycle='open') DESC, updated_at DESC""")
    n_open = sum(1 for a in arcs if a["lifecycle"] == "open")
    n_closed = sum(1 for a in arcs if a["lifecycle"] == "closed")

    # tags per arc + tag counts
    tagmap = {}
    for r in _q(con, "SELECT arc_id, tag FROM arc_tags"):
        tagmap.setdefault(r["arc_id"], []).append(r["tag"])
    tag_counts = {}
    for r in _q(con, "SELECT tag, COUNT(*) c FROM arc_tags GROUP BY tag ORDER BY c DESC"):
        tag_counts[r["tag"]] = r["c"]

    cards = []
    for a in arcs:
        tags = sorted(tagmap.get(a["id"], []))
        msgs = _q(con, "SELECT ts, sender, text FROM topic_messages WHERE topic_id=? ORDER BY ts", (a["topic_id"],))
        mlines = []
        for m in msgs:
            ts = datetime.fromtimestamp(m["ts"]).strftime("%m/%d %H:%M") if m["ts"] else "?"
            who = _esc(m["sender"] or "me")
            txt = _esc((m["text"] or "").strip()) or "<i class='muted'>[media / no text]</i>"
            mlines.append('<div class="msg"><span class="ts">%s</span> <span class="who">%s</span>: %s</div>'
                          % (ts, who, txt))
        thread = "".join(mlines) or '<div class="muted">(no messages)</div>'
        badge = ('<span class="badge open">OPEN</span>' if a["lifecycle"] == "open"
                 else '<span class="badge closed">CLOSED</span>')
        chips = "".join('<span class="tag t-%s">%s</span>' % (_esc(t), _esc(t)) for t in tags)
        cards.append("""<details class="arc" data-life="%s" data-tags="%s">
<summary>%s <b>#%d %s</b> %s <span class="state">%s</span></summary>
<div class="body">
 <div class="fld"><span class="k">Goal</span> %s</div>
 <div class="fld"><span class="k">Summary</span> %s</div>
 <div class="fld"><span class="k">Current status</span> %s</div>
 <div class="fld"><span class="k">Messages (%d)</span></div>
 <div class="thread">%s</div>
</div></details>""" % (a["lifecycle"], ",".join(tags), badge, a["id"], _esc(a["title"]), chips,
                       _esc(a["current_status"]),
                       _esc(a["goal"]) or "<span class='muted'>-</span>",
                       _esc(a["summary"]) or "<span class='muted'>-</span>",
                       _esc(a["current_status"]) or "<span class='muted'>-</span>",
                       len(msgs), thread))
    con.close()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    domchips = '<button class="fchip active" data-dom="">All domains</button>'
    for t, c in tag_counts.items():
        domchips += '<button class="fchip" data-dom="%s">%s <span class="ct">%d</span></button>' % (_esc(t), _esc(t), c)

    return """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arc Review (golden)</title><style>
:root{color-scheme:light dark}
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;margin:0 auto;padding:18px;background:#f8fafc;color:#0f172a}
@media(prefers-color-scheme:dark){body{background:#0b1220;color:#e2e8f0}}
h1{margin:0 0 2px}.sub{color:#64748b;margin:0 0 16px}
.arc{background:#fff;border:1px solid #e2e8f0;border-radius:10px;margin:8px 0;padding:2px 12px}
@media(prefers-color-scheme:dark){.arc{background:#111a2e;border-color:#1e293b}}
summary{cursor:pointer;padding:9px 2px;font-size:15px;line-height:1.6}
summary b{margin-right:6px}
.state{color:#64748b;font-size:13px}
.badge{font-size:10px;font-weight:800;padding:2px 7px;border-radius:20px;vertical-align:middle}
.badge.open{background:#dcfce7;color:#166534}.badge.closed{background:#e2e8f0;color:#475569}
.tag{font-size:10px;font-weight:700;padding:2px 7px;border-radius:20px;vertical-align:middle;margin-right:3px;background:#eef2ff;color:#3730a3}
.tag.t-bot-dev{background:#e2e8f0;color:#475569}.tag.t-relationship{background:#fce7f3;color:#9d174d}
.tag.t-family{background:#fef3c7;color:#92400e}.tag.t-purchases{background:#dbeafe;color:#1e40af}
.tag.t-research{background:#ede9fe;color:#5b21b6}.tag.t-academic{background:#cffafe;color:#155e75}
.tag.t-travel{background:#d1fae5;color:#065f46}.tag.t-finance{background:#fee2e2;color:#991b1b}
.tag.t-health{background:#ffe4e6;color:#9f1239}.tag.t-events{background:#ffedd5;color:#9a3412}
.body{padding:4px 2px 12px;border-top:1px solid #eef2f7}
@media(prefers-color-scheme:dark){.body{border-color:#1e293b}}
.fld{margin:7px 0;font-size:14px}.fld .k{display:inline-block;min-width:110px;color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:.03em;vertical-align:top}
.thread{margin-top:6px;background:#f8fafc;border-radius:8px;padding:8px 10px;max-height:340px;overflow:auto;font-size:13px}
@media(prefers-color-scheme:dark){.thread{background:#0b1220}}
.msg{padding:3px 0;border-bottom:1px solid #eef2f7;line-height:1.45}
@media(prefers-color-scheme:dark){.msg{border-color:#182238}}
.msg .ts{color:#94a3b8;font-variant-numeric:tabular-nums;margin-right:6px}
.msg .who{font-weight:700;color:#334155}
@media(prefers-color-scheme:dark){.msg .who{color:#93c5fd}}
.muted{color:#94a3b8}
.cards{display:flex;gap:10px;margin:12px 0;flex-wrap:wrap}
.pill{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:8px 14px}
@media(prefers-color-scheme:dark){.pill{background:#111a2e;border-color:#1e293b}}
.pill .big{font-size:22px;font-weight:800}.pill .lbl{color:#64748b;font-size:11px}
.filters{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:10px 0 4px}
.fchip{font-size:12px;padding:5px 11px;border-radius:20px;border:1px solid #cbd5e1;background:#fff;color:#334155;cursor:pointer}
@media(prefers-color-scheme:dark){.fchip{background:#111a2e;border-color:#334155;color:#cbd5e1}}
.fchip.active{background:#4f46e5;color:#fff;border-color:#4f46e5}
.fchip .ct{opacity:.6;font-size:10px}
.search{flex:1;min-width:220px;font-size:14px;padding:9px 13px;border-radius:20px;border:1px solid #cbd5e1;background:#fff;color:#0f172a}
@media(prefers-color-scheme:dark){.search{background:#111a2e;border-color:#334155;color:#e2e8f0}}
.search:focus{outline:none;border-color:#4f46e5;box-shadow:0 0 0 2px rgba(79,70,229,.2)}
mark{background:#fde68a;color:#0f172a;border-radius:2px;padding:0 1px}
.sep{width:1px;height:20px;background:#cbd5e1;margin:0 4px}
label.tog{font-size:12px;color:#334155;display:inline-flex;align-items:center;gap:5px;cursor:pointer}
@media(prefers-color-scheme:dark){label.tog{color:#cbd5e1}}
.vis{color:#64748b;font-size:12px;margin:6px 0 10px}
</style></head><body>
<h1>Arc Review &mdash; golden set</h1>
<p class="sub">Deduped arcs from arcs_golden.db &middot; click any arc to expand its full thread &middot; rendered """ + now + """</p>
<div class="cards">
 <div class="pill"><div class="big">""" + str(n_open) + """</div><div class="lbl">open</div></div>
 <div class="pill"><div class="big">""" + str(n_closed) + """</div><div class="lbl">closed</div></div>
 <div class="pill"><div class="big">""" + str(n_open + n_closed) + """</div><div class="lbl">total arcs</div></div>
</div>
<div class="filters">
 <button class="fchip active" data-life="open">Open</button>
 <button class="fchip" data-life="closed">Closed</button>
 <button class="fchip" data-life="">All status</button>
 <span class="sep"></span>
 <label class="tog"><input type="checkbox" id="hidebot" checked> Hide bot-dev</label>
</div>
<div class="filters"><input id="q" class="search" type="search" placeholder="Search arc names, summaries & message contents..." autocomplete="off" autocapitalize="off" spellcheck="false"></div>
<div class="filters">""" + domchips + """</div>
<div class="vis" id="vis"></div>
""" + "".join(cards) + """
<script>
var dom="", life="open";
function apply(){
  var q=document.getElementById('q').value.trim().toLowerCase();
  var searching=q.length>0;
  var hb=document.getElementById('hidebot').checked, shown=0;
  document.querySelectorAll('.arc').forEach(function(el){
    var tags=(el.dataset.tags||'').split(',').filter(Boolean), l=el.dataset.life, ok=true;
    if(searching){
      // global text search across the whole card: title, goal, summary, status AND every message in the thread. ignores the chip/toggle filters so nothing hides a real hit.
      ok=el.textContent.toLowerCase().indexOf(q)>=0;
    } else {
      if(life && l!==life) ok=false;
      if(dom && tags.indexOf(dom)<0) ok=false;
      if(hb && tags.indexOf('bot-dev')>=0) ok=false;
    }
    el.style.display=ok?'':'none';
    if(ok) shown++;
    // auto-expand matches while searching so you can see WHERE it hit; collapse them again when the search clears (leave manually-opened arcs alone).
    if(searching && ok && !el.open){ el.open=true; el.dataset.ao='1'; }
    if(!searching && el.dataset.ao){ el.open=false; delete el.dataset.ao; }
  });
  var vis=document.getElementById('vis');
  vis.textContent = searching ? ('found '+shown+' arc'+(shown==1?'':'s')+' matching "'+q+'"') : ('showing '+shown+' arcs');
}
document.querySelectorAll('.fchip[data-life]').forEach(function(b){b.onclick=function(){
  life=b.dataset.life; document.querySelectorAll('.fchip[data-life]').forEach(function(x){x.classList.remove('active')}); b.classList.add('active'); apply();
}});
document.querySelectorAll('.fchip[data-dom]').forEach(function(b){b.onclick=function(){
  dom=b.dataset.dom; document.querySelectorAll('.fchip[data-dom]').forEach(function(x){x.classList.remove('active')}); b.classList.add('active'); apply();
}});
document.getElementById('hidebot').onchange=apply;
var qi=document.getElementById('q');
qi.addEventListener('input', apply);
qi.addEventListener('search', apply); // fires on the clear-'x'
apply();
</script>
</body></html>"""


if __name__ == "__main__":
    print(render()[:600])
