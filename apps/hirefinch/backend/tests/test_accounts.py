"""Accounts, roles, tenant isolation, secret handling and hosted-mode hardening."""

from __future__ import annotations

import re

import httpx
from fastapi.routing import APIRoute
from sqlalchemy import func, select

from hirefinch.db import AppUser, JobPosting, UserSession

PASSWORD = "correct-horse-battery-staple"
JOB = {"title": "Java Developer", "company": "Example Bank", "url": "https://careers.example-bank.example/jobs/42",
       "description": "Requirements\n- 3+ years of experience\n- Java, Spring Boot, Microservices, Kafka, MySQL"}


async def anon(app) -> httpx.AsyncClient:  # noqa: ANN001
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    c.headers["x-csrf-token"] = (await c.get("/api/auth/csrf")).json()["csrf_token"]
    return c


async def login(app, email: str, password: str = PASSWORD) -> httpx.AsyncClient:  # noqa: ANN001
    c = await anon(app)
    r = await c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


async def register_and_verify(app, email: str) -> httpx.AsyncClient:  # noqa: ANN001
    c = await anon(app)
    r = await c.post("/api/auth/register", json={"email": email, "password": PASSWORD, "consent": True})
    assert r.status_code == 202, r.text
    token = re.search(r"token=([\w-]+)", r.json()["dev_link"]).group(1)
    assert (await c.post("/api/auth/verify-email", json={"token": token})).status_code == 200
    await c.aclose()
    return await login(app, email)


async def test_registration_verification_and_sign_in(app):
    async with app.router.lifespan_context(app):
        c = await anon(app)
        assert (await c.post("/api/auth/register", json={"email": "a@example.com", "password": PASSWORD})).status_code == 422
        weak = await c.post("/api/auth/register", json={"email": "a@example.com", "password": "short", "consent": True})
        assert weak.status_code == 422
        r = await c.post("/api/auth/register", json={"email": "A@Example.com", "password": PASSWORD, "consent": True})
        assert r.status_code == 202 and "dev_link" in r.json()  # no platform email: link returned (dev only)
        early = await c.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD})
        assert early.status_code == 403 and "confirm your email" in early.json()["message"]
        token = re.search(r"token=([\w-]+)", r.json()["dev_link"]).group(1)
        assert (await c.post("/api/auth/verify-email", json={"token": token})).status_code == 200
        assert (await c.post("/api/auth/verify-email", json={"token": token})).status_code == 400  # single use
        ok = await c.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD})
        assert ok.status_code == 200 and ok.json()["user"]["role"] == "user"
        me = (await c.get("/api/auth/me")).json()
        assert me["authenticated"] and me["user"]["email"] == "a@example.com"
        await c.post("/api/auth/logout")
        assert (await c.get("/api/dashboard")).status_code == 401


async def test_responses_do_not_reveal_registered_emails(app, user_id):
    async with app.router.lifespan_context(app):
        c = await anon(app)
        taken = await c.post("/api/auth/register", json={"email": "riya.sharma@example.com", "password": PASSWORD, "consent": True})
        fresh = await c.post("/api/auth/register", json={"email": "new@example.com", "password": PASSWORD, "consent": True})
        assert taken.status_code == fresh.status_code == 202
        assert taken.json()["message"] == fresh.json()["message"]
        r1 = await c.post("/api/auth/forgot-password", json={"email": "riya.sharma@example.com"})
        r2 = await c.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
        assert r1.status_code == r2.status_code == 202 and r1.json()["message"] == r2.json()["message"]
        bad = await c.post("/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
        wrong = await c.post("/api/auth/login", json={"email": "riya.sharma@example.com", "password": "nope-nope-nope"})
        assert bad.json()["message"] == wrong.json()["message"] == "wrong email or password"


async def test_lockout_after_repeated_failures(app, user_id, sessionmaker):
    app.state.runtime.limiter.clear()
    async with app.router.lifespan_context(app):
        c = await anon(app)
        for _ in range(10):
            await c.post("/api/auth/login", json={"email": "riya.sharma@example.com", "password": "wrong-password-xx"})
        locked = await c.post("/api/auth/login", json={"email": "riya.sharma@example.com", "password": PASSWORD})
        assert locked.status_code == 429
    app.state.runtime.limiter.clear()


async def test_password_reset_and_change_end_other_sessions(app, user_id, sessionmaker):
    async with app.router.lifespan_context(app):
        first, second = await login(app, "riya.sharma@example.com"), await login(app, "riya.sharma@example.com")
        changed = await first.post("/api/auth/change-password", json={"current_password": PASSWORD,
                                                                       "new_password": "another-long-passphrase"})
        assert changed.status_code == 200
        assert (await first.get("/api/dashboard")).status_code == 200  # this session stays
        assert (await second.get("/api/dashboard")).status_code == 401  # others end
        c = await anon(app)
        link = (await c.post("/api/auth/forgot-password", json={"email": "riya.sharma@example.com"})).json()["dev_link"]
        token = re.search(r"token=([\w-]+)", link).group(1)
        assert (await c.post("/api/auth/reset-password", json={"token": token, "password": PASSWORD})).status_code == 200
        assert (await first.get("/api/dashboard")).status_code == 401  # reset ends every session
        assert (await c.post("/api/auth/reset-password", json={"token": token, "password": PASSWORD})).status_code == 400
        await login(app, "riya.sharma@example.com")


async def test_users_cannot_see_each_others_data(app, client, resume_docx):
    async with app.router.lifespan_context(app):
        await client.post("/api/resumes/masters", files={"file": ("cv.docx", resume_docx)})
        job_id = (await client.post("/api/jobs/import", json=JOB)).json()["id"]
        await client.post(f"/api/jobs/{job_id}/tailor")
        version_id = (await client.get(f"/api/jobs/{job_id}")).json()["resume_versions"][0]["id"]
        app_id = (await client.post(f"/api/jobs/{job_id}/application")).json()["id"]
        contact = (await client.post(f"/api/outreach/jobs/{job_id}/contacts",
                                     json={"email": "hr@example-bank.example", "note": "on the careers page"})).json()

        other = await register_and_verify(app, "other@example.com")
        assert (await other.get("/api/jobs")).json()["total"] == 0
        for path in (f"/api/jobs/{job_id}", f"/api/resumes/versions/{version_id}",
                     f"/api/resumes/versions/{version_id}/download?format=pdf", f"/api/applications/{app_id}"):
            assert (await other.get(path)).status_code == 404, path  # "not found", never "forbidden"
        for path, body in ((f"/api/jobs/{job_id}/tailor", None), (f"/api/applications/{app_id}/approve", {}),
                           (f"/api/outreach/contacts/{contact['id']}/draft", None),
                           (f"/api/jobs/{job_id}/status", {"status": "withdrawn"})):
            assert (await other.post(path, json=body)).status_code == 404, path
        assert (await other.get("/api/applications")).json() == []
        assert (await other.get("/api/outreach")).json() == {"contacts": [], "drafts": []}
        assert (await other.get("/api/resumes/masters")).json() == []
        assert all(e["entity_id"] != job_id for e in (await other.get("/api/audit")).json()["items"])
        assert (await other.get("/api/dashboard")).json()["metrics"]["applications_submitted"] == 0
        # The owner still sees everything.
        assert (await client.get(f"/api/jobs/{job_id}")).status_code == 200


async def test_same_resume_and_job_for_two_users_stay_separate(app, client, resume_docx, sessionmaker):
    async with app.router.lifespan_context(app):
        other = await register_and_verify(app, "twin@example.com")
        for c in (client, other):
            assert (await c.post("/api/resumes/masters", files={"file": ("cv.docx", resume_docx)})).status_code == 201
            assert (await c.post("/api/jobs/import", json=JOB)).status_code == 201
        async with sessionmaker() as db:
            assert await db.scalar(select(func.count(JobPosting.id))) == 2  # not deduplicated across accounts


async def _account(sessionmaker, email: str, role: str) -> int:
    from hirefinch.db import utcnow
    from hirefinch.security.passwords import hash_password

    async with sessionmaker() as db:
        user = AppUser(email=email, password_hash=hash_password(PASSWORD), role=role, status="active",
                       email_verified_at=utcnow(), consent_at=utcnow())
        db.add(user)
        await db.commit()
        return user.id


async def test_roles(app, client, sessionmaker):
    admin_id = await _account(sessionmaker, "admin@example.com", "admin")
    plain_id = await _account(sessionmaker, "plain@example.com", "user")
    async with app.router.lifespan_context(app):
        plain, admin = await login(app, "plain@example.com"), await login(app, "admin@example.com")
        assert (await plain.get("/api/admin/users")).status_code == 403
        assert (await plain.get("/api/admin/overview")).status_code == 403
        users = (await admin.get("/api/admin/users")).json()
        assert users["total"] == 3
        assert {"jobs", "applications", "resumes"} <= set(users["items"][0])  # counts only, no content
        assert (await admin.post(f"/api/admin/users/{plain_id}/status", json={"status": "disabled"})).status_code == 200
        assert (await plain.get("/api/dashboard")).status_code == 401  # disabling ends the session
        assert (await admin.post(f"/api/admin/users/{plain_id}/role", json={"role": "admin"})).status_code == 403
        assert (await admin.get("/api/admin/settings")).status_code == 403  # platform settings: superadmin only
        superadmin = (await client.get("/api/auth/me")).json()["user"]["id"]
        assert (await admin.post(f"/api/admin/users/{superadmin}/status", json={"status": "disabled"})).status_code == 403
        assert (await client.post(f"/api/admin/users/{admin_id}/role", json={"role": "user"})).status_code == 200
        assert (await client.post(f"/api/admin/users/{superadmin}/role", json={"role": "user"})).status_code == 403


async def test_every_private_route_requires_sign_in(app):
    public = {"/api/auth/csrf", "/api/auth/me", "/api/auth/register", "/api/auth/verify-email",
              "/api/auth/resend-verification", "/api/auth/login", "/api/auth/logout", "/api/auth/forgot-password",
              "/api/auth/reset-password", "/api/auth/login/2fa", "/api/auth/google/config", "/api/auth/google/start",
              "/api/auth/google/callback", "/healthz", "/readyz"}
    async with app.router.lifespan_context(app):
        c = await anon(app)
        from hirefinch.api import ROUTERS

        checked = 0
        for route in (r for router in ROUTERS for r in router.routes):
            if not isinstance(route, APIRoute) or route.path in public or not route.path.startswith("/api/"):
                continue
            if route.path.startswith(("/api/docs", "/api/openapi")):
                continue
            method = sorted(route.methods - {"HEAD", "OPTIONS"})[0]
            path = re.sub(r"\{[^}]+\}", "1", route.path)
            response = await c.request(method, path, json={} if method != "GET" else None)
            assert response.status_code in (401, 422), f"{method} {route.path} -> {response.status_code}"
            checked += 1
        assert checked > 50


async def test_delete_account_removes_data_and_files(app, settings, sessionmaker, resume_docx):
    async with app.router.lifespan_context(app):
        c = await register_and_verify(app, "leaving@example.com")
        await c.post("/api/resumes/masters", files={"file": ("cv.docx", resume_docx)})
        job_id = (await c.post("/api/jobs/import", json=JOB)).json()["id"]
        await c.post(f"/api/jobs/{job_id}/tailor")
        me = (await c.get("/api/auth/me")).json()["user"]["id"]
        assert (settings.data_dir / "masters" / str(me)).exists()
        bad = await c.post("/api/auth/delete-account", json={"password": PASSWORD, "confirm": "yes"})
        assert bad.status_code == 422
        ok = await c.post("/api/auth/delete-account", json={"password": PASSWORD, "confirm": "DELETE MY ACCOUNT"})
        assert ok.status_code == 200, ok.text
        async with sessionmaker() as db:
            assert await db.get(AppUser, me) is None
            assert await db.scalar(select(func.count(JobPosting.id)).where(JobPosting.user_id == me)) == 0
            assert await db.scalar(select(func.count(UserSession.id)).where(UserSession.user_id == me)) == 0
        assert not (settings.data_dir / "masters" / str(me)).exists()
        assert not (settings.artifacts_dir / "users" / str(me)).exists()


async def test_user_settings_reject_unsafe_hosts_and_keyless_ai(client):
    private = await client.put("/api/integrations/email", json={"config": {"provider": "smtp", "host": "127.0.0.1", "port": 587,
                                                                          "username": "me", "from_address": "me@example.com"},
                                                               "secrets": {"password": "x" * 16}})
    assert private.status_code == 422 and "private" in private.json()["message"]
    port = await client.put("/api/integrations/email", json={"config": {"provider": "smtp", "host": "smtp.gmail.com", "port": 22,
                                                                       "from_address": "me@example.com"}})
    assert port.status_code == 422 and "port" in port.json()["message"]
    http = await client.put("/api/integrations/llm", json={"config": {"provider": "azure_openai", "endpoint": "http://x.example.com",
                                                                     "deployment": "gpt-5.1"}, "secrets": {"api_key": "k" * 30}})
    assert http.status_code == 422 and "https" in http.json()["message"]
    metadata = await client.put("/api/integrations/llm", json={"config": {"provider": "openai_compatible", "model": "m",
                                                                         "base_url": "https://169.254.169.254/v1"},
                                                              "secrets": {"api_key": "k" * 30}})
    assert metadata.status_code == 422
    keyless = await client.put("/api/integrations/llm", json={"config": {"provider": "gemini", "model": "gemini-2.5-flash"}})
    assert keyless.status_code == 422 and "api_key" in keyless.json()["message"]  # never the server's cloud identity


async def test_each_user_gets_their_own_sender(runtime, sessionmaker, user_id, settings):
    from hirefinch.notifications.email import SmtpSender, UnconfiguredSender
    from hirefinch.services import integrations as integ

    runtime.sender_override = None  # use real per-user construction
    runtime.settings = settings.model_copy(update={"allow_private_hosts": True})  # test host does not resolve
    second = await _account(sessionmaker, "second@example.com", "user")
    async with sessionmaker() as db:
        await integ.save(db, settings.model_copy(update={"allow_private_hosts": True}), runtime.box, user_id, "email",
                         {"provider": "smtp", "host": "smtp.example.com", "port": 587, "username": "riya",
                          "from_address": "riya@example.com"}, {"password": "riya-app-password"})
        await db.commit()
        mine, theirs = await runtime.for_user(db, user_id), await runtime.for_user(db, second)
    assert isinstance(mine.sender, SmtpSender) and mine.sender.username == "riya"
    assert not isinstance(theirs.sender, SmtpSender)  # never someone else's account
    prod = runtime.settings.model_copy(update={"environment": "production"})
    runtime.settings = prod
    async with sessionmaker() as db:
        theirs = await runtime.for_user(db, second)
    assert isinstance(theirs.sender, UnconfiguredSender) and "mock" not in theirs.routes


async def test_platform_settings_and_closed_registration(app, client):
    async with app.router.lifespan_context(app):
        closed = await client.put("/api/admin/settings/registration", json={"config": {"open": False}})
        assert closed.status_code == 200 and closed.json()["registration"]["open"] is False
        c = await anon(app)
        r = await c.post("/api/auth/register", json={"email": "late@example.com", "password": PASSWORD, "consent": True})
        assert r.status_code == 403
        saved = await client.put("/api/admin/settings/system_email", json={
            "config": {"provider": "smtp", "host": "smtp.gmail.com", "port": 587, "username": "platform@example.com",
                       "from_address": "platform@example.com"}, "secrets": {"password": "platform-app-password"}})
        assert saved.status_code == 200, saved.text
        assert "platform-app-password" not in saved.text and saved.json()["system_email"]["secrets_set"] == ["password"]


async def test_registration_without_email_confirmation(app, client):
    async with app.router.lifespan_context(app):
        off = await client.put("/api/admin/settings/registration", json={"config": {"open": True, "verify_email": False}})
        assert off.status_code == 200 and off.json()["registration"]["verify_email"] is False
        c = await anon(app)
        r = await c.post("/api/auth/register", json={"email": "friend@example.com", "password": PASSWORD, "consent": True})
        assert r.status_code == 202 and r.json()["active"] is True and "dev_link" not in r.json()
        assert (await c.post("/api/auth/login", json={"email": "friend@example.com", "password": PASSWORD})).status_code == 200
        # Signing up again with a taken address gives the same answer and changes nothing.
        again = await (await anon(app)).post("/api/auth/register", json={"email": "friend@example.com", "password": "another-long-passphrase",
                                                                          "consent": True})
        assert again.json() == r.json()
        assert (await (await anon(app)).post("/api/auth/login", json={"email": "friend@example.com",
                                                                      "password": "another-long-passphrase"})).status_code == 401
