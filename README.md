# sahmoud-private-infra

Single-host multi-app infrastructure: one FastAPI control plane reverse-proxies many Flask apps behind a Google OAuth gate, supervised by a long-running tick loop, with a SQLite registry of apps. All five demo apps inside `apps/` (todo, habits, bookmarks, expenses, reading) ship with their own SQLite DBs + minimal HTML frontends.

Production URL is exposed via Tailscale Funnel.

## Architecture

```
                                  ┌────────────────────────────────────────┐
external HTTPS                    │           Windows desktop              │
(Tailscale Funnel) ──────────────►│                                        │
                                  │  ┌──────────────────────┐              │
                                  │  │ control_plane.py     │              │
                                  │  │  FastAPI :8765       │              │
                                  │  │  ┌────────────────┐  │              │
                                  │  │  │ OAuth gate     │  │              │
                                  │  │  │ (allowlist)    │  │              │
                                  │  │  └────────────────┘  │              │
                                  │  │  /app/<name>/...     │              │
                                  │  │  ──────reverse-proxy────►           │
                                  │  └──────────────────────┘  ┌────────┐  │
                                  │                            │ todo   │  │
                                  │  ┌─────────────────┐       │ :18001 │  │
                                  │  │ supervisor.py   │       └────────┘  │
                                  │  │  10s tick loop  │       ┌────────┐  │
                                  │  │  spawns/restarts│       │ habits │  │
                                  │  │  child apps     │       │ :18002 │  │
                                  │  └─────────────────┘       └────────┘  │
                                  │           ▲                ┌────────┐  │
                                  │           │ reads/writes   │ ...    │  │
                                  │           ▼                └────────┘  │
                                  │  ┌──────────────────────────────────┐  │
                                  │  │ state/infra.db (sqlite registry) │  │
                                  │  │  apps + app_state tables         │  │
                                  │  └──────────────────────────────────┘  │
                                  └────────────────────────────────────────┘
```

## Setup

1. **Clone & install deps**
   ```
   git clone https://github.com/bubakazouba/sahmoud-private-infra
   cd sahmoud-private-infra
   pip install -r requirements.txt
   ```

2. **Create a Google OAuth web client**
   - Console → APIs & Services → Credentials → Create OAuth client ID → Web application
   - Add `${PUBLIC_URL}` to Authorized JavaScript origins
   - Add `${PUBLIC_URL}/oauth-callback` to Authorized redirect URIs
   - Download the JSON, save as `credentials/google_oauth_web.json`

3. **Configure**
   ```
   cp .env.example .env
   ```
   Fill in `ALLOWED_EMAILS`, `PUBLIC_URL`, `OAUTH_CLIENT_ID`. Then `set -a; source .env; set +a` (bash) or load equivalently in PowerShell.

4. **Bootstrap the registry + register apps**
   ```
   python manage.py register todo      apps/todo/app.py      --port 18001 --description "Simple todo list"
   python manage.py register habits    apps/habits/app.py    --port 18002 --description "Habit streak tracker"
   python manage.py register bookmarks apps/bookmarks/app.py --port 18003 --description "Bookmark collection"
   python manage.py register expenses  apps/expenses/app.py  --port 18004 --description "Expense log"
   python manage.py register reading   apps/reading/app.py   --port 18005 --description "Reading progress"
   python manage.py list
   ```

5. **Run**
   ```
   python manage.py console start    # FastAPI control plane on :8765
   python manage.py supervisor start # spawns + monitors child apps
   ```

6. **Expose externally** (Tailscale, optional)
   ```
   tailscale funnel 8765
   ```
   Use the printed `https://<host>.tail-XXXX.ts.net` URL as your `PUBLIC_URL`.

## CLI cheatsheet

```
python manage.py list                     # all registered apps + status
python manage.py register <name> <script> [--port N] [--description ...]
python manage.py start <name>             # auto_start=1 (supervisor will spawn)
python manage.py stop <name>              # auto_start=0 + kill
python manage.py restart <name>           # kill + supervisor respawns
python manage.py reset <name>             # clear crashloop status
python manage.py logs <name> [N]          # tail per-app log
python manage.py rm <name>                # unregister + delete row
python manage.py supervisor start|stop|status|restart
python manage.py console    start|stop|status|restart
```

## Adding a new app

1. Create `apps/<yourname>/app.py` — must read `APP_PORT` from env, listen on 127.0.0.1, expose at minimum `GET /healthz` returning `{"ok": True}`.
2. If you have a frontend, expose it under `GET /` and use `APPLICATION_ROOT` from env when constructing URLs (use `{{ base }}` in Jinja templates so the proxy prefix is honored).
3. `python manage.py register <yourname> apps/<yourname>/app.py --description "what it does"`
4. Supervisor will spawn it within 10 seconds.

See `apps/todo/` for the canonical minimal example.

## Tests

```
pytest tests/
```

The proxy + registry round-trip is covered. Each demo app's CRUD is exercised through the OAuth-gated proxy, not direct-port — same shape as production traffic. Test schema is isolated via `INFRA_DB=:memory:`.

## Security notes

- All user-supplied data rendered into HTML is HTML-escaped via the templates' `esc()` helper. Do NOT introduce `innerHTML = userInput` patterns in new apps.
- `SECRET_KEY` for session cookies is auto-persisted to `state/secret.key` (mode 0600) on first boot — sessions survive supervisor restarts. Override via `INFRA_SECRET_KEY` env var.
- The OAuth allowlist is enforced server-side at the control plane. Child apps never see unauthenticated traffic — the proxy strips/rejects before forwarding.
- Credentials and secrets live under `credentials/` (git-ignored). Never commit `google_oauth_web.json`.

## License

Private project, no license. Don't redistribute the OAuth client secrets.
