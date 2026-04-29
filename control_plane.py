"""FastAPI control plane: OAuth gate + reverse-proxy + admin console.

Routes:
  GET  /                     admin console (lists registered apps)
  GET  /healthz              public liveness check
  GET  /login                kicks off Google OAuth
  GET  /oauth-callback       finishes OAuth, sets session cookie
  GET  /logout               clears session
  GET  /api/apps             list registered apps (gated)
  GET  /api/apps/{name}      single app + state (gated)
  *    /app/{name}/{path}    reverse-proxy to child app on its assigned port (gated)

Run:  python control_plane.py
"""
import json
import os
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


@app.middleware("http")
async def auth_gate(req: Request, call_next):
    path = req.url.path
    if path in PUBLIC_PATHS:
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


@app.get("/", response_class=HTMLResponse)
def index(req: Request):
    sess = _read_session(req) or {}
    apps = db.list_apps()
    cards = "\n".join(
        f'<a class=card href="/app/{a["name"]}/"><h3>{a["name"]}</h3>'
        f'<p>{a.get("description") or ""}</p>'
        f'<p class=meta>port {a["port"]} · status <strong>{a.get("status") or "?"}</strong></p></a>'
        for a in apps
    )
    return HTMLResponse(f"""<!doctype html><html><head><meta charset=utf-8>
<title>sahmoud-private infra</title>
<style>
body{{background:#0d1117;color:#c9d1d9;font-family:-apple-system,sans-serif;margin:0;padding:24px;}}
h1{{margin:0 0 4px;font-size:24px}}
.meta{{color:#8b949e;font-size:13px;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}}
.card{{display:block;background:#161b22;border:1px solid #21262d;border-radius:10px;padding:16px;color:#c9d1d9;text-decoration:none}}
.card:hover{{border-color:#79c0ff;transform:translateY(-2px)}}
.card h3{{margin:0 0 4px;color:#79c0ff}}
.card p{{margin:0;color:#8b949e;font-size:13px}}
.card .meta{{margin-top:8px;font-size:11px}}
.card strong{{color:#7ee787}}
.foot{{margin-top:24px;color:#6e7681;font-size:11px}}
</style></head><body>
<h1>⚙️ sahmoud-private infra</h1>
<div class=meta>logged in as <strong>{sess.get("email")}</strong> · {len(apps)} apps registered · <a style=color:#79c0ff href=/logout>logout</a></div>
<div class=grid>{cards or '<p>no apps registered yet — see manage.py</p>'}</div>
<div class=foot>FastAPI control plane on :{PORT} · OAuth-gated · reverse-proxy via /app/&lt;name&gt;/</div>
</body></html>""")


@app.get("/api/apps")
def api_list_apps():
    return {"apps": db.list_apps()}


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
