from datetime import date

from sqlalchemy import select

from saathi.db import User
from saathi.profile import age_on
from saathi.schemes import Scheme
from saathi.services.schemes import create_scheme

DETAILS = {
    "display_name": "Sunita Devi",
    "date_of_birth": "1961-03-15",
    "gender": "female",
    "contact_email": "sunita@example.org",
    "state": "Uttar Pradesh",
    "district": "  Lucknow ",
    "pincode": "226001",
    "locality": "Chinhat",
    "address_line": "House 12, Ward 4",
    "residence": "rural",
}


async def _code(client, sms, phone="9876500200"):
    client.headers["x-csrf-token"] = (await client.get("/api/auth/csrf")).json()["csrf_token"]
    await client.post("/api/auth/otp/request", json={"phone": phone})
    return sms.last_code()


async def test_register_creates_account_with_details_and_consent(make_client, sms, sessionmaker):
    client = make_client()
    code = await _code(client, sms)
    response = await client.post("/api/auth/register", json={**DETAILS, "phone": "9876500200", "code": code, "consent": True})
    assert response.status_code == 201, response.text
    assert response.json()["display_name"] == "Sunita Devi"

    me = (await client.get("/api/me/citizen")).json()
    assert me["consent_at"] is not None
    assert me["pincode"] == "226001" and me["locality"] == "Chinhat" and me["contact_email"] == "sunita@example.org"
    assert me["profile"]["state"] == "uttar_pradesh" and me["profile"]["district"] == "lucknow"
    assert me["profile"]["age"] == age_on(date(1961, 3, 15))

    # The typed email is a contact detail only; it must never become a sign-in email.
    async with sessionmaker() as db:
        user = await db.scalar(select(User).where(User.phone_e164 == "+919876500200"))
    assert user.email is None


async def test_register_requires_consent_and_valid_details(make_client, sms):
    client = make_client()
    code = await _code(client, sms)
    base = {**DETAILS, "phone": "9876500200", "code": code}
    assert (await client.post("/api/auth/register", json={**base, "consent": False})).status_code == 422
    for bad in ({"pincode": "012345"}, {"date_of_birth": "2999-01-01"}, {"state": "Atlantis"}, {"contact_email": "nope"}):
        assert (await client.post("/api/auth/register", json={**base, **bad, "consent": True})).status_code == 422, bad


async def test_register_refuses_an_existing_number(citizen_client, make_client, sms):
    client = make_client()
    code = await _code(client, sms, "9876500001")  # citizen_client's number
    response = await client.post("/api/auth/register", json={**DETAILS, "phone": "9876500001", "code": code, "consent": True})
    assert response.status_code == 409


async def test_edit_details_updates_profile(citizen_client):
    me = (await citizen_client.get("/api/me/citizen")).json()
    url = f"/api/citizens/{me['id']}/details"
    assert (await citizen_client.put(url, json=DETAILS)).json()["message"] == "consent_required"
    await citizen_client.post(f"/api/citizens/{me['id']}/consent")

    updated = (await citizen_client.put(url, json={**DETAILS, "district": "Barabanki", "pincode": ""})).json()
    assert updated["profile"]["district"] == "barabanki" and updated["pincode"] is None
    assert updated["display_name"] == "Sunita Devi"


async def test_age_follows_date_of_birth_for_eligibility(citizen_client):
    me = (await citizen_client.get("/api/me/citizen")).json()
    await citizen_client.post(f"/api/citizens/{me['id']}/consent")
    await citizen_client.put(f"/api/citizens/{me['id']}/profile", json={"age": 30, "is_bpl": True})
    await citizen_client.put(f"/api/citizens/{me['id']}/details", json={"display_name": "Me", "date_of_birth": "1950-01-01"})
    eligible = {m["scheme_id"] for m in (await citizen_client.get(f"/api/citizens/{me['id']}/eligibility")).json() if m["status"] == "eligible"}
    assert "ignoaps" in eligible  # 76 from the date of birth, not the stale 30


async def test_state_and_district_schemes(citizen_client, sessionmaker, app):
    async with sessionmaker() as db:
        await create_scheme(
            db,
            Scheme.model_validate({
                "id": "up-district-pilot", "name": "District pilot", "level": "state", "state": "uttar_pradesh",
                "ministry": "Test", "summary": "s", "benefits": "b", "documents": ["Aadhaar"], "how_to_apply": "h",
                "source_url": "https://example.org",
                "eligibility": [{"field": "district", "op": "in", "value": ["lucknow", "barabanki"], "reason": "Pilot districts only"}],
            }),
            None,
        )  # fmt: skip
        await db.commit()
    app.state.scheme_source.invalidate()

    me = (await citizen_client.get("/api/me/citizen")).json()
    await citizen_client.post(f"/api/citizens/{me['id']}/consent")
    url = f"/api/citizens/{me['id']}/details"

    def status(results):
        return next(m for m in results if m["scheme_id"] == "up-district-pilot")

    await citizen_client.put(url, json={"display_name": "Me", "state": "uttar_pradesh", "district": "Lucknow"})
    match = status((await citizen_client.get(f"/api/citizens/{me['id']}/eligibility")).json())
    assert match["status"] == "eligible" and match["level"] == "state" and match["state"] == "uttar_pradesh"

    await citizen_client.put(url, json={"display_name": "Me", "state": "uttar_pradesh", "district": "Agra"})
    assert status((await citizen_client.get(f"/api/citizens/{me['id']}/eligibility")).json())["status"] == "not_eligible"

    await citizen_client.put(url, json={"display_name": "Me", "state": "kerala", "district": "Lucknow"})
    assert status((await citizen_client.get(f"/api/citizens/{me['id']}/eligibility")).json())["status"] == "not_eligible"
