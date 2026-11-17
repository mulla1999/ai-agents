"""Two-factor sign-in, Sign in with Google, shared rate limits, retention and the Resend sender."""

from __future__ import annotations

import base64
import json
import time
from datetime import timedelta

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import select

from hirefinch.db import AppUser, utcnow
from hirefinch.security import google_oidc, totp
from hirefinch.security.ratelimit import MemoryLimiter, RedisLimiter

PASSWORD = "correct-horse-battery-staple"


async def anon(app) -> httpx.AsyncClient:  # noqa: ANN001
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    c.headers["x-csrf-token"] = (await c.get("/api/auth/csrf")).json()["csrf_token"]
    return c


def current_code(secret: str, offset: int = 0) -> str:
    return totp._code(secret, int(time.time() // 30) + offset)


async def test_two_factor_sign_in(app, client):
    async with app.router.lifespan_context(app):
        setup = (await client.post("/api/auth/2fa/setup")).json()
        assert setup["otpauth_uri"].startswith("otpauth://totp/") and "<svg" in setup["qr_svg"]
        assert (await client.post("/api/auth/2fa/enable", json={"code": "000000"})).status_code == 422
        enabled = (await client.post("/api/auth/2fa/enable", json={"code": current_code(setup["secret"])})).json()
        codes = enabled["recovery_codes"]
        assert len(codes) == 10 and (await client.get("/api/auth/me")).json()["user"]["two_factor"]

        c = await anon(app)
        step1 = (await c.post("/api/auth/login", json={"email": "riya.sharma@example.com", "password": PASSWORD})).json()
        assert step1["two_factor_required"] and not step1["authenticated"]
        assert (await c.get("/api/dashboard")).status_code == 401  # no session after the password alone
        bad = await c.post("/api/auth/login/2fa", json={"challenge": step1["challenge"], "code": "123456"})
        assert bad.status_code == 401
        replay = await c.post("/api/auth/login/2fa", json={"challenge": step1["challenge"], "code": current_code(setup["secret"])})
        assert replay.status_code == 401  # the code used to enable cannot be reused
        ok = await c.post("/api/auth/login/2fa", json={"challenge": step1["challenge"], "code": current_code(setup["secret"], 1)})
        assert ok.status_code == 200 and (await c.get("/api/dashboard")).status_code == 200

        c2 = await anon(app)
        step = (await c2.post("/api/auth/login", json={"email": "riya.sharma@example.com", "password": PASSWORD})).json()
        assert (await c2.post("/api/auth/login/2fa", json={"challenge": step["challenge"], "code": codes[0]})).status_code == 200
        c3 = await anon(app)
        step = (await c3.post("/api/auth/login", json={"email": "riya.sharma@example.com", "password": PASSWORD})).json()
        assert (await c3.post("/api/auth/login/2fa", json={"challenge": step["challenge"], "code": codes[0]})).status_code == 401
        assert (await c2.get("/api/auth/me")).json()["user"]["recovery_codes_left"] == 9
        off = await c2.post("/api/auth/2fa/disable", json={"password": PASSWORD, "code": codes[1]})
        assert off.status_code == 200


def test_challenges_expire_and_cannot_be_forged(settings):
    from itsdangerous import URLSafeTimedSerializer

    forged = URLSafeTimedSerializer("not-the-server-key", salt="hirefinch-2fa").dumps({"u": 1, "n": "x"})
    from hirefinch.services.accounts import _challenges

    with pytest.raises(Exception):
        _challenges(settings).loads(forged, max_age=300)


# ---------------------------------------------------------------- Sign in with Google

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def id_token(claims: dict, key=KEY, kid: str = "k1") -> str:  # noqa: ANN001
    header = _b64(json.dumps({"alg": "RS256", "kid": kid}).encode())
    body = _b64(json.dumps(claims).encode())
    sig = key.sign(f"{header}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{body}.{_b64(sig)}"


def jwks() -> dict:
    n = KEY.public_key().public_numbers()
    return {"keys": [{"kty": "RSA", "kid": "k1", "n": _b64(n.n.to_bytes(256, "big")), "e": _b64(n.e.to_bytes(3, "big"))}]}


def google_transport(claims_for: dict):  # noqa: ANN201
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.googleapis.com":
            return httpx.Response(200, json=jwks())
        if request.url.host == "oauth2.googleapis.com":
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            return httpx.Response(200, json={"id_token": claims_for[form["code"]]})
        raise AssertionError(request.url)
    return httpx.MockTransport(handler)


def claims(nonce: str, **over) -> dict:  # noqa: ANN003
    now = int(time.time())
    return {"iss": "https://accounts.google.com", "aud": "cid.apps.googleusercontent.com", "sub": "g-123",
            "email": "new.person@example.com", "email_verified": True, "name": "New Person", "iat": now,
            "exp": now + 600, "nonce": nonce, **over}


async def test_google_token_verification():
    google_oidc._keys.clear()
    http = httpx.AsyncClient(transport=google_transport({}))
    good = id_token(claims("n1"))
    ident = await google_oidc.verify_id_token(http, good, client_id="cid.apps.googleusercontent.com", nonce="n1")
    assert ident.sub == "g-123" and ident.email == "new.person@example.com"
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token, message in ((id_token(claims("n1"), key=other_key), "signature"),
                           (id_token(claims("n1", aud="someone-else")), "not issued"),
                           (id_token(claims("n2")), "mismatch"),
                           (id_token(claims("n1", email_verified=False)), "not verified"),
                           (id_token(claims("n1", exp=int(time.time()) - 3600)), "expired")):
        with pytest.raises(google_oidc.GoogleAuthError, match=message):
            await google_oidc.verify_id_token(http, token, client_id="cid.apps.googleusercontent.com", nonce="n1")


async def test_google_sign_in_flow(app, client, runtime, sessionmaker):
    google_oidc._keys.clear()
    async with app.router.lifespan_context(app):
        assert (await client.get("/api/auth/google/config")).json() == {"enabled": False}
        saved = await client.put("/api/admin/settings/google_oauth", json={
            "config": {"client_id": "cid.apps.googleusercontent.com"}, "secrets": {"client_secret": "shh-google-secret"}})
        assert saved.status_code == 200 and "shh-google-secret" not in saved.text
        c = await anon(app)
        assert (await c.get("/api/auth/google/config")).json() == {"enabled": True}
        start = await c.get("/api/auth/google/start", follow_redirects=False)
        assert start.status_code == 303 and start.headers["location"].startswith(google_oidc.AUTH_URL)
        query = dict(x.split("=", 1) for x in start.headers["location"].split("?", 1)[1].split("&"))
        assert query["code_challenge_method"] == "S256"
        from hirefinch.api.auth import OAUTH_COOKIE
        from itsdangerous import URLSafeTimedSerializer

        saved_state = URLSafeTimedSerializer(runtime.settings.secret, salt="hirefinch-oauth").loads(
            start.cookies.get(OAUTH_COOKIE) or c.cookies.get(OAUTH_COOKIE))
        runtime.http = httpx.AsyncClient(transport=google_transport({"code1": id_token(claims(saved_state["nonce"]))}))
        wrong_state = await c.get("/api/auth/google/callback", params={"code": "code1", "state": "nope"}, follow_redirects=False)
        assert "error=google_state" in wrong_state.headers["location"]
        start = await c.get("/api/auth/google/start", follow_redirects=False)
        saved_state = URLSafeTimedSerializer(runtime.settings.secret, salt="hirefinch-oauth").loads(c.cookies.get(OAUTH_COOKIE))
        runtime.http = httpx.AsyncClient(transport=google_transport({"code1": id_token(claims(saved_state["nonce"]))}))
        done = await c.get("/api/auth/google/callback", params={"code": "code1", "state": saved_state["state"]},
                           follow_redirects=False)
        assert done.status_code == 303 and done.headers["location"].endswith("/")
        me = (await c.get("/api/auth/me")).json()
        assert me["user"]["email"] == "new.person@example.com" and me["user"]["google_linked"]
        async with sessionmaker() as db:
            user = await db.scalar(select(AppUser).where(AppUser.email == "new.person@example.com"))
            assert user.status == "active" and user.google_sub == "g-123" and user.password_hash is None


# ---------------------------------------------------------------- rate limits, retention, Resend


async def test_memory_and_redis_limiters():
    memory = MemoryLimiter()
    assert all([await memory.hit("k", 3, 60) for _ in range(3)]) and not await memory.hit("k", 3, 60)
    unreachable = RedisLimiter("redis://127.0.0.1:1/0")  # nothing listens: falls back, still limiting
    assert all([await unreachable.hit("k", 2, 60) for _ in range(2)]) and not await unreachable.hit("k", 2, 60)


async def test_retention_warns_then_deletes_inactive_accounts(runtime, sessionmaker, sender, user_id):
    from hirefinch.security.passwords import hash_password
    from hirefinch.services import integrations as integ
    from hirefinch.services.retention import run_retention

    async with sessionmaker() as db:
        idle = AppUser(email="idle@example.com", password_hash=hash_password(PASSWORD), status="active",
                       email_verified_at=utcnow(), consent_at=utcnow(), last_login_at=utcnow() - timedelta(days=400))
        busy = AppUser(email="busy@example.com", password_hash=hash_password(PASSWORD), status="active",
                       email_verified_at=utcnow(), consent_at=utcnow(), last_login_at=utcnow() - timedelta(days=10))
        db.add_all([idle, busy])
        boss = await db.get(AppUser, user_id)
        boss.last_login_at = utcnow() - timedelta(days=900)  # the superadmin is never deleted
        await integ.platform_save(db, runtime.settings, runtime.box, "system_email",
                                  {"provider": "smtp", "host": "smtp.gmail.com", "port": 587, "from_address": "p@example.com"},
                                  {}, user_id)
        await db.commit()
    from unittest import mock

    with mock.patch("hirefinch.services.retention.system_sender", mock.AsyncMock(return_value=sender)):
        assert (await run_retention(runtime)).startswith("1 warned, 0 deleted")
        assert sender.sent[-1][0].to == "idle@example.com"
        assert (await run_retention(runtime)).startswith("0 warned, 0 deleted")  # grace period
        async with sessionmaker() as db:
            row = await db.scalar(select(AppUser).where(AppUser.email == "idle@example.com"))
            row.retention_warned_at = utcnow() - timedelta(days=31)
            await db.commit()
        assert (await run_retention(runtime)).startswith("0 warned, 1 deleted")
    async with sessionmaker() as db:
        emails = set((await db.scalars(select(AppUser.email))).all())
    assert emails == {"riya.sharma@example.com", "busy@example.com"}


async def test_resend_sender(tmp_path):
    from hirefinch.notifications.email import Attachment, OutgoingEmail, ResendSender
    from hirefinch.text import sha256_file

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"], seen["key"] = request.headers["authorization"], request.headers["idempotency-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "re_123"})

    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    sender = ResendSender("HireFinch <no-reply@example.com>", httpx.AsyncClient(transport=httpx.MockTransport(handler)), "re_key")
    result = await sender.send(OutgoingEmail(to="a@example.com", subject="Hi", body="Body", message_id="<m-1@x>",
                                             attachments=[Attachment(str(pdf), "r.pdf", sha256_file(str(pdf)))]))
    assert "re_123" in result.detail and seen["auth"] == "Bearer re_key" and seen["key"] == "m-1@x"
    assert base64.b64decode(seen["body"]["attachments"][0]["content"]) == b"%PDF-1.4 test"


async def test_google_owner_takes_over_an_unverified_sign_up(settings, sessionmaker):
    """Someone signs up with another person's email and never verifies it. When the real owner signs in
    with Google, the earlier password, two-factor setup and sessions must all be gone."""
    from hirefinch.db import UserSession, UserStatus
    from hirefinch.security.passwords import hash_password
    from hirefinch.services import accounts

    async with sessionmaker() as db:
        squatter = AppUser(email="victim@example.com", password_hash=hash_password("attacker-password-123"),
                           status=UserStatus.PENDING, totp_secret="X" * 32, recovery_codes=["abc"])
        db.add(squatter)
        await db.flush()
        db.add(UserSession(user_id=squatter.id, token_hash="h" * 64, expires_at=utcnow() + timedelta(days=1)))
        await db.commit()
        user = await accounts.google_account(db, settings, google_oidc.GoogleIdentity("google-sub-1", "victim@example.com", "Victim"))
        await db.commit()
        assert user.id == squatter.id and user.status == UserStatus.ACTIVE and user.google_sub == "google-sub-1"
        assert user.password_hash is None and user.totp_secret is None and user.recovery_codes == []
        assert (await db.scalar(select(UserSession).where(UserSession.user_id == user.id))) is None
