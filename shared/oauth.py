"""Reusable Google OAuth gate, ported from the Flask POC and adapted for FastAPI.

Strategy: a session cookie holds {"email": <addr>} once the user has completed
the OAuth dance. The control plane checks this on every inbound request and
redirects to /login if missing or not on the allowlist.

Config — all via environment variables (no personal data baked in):
  OAUTH_CLIENT_SECRETS_FILE   path to Google OAuth web client JSON
  OAUTH_CLIENT_ID             OAuth web client_id (must match the secrets file)
  ALLOWED_EMAILS              comma-separated allowlist
  PUBLIC_URL                  external https URL (Tailscale Funnel URL etc.)
  INFRA_SECRET_KEY            session-cookie signing key — persisted across restarts
                              (auto-generated to state/secret.key on first boot)
"""
import os
import secrets
from itsdangerous import URLSafeTimedSerializer, BadSignature
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as g_requests
from pathlib import Path

# Allow http://localhost in dev; tolerate scope expansion from prior grants.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

INFRA_ROOT = Path(__file__).resolve().parent.parent

# Load .env from project root if present (no python-dotenv dependency required).
# manage.py spawns control_plane / supervisor as subprocess.Popen without env=,
# so any vars set only in .env wouldn't reach them otherwise.
_env_file = INFRA_ROOT / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

CREDS_FILE = os.environ.get(
    "OAUTH_CLIENT_SECRETS_FILE",
    str(INFRA_ROOT / "credentials" / "google_oauth_web.json"),
)
ALLOWED_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ALLOWED_EMAILS", "").split(",")
    if e.strip()
}
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://127.0.0.1:8765")
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "")
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]


def _load_secret_key() -> str:
    """Persist the session-cookie signing key across restarts.
    Order: INFRA_SECRET_KEY env var > state/secret.key file > generate fresh.
    """
    env_val = os.environ.get("INFRA_SECRET_KEY")
    if env_val:
        return env_val
    key_file = INFRA_ROOT / "state" / "secret.key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    fresh = secrets.token_hex(32)
    key_file.write_text(fresh, encoding="utf-8")
    try:
        os.chmod(str(key_file), 0o600)
    except Exception:
        pass
    return fresh


SECRET_KEY = _load_secret_key()
SERIALIZER = URLSafeTimedSerializer(SECRET_KEY, salt="infra-session")
SESSION_TTL = 60 * 60 * 24 * 7  # 7 days
COOKIE_NAME = "infra_sess"


def make_flow(redirect_uri):
    return Flow.from_client_secrets_file(CREDS_FILE, scopes=SCOPES, redirect_uri=redirect_uri)


def begin_login(state_holder: dict):
    """Returns (auth_url, state). Caller stores state + code_verifier in session."""
    flow = make_flow(f"{PUBLIC_URL}/oauth-callback")
    auth_url, state = flow.authorization_url(access_type="online", prompt="select_account")
    state_holder["oauth_state"] = state
    state_holder["oauth_code_verifier"] = flow.code_verifier
    return auth_url


def complete_login(state_holder: dict, full_callback_url: str):
    """Returns email if allowed, raises ValueError otherwise."""
    flow = make_flow(f"{PUBLIC_URL}/oauth-callback")
    flow.code_verifier = state_holder.get("oauth_code_verifier")
    flow.fetch_token(authorization_response=full_callback_url)
    info = id_token.verify_oauth2_token(
        flow.credentials.id_token, g_requests.Request(),
        audience=OAUTH_CLIENT_ID, clock_skew_in_seconds=10,
    )
    email = (info.get("email") or "").lower()
    if email not in ALLOWED_EMAILS:
        raise ValueError(f"{email} not on allowlist")
    return email


def encode_session(payload: dict) -> str:
    return SERIALIZER.dumps(payload)


def decode_session(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        return SERIALIZER.loads(token, max_age=SESSION_TTL)
    except BadSignature:
        return None
