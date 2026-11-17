"""Sign in with Google (OpenID Connect, authorization code + PKCE).

The ID token is verified locally: RS256 signature against Google's published keys (cached for an
hour), issuer, audience (our client id), expiry, the nonce we issued, and ``email_verified``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")

_keys: dict[str, rsa.RSAPublicKey] = {}
_keys_at = 0.0


class GoogleAuthError(RuntimeError):
    pass


@dataclass
class GoogleIdentity:
    sub: str
    email: str
    name: str | None


def _b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def start(client_id: str, redirect_uri: str) -> tuple[str, dict[str, str]]:
    """The URL to send the browser to, and the state to keep in a short-lived signed cookie."""
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    query = urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
                       "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account",
                       "code_challenge": challenge, "code_challenge_method": "S256"})
    return f"{AUTH_URL}?{query}", {"state": state, "nonce": nonce, "verifier": verifier}


async def _public_keys(http: httpx.AsyncClient, *, refresh: bool = False) -> dict[str, rsa.RSAPublicKey]:
    global _keys_at
    if _keys and not refresh and time.time() - _keys_at < 3600:
        return _keys
    response = await http.get(CERTS_URL, timeout=15)
    response.raise_for_status()
    _keys.clear()
    for jwk in response.json().get("keys", []):
        if jwk.get("kty") == "RSA":
            n, e = int.from_bytes(_b64(jwk["n"]), "big"), int.from_bytes(_b64(jwk["e"]), "big")
            _keys[jwk["kid"]] = rsa.RSAPublicNumbers(e, n).public_key()
    _keys_at = time.time()
    return _keys


async def verify_id_token(http: httpx.AsyncClient, token: str, *, client_id: str, nonce: str) -> GoogleIdentity:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header, claims = json.loads(_b64(header_b64)), json.loads(_b64(payload_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise GoogleAuthError("malformed ID token") from exc
    if header.get("alg") != "RS256":
        raise GoogleAuthError("unexpected token algorithm")
    keys = await _public_keys(http)
    key = keys.get(header.get("kid")) or (await _public_keys(http, refresh=True)).get(header.get("kid"))
    if key is None:
        raise GoogleAuthError("unknown signing key")
    try:
        key.verify(_b64(signature_b64), f"{header_b64}.{payload_b64}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise GoogleAuthError("invalid token signature") from exc
    now = time.time()
    if claims.get("iss") not in ISSUERS or claims.get("aud") != client_id:
        raise GoogleAuthError("token was not issued for this application")
    if float(claims.get("exp", 0)) < now - 60 or float(claims.get("iat", now)) > now + 300:
        raise GoogleAuthError("token expired")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleAuthError("sign-in session mismatch; try again")
    if claims.get("email_verified") is not True or not claims.get("email"):
        raise GoogleAuthError("your Google email address is not verified")
    return GoogleIdentity(str(claims["sub"]), str(claims["email"]).lower(), claims.get("name"))


async def exchange(http: httpx.AsyncClient, *, code: str, client_id: str, client_secret: str, redirect_uri: str,
                   verifier: str, nonce: str) -> GoogleIdentity:
    response = await http.post(TOKEN_URL, data={"code": code, "client_id": client_id, "client_secret": client_secret,
                                                 "redirect_uri": redirect_uri, "grant_type": "authorization_code",
                                                 "code_verifier": verifier}, timeout=15)
    if response.status_code != 200:
        raise GoogleAuthError("Google did not accept the sign-in; try again")
    token = response.json().get("id_token")
    if not token:
        raise GoogleAuthError("Google returned no identity token")
    return await verify_id_token(http, token, client_id=client_id, nonce=nonce)
