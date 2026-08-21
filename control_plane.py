"""FastAPI control plane: OAuth gate + reverse-proxy + admin console.

Routes:
  GET  /                          admin console (lists registered apps)
  GET  /healthz                   public liveness check
  GET  /login                     kicks off Google OAuth
  GET  /oauth-callback            finishes OAuth, sets session cookie
  GET  /logout                    clears session
  GET  /api/apps                  list registered apps (gated)
  GET  /api/apps/{name}           single app + state (gated)
  POST /api/apps/{name}/acl       set per-app ACL (gated)
  POST /api/global-allowlist      update global ALLOWED_EMAILS (gated)
  *    /app/{name}/{path}         reverse-proxy to child app on its assigned port (gated)

Run:  python control_plane.py
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from shared import db, oauth

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import httpx
import uvicorn

PORT = int(os.environ.get("CONTROL_PORT", "8765"))
ADMIN_DIR = HERE / "admin"
PUBLIC_PATHS = {"/healthz", "/login", "/oauth-callback", "/favicon.ico"}

db.init_schema()

app = FastAPI(docs_url=None, redoc_url=None)
http_client = httpx.AsyncClient(timeout=30.0, follow_redirects=False)


def _read_session(req: Request) -> dict | None:
    return oauth.decode_session(req.cookies.get(oauth.COOKIE_NAME))


def _set_session(resp: Response, payload: dict):
    token = oauth.encode_session(payload)
    resp.set_cookie(oauth.COOKIE_NAME, token, max_age=oauth.SESSION_TTL,
                    httponly=True, secure=True, samesite="lax")


def _is_public_app_path(path: str) -> bool:
    """Allow unauthenticated access to /app/<name>/* if that app's is_public=1.

    Looks up the registry on each request — cheap single-row sqlite query, OK.
    Returns False on any parse / lookup error so unauth requests fail closed.
    """
    if not path.startswith("/app/"):
        return False
    parts = path.split("/", 3)  # ['', 'app', '<name>', '<rest>']
    if len(parts) < 3 or not parts[2]:
        return False
    try:
        a = db.get_app(parts[2])
        return bool(a and a.get("is_public"))
    except Exception:
        return False


@app.middleware("http")
async def auth_gate(req: Request, call_next):
    path = req.url.path
    if path in PUBLIC_PATHS:
        return await call_next(req)
    if _is_public_app_path(path):
        return await call_next(req)
    sess = _read_session(req)
    if not sess or not sess.get("email"):
        return RedirectResponse(url="/login", status_code=302)
    return await call_next(req)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/login")
def login(req: Request):
    state_holder = {}
    auth_url = oauth.begin_login(state_holder)
    resp = RedirectResponse(url=auth_url, status_code=302)
    _set_session(resp, state_holder)
    return resp


@app.get("/oauth-callback")
def callback(req: Request):
    sess = _read_session(req) or {}
    try:
        email = oauth.complete_login(sess, str(req.url))
    except Exception as e:
        return HTMLResponse(f"<h1>Login failed</h1><p>{e}</p>", status_code=403)
    resp = RedirectResponse(url="/", status_code=302)
    _set_session(resp, {"email": email})
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(oauth.COOKIE_NAME)
    return resp


CRON_SNIPPET_PATH = "C:/users/bubakazouba/chat-assistant/state/cron_dashboard_snippet.html"


def _read_cron_snippet():
    try:
        with open(CRON_SNIPPET_PATH, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f'<p style="color:#f85149">cron snippet unavailable: {e}</p>'


# Standalone one-off dashboards live as static HTML inside the amazon-dashboard app
# (sheraton prices, food freebies, beach/happiness charts, etc.). They are not
# registered apps, so surface them here so they show on the home page too.
_DASH_STATIC = HERE / "apps" / "amazon-dashboard" / "static"
_DASH_SKIP = {"index.html"}  # index.html = the Amazon expenses dashboard (the app itself)


def _standalone_dashboards():
    try:
        items = []
        for f in sorted(_DASH_STATIC.glob("*.html")):
            if f.name in _DASH_SKIP:
                continue
            label = f.stem.replace("_", " ").title()
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")[:4000]
                m = re.search(r"<title>(.*?)</title>", txt, re.I | re.S)
                if m and m.group(1).strip():
                    label = m.group(1).strip()[:80]
            except Exception:
                pass
            items.append(
                f'<tr><td><a class=app-link href="/app/amazon-dashboard/{f.name}">{label}</a></td>'
                f'<td class=desc>{f.name}</td></tr>'
            )
        if not items:
            return ""
        body = "\n".join(items)
        return (
            '<h2>📊 Standalone Dashboards</h2>'
            '<table class=apps-table><thead><tr><th>dashboard</th><th>file</th></tr></thead>'
            f'<tbody>{body}</tbody></table>'
        )
    except Exception as e:
        return f'<!-- standalone dashboards error: {e} -->'


@app.get("/", response_class=HTMLResponse)
def index(req: Request):
    sess = _read_session(req) or {}
    email = (sess.get("email") or "").lower()
    all_apps = db.list_apps()
    # Filter to only apps this user can see per per-app ACL.
    apps = [a for a in all_apps if db.email_can_see_app(email, a)]
    def _acl_badge(a):
        raw = a.get("allowed_emails")
        if raw is None:
            return ''
        emails = [e.strip() for e in raw.split(",") if e.strip()]
        n = len(emails)
        return f'<span class=acl-badge title="per-app ACL: {n} email(s)">ACL: {n}</span>'

    def _row(a):
        is_pub = bool(a.get("is_public"))
        badge = ('<span class=pub-badge title="visible without login">PUBLIC</span>'
                 if is_pub else '<span class=priv-badge title="OAuth-gated">private</span>')
        toggle_label = "→ private" if is_pub else "→ public"
        status = a.get("status") or "?"
        status_class = "status-running" if status == "running" else "status-other"
        acl_badge = _acl_badge(a)
        # Encode current ACL as JSON for the JS
        raw_acl = a.get("allowed_emails")
        if raw_acl is None:
            acl_json = "null"
        else:
            emails_list = [e.strip() for e in raw_acl.split(",") if e.strip()]
            acl_json = json.dumps(emails_list)
        return (
            f'<tr>'
            f'<td><a class=app-link href="/app/{a["name"]}/">{a["name"]}</a> {badge} {acl_badge}</td>'
            f'<td class=desc>{a.get("description") or ""}</td>'
            f'<td class=port>{a["port"]}</td>'
            f'<td><span class="{status_class}">{status}</span></td>'
            f'<td style="white-space:nowrap">'
            f'<button class=pub-toggle data-app="{a["name"]}" data-now="{1 if is_pub else 0}">{toggle_label}</button>'
            f' <button class=acl-btn data-app="{a["name"]}" data-acl=\'{acl_json}\'>manage access</button>'
            f'</td>'
            f'</tr>'
            f'<tr class=acl-panel id="acl-panel-{a["name"]}" style="display:none">'
            f'<td colspan=5 class=acl-panel-cell></td>'
            f'</tr>'
        )
    rows = "\n".join(_row(a) for a in apps)
    global_emails_json = json.dumps(sorted(oauth.ALLOWED_EMAILS))
    return HTMLResponse(f"""<!doctype html><html><head><meta charset=utf-8>
<title>sahmoud-private infra</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
body{{background:#0d1117;color:#c9d1d9;font-family:-apple-system,sans-serif;margin:0;padding:16px;}}
h1{{margin:0 0 4px;font-size:22px}}
.meta{{color:#8b949e;font-size:13px;margin-bottom:18px}}
h2{{margin:24px 0 10px;font-size:16px;color:#79c0ff;border-bottom:1px solid #21262d;padding-bottom:6px}}
table.apps-table{{width:100%;border-collapse:collapse;font-size:13px}}
table.apps-table th,table.apps-table td{{text-align:left;padding:8px 8px;vertical-align:middle;border-bottom:1px solid #21262d}}
table.apps-table th{{background:#161b22;color:#8b949e;font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;position:sticky;top:0}}
table.apps-table tr:hover:not(.acl-panel){{background:#161b22}}
.app-link{{color:#79c0ff;text-decoration:none;font-weight:600}}
.app-link:hover{{text-decoration:underline}}
.desc{{color:#8b949e;font-size:12px;max-width:380px}}
.port{{color:#8b949e;font-family:monospace;font-size:12px}}
.status-running{{color:#7ee787;font-weight:600;font-size:12px}}
.status-other{{color:#d2a8ff;font-size:12px}}
.pub-badge{{display:inline-block;padding:1px 6px;background:#7ee78722;color:#7ee787;border-radius:8px;font-size:10px;font-weight:600;letter-spacing:0.05em;margin-left:4px;vertical-align:middle;white-space:nowrap}}
.priv-badge{{display:inline-block;padding:1px 6px;background:#8b949e22;color:#8b949e;border-radius:8px;font-size:10px;letter-spacing:0.05em;margin-left:4px;vertical-align:middle;white-space:nowrap}}
.acl-badge{{display:inline-block;padding:1px 6px;background:#f0883e22;color:#f0883e;border-radius:8px;font-size:10px;letter-spacing:0.05em;margin-left:4px;vertical-align:middle;white-space:nowrap}}
.pub-toggle{{background:transparent;border:1px solid #30363d;color:#8b949e;border-radius:6px;padding:3px 10px;font-size:11px;cursor:pointer;white-space:nowrap}}
.pub-toggle:hover{{border-color:#79c0ff;color:#79c0ff}}
.acl-btn{{background:transparent;border:1px solid #30363d;color:#f0883e;border-radius:6px;padding:3px 10px;font-size:11px;cursor:pointer;white-space:nowrap;margin-left:4px}}
.acl-btn:hover{{border-color:#f0883e}}
.acl-btn.active{{border-color:#f0883e;background:#f0883e22}}
.acl-panel-cell{{background:#0d1117;padding:12px 16px !important;border-bottom:2px solid #f0883e44 !important}}
.acl-editor{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;max-width:560px}}
.acl-editor h4{{margin:0 0 10px;font-size:13px;color:#f0883e}}
.email-chip{{display:inline-flex;align-items:center;gap:4px;background:#1c2128;border:1px solid #30363d;border-radius:12px;padding:2px 8px;font-size:12px;margin:3px 3px 3px 0;color:#c9d1d9}}
.email-chip button{{background:none;border:none;color:#8b949e;cursor:pointer;font-size:13px;padding:0;line-height:1}}
.email-chip button:hover{{color:#f85149}}
.acl-add-row{{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}}
.acl-add-row input{{flex:1;min-width:160px;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:5px 10px;color:#c9d1d9;font-size:12px;outline:none}}
.acl-add-row input:focus{{border-color:#79c0ff}}
.btn-add{{background:#238636;border:none;border-radius:6px;color:#fff;padding:5px 12px;font-size:12px;cursor:pointer}}
.btn-add:hover{{background:#2ea043}}
.btn-clear{{background:transparent;border:1px solid #6e7681;border-radius:6px;color:#8b949e;padding:5px 12px;font-size:12px;cursor:pointer;margin-left:auto}}
.btn-clear:hover{{border-color:#f85149;color:#f85149}}
.acl-hint{{font-size:11px;color:#8b949e;margin-top:8px}}
.global-panel{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;margin-bottom:20px}}
.global-panel h3{{margin:0 0 4px;font-size:14px;color:#79c0ff;cursor:pointer;user-select:none}}
.global-panel h3::before{{content:'▶ ';font-size:10px;transition:transform 0.2s}}
.global-panel.open h3::before{{content:'▼ ';}}
.global-body{{display:none;margin-top:10px}}
.global-panel.open .global-body{{display:block}}
.foot{{margin-top:24px;color:#6e7681;font-size:11px}}
table.cron-table{{width:100%;border-collapse:collapse;margin-top:8px}}
table.cron-table th,table.cron-table td{{text-align:left;padding:8px 10px;vertical-align:top;border-bottom:1px solid #21262d;font-size:13px}}
table.cron-table th{{background:#161b22;color:#8b949e;font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:0.05em}}
table.cron-table code{{font-size:12px;color:#79c0ff}}
.src{{font-size:11px;color:#8b949e}}
.fire{{display:block;font-size:12px;font-family:monospace;color:#7ee787}}
.kind-croncreate{{display:inline-block;padding:2px 8px;background:#1f6feb22;color:#79c0ff;border-radius:12px;font-size:11px}}
.kind-windows{{display:inline-block;padding:2px 8px;background:#f0883e22;color:#f0883e;border-radius:12px;font-size:11px}}
.res-ok{{color:#7ee787;font-weight:600}}
.res-info{{color:#79c0ff}}
.res-warn{{color:#d2a8ff}}
.res-err{{color:#f85149;font-weight:600}}
.purpose{{font-size:11px;color:#adbac7;margin-top:4px;line-height:1.45;max-width:580px}}
.apps-search{{display:block;width:100%;max-width:560px;margin:0 0 12px;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 12px;color:#c9d1d9;font-size:14px;outline:none;box-sizing:border-box}}
.apps-search:focus{{border-color:#79c0ff}}
.apps-search-count{{color:#8b949e;font-size:11px;margin:-6px 0 10px}}
@media (max-width:720px){{
  body{{padding:10px}}
  h1{{font-size:18px}}
  h2{{font-size:14px;margin:18px 0 8px}}
  .meta{{font-size:12px}}
  table.apps-table thead{{display:none}}
  table.apps-table,table.apps-table tbody,table.apps-table tr,table.apps-table td{{display:block;width:100%;box-sizing:border-box}}
  table.apps-table tr{{border:1px solid #21262d;border-radius:8px;margin-bottom:10px;padding:10px 12px;background:#0d1117}}
  table.apps-table tr.acl-panel{{padding:0;border:none;margin-bottom:0}}
  table.apps-table tr:hover:not(.acl-panel){{background:#0d1117}}
  table.apps-table td{{border-bottom:none;padding:3px 0}}
  table.apps-table td.port::before{{content:'port: ';color:#6e7681}}
  table.apps-table td.desc:empty{{display:none}}
  .desc{{font-size:12px;max-width:100%;color:#8b949e}}
  .acl-panel-cell{{padding:8px !important}}
  .acl-editor{{max-width:100%}}
  .pub-toggle,.acl-btn{{padding:6px 12px;font-size:12px}}
  table.cron-table th,table.cron-table td{{padding:6px 4px;font-size:12px}}
}}
</style></head><body>
<h1>⚙️ sahmoud-private infra</h1>
<div class=meta>logged in as <strong>{sess.get("email")}</strong> · {len(apps)} apps · <a style=color:#79c0ff href=/logout>logout</a></div>

<div class="global-panel" id="global-panel">
<h3 onclick="toggleGlobal()">Global allowlist</h3>
<div class=global-body>
<div id=global-chips></div>
<div class=acl-add-row>
<input id=global-add-input type=email placeholder="add email to global allowlist">
<button class=btn-add onclick="globalAddEmail()">Add</button>
</div>
<div class=acl-hint>Changes save to .env (backed up) and take effect immediately — no restart needed.</div>
</div>
</div>

<h2>📦 Apps</h2>
<input id=apps-search class=apps-search type=search placeholder="🔎 search apps by name, description, or port..." autocomplete=off>
<div id=apps-search-count class=apps-search-count></div>
<table class=apps-table>
<thead><tr><th>name</th><th>description</th><th>port</th><th>status</th><th>access</th></tr></thead>
<tbody>
{rows or '<tr><td colspan=5>no apps registered yet — see manage.py</td></tr>'}
</tbody></table>
{_standalone_dashboards()}
<h2>⏰ Cron jobs</h2>
{_read_cron_snippet()}
<div class=foot>FastAPI control plane on :{PORT} · OAuth-gated · reverse-proxy via /app/&lt;name&gt;/</div>
<script>
var CURRENT_USER = {json.dumps(email)};
var globalEmails = {global_emails_json};

// ── Global allowlist UI ──────────────────────────────────────────────────────
function toggleGlobal() {{
  document.getElementById('global-panel').classList.toggle('open');
}}
function renderGlobalChips() {{
  var c = document.getElementById('global-chips');
  c.innerHTML = '';
  if (!globalEmails.length) {{
    c.innerHTML = '<span style="color:#8b949e;font-size:12px">no emails in global allowlist</span>';
    return;
  }}
  globalEmails.forEach(function(em) {{
    var chip = document.createElement('span');
    chip.className = 'email-chip';
    chip.innerHTML = em + ' <button title="remove" onclick="globalRemoveEmail(\\'' + em + '\\')">×</button>';
    c.appendChild(chip);
  }});
}}
function globalRemoveEmail(em) {{
  var warning = (em === CURRENT_USER) ? 'WARNING: removing yourself will lock you out on next request!\\n\\n' : '';
  if (!confirm(warning + 'Remove ' + em + ' from global allowlist?')) return;
  var next = globalEmails.filter(function(e) {{ return e !== em; }});
  saveGlobalAllowlist(next);
}}
function globalAddEmail() {{
  var inp = document.getElementById('global-add-input');
  var em = inp.value.trim().toLowerCase();
  if (!em) return;
  if (globalEmails.indexOf(em) !== -1) {{ alert(em + ' already in list'); return; }}
  saveGlobalAllowlist(globalEmails.concat([em]));
  inp.value = '';
}}
function saveGlobalAllowlist(emails) {{
  fetch('/api/global-allowlist', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{emails: emails}})
  }}).then(function(r) {{
    return r.json().then(function(d) {{ return {{ok: r.ok, d: d}}; }});
  }}).then(function(x) {{
    if (!x.ok) {{ alert('save failed: ' + JSON.stringify(x.d)); return; }}
    globalEmails = x.d.emails;
    renderGlobalChips();
  }}).catch(function(e) {{ alert('save failed: ' + e); }});
}}
renderGlobalChips();

// ── Per-app public toggle ────────────────────────────────────────────────────
document.addEventListener('click', function(ev) {{
  var btn = ev.target.closest('.pub-toggle');
  if (!btn) return;
  ev.preventDefault();
  var name = btn.dataset.app;
  var nowPub = btn.dataset.now === '1';
  var next = nowPub ? 0 : 1;
  btn.disabled = true;
  fetch('/api/apps/' + encodeURIComponent(name) + '/public', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{is_public: next}})
  }}).then(function(r) {{
    if (r.ok) location.reload();
    else r.text().then(function(t) {{ alert('toggle failed: ' + t); btn.disabled = false; }});
  }}).catch(function(e) {{ alert('toggle failed: ' + e); btn.disabled = false; }});
}});

// ── Per-app ACL editor ───────────────────────────────────────────────────────
var aclState = {{}};  // appName -> [emails] or null

document.addEventListener('click', function(ev) {{
  var btn = ev.target.closest('.acl-btn');
  if (!btn) return;
  ev.preventDefault();
  var name = btn.dataset.app;
  var rawAcl = btn.dataset.acl;
  var panel = document.getElementById('acl-panel-' + name);
  var cell = panel.querySelector('.acl-panel-cell');
  if (panel.style.display !== 'none') {{
    panel.style.display = 'none';
    btn.classList.remove('active');
    return;
  }}
  // Parse current ACL from data attribute
  try {{ aclState[name] = (rawAcl === 'null') ? null : JSON.parse(rawAcl); }}
  catch(e) {{ aclState[name] = null; }}
  renderAclPanel(name, cell);
  panel.style.display = '';
  btn.classList.add('active');
}});

function renderAclPanel(name, cell) {{
  var emails = aclState[name];
  var chipsHtml = '';
  if (emails === null) {{
    chipsHtml = '<span style="color:#8b949e;font-size:12px">using global allowlist (no per-app ACL)</span>';
  }} else if (emails.length === 0) {{
    chipsHtml = '<span style="color:#8b949e;font-size:12px">no emails — this app is inaccessible to all</span>';
  }} else {{
    emails.forEach(function(em) {{
      chipsHtml += '<span class="email-chip">' + em +
        ' <button title="remove" onclick="aclRemoveEmail(\\'' + name + '\\',\\'' + em + '\\')">×</button></span>';
    }});
  }}
  cell.innerHTML =
    '<div class=acl-editor>' +
    '<h4>Per-app access: ' + name + '</h4>' +
    '<div id="chips-' + name + '">' + chipsHtml + '</div>' +
    '<div class=acl-add-row>' +
    '<input id="aclInput-' + name + '" type=email placeholder="add email">' +
    '<button class=btn-add onclick="aclAddEmail(\\'' + name + '\\')">Add</button>' +
    '<button class=btn-clear onclick="aclClear(\\'' + name + '\\')">Clear (use global)</button>' +
    '</div>' +
    '<div class=acl-hint>' +
    (emails === null ? 'All global-allowlist members can access this app.' :
      'Only the emails above can access this app. Empty list = nobody.') +
    '</div>' +
    '</div>';
}}

function aclRemoveEmail(name, em) {{
  var curr = aclState[name];
  var warning = (em === CURRENT_USER) ? 'WARNING: removing yourself will lock you out of this app!\\n\\n' : '';
  if (!confirm(warning + 'Remove ' + em + ' from ' + name + '?')) return;
  var next = (curr || []).filter(function(e) {{ return e !== em; }});
  saveAppAcl(name, next);
}}
function aclAddEmail(name) {{
  var inp = document.getElementById('aclInput-' + name);
  var em = inp.value.trim().toLowerCase();
  if (!em) return;
  var curr = aclState[name] || [];
  if (curr.indexOf(em) !== -1) {{ alert(em + ' already in list'); return; }}
  saveAppAcl(name, curr.concat([em]));
  inp.value = '';
}}
function aclClear(name) {{
  if (!confirm('Clear per-app ACL for ' + name + '? It will fall back to global allowlist.')) return;
  saveAppAcl(name, null);
}}
function saveAppAcl(name, emails) {{
  fetch('/api/apps/' + encodeURIComponent(name) + '/acl', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{emails: emails}})
  }}).then(function(r) {{
    return r.json().then(function(d) {{ return {{ok: r.ok, d: d}}; }});
  }}).then(function(x) {{
    if (!x.ok) {{ alert('save failed: ' + JSON.stringify(x.d)); return; }}
    aclState[name] = x.d.allowed_emails;
    var panel = document.getElementById('acl-panel-' + name);
    var cell = panel.querySelector('.acl-panel-cell');
    renderAclPanel(name, cell);
    // Update the data-acl on the button so re-open shows fresh state
    var btn = document.querySelector('.acl-btn[data-app="' + name + '"]');
    if (btn) btn.dataset.acl = (x.d.allowed_emails === null) ? 'null' : JSON.stringify(x.d.allowed_emails);
    // Refresh ACL badge in name cell
    location.reload();
  }}).catch(function(e) {{ alert('save failed: ' + e); }});
}}

// ── Apps search filter ──────────────────────────────────────────────────────
(function() {{
  var input = document.getElementById('apps-search');
  var countEl = document.getElementById('apps-search-count');
  if (!input) return;
  var rows = Array.prototype.slice.call(document.querySelectorAll('table.apps-table tbody tr')).filter(function(r) {{ return !r.classList.contains('acl-panel'); }});
  var total = rows.length;
  function apply() {{
    var q = input.value.trim().toLowerCase();
    var shown = 0;
    rows.forEach(function(r) {{
      var match = !q || r.textContent.toLowerCase().indexOf(q) >= 0;
      r.style.display = match ? '' : 'none';
      var nxt = r.nextElementSibling;
      if (nxt && nxt.classList.contains('acl-panel') && !match) nxt.style.display = 'none';
      if (match) shown++;
    }});
    countEl.textContent = q ? (shown + ' of ' + total + ' apps') : '';
  }}
  input.addEventListener('input', apply);
}})();
</script>
</body></html>""")


@app.get("/api/apps")
def api_list_apps():
    return {"apps": db.list_apps()}


@app.post("/api/apps/{name}/public")
async def api_set_public(name: str, req: Request):
    """Toggle whether <name> is publicly accessible (no OAuth). OAuth-gated itself."""
    a = db.get_app(name)
    if not a:
        raise HTTPException(404, f"app {name!r} not registered")
    body = await req.json()
    db.set_public(name, bool(body.get("is_public", False)))
    return {"ok": True, "name": name, "is_public": bool(body.get("is_public", False))}


@app.post("/api/apps/{name}/acl")
async def api_set_acl(name: str, req: Request):
    """Set per-app email whitelist. emails=null clears to global. OAuth-gated."""
    a = db.get_app(name)
    if not a:
        raise HTTPException(404, f"app {name!r} not registered")
    body = await req.json()
    emails = body.get("emails")  # list or None
    db.set_acl(name, emails)
    # Reload from DB to confirm write (task constraint: don't echo input).
    refreshed = db.get_app(name)
    raw = refreshed.get("allowed_emails")
    if raw is None:
        result_emails = None
    else:
        result_emails = [e.strip() for e in raw.split(",") if e.strip()]
    return {"ok": True, "name": name, "allowed_emails": result_emails}


_ENV_PATH = HERE / ".env"


def _rewrite_env_allowed_emails(new_emails: list[str]):
    """Atomically rewrite ALLOWED_EMAILS line in .env. Backs up first."""
    env_path = _ENV_PATH
    bak_path = env_path.parent / ".env.bak"
    content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    # Write backup first (full copy).
    bak_path.write_text(content, encoding="utf-8")
    new_line = f"ALLOWED_EMAILS={','.join(new_emails)}"
    if re.search(r"^ALLOWED_EMAILS=.*$", content, re.MULTILINE):
        new_content = re.sub(r"^ALLOWED_EMAILS=.*$", new_line, content, flags=re.MULTILINE)
    else:
        new_content = content.rstrip("\n") + "\n" + new_line + "\n"
    # Atomic write via temp file.
    tmp_path = env_path.parent / ".env.tmp"
    tmp_path.write_text(new_content, encoding="utf-8")
    tmp_path.replace(env_path)


@app.post("/api/global-allowlist")
async def api_set_global_allowlist(req: Request):
    """Update global ALLOWED_EMAILS. Rewrites .env (with backup) + updates in-process. OAuth-gated."""
    body = await req.json()
    emails_raw = body.get("emails", [])
    if not isinstance(emails_raw, list):
        raise HTTPException(400, "emails must be a list")
    normalized = sorted({e.strip().lower() for e in emails_raw if e.strip()})
    # Write to .env first (fail-safe: if this throws, in-memory is not yet changed).
    _rewrite_env_allowed_emails(normalized)
    # Update in-process set in place (clear+update keeps all import-time references valid).
    oauth.ALLOWED_EMAILS.clear()
    oauth.ALLOWED_EMAILS.update(normalized)
    return {"ok": True, "emails": normalized}


@app.get("/api/apps/{name}")
def api_get_app(name: str):
    a = db.get_app(name)
    if not a:
        raise HTTPException(404, f"app {name!r} not found")
    return a


PROXY_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                     "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length"}


@app.api_route("/app/{name}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@app.api_route("/app/{name}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_to_child(req: Request, name: str, path: str = ""):
    a = db.get_app(name)
    if not a:
        raise HTTPException(404, f"app {name!r} not registered")
    # Per-app ACL check (public apps bypass; global allowlist already enforced at login).
    if not a.get("is_public"):
        sess = _read_session(req) or {}
        email = (sess.get("email") or "").lower()
        if not db.email_can_see_app(email, a):
            raise HTTPException(403, f"not authorized to access {name!r}")
    target = f"http://127.0.0.1:{a['port']}/{path}"
    if req.url.query:
        target += f"?{req.url.query}"
    headers = {k: v for k, v in req.headers.items() if k.lower() not in PROXY_HOP_HEADERS}
    # Forward the prefix so child apps know their base url (also set via APPLICATION_ROOT)
    headers["X-Forwarded-Prefix"] = f"/app/{name}"
    headers["X-Forwarded-Proto"] = "https"
    headers["X-Forwarded-Host"] = req.headers.get("host", "")
    body = await req.body()
    try:
        r = await http_client.request(req.method, target, headers=headers, content=body)
    except httpx.ConnectError:
        return JSONResponse({"error": f"app {name!r} not responding on port {a['port']}"}, status_code=502)
    out_headers = {k: v for k, v in r.headers.items() if k.lower() not in PROXY_HOP_HEADERS}
    return Response(content=r.content, status_code=r.status_code, headers=out_headers)


if __name__ == "__main__":
    print(f"[control_plane] up on :{PORT}, allowlist={oauth.ALLOWED_EMAILS}, public_url={oauth.PUBLIC_URL}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
