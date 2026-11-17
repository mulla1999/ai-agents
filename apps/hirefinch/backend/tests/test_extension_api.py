"""Browser-extension keys and the extension API."""

from __future__ import annotations

from datetime import date

import httpx
from sqlalchemy import select

from hirefinch.db import Application, JobPosting, JobSource, JobStatus
from hirefinch.domain import Profile, RawJob
from hirefinch.services import settings_store as store
from hirefinch.services.jobs import ensure_sources, ingest
from hirefinch.services.resumes import store_master
from hirefinch.workflow.pipeline import advance

from .conftest import make_user, signed_in

JD = ("Requirements\n- 3+ years of experience\n- Java, Spring Boot, Kafka, Microservices, Kubernetes, AWS, MySQL\n"
      "Salary: 30-40 LPA. Hybrid, Pune.")
URL = "https://jobs.lever.co/acme/1111-2222"


async def _manual_app(rt, resume_docx) -> int:
    """A job applied to on the employer's site, prepared and waiting (no email route)."""
    async with rt.sessionmaker() as db:
        await ensure_sources(db, rt.user_id)
        await store_master(db, rt.settings, rt.user_id, resume_docx, "cv.docx")
        await store.save_profile(db, rt.user_id, Profile(notification_email="me@example.com", notice_period_days=30,
                                                         expected_ctc_lpa=25))
        source = await db.scalar(select(JobSource).where(JobSource.key == "mock", JobSource.user_id == rt.user_id))
        raw = RawJob(posted_at=date.today(), external_id="m1", url=URL, apply_url=URL, title="Backend Engineer",
                     company="Acme", description=JD, location="Pune",
                     questions=["What is your notice period?", "What is your gender?"])
        job_id = (await ingest(db, rt.settings, source, [raw], await store.get_preferences(db, rt.user_id))).new_ids[0]
        await db.commit()
        job = await db.get(JobPosting, job_id)
        await advance(db, rt, job)
        assert job.status == JobStatus.AWAITING_APPROVAL, job.status_reason
        app = await db.scalar(select(Application).where(Application.job_id == job_id))
        assert app.route == "manual"
        return app.id


def _bearer(app, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                             headers={"Authorization": f"Bearer {token}"})


async def test_key_lifecycle_and_scope(app, client, urt, resume_docx):
    app_id = await _manual_app(urt, resume_docx)
    created = (await client.post("/api/account/extension-tokens", json={"name": "Chrome"})).json()
    token = created["token"]
    assert token.startswith("jae_") and created["prefix"] == token[:10]
    listed = (await client.get("/api/account/extension-tokens")).json()
    assert len(listed) == 1 and "token" not in listed[0]  # shown once only

    ext = _bearer(app, token)
    try:
        items = (await ext.get("/api/extension/applications", params={"url": URL + "/apply"})).json()["items"]
        assert items[0]["id"] == app_id and items[0]["matches_page"] is True

        data = (await ext.get(f"/api/extension/applications/{app_id}/autofill")).json()
        assert data["fields"]["first_name"] and data["fields"]["notice_period_days"] == 30
        assert data["fields"]["expected_ctc_lpa"] == 25
        assert data["resume"]["content_type"] == "application/pdf" and len(data["resume"]["base64"]) > 1000
        questions = [a["question"] for a in data["answers"]]
        assert "What is your notice period?" in questions and not any("gender" in q.lower() for q in questions)

        # No CSRF token needed with a key, and the cookie alone never works here.
        r = await ext.post(f"/api/extension/applications/{app_id}/applied", json={"reference": "LEV-123"})
        assert r.status_code == 200 and r.json()["outcome"] == "confirmed"
        assert (await ext.get(f"/api/extension/applications/{app_id}/autofill")).status_code == 409  # already applied

        await client.delete(f"/api/account/extension-tokens/{created['id']}")
        assert (await ext.get("/api/extension/me")).status_code == 401  # revoked
    finally:
        await ext.aclose()
    assert (await client.get("/api/extension/me")).status_code == 401  # session cookie is not accepted


async def test_blocked_sites_and_other_users(app, client, urt, resume_docx, sessionmaker):
    app_id = await _manual_app(urt, resume_docx)
    await make_user(sessionmaker, "other@example.com")
    other = await signed_in(app, "other@example.com")
    try:
        token = (await other.post("/api/account/extension-tokens", json={})).json()["token"]
    finally:
        await other.aclose()
    ext = _bearer(app, token)
    try:
        assert (await ext.get(f"/api/extension/applications/{app_id}/autofill")).status_code == 404
        r = await ext.get("/api/extension/applications", params={"url": "https://www.linkedin.com/jobs/view/1"})
        assert r.json()["blocked"] is True and r.json()["items"] == []
        assert (await ext.get("/api/extension/me", headers={"Authorization": "Bearer jae_wrong"})).status_code == 401
    finally:
        await ext.aclose()


async def test_key_management_needs_csrf(app, client):
    client.headers.pop("x-csrf-token")
    assert (await client.post("/api/account/extension-tokens", json={})).status_code == 403


async def test_auto_apply_ticket_and_confirmation_email(app, client, urt, resume_docx, sessionmaker):
    from hirefinch.db import NotificationOutbox

    app_id = await _manual_app(urt, resume_docx)
    start = await client.post(f"/api/applications/{app_id}/auto-apply")
    assert start.status_code == 200, start.text
    url = start.json()["url"]
    page, ticket = url.split("#hirefinch-apply=")
    assert page == URL
    token = (await client.post("/api/account/extension-tokens", json={})).json()["token"]
    ext = _bearer(app, token)
    try:
        assert (await ext.get("/api/extension/ticket", params={"t": ticket, "url": "https://evil.example/apply"})).status_code == 422
        forged = ticket.rsplit(".", 1)[0] + ".0123456789abcdef0123456789abcdef"
        assert (await ext.get("/api/extension/ticket", params={"t": forged, "url": page + "/apply"})).status_code == 403
        data = (await ext.get("/api/extension/ticket", params={"t": ticket, "url": page + "/apply"})).json()
        assert data["auto_submit"] is True and data["application_id"] == app_id and data["resume"]

        r = await ext.post(f"/api/extension/applications/{app_id}/applied",
                           json={"automatic": True, "confirmation_page": "Thank you for applying to Acme! We have received your application."})
        assert r.json()["outcome"] == "confirmed"
    finally:
        await ext.aclose()
    async with sessionmaker() as db:
        mails = (await db.scalars(select(NotificationOutbox).where(NotificationOutbox.user_id == urt.user_id))).all()
        assert any(m.kind == "application_submitted" and "Applied: Backend Engineer at Acme" in m.subject for m in mails)
        application = await db.get(Application, app_id)
        assert application.evidence["channel"] == "extension_auto" and "Thank you" in application.evidence["confirmation_page"]


async def test_auto_apply_rules(app, client, urt, resume_docx, sessionmaker):
    app_id = await _manual_app(urt, resume_docx)
    ticket = (await client.post(f"/api/applications/{app_id}/auto-apply")).json()["url"].split("#hirefinch-apply=")[1]
    await make_user(sessionmaker, "other@example.com")
    other = await signed_in(app, "other@example.com")
    try:
        assert (await other.post(f"/api/applications/{app_id}/auto-apply")).status_code == 404  # not theirs
        other_key = (await other.post("/api/account/extension-tokens", json={})).json()["token"]
    finally:
        await other.aclose()
    ext = _bearer(app, other_key)
    try:  # another user's key cannot redeem my ticket
        assert (await ext.get("/api/extension/ticket", params={"t": ticket, "url": URL})).status_code == 403
    finally:
        await ext.aclose()
    # Without the employer's confirmation page it is recorded as uncertain, never confirmed.
    mine = _bearer(app, (await client.post("/api/account/extension-tokens", json={})).json()["token"])
    try:
        r = await mine.post(f"/api/extension/applications/{app_id}/applied", json={"automatic": True})
        assert r.json()["outcome"] == "uncertain"
    finally:
        await mine.aclose()
