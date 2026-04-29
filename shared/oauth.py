"""Reusable Google OAuth gate, ported from the Flask POC and adapted for FastAPI.

Strategy: a session cookie holds {"email": <addr>} once the user has completed
the OAuth dance. The control plane checks this on every inbound request and
redirects to /login if missing or not on the allowlist.
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

CREDS_FILE = os.environ.get(
    "OAUTH_CLIENT_SECRETS_FILE",
    str(Path(__file__).resolve().parents[2] / "chat-assistant" / "credentials" / "google_oauth_web.json"),
)
ALLOWED_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ALLOWED_EMAILS", "slashhashdash@gmail.com,ahssahmoud@gmail.com").split(",")
    if e.strip()
}
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://desktop-0rco3g7.tail0159f4.ts.net")
OAUTH_CLIENT_ID = "849053190568-199sqvibphtmburgihpj484scoo8npk8.apps.googleusercontent.com"
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]
SECRET_KEY = secrets.token_hex(32)
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
