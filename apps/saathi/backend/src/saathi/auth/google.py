"""Google sign-in (OpenID Connect authorization code flow with PKCE and nonce, via Authlib)."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from ..config import Settings

GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"


def build_google_oauth(settings: Settings) -> OAuth | None:
    if not settings.google_configured:
        return None
    oauth = OAuth()
    oauth.register(
        "google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        server_metadata_url=GOOGLE_METADATA_URL,
        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
    )
    return oauth


def safe_next(path: str | None) -> str:
    """Only allow same-site relative paths after sign-in, to prevent open redirects."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path
