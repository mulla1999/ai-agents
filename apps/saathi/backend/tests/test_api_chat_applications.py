from saathi.db import Role


async def test_chat_needs_consent_then_persists_profile_and_messages(citizen_client, llm):
    me = (await citizen_client.get("/api/me/citizen")).json()
    url = f"/api/citizens/{me['id']}/chat"

    refused = await citizen_client.post(url, json={"message": "hi"})
    assert refused.status_code == 400 and refused.json()["message"] == "consent_required"

    consent = await citizen_client.post(f"/api/citizens/{me['id']}/consent")
    assert consent.json()["consent_at"] is not None

    llm.json_replies = [{"language": "Hindi", "updates": {"age": 61, "is_bpl": True}}]
    reply = await citizen_client.post(url, json={"message": "मेरी उम्र 61 है, आधार 2345 6789 0123"})
    assert reply.status_code == 200
    assert reply.json() == {"reply": "REPLY", "profile": {"age": 61, "is_bpl": True}}

    citizen = (await citizen_client.get(f"/api/citizens/{me['id']}")).json()
    assert citizen["profile"]["age"] == 61 and citizen["language"] == "Hindi"

    history = (await citizen_client.get(f"/api/citizens/{me['id']}/messages")).json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert "2345 6789 0123" not in history[0]["content"]

    # The next turn sees the stored history.
    llm.json_replies = [{}]
    await citizen_client.post(url, json={"message": "ok"})
    last_call_messages = llm.calls[-1][0]
    assert any(m.content == "REPLY" and m.role == "assistant" for m in last_call_messages)


async def test_chat_delete_my_data_clears_profile_and_history(citizen_client, llm):
    me = (await citizen_client.get("/api/me/citizen")).json()
    await citizen_client.post(f"/api/citizens/{me['id']}/consent")
    llm.json_replies = [{"updates": {"age": 30}}, {"intent": "delete_data"}]
    await citizen_client.post(f"/api/citizens/{me['id']}/chat", json={"message": "30"})
    await citizen_client.post(f"/api/citizens/{me['id']}/chat", json={"message": "delete my data"})

    assert (await citizen_client.get(f"/api/citizens/{me['id']}")).json()["profile"] == {}
    assert (await citizen_client.get(f"/api/citizens/{me['id']}/messages")).json() == []


async def test_application_lifecycle(citizen_client):
    me = (await citizen_client.get("/api/me/citizen")).json()
    url = f"/api/citizens/{me['id']}/applications"
    assert (await citizen_client.post(url, json={"scheme_id": "pm-kisan"})).json()["message"] == "consent_required"
    await citizen_client.post(f"/api/citizens/{me['id']}/consent")

    created = await citizen_client.post(url, json={"scheme_id": "pm-kisan"})
    assert created.status_code == 201
    app = created.json()
    assert app["status"] == "interested" and set(app["checklist"].values()) == {False}
    assert (await citizen_client.post(url, json={"scheme_id": "pm-kisan"})).status_code == 409
    assert (await citizen_client.post(url, json={"scheme_id": "no-such"})).status_code == 404

    patch = f"/api/applications/{app['id']}"
    first_doc = next(iter(app["checklist"]))
    assert (await citizen_client.patch(patch, json={"checklist": {first_doc: True}})).json()["checklist"][first_doc]
    assert (await citizen_client.patch(patch, json={"checklist": {"Bribe": True}})).status_code == 400

    assert (await citizen_client.patch(patch, json={"status": "approved"})).status_code == 400
    submitted = await citizen_client.patch(patch, json={"status": "submitted", "portal_reference": "PMK-UP-77"})
    assert submitted.json()["status"] == "submitted"
    assert [e["to_status"] for e in submitted.json()["events"]] == ["interested", "submitted"]

    aadhaar = await citizen_client.patch(patch, json={"portal_reference": "2345 6789 0123"})
    assert aadhaar.status_code == 400

    listed = (await citizen_client.get(url)).json()
    assert listed[0]["scheme_name"].startswith("PM-KISAN")


async def test_other_users_cannot_touch_my_application(citizen_client, make_client, login):
    me = (await citizen_client.get("/api/me/citizen")).json()
    await citizen_client.post(f"/api/citizens/{me['id']}/consent")
    app = (await citizen_client.post(f"/api/citizens/{me['id']}/applications", json={"scheme_id": "pmsby"})).json()
    stranger = make_client()
    await login(stranger, "9876500002")
    assert (await stranger.patch(f"/api/applications/{app['id']}", json={"status": "withdrawn"})).status_code == 404


async def test_helper_registers_citizen_and_tracks_application(make_client, login):
    helper = make_client()
    await login(helper, "9876500003", Role.HELPER)
    cid = (await helper.post("/api/citizens", json={"display_name": "Kamla Devi"})).json()["id"]
    await helper.post(f"/api/citizens/{cid}/consent")  # helper records the person's verbal consent
    await helper.put(f"/api/citizens/{cid}/profile", json={"age": 67, "is_bpl": True})
    eligible = [m["scheme_id"] for m in (await helper.get(f"/api/citizens/{cid}/eligibility")).json() if m["status"] == "eligible"]
    assert "ignoaps" in eligible
    assert (await helper.post(f"/api/citizens/{cid}/applications", json={"scheme_id": "ignoaps"})).status_code == 201
