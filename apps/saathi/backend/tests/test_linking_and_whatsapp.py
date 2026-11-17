from agents_core.channels.whatsapp import TEXT_ONLY_REPLY, IncomingMessage
from sqlalchemy import func, select

from saathi.auth.users import upsert_google_user
from saathi.db import AuthIdentity, Citizen, User
from saathi.services.whatsapp import CONSENT_NOTICE, UNSUPPORTED_NUMBER, WELCOME, is_consent_reply


async def _request_code(client, sms, phone: str) -> str:
    assert (await client.post("/api/auth/otp/request", json={"phone": phone})).status_code == 202
    return sms.last_code()


async def test_signed_in_user_can_add_a_phone_number(citizen_client, make_client, login, sms):
    me = (await citizen_client.get("/api/auth/me")).json()
    assert me["sign_in_methods"] == ["phone"]

    # A Google-only user adds a phone number.
    other = make_client()
    await login(other, "9876500002")
    code = await _request_code(other, sms, "9876500003")
    linked = await other.post("/api/auth/link/phone", json={"phone": "9876500003", "code": code})
    assert linked.status_code == 200
    assert linked.json()["phone"] == "+91 ******0003"


async def test_cannot_link_a_number_owned_by_another_account(citizen_client, make_client, login, sms):
    other = make_client()
    await login(other, "9876500002")
    code = await _request_code(other, sms, "9876500001")  # citizen_client's number
    taken = await other.post("/api/auth/link/phone", json={"phone": "9876500001", "code": code})
    assert taken.status_code == 409
    again = await other.post("/api/auth/link/phone", json={"phone": "9876500001", "code": code})
    assert again.status_code == 400  # the code was used up


async def test_linking_requires_sign_in(make_client):
    client = make_client()
    client.headers["x-csrf-token"] = (await client.get("/api/auth/csrf")).json()["csrf_token"]
    assert (await client.post("/api/auth/link/phone", json={"phone": "9876500001", "code": "123456"})).status_code == 401


async def test_google_link_needs_a_signed_in_user(make_client):
    response = await make_client().get("/api/auth/google/login", params={"link": "true"})
    assert response.status_code == 404  # Google is not configured in tests; never links anonymously


async def test_google_identity_cannot_be_stolen_by_linking(sessionmaker):
    from saathi.auth.users import link_identity
    from saathi.db import AuthProvider
    from saathi.errors import Conflict

    async with sessionmaker() as db:
        owner = await upsert_google_user(db, subject="g-9", email="a@example.org", name=None, admin_emails=frozenset())
        intruder = User(phone_e164="+919876500005")
        db.add(intruder)
        await db.flush()
        try:
            await link_identity(db, intruder, AuthProvider.GOOGLE, "g-9")
            raise AssertionError("expected Conflict")
        except Conflict:
            pass
        assert owner.id != intruder.id


def wa(text: str | None, sender: str = "919876500001", kind: str = "text", media: str | None = None) -> IncomingMessage:
    return IncomingMessage("m", sender, kind, text, media)


async def test_whatsapp_asks_consent_then_chats_on_the_shared_record(app, llm, sessionmaker, citizen_client):
    handler = app.state.whatsapp_handler

    assert await handler(wa("hi")) == CONSENT_NOTICE
    assert await handler(wa("what is this?")) == CONSENT_NOTICE
    assert await handler(wa("हाँ")) == WELCOME

    llm.json_replies = [{"language": "Hindi", "updates": {"age": 45, "occupation": "farmer"}}]
    assert await handler(wa("मैं 45 साल का किसान हूँ")) == "REPLY"

    # Same number signed in on the web: same citizen record and profile.
    web = (await citizen_client.get("/api/me/citizen")).json()
    assert web["profile"] == {"age": 45, "occupation": "farmer"}
    assert web["consent_at"] is not None
    # WhatsApp messages stay out of the web chat, but are part of the data export.
    assert (await citizen_client.get(f"/api/citizens/{web['id']}/messages")).json() == []
    export = (await citizen_client.get(f"/api/citizens/{web['id']}/export")).json()
    assert {m["channel"] for m in export["messages"]} == {"whatsapp"}

    async with sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(Citizen)) == 1
        assert await db.scalar(select(func.count()).select_from(AuthIdentity)) == 1


async def test_whatsapp_rejects_non_indian_numbers_and_handles_voice_notes(app):
    handler = app.state.whatsapp_handler
    assert await handler(wa("hi", sender="12025550100")) == UNSUPPORTED_NUMBER
    await handler(wa("yes", sender="919876500007"))
    assert await handler(wa(None, sender="919876500007", kind="audio", media="media-1")) == TEXT_ONLY_REPLY


async def test_whatsapp_respects_disabled_accounts(app, make_client, login):
    admin, user = make_client(), make_client()
    from saathi.db import Role

    await login(admin, "9876500009", Role.ADMIN)
    me = await login(user, "9876500001")
    await admin.patch(f"/api/admin/users/{me['id']}", json={"is_active": False})
    reply = await app.state.whatsapp_handler(wa("hi"))
    assert "disabled" in reply


def test_consent_reply_detection():
    for yes in ("YES", "haan", "हाँ", "ok!", " ji "):
        assert is_consent_reply(yes)
    for no in ("no", "yes but what?", "", None):
        assert not is_consent_reply(no)
