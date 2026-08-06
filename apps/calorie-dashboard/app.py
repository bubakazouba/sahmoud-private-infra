"""Preksha calorie dashboard — live from state/preksha_calories.db, with a
Recalculate button that shells the real calculator.

Sahmoud 2026-08-05. The DB is owned by chat-assistant/scripts/preksha_calories.py;
this app only READS it and triggers that script. No nutrition logic lives here, so
there is exactly one source of truth for what a day's calories are.

Charts are hand-rolled SVG: no CDN, no chart library. A Tailscale-only dashboard that
silently breaks because a CDN is unreachable is worse than a plain one.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request

HERE = Path(__file__).resolve().parent
CHAT = Path(r"C:\Users\bubakazouba\chat-assistant")
DB_PATH = CHAT / "state" / "preksha_calories.db"
CALC = CHAT / "scripts" / "preksha_calories.py"
STATUS_PATH = CHAT / "state" / "_calorie_recalc_status.json"
APPLICATION_ROOT = os.environ.get("APPLICATION_ROOT", "")

app = Flask(__name__)
app.config["APPLICATION_ROOT"] = APPLICATION_ROOT

_job_lock = threading.Lock()


# ------------------------------------------------------------------------- data

def _rows(sql, args=()):
    if not DB_PATH.exists():
        return []
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def payload():
    days = _rows("SELECT date, total_cal, preksha_cal, shape, note, protein_g, fat_g,"
                 " carbs_g, stated_cal, estimated_cal, unparsed, computed_at, msg_count"
                 " FROM days ORDER BY date")
    items = _rows("SELECT date, ts, food, qty, cal, protein, fat, carbs, basis,"
                  " person, day_label FROM items ORDER BY date, ts")
    return {"days": days, "items": items}


def read_status():
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"state": "idle", "lines": []}


def write_status(d):
    try:
        STATUS_PATH.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------- recalc

def _run_recalc(start, end, force):
    """Run the calculator as a subprocess and stream its output into the status file.

    File-backed stdio and an explicit exe for the same reason the calculator itself
    uses them: a hung child behind a pipe cannot be killed cleanly.
    """
    out_path = CHAT / "state" / "_calorie_recalc.out"
    args = [sys.executable, str(CALC), "recalc"]
    if start:
        args += ["--start", start]
    if end:
        args += ["--end", end]
    if force:
        args += ["--force"]

    write_status({"state": "running", "started": time.time(),
                  "cmd": " ".join(args[2:]), "lines": ["starting..."]})
    try:
        with open(out_path, "wb") as fout:
            p = subprocess.Popen(args, stdout=fout, stderr=subprocess.STDOUT,
                                 cwd=str(CHAT))
            while p.poll() is None:
                time.sleep(2)
                try:
                    txt = out_path.read_text(encoding="utf-8", errors="replace")
                    st = read_status()
                    st["lines"] = txt.splitlines()[-40:]
                    st["state"] = "running"
                    write_status(st)
                except Exception:
                    pass
            rc = p.returncode
        txt = out_path.read_text(encoding="utf-8", errors="replace")
        write_status({"state": "done" if rc == 0 else "failed", "rc": rc,
                      "finished": time.time(), "lines": txt.splitlines()[-60:]})
    except Exception as e:
        write_status({"state": "failed", "error": "%s: %s" % (type(e).__name__, e),
                      "lines": []})


@app.post("/recalc")
def recalc():
    st = read_status()
    if st.get("state") == "running":
        return jsonify({"ok": False, "why": "a recalculation is already running"}), 409
    body = request.get_json(silent=True) or {}
    if not _job_lock.acquire(blocking=False):
        return jsonify({"ok": False, "why": "busy"}), 409
    try:
        t = threading.Thread(target=_run_recalc, daemon=True,
                             args=(body.get("start"), body.get("end"),
                                   bool(body.get("force"))))
        t.start()
    finally:
        _job_lock.release()
    return jsonify({"ok": True})


@app.get("/recalc/status")
def recalc_status():
    return jsonify(read_status())


@app.get("/data.json")
def data_json():
    return jsonify(payload())


@app.get("/healthz")
def healthz():
    return {"ok": True, "app": "calorie-dashboard", "db": DB_PATH.exists(),
            "days": len(_rows("SELECT date FROM days"))}


@app.get("/")
def index():
    d = payload()
    return PAGE.replace("__DATA__", json.dumps(d))


PAGE = r"""<!doctype html>
<html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Preksha - calories</title>
<style>
:root{
  --bg:#f7f7f5; --card:#fff; --ink:#16181d; --ink2:#5b616e; --line:#e3e4e8;
  --protein:#2f6fd0; --fat:#d98324; --carbs:#2e9e6b;
  --stated:#3b5bdb; --estimated:#9aa6c4; --warn:#c1121f;
}
@media (prefers-color-scheme:dark){
  :root{--bg:#14161a; --card:#1c1f25; --ink:#eceef2; --ink2:#9aa1ad; --line:#2b2f37;
        --estimated:#4a5570;}
}
:root[data-theme=dark]{--bg:#14161a;--card:#1c1f25;--ink:#eceef2;--ink2:#9aa1ad;
  --line:#2b2f37;--estimated:#4a5570;}
:root[data-theme=light]{--bg:#f7f7f5;--card:#fff;--ink:#16181d;--ink2:#5b616e;
  --line:#e3e4e8;--estimated:#9aa6c4;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:22px 18px 60px}
h1{font-size:21px;margin:0 0 2px;letter-spacing:-.01em}
.sub{color:var(--ink2);font-size:13px;margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:16px 18px;margin-bottom:16px}
.card h2{font-size:13px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--ink2);margin:0 0 12px;font-weight:600}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:16px}
button,select,input{font:inherit;color:var(--ink);background:var(--card);
  border:1px solid var(--line);border-radius:7px;padding:7px 11px}
button{cursor:pointer}
button.primary{background:var(--stated);border-color:var(--stated);color:#fff;
  font-weight:600}
button:disabled{opacity:.5;cursor:not-allowed}
.pill{display:inline-flex;gap:6px;align-items:center;font-size:12px;color:var(--ink2)}
.sw{width:10px;height:10px;border-radius:2px;display:inline-block}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--line);
  white-space:nowrap}
th{color:var(--ink2);font-weight:600;font-size:12px}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.est{color:var(--ink2)}
.tag{font-size:11px;padding:1px 6px;border-radius:99px;border:1px solid var(--line)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:820px){.grid2{grid-template-columns:1fr}}
#log{font:12px ui-monospace,Menlo,Consolas,monospace;color:var(--ink2);
  white-space:pre-wrap;max-height:150px;overflow:auto;margin-top:10px}
.empty{color:var(--ink2);padding:20px 0}
</style></head><body><div class=wrap>

<h1>Preksha - calorie tracking</h1>
<div class=sub id=sub></div>

<div class=card>
  <div class=bar>
    <button class=primary id=recalc>Recalculate range</button>
    <label class=pill>from <input type=date id=from></label>
    <label class=pill>to <input type=date id=to></label>
    <label class=pill><input type=checkbox id=force> force (ignore cache)</label>
    <span class=pill id=jobstate></span>
  </div>
  <div class=sub style="margin:0">Cached days are skipped; the last 2 days always
    recompute because entries get added late.</div>
  <div id=log></div>
</div>

<div class=bar>
  <label class=pill>aggregate
    <select id=agg><option value=day>by day</option><option value=week>by week</option></select>
  </label>
  <span class=pill><span class=sw style="background:var(--stated)"></span>stated by Preksha</span>
  <span class=pill><span class=sw style="background:var(--estimated)"></span>estimated</span>
  <span class=pill><span class=sw style="background:var(--protein)"></span>protein</span>
  <span class=pill><span class=sw style="background:var(--fat)"></span>fat</span>
  <span class=pill><span class=sw style="background:var(--carbs)"></span>carbs</span>
</div>

<div class=card><h2>Total calories</h2><div class=scroll id=c_cal></div></div>
<div class=card><h2>Macros (grams)</h2><div class=scroll id=c_mac></div></div>

<div class=grid2>
  <div class=card><h2>Day detail - cumulative through the day</h2>
    <div class=bar><label class=pill>day <select id=daysel></select></label></div>
    <div class=scroll id=c_cum></div></div>
  <div class=card><h2>Macro split (calories) for that day</h2>
    <div id=c_pie></div></div>
</div>

<div class=card><h2>Items</h2><div class=scroll id=tbl></div></div>

<script>
const DATA = __DATA__;
const $ = s => document.querySelector(s);
const NS = "http://www.w3.org/2000/svg";
const CSS = k => getComputedStyle(document.documentElement).getPropertyValue(k).trim();

function el(t, a){ const n=document.createElementNS(NS,t);
  for(const k in (a||{})) n.setAttribute(k,a[k]); return n; }
function fmt(n){ return n==null?"-":Math.round(n).toLocaleString(); }

function weekKey(d){
  const dt=new Date(d+"T00:00:00");
  const day=(dt.getDay()+6)%7;             // Monday-start
  dt.setDate(dt.getDate()-day);
  return dt.toISOString().slice(0,10);
}

/* Only 'live' days are real single-day totals. A 'bulk_multiday' row is a
   retrospective dump (one message per weekday, several days posted at once); summing
   it into its posting date would invent a 6,000-calorie Tuesday. Those are listed
   separately instead. */
const LIVE = DATA.days.filter(d=>(d.shape||"live")==="live");
const BULK = DATA.days.filter(d=>(d.shape||"live")==="bulk_multiday");

function aggregate(mode){
  const out={};
  for(const d of LIVE){
    const k = mode==="week" ? weekKey(d.date) : d.date;
    const o = out[k] || (out[k]={key:k, n:0, cal:0, stated:0, est:0,
                                 protein:0, fat:0, carbs:0, unparsed:0});
    o.n++; o.cal+=d.preksha_cal||0; o.stated+=d.stated_cal||0; o.est+=d.estimated_cal||0;
    o.protein+=d.protein_g||0; o.fat+=d.fat_g||0; o.carbs+=d.carbs_g||0;
    o.unparsed+=d.unparsed||0;
  }
  return Object.values(out).sort((a,b)=>a.key<b.key?-1:1);
}

/* stacked bars; series = [{key,color,label}] */
function stackedBars(host, rows, series, unit){
  host.innerHTML="";
  if(!rows.length){ host.innerHTML='<div class=empty>No data yet - hit Recalculate.</div>'; return; }
  const bw=Math.max(26, Math.min(64, Math.floor(940/rows.length)));
  const W=Math.max(560, rows.length*bw+70), H=260, pad={l:52,r:12,t:12,b:46};
  const max=Math.max(1,...rows.map(r=>series.reduce((s,x)=>s+(r[x.key]||0),0)));
  const svg=el("svg",{width:W,height:H,role:"img"});
  const y=v=>H-pad.b-(v/max)*(H-pad.t-pad.b);
  for(let i=0;i<=4;i++){ const v=max*i/4;
    svg.appendChild(el("line",{x1:pad.l,x2:W-pad.r,y1:y(v),y2:y(v),
      stroke:CSS("--line")}));
    const t=el("text",{x:pad.l-8,y:y(v)+4,"text-anchor":"end","font-size":11,
      fill:CSS("--ink2")}); t.textContent=fmt(v); svg.appendChild(t); }
  rows.forEach((r,i)=>{
    let acc=0;
    const x=pad.l+i*bw+4, w=bw-8;
    series.forEach(s=>{
      const v=r[s.key]||0; if(v<=0) return;
      const h=(v/max)*(H-pad.t-pad.b);
      const rect=el("rect",{x:x,y:y(acc+v),width:w,height:Math.max(1,h-2),
        fill:s.color,rx:3});
      const ttl=el("title"); ttl.textContent=`${r.key}\n${s.label}: ${fmt(v)} ${unit}`;
      rect.appendChild(ttl); svg.appendChild(rect); acc+=v;
    });
    /* A day whose entries were mostly PHOTOS is not a low-calorie day, it is a day we
       could not read. 2026-08-01 parsed to 400 cal with 4 of its 5 entries unparsed.
       Drawing that as an ordinary short bar would be a lie of omission, so incomplete
       days get a dashed red outline and say so on hover. */
    if(r.unparsed>0){
      const top=y(acc);
      svg.appendChild(el("rect",{x:x-2,y:top-3,width:w+4,height:(H-pad.b)-top+3,
        fill:"none",stroke:CSS("--warn"),"stroke-width":1.5,
        "stroke-dasharray":"4 3",rx:3}));
      const mk=el("text",{x:x+w/2,y:top-7,"text-anchor":"middle","font-size":11,
        fill:CSS("--warn"),"font-weight":"700"});
      mk.textContent="!";
      const mt=el("title");
      mt.textContent=`${r.key}: ${r.unparsed} entr${r.unparsed===1?"y":"ies"} were `+
        `photo-only and could not be counted - this total is INCOMPLETE`;
      mk.appendChild(mt); svg.appendChild(mk);
    }
    if(rows.length<=32||i%Math.ceil(rows.length/24)===0){
      const t=el("text",{x:x+w/2,y:H-pad.b+16,"text-anchor":"middle","font-size":10,
        fill:CSS("--ink2"),transform:`rotate(-40 ${x+w/2} ${H-pad.b+16})`});
      t.textContent=r.key.slice(5); svg.appendChild(t);
    }
  });
  host.appendChild(svg);
}

function cumulativeChart(host, date){
  host.innerHTML="";
  const its=DATA.items.filter(i=>i.date===date && i.cal!=null)
                      .sort((a,b)=>(a.ts||"")<(b.ts||"")?-1:1);
  if(!its.length){ host.innerHTML='<div class=empty>No parsed items for that day.</div>'; return; }
  const W=560,H=250,pad={l:52,r:14,t:12,b:34};
  const pts=[]; let c=0;
  its.forEach(i=>{ c+=i.cal||0; pts.push({t:i.ts||"", v:c, food:i.food}); });
  const max=Math.max(1,c);
  const toMin=t=>{ const m=/^(\d{1,2}):(\d{2})/.exec(t||"");
    return m?(+m[1])*60+(+m[2]):0; };
  const t0=Math.min(...pts.map(p=>toMin(p.t))), t1=Math.max(...pts.map(p=>toMin(p.t)));
  const span=Math.max(30,t1-t0);
  const X=p=>pad.l+((toMin(p.t)-t0)/span)*(W-pad.l-pad.r);
  const Y=v=>H-pad.b-(v/max)*(H-pad.t-pad.b);
  const svg=el("svg",{width:W,height:H});
  for(let i=0;i<=4;i++){ const v=max*i/4;
    svg.appendChild(el("line",{x1:pad.l,x2:W-pad.r,y1:Y(v),y2:Y(v),stroke:CSS("--line")}));
    const tx=el("text",{x:pad.l-8,y:Y(v)+4,"text-anchor":"end","font-size":11,
      fill:CSS("--ink2")}); tx.textContent=fmt(v); svg.appendChild(tx); }
  let d="";
  pts.forEach((p,i)=>{ d+=(i?" L":"M")+X(p)+" "+Y(p.v); });
  svg.appendChild(el("path",{d:d,fill:"none",stroke:CSS("--stated"),"stroke-width":2}));
  pts.forEach(p=>{ const cc=el("circle",{cx:X(p),cy:Y(p.v),r:4,fill:CSS("--stated")});
    const ttl=el("title"); ttl.textContent=`${p.t} ${p.food}\ncumulative ${fmt(p.v)} cal`;
    cc.appendChild(ttl); svg.appendChild(cc); });
  const lab=el("text",{x:pad.l,y:H-10,"font-size":11,fill:CSS("--ink2")});
  lab.textContent=pts[0].t+"  ->  "+pts[pts.length-1].t; svg.appendChild(lab);
  host.appendChild(svg);
}

function pieChart(host, date){
  host.innerHTML="";
  const d=DATA.days.find(x=>x.date===date);
  if(!d){ host.innerHTML='<div class=empty>No data.</div>'; return; }
  const parts=[{l:"protein",v:(d.protein_g||0)*4,c:CSS("--protein")},
               {l:"carbs",  v:(d.carbs_g||0)*4,  c:CSS("--carbs")},
               {l:"fat",    v:(d.fat_g||0)*9,    c:CSS("--fat")}];
  const tot=parts.reduce((s,p)=>s+p.v,0);
  if(tot<=0){ host.innerHTML='<div class=empty>No macro data for that day.</div>'; return; }
  const W=300,H=250,cx=110,cy=118,r=88;
  const svg=el("svg",{width:W,height:H});
  let a0=-Math.PI/2;
  parts.forEach(p=>{
    const a1=a0+(p.v/tot)*Math.PI*2;
    const x0=cx+r*Math.cos(a0), y0=cy+r*Math.sin(a0);
    const x1=cx+r*Math.cos(a1), y1=cy+r*Math.sin(a1);
    const large=(a1-a0)>Math.PI?1:0;
    const path=el("path",{d:`M ${cx} ${cy} L ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1} Z`,
      fill:p.c,stroke:CSS("--card"),"stroke-width":2});
    const ttl=el("title");
    ttl.textContent=`${p.l}: ${fmt(p.v)} cal (${Math.round(p.v/tot*100)}%)`;
    path.appendChild(ttl); svg.appendChild(path); a0=a1;
  });
  parts.forEach((p,i)=>{
    svg.appendChild(el("rect",{x:216,y:60+i*24,width:10,height:10,fill:p.c,rx:2}));
    const t=el("text",{x:232,y:70+i*24,"font-size":12,fill:CSS("--ink")});
    t.textContent=`${p.l} ${Math.round(p.v/tot*100)}%`; svg.appendChild(t);
  });
  host.appendChild(svg);
}

function table(date){
  const its=DATA.items.filter(i=>i.date===date);
  if(!its.length){ $("#tbl").innerHTML='<div class=empty>No items.</div>'; return; }
  let h="<table><thead><tr><th>time</th><th>food</th><th>qty</th>"+
    "<th class=n>cal</th><th class=n>P</th><th class=n>F</th><th class=n>C</th>"+
    "<th>basis</th><th>who</th><th>day</th></tr></thead><tbody>";
  for(const i of its){
    const warn=(i.basis||"").indexOf("unparsed")>=0;
    const notHers=(i.person||"preksha")==="sahmoud";
    h+=`<tr${notHers?' class=est':''}><td>${i.ts||""}</td><td>${i.food||""}</td>`+
       `<td>${i.qty||""}</td>`+
       `<td class=n>${i.cal==null?"-":fmt(i.cal)}</td>`+
       `<td class=n>${fmt(i.protein)}</td><td class=n>${fmt(i.fat)}</td>`+
       `<td class=n>${fmt(i.carbs)}</td>`+
       `<td><span class=tag style="${warn?'color:var(--warn);border-color:var(--warn)':''}">`+
       `${i.basis||""}</span></td>`+
       `<td>${i.person||""}</td><td>${i.day_label||""}</td></tr>`;
  }
  $("#tbl").innerHTML=h+"</tbody></table>";
}

function render(){
  const mode=$("#agg").value;
  const rows=aggregate(mode);
  stackedBars($("#c_cal"),rows,
    [{key:"stated",color:CSS("--stated"),label:"stated"},
     {key:"est",color:CSS("--estimated"),label:"estimated"}],"cal");
  stackedBars($("#c_mac"),rows,
    [{key:"protein",color:CSS("--protein"),label:"protein"},
     {key:"carbs",color:CSS("--carbs"),label:"carbs"},
     {key:"fat",color:CSS("--fat"),label:"fat"}],"g");
  const day=$("#daysel").value;
  cumulativeChart($("#c_cum"),day);
  pieChart($("#c_pie"),day);
  table(day);
}

function boot(){
  const ds=DATA.days.map(d=>d.date);
  const unp=DATA.days.reduce((s,d)=>s+(d.unparsed||0),0);
  $("#sub").textContent = ds.length
    ? `${LIVE.length} tracked days, ${ds[0]} to ${ds[ds.length-1]}`+
      (unp?` - ${unp} photo-only entries not counted`:"")+
      (BULK.length?` - ${BULK.length} retrospective dumps excluded`:"")
    : "No days computed yet.";
  if(BULK.length){
    const b=document.createElement("div");
    b.className="card";
    b.innerHTML="<h2>Excluded from the charts</h2>"+
      "<div class=sub style='margin:0 0 8px'>These dates are retrospective dumps: one "+
      "message per weekday, several days written up in one sitting, and they log both "+
      "people. Charting them as single-day totals would invent a 6,000-calorie day.</div>"+
      BULK.map(d=>`<div class=pill>${d.date} - ${fmt(d.preksha_cal)} cal attributed to `+
        `Preksha across ${d.note?d.note.replace(/^retrospective dump covering /,""):"several days"}</div>`)
        .join("<br>");
    $("#sub").after(b);
  }
  $("#daysel").innerHTML=ds.slice().reverse().map(d=>`<option>${d}</option>`).join("");
  if(ds.length){ $("#from").value=ds[0]; $("#to").value=ds[ds.length-1]; }
  $("#agg").onchange=render;
  $("#daysel").onchange=render;
  render();
  poll();
}

async function poll(){
  try{
    const r=await fetch("recalc/status",{cache:"no-store"});
    const s=await r.json();
    $("#jobstate").textContent = s.state==="running" ? "running..." :
      (s.state==="done" ? "last run: done" :
       (s.state==="failed" ? "last run FAILED" : ""));
    $("#log").textContent=(s.lines||[]).join("\n");
    $("#recalc").disabled = s.state==="running";
    if(s.state==="running") setTimeout(poll,2500);
    else if(window.__wasRunning){ window.__wasRunning=false; location.reload(); }
    if(s.state==="running") window.__wasRunning=true;
  }catch(e){ $("#jobstate").textContent="status unavailable"; }
}

$("#recalc").onclick=async()=>{
  $("#recalc").disabled=true;
  const body={start:$("#from").value||null,to:null,end:$("#to").value||null,
              force:$("#force").checked};
  const r=await fetch("recalc",{method:"POST",
    headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!r.ok){ const j=await r.json().catch(()=>({}));
    $("#jobstate").textContent=j.why||"could not start"; $("#recalc").disabled=false;
    return; }
  window.__wasRunning=true; poll();
};

boot();
</script></div></body></html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", "18036"))
    app.run(host="127.0.0.1", port=port, threaded=True)
