import pytest
from pydantic import ValidationError
from sqlalchemy import select

from saathi.auth.google import safe_next
from saathi.auth.otp import MAX_ATTEMPTS, normalize_phone
from saathi.auth.users import upsert_google_user
from saathi.config import Settings
from saathi.db import Role, UserSession
from saathi.errors import BadRequest


async def test_state_changing_requests_need_csrf_token(make_client):
    client = make_client()
    assert (await client.post("/api/auth/otp/request", json={"phone": "9876500001"})).status_code == 403
    client.cookies.set("saathi_csrf", "abc")
    client.headers["x-csrf-token"] = "different"
    assert (await client.post("/api/auth/otp/request", json={"phone": "9876500001"})).status_code == 403


async def test_otp_sign_in_session_and_logout(make_client, sms, sessionmaker):
    client = make_client()
    client.headers["x-csrf-token"] = (await client.get("/api/auth/csrf")).json()["csrf_token"]
    assert (await client.get("/api/auth/me")).status_code == 401

    await client.post("/api/auth/otp/request", json={"phone": "+91 98765 00001"})
    assert sms.sent[-1][0] == "+919876500001"

    wrong = await client.post("/api/auth/otp/verify", json={"phone": "9876500001", "code": "000000"})
    assert wrong.status_code == 400 or sms.last_code() == "000000"

    ok = await client.post("/api/auth/otp/verify", json={"phone": "9876500001", "code": sms.last_code()})
    assert ok.status_code == 200
    assert ok.json()["role"] == "citizen"
    assert ok.json()["phone"] == "+91 ******0001"  # never echo the full number
    assert "httponly" in ok.headers["set-cookie"].lower()

    me = await client.get("/api/auth/me")
    assert me.status_code == 200

    async with sessionmaker() as db:
        stored = (await db.scalars(select(UserSession))).all()
    assert len(stored) == 1 and stored[0].token_hash != client.cookies.get("saathi_session")

    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_otp_code_cannot_be_reused(make_client, sms):
    client = make_client()
    client.headers["x-csrf-token"] = (await client.get("/api/auth/csrf")).json()["csrf_token"]
    await client.post("/api/auth/otp/request", json={"phone": "9876500001"})
    body = {"phone": "9876500001", "code": sms.last_code()}
    assert (await client.post("/api/auth/otp/verify", json=body)).status_code == 200
    assert (await client.post("/api/auth/otp/verify", json=body)).status_code == 400


async def test_otp_attempts_are_limited(make_client, sms):
    client = make_client()
    client.headers["x-csrf-token"] = (await client.get("/api/auth/csrf")).json()["csrf_token"]
    await client.post("/api/auth/otp/request", json={"phone": "9876500001"})
    right = sms.last_code()
    wrong = "111111" if right != "111111" else "222222"
    for _ in range(MAX_ATTEMPTS):
        await client.post("/api/auth/otp/verify", json={"phone": "9876500001", "code": wrong})
    late = await client.post("/api/auth/otp/verify", json={"phone": "9876500001", "code": right})
    assert late.status_code == 400


async def test_otp_requests_are_rate_limited(make_client):
    client = make_client()
    client.headers["x-csrf-token"] = (await client.get("/api/auth/csrf")).json()["csrf_token"]
    codes = [(await client.post("/api/auth/otp/request", json={"phone": "9876500001"})).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 429]


@pytest.mark.parametrize("raw", ["12345", "5876500001", "+1 202 555 0100"])
def test_rejects_non_indian_mobile_numbers(raw):
    with pytest.raises(BadRequest):
        normalize_phone(raw)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("/me/chat", "/me/chat"), ("https://evil.example", "/"), ("//evil.example", "/"), ("/\\evil", "/"), (None, "/")],
)
def test_safe_next_blocks_open_redirects(value, expected):
    assert safe_next(value) == expected


async def test_google_user_upsert_and_admin_bootstrap(sessionmaker):
    async with sessionmaker() as db:
        user = await upsert_google_user(
            db, subject="g-1", email="Boss@Example.org", name="Boss", admin_emails=frozenset({"boss@example.org"})
        )
        again = await upsert_google_user(db, subject="g-1", email="boss@example.org", name=None, admin_emails=frozenset())
        await db.commit()
    assert user.id == again.id and user.role is Role.ADMIN and user.email == "boss@example.org"


async def test_disabled_user_is_signed_out(make_client, login):
    admin, citizen = make_client(), make_client()
    await login(admin, "9876500009", Role.ADMIN)
    me = await login(citizen, "9876500001")
    assert (await admin.patch(f"/api/admin/users/{me['id']}", json={"is_active": False})).status_code == 200
    assert (await citizen.get("/api/auth/me")).status_code == 401


def test_production_refuses_unsafe_settings():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None, environment="production", sms_provider="twilio")
    with pytest.raises(ValidationError, match="console"):
        Settings(_env_file=None, environment="production", secret_key="x" * 40)
