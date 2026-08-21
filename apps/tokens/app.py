"""Tokens dashboard wrapper — proxies to nateherkai/token-dashboard.

The upstream tool binds 127.0.0.1:8080 with no port flag. This Flask wrapper:
  1. spawns the upstream `python cli.py dashboard --no-open --no-scan` as a
     child process on first request (idempotent — ps-checks before respawn)
  2. reverse-proxies all GET requests on / to http://127.0.0.1:8080/

Sahmoud-private-infra control plane proxies /app/tokens/* → / here, then we
rewrite to upstream. `python C:/users/bubakazouba/token-dashboard/cli.py scan`
should be re-run periodically to refresh the SQLite cache (the upstream's
auto-refresh fires every 30s when running, so the persistent daemon handles it).
"""
import os
import re
import subprocess
import sys
import time
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    _LA = ZoneInfo("America/Los_Angeles")
except Exception:
    _LA = timezone(timedelta(hours=-7))  # PDT fallback

import requests
from flask import Flask, Response, request, abort, jsonify

UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 8080
UPSTREAM_BASE = f"http://{UPSTREAM_HOST}:{UPSTREAM_PORT}"
TOKEN_DASH_DIR = Path(r"C:/users/bubakazouba/token-dashboard")
HERE = Path(__file__).resolve().parent  # this app's dir (holds usage_snapshot.json)
APPLICATION_ROOT = os.environ.get("APPLICATION_ROOT", "")

app = Flask(__name__)
app.config["APPLICATION_ROOT"] = APPLICATION_ROOT

_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length"}

# The upstream dashboard uses ROOT-ABSOLUTE paths (/web/app.js, /api/overview), which
# 404 when this app is served under the control-plane sub-path /app/tokens/ (browser
# requests them at the Tailscale ROOT). Fix: rewrite the HTML's static asset paths to
# the prefix AND inject a fetch/XHR shim so JS-driven /api/ + /web/ calls get prefixed.
PREFIX = (APPLICATION_ROOT or "/app/tokens").rstrip("/")
_INJECT = (
    "<script>(function(){var P=" + repr(PREFIX) + ";"
    "function fix(u){if(typeof u==='string'&&u.charAt(0)==='/'&&u.indexOf(P+'/')!==0&&"
    "(u.indexOf('/api/')===0||u.indexOf('/web/')===0))return P+u;return u;}"
    "var of=window.fetch;window.fetch=function(u,o){return of(fix(u),o);};"
    "var ox=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(m,u){"
    "var a=[].slice.call(arguments);a[1]=fix(u);return ox.apply(this,a);};"
    "})();</script>"
    # Floating entry point to the custom Limits view (session/weekly % + projection).
    "<style>#limitsBtn{position:fixed;top:12px;right:14px;z-index:99999;background:#233148;"
    "color:#e8eef4;border:1px solid #4ea8de;border-radius:999px;padding:7px 14px;font:600 13px "
    "-apple-system,sans-serif;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,.4)}"
    "#limitsBtn:hover{background:#2d3f59}</style>"
    "<script>document.addEventListener('DOMContentLoaded',function(){var a=document.createElement('a');"
    "a.id='limitsBtn';a.href=" + repr(PREFIX + "/limits") + ";a.textContent='📊 Limits';"
    "document.body.appendChild(a);});</script>"
)


_LIMITS_PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Usage Limits</title><style>
 :root{--bg:#0f1419;--panel:#1a2332;--panel2:#233148;--text:#e8eef4;--muted:#8b9bb4;--good:#6ee7b7;--warn:#fbbf24;--bad:#f87171;--accent:#4ea8de}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:15px}
 .wrap{max-width:720px;margin:0 auto;padding:22px 18px 60px}
 h1{font-size:22px;margin:0 0 2px}.sub{color:var(--muted);font-size:13px;margin-bottom:18px}
 .sub a{color:var(--accent);text-decoration:none}
 .card{background:var(--panel);border:1px solid var(--panel2);border-radius:12px;padding:16px 18px;margin-bottom:14px}
 .row{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}
 .lbl{font-weight:600;font-size:15px}.pct{font-size:22px;font-weight:700}
 .bar{height:12px;border-radius:6px;background:var(--panel2);overflow:hidden}
 .fill{height:100%;border-radius:6px;transition:width .4s}
 .meta{color:var(--muted);font-size:13px;margin-top:9px;line-height:1.5}
 .proj{margin-top:8px;font-size:13.5px;padding:8px 10px;border-radius:8px;background:var(--panel2)}
 .proj.warn{background:rgba(248,113,113,.12);color:#fecaca}
 .proj.ok{background:rgba(110,231,183,.10);color:#bbf7d0}
 .foot{color:var(--muted);font-size:12px;margin-top:16px;line-height:1.5}
 .err{color:var(--bad)}
</style></head><body><div class=wrap>
 <h1>📊 Usage Limits</h1>
 <div class=sub>Real account limits from <code>claude /usage</code> + burn-rate projection. <a href="__PREFIX__/">← back to token dashboard</a></div>
 <div id=cards></div>
 <div class=foot id=foot></div>
</div><script>
const PREFIX="__PREFIX__";
function fmt(iso){if(!iso)return"—";const d=new Date(iso);return d.toLocaleString(undefined,{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}
function dur(ms){if(ms==null)return"—";const h=ms/3.6e6;if(h<1)return Math.round(h*60)+"m";if(h<48)return h.toFixed(1)+"h";return (h/24).toFixed(1)+"d"}
function color(p){return p>=90?'var(--bad)':p>=70?'var(--warn)':'var(--good)'}
async function load(){
 const f=document.getElementById('foot');
 let j;try{const r=await fetch(PREFIX+"/api/limits?_="+Date.now());j=await r.json();if(!r.ok)throw new Error(j.error||r.status)}
 catch(e){document.getElementById('cards').innerHTML='<div class="card err">Couldn\\'t load: '+e.message+'</div>';return}
 const now=new Date(j.now);
 const order=['session','week_all','week_sonnet','week_opus'];
 const keys=Object.keys(j.buckets).sort((a,b)=>(order.indexOf(a)+99*(order.indexOf(a)<0))-(order.indexOf(b)+99*(order.indexOf(b)<0)));
 document.getElementById('cards').innerHTML=keys.map(k=>{
  const b=j.buckets[k];const p=b.pct;
  const resetMs=b.reset_at?new Date(b.reset_at)-now:null;
  const etaMs=b.eta_100_at?new Date(b.eta_100_at)-now:null;
  let proj='',cls='';
  if(p>=100){proj='⛔ At the cap. Resets '+fmt(b.reset_at)+' ('+dur(resetMs)+').';cls='warn'}
  else if(b.eta_100_at&&b.hits_cap_before_reset){proj='⚠ At ~'+b.rate_pct_per_hr+'%/hr you\\'d hit 100% in ~'+dur(etaMs)+' ('+fmt(b.eta_100_at)+') — BEFORE the reset.';cls='warn'}
  else if(b.eta_100_at){proj='✓ On pace to reset ('+fmt(b.reset_at)+') with room to spare. 100% only at ~'+fmt(b.eta_100_at)+'.';cls='ok'}
  else{proj='✓ Flat / no recent burn. Resets '+fmt(b.reset_at)+'.';cls='ok'}
  return '<div class=card><div class=row><span class=lbl>'+b.label+'</span><span class=pct style="color:'+color(p)+'">'+p+'%</span></div>'
   +'<div class=bar><div class=fill style="width:'+Math.min(p,100)+'%;background:'+color(p)+'"></div></div>'
   +'<div class=meta>Resets '+fmt(b.reset_at)+' · in '+dur(resetMs)+(b.rate_pct_per_hr!=null?' · burn ~'+b.rate_pct_per_hr+'%/hr':'')+'</div>'
   +'<div class="proj '+cls+'">'+proj+'</div></div>';
 }).join('');
 f.innerHTML='Sampled '+fmt(j.sampled_at)+' · '+j.samples+' history points. The %% are Anthropic\\'s real account numbers; projection is estimated from your local burn rate (sharpens as more samples accrue). Tip: heavy work on Sonnet spares the all-models weekly bucket.';
}
load();setInterval(load,60000);
</script></body></html>"""


def _upstream_alive(timeout=1.5):
    try:
        r = requests.get(UPSTREAM_BASE, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


def _ensure_upstream():
    if _upstream_alive():
        return True
    # Start it detached
    log_path = TOKEN_DASH_DIR / "token-dashboard.log"
    log = open(log_path, "ab")
    subprocess.Popen(
        [sys.executable, str(TOKEN_DASH_DIR / "cli.py"), "dashboard",
         "--no-open", "--no-scan"],
        cwd=str(TOKEN_DASH_DIR),
        stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    # Wait up to ~6s for it to bind
    for _ in range(12):
        time.sleep(0.5)
        if _upstream_alive():
            return True
    return False


@app.get("/healthz")
def healthz():
    up = _upstream_alive()
    return {"ok": True, "app": "tokens", "upstream_alive": up}


USAGE_SNAPSHOT = HERE / "usage_snapshot.json"
USAGE_HISTORY = HERE / "usage_history.jsonl"


def _parse_reset(reset_str, now):
    """Parse a /usage reset like 'Jul 2, 9:59am' into a future aware LA datetime."""
    for fmt in ("%b %d, %I:%M%p", "%b %d, %I%p"):
        try:
            dt = datetime.strptime(f"{reset_str} {now.year}", f"{fmt} %Y").replace(tzinfo=_LA)
            if dt < now - timedelta(days=1):
                dt = dt.replace(year=now.year + 1)
            return dt
        except ValueError:
            continue
    return None


def _project(key, pct, reset_str, history, now):
    """When does this bucket hit 100% at the observed burn rate, vs when it resets?
    Uses recent-history slope if we have it, else average burn since window open."""
    reset_dt = _parse_reset(reset_str, now)
    window = timedelta(hours=5) if key == "session" else timedelta(days=7)
    out = {"reset_at": reset_dt.isoformat() if reset_dt else None, "pct": pct,
           "rate_pct_per_hr": None, "eta_100_at": None, "hits_cap_before_reset": False}
    if reset_dt is None:
        return out
    window_start = reset_dt - window
    samples = []
    for row in history:
        try:
            ts = datetime.fromisoformat(row["sampled_at"])
            p = row.get("pct", {}).get(key)
        except Exception:
            continue
        if p is not None and ts >= window_start:
            samples.append((ts, p))
    samples.sort()
    rate = None
    if len(samples) >= 2 and (samples[-1][0] - samples[0][0]) >= timedelta(minutes=20):
        dt_hr = (samples[-1][0] - samples[0][0]).total_seconds() / 3600.0
        if dt_hr > 0:
            rate = (samples[-1][1] - samples[0][1]) / dt_hr
    if rate is None:
        elapsed_hr = max((now - window_start).total_seconds() / 3600.0, 0.01)
        rate = pct / elapsed_hr
    out["rate_pct_per_hr"] = round(rate, 3)
    if rate > 0 and pct < 100:
        eta = now + timedelta(hours=(100 - pct) / rate)
        out["eta_100_at"] = eta.isoformat()
        out["hits_cap_before_reset"] = eta < reset_dt
    return out


@app.get("/api/limits")
def api_limits():
    """Real account usage limits (from `claude -p /usage`, sampled by
    scripts/usage_probe.py) + a burn-rate projection of time-to-cap. The % are
    authoritative (Anthropic, server-side); the projection is a local estimate."""
    if not USAGE_SNAPSHOT.exists():
        return jsonify({"error": "no usage snapshot yet — run scripts/usage_probe.py"}), 503
    try:
        snap = json.loads(USAGE_SNAPSHOT.read_text(encoding="utf-8"))
    except Exception as e:
        return jsonify({"error": f"bad snapshot: {e}"}), 500
    history = []
    if USAGE_HISTORY.exists():
        for ln in USAGE_HISTORY.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try:
                    history.append(json.loads(ln))
                except Exception:
                    pass
    now = datetime.now(_LA)
    result = {}
    for key, b in snap.get("buckets", {}).items():
        result[key] = {"label": b.get("label", key),
                       **_project(key, b["pct"], b.get("resets", ""), history, now)}
    return jsonify({"sampled_at": snap.get("sampled_at"), "now": now.isoformat(),
                    "buckets": result, "samples": len(history)})


@app.get("/limits")
def limits_page():
    return Response(_LIMITS_PAGE.replace("__PREFIX__", PREFIX),
                    content_type="text/html; charset=utf-8")


@app.route("/", defaults={"p": ""}, methods=["GET"])
@app.route("/<path:p>", methods=["GET"])
def proxy(p):
    if not _ensure_upstream():
        return Response("token-dashboard upstream did not start", status=502)
    target = f"{UPSTREAM_BASE}/{p}"
    if request.query_string:
        target += f"?{request.query_string.decode()}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_HEADERS}
    try:
        r = requests.get(target, headers=headers, timeout=30, stream=True)
    except requests.RequestException as e:
        return Response(f"proxy error: {e}", status=502)
    out_headers = [(k, v) for k, v in r.raw.headers.items() if k.lower() not in _HOP_HEADERS]
    # Strip any caching directives the upstream sent + force no-cache on everything.
    # Without this, iOS Safari aggressively re-uses cached HTML/JS even on pull-refresh
    # (broke the 2026-05-20 wizard patch from reaching Sahmoud's phone).
    out_headers = [(k, v) for k, v in out_headers if k.lower() not in ("cache-control", "etag", "last-modified", "expires", "pragma")]
    out_headers.append(("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"))
    out_headers.append(("Pragma", "no-cache"))
    out_headers.append(("Expires", "0"))
    ctype = r.headers.get("Content-Type", "")
    ctl = ctype.lower()
    # For HTML: rewrite root-absolute asset paths to the sub-path prefix + inject the
    # fetch/XHR shim so the dashboard works under /app/tokens/ (not just at root :8080).
    if "text/html" in ctl:
        html = r.content.decode("utf-8", "replace")
        for attr in ('="/web/', "='/web/", '="/api/', "='/api/"):
            html = html.replace(attr, attr[:2] + PREFIX + attr[2:])
        # Unify the app.js module URL: index.html loads it with a `?v=` cache-buster
        # while the route modules `import` it without one — two distinct module URLs
        # means app.js (and its top-level boot()) evaluates TWICE → a doubled topbar.
        # Our no-store headers make the cache-buster redundant, so strip the query so
        # both references resolve to the SAME module (boot runs once).
        html = re.sub(r"(/web/app\.js)\?[^\"'<> ]*", r"\1", html)
        if "<head>" in html:
            html = html.replace("<head>", "<head>" + _INJECT, 1)
        else:
            html = _INJECT + html
        return Response(html, status=r.status_code, headers=out_headers, content_type=ctype)
    # For JavaScript: rewrite root-absolute path LITERALS (the dashboard's route modules
    # load via dynamic `import('/web/routes/x.js')` + `from '/web/app.js'` + `'/api/...'`).
    # The fetch/XHR shim canNOT intercept ES `import()`, so those 404 at the Tailscale
    # root and render() stays stuck on "loading…". Rewriting the quoted path literals in
    # the JS source itself is the robust fix (covers import, fetch, EventSource alike).
    if "javascript" in ctl:
        js = r.content.decode("utf-8", "replace")
        for q in ("'", '"', "`"):
            js = js.replace(q + "/web/", q + PREFIX + "/web/")
            js = js.replace(q + "/api/", q + PREFIX + "/api/")
        return Response(js, status=r.status_code, headers=out_headers, content_type=ctype)
    return Response(r.iter_content(8192), status=r.status_code, headers=out_headers,
                    content_type=r.headers.get("Content-Type"))


if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", "18019"))
    app.run(host="127.0.0.1", port=port, debug=False)
