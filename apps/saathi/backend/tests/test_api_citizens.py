from sqlalchemy import func, select

from saathi.db import AuditLog, Citizen, Role

FARMER = {
    "age": 32, "gender": "male", "occupation": "farmer", "has_bank_account": True,
    "owns_cultivable_land": True, "is_income_tax_payer": False, "has_paid_income_tax": False, "is_government_employee": False,
    "plans_new_business": False, "is_studying_post_matric": False, "is_bpl": False,
}  # fmt: skip


async def test_self_service_profile_and_eligibility(citizen_client):
    me = (await citizen_client.get("/api/me/citizen")).json()
    assert me["is_self"] and me["profile"] == {}
    blocked = await citizen_client.put(f"/api/citizens/{me['id']}/profile", json=FARMER)
    assert blocked.status_code == 400 and blocked.json()["message"] == "consent_required"
    await citizen_client.post(f"/api/citizens/{me['id']}/consent")

    updated = await citizen_client.put(f"/api/citizens/{me['id']}/profile", json=FARMER)
    assert updated.status_code == 200 and updated.json()["profile"]["age"] == 32

    results = (await citizen_client.get(f"/api/citizens/{me['id']}/eligibility")).json()
    eligible = {r["scheme_id"] for r in results if r["status"] == "eligible"}
    assert eligible == {"pm-kisan", "atal-pension-yojana", "pmjjby", "pmsby"}
    assert results[0]["status"] == "eligible"  # eligible schemes first


async def test_invalid_profile_values_are_rejected(citizen_client):
    me = (await citizen_client.get("/api/me/citizen")).json()
    response = await citizen_client.put(f"/api/citizens/{me['id']}/profile", json={"age": -1})
    assert response.status_code == 422
    response = await citizen_client.put(f"/api/citizens/{me['id']}/profile", json={"aadhaar": "1234"})
    assert response.status_code == 422


async def test_citizens_cannot_see_each_other(make_client, login, citizen_client):
    other = make_client()
    await login(other, "9876500002")
    mine = (await citizen_client.get("/api/me/citizen")).json()

    assert (await other.get(f"/api/citizens/{mine['id']}")).status_code == 404
    assert (await other.get(f"/api/citizens/{mine['id']}/eligibility")).status_code == 404
    assert (await other.get("/api/citizens")).status_code == 403


async def test_helper_manages_only_own_citizens_and_access_is_audited(make_client, login, sessionmaker, citizen_client):
    helper_a, helper_b, admin = make_client(), make_client(), make_client()
    await login(helper_a, "9876500003", Role.HELPER)
    await login(helper_b, "9876500004", Role.HELPER)
    await login(admin, "9876500009", Role.ADMIN)

    created = await helper_a.post("/api/citizens", json={"display_name": "Ramesh"})
    assert created.status_code == 201
    cid = created.json()["id"]

    assert [c["id"] for c in (await helper_a.get("/api/citizens")).json()] == [cid]
    assert (await helper_b.get(f"/api/citizens/{cid}")).status_code == 404
    assert (await helper_b.get("/api/citizens")).json() == []
    self_service = (await citizen_client.get("/api/me/citizen")).json()
    assert (await helper_a.get(f"/api/citizens/{self_service['id']}")).status_code == 404

    assert (await admin.get(f"/api/citizens/{cid}")).status_code == 200
    async with sessionmaker() as db:
        actions = (await db.scalars(select(AuditLog.action).where(AuditLog.entity_id == cid))).all()
    assert "citizen.create" in actions and actions.count("citizen.view") == 1


async def test_list_search_treats_wildcards_literally(make_client, login):
    helper = make_client()
    await login(helper, "9876500003", Role.HELPER)
    await helper.post("/api/citizens", json={"display_name": "Sita"})
    assert (await helper.get("/api/citizens", params={"q": "%"})).json() == []
    assert len((await helper.get("/api/citizens", params={"q": "sit"})).json()) == 1


async def test_delete_my_account_erases_everything(citizen_client, sessionmaker, llm):
    me = (await citizen_client.get("/api/me/citizen")).json()
    await citizen_client.post(f"/api/citizens/{me['id']}/consent")
    await citizen_client.post(f"/api/citizens/{me['id']}/chat", json={"message": "hi"})
    await citizen_client.post(f"/api/citizens/{me['id']}/applications", json={"scheme_id": "pmsby"})

    assert (await citizen_client.delete("/api/me")).status_code == 204
    assert (await citizen_client.get("/api/auth/me")).status_code == 401
    async with sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(Citizen)) == 0


async def test_export_contains_profile_applications_and_messages(citizen_client):
    me = (await citizen_client.get("/api/me/citizen")).json()
    await citizen_client.post(f"/api/citizens/{me['id']}/consent")
    await citizen_client.put(f"/api/citizens/{me['id']}/profile", json={"age": 40})
    await citizen_client.post(f"/api/citizens/{me['id']}/chat", json={"message": "hello"})
    await citizen_client.post(f"/api/citizens/{me['id']}/applications", json={"scheme_id": "pmsby"})

    export = (await citizen_client.get(f"/api/citizens/{me['id']}/export")).json()
    assert export["citizen"]["profile"]["age"] == 40
    assert export["applications"][0]["scheme_id"] == "pmsby"
    assert [m["role"] for m in export["messages"]] == ["user", "assistant"]


async def test_profile_fields_describe_the_form(make_client):
    fields = {f["name"]: f for f in (await make_client().get("/api/profile-fields")).json()}
    assert fields["age"]["type"] == "int"
    assert fields["occupation"]["type"] == "enum" and "farmer" in fields["occupation"]["options"]
    assert fields["state"]["type"] == "state" and "bihar" in fields["state"]["options"]
