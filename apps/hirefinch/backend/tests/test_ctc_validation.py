"""CTC is stored in lakhs per annum. Rupee amounts typed into the LPA fields are rejected on save,
tolerated on load (so a profile never goes blank), and never used to answer a form."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hirefinch.db import UserProfile
from hirefinch.domain import Profile, plausible_lpa
from hirefinch.services import settings_store as store


@pytest.mark.parametrize("value", [1249000, 2000000, 501, 0, -3])
def test_save_rejects_values_that_are_not_lpa(value):
    with pytest.raises(ValidationError, match="lakhs per annum|looks like rupees"):
        Profile(expected_ctc_lpa=value)


def test_message_gives_the_conversion():
    with pytest.raises(ValidationError, match=r"₹12,49,000 is 12\.49 LPA"):
        Profile(current_ctc_lpa=1249000)


@pytest.mark.parametrize("value", [12.49, 20, 3.5, 500])
def test_valid_lpa(value):
    assert Profile(expected_ctc_lpa=value).expected_ctc_lpa == value


async def test_stored_bad_value_loads_but_is_not_used(sessionmaker, user_id):
    async with sessionmaker() as db:
        db.add(UserProfile(user_id=user_id, profile={"full_name": "Riya", "current_ctc_lpa": 1249000, "expected_ctc_lpa": 20}))
        await db.commit()
        profile = await store.get_profile(db, user_id)
    assert profile.full_name == "Riya" and profile.current_ctc_lpa == 1249000  # nothing blanked
    assert plausible_lpa(profile.current_ctc_lpa) is None and plausible_lpa(profile.expected_ctc_lpa) == 20


async def test_api_rejects_rupees_with_a_clear_message(client):
    r = await client.put("/api/profile", json={"expected_ctc_lpa": 2000000})
    assert r.status_code == 422 and "looks like rupees" in r.text and "20.00 LPA" in r.text
    assert (await client.put("/api/profile", json={"expected_ctc_lpa": 20})).status_code == 200


async def test_chat_asks_instead_of_saving_rupees(client):
    cid = (await client.post("/api/assistant/conversations")).json()["id"]
    reply = (await client.post(f"/api/assistant/conversations/{cid}/messages",
                               json={"text": "my expected ctc is 2000000"})).json()["messages"][-1]
    assert reply["action"] is None and "looks like rupees" in reply["content"]


def test_form_question_pauses_on_a_rupee_value(resume_doc):
    from datetime import date

    from hirefinch.applications.answers import prepare_answer
    from hirefinch.candidate import build_candidate

    candidate = build_candidate(resume_doc, Profile(), today=date(2026, 9, 1))
    stored = Profile.model_validate({"expected_ctc_lpa": 2000000, "current_ctc_lpa": 12.49}, context={"stored": True})
    expected = prepare_answer("What is your expected CTC?", stored, candidate)
    assert expected.needs_user and expected.answer is None
    assert prepare_answer("Current CTC (LPA)", stored, candidate).answer == "12.49 LPA"


async def test_profile_gaps_flag_rupee_ctc(client, sessionmaker, user_id):
    async with sessionmaker() as db:
        db.add(UserProfile(user_id=user_id, profile={"expected_ctc_lpa": 2000000, "current_ctc_lpa": 1249000}))
        await db.commit()
    cid = (await client.post("/api/assistant/conversations")).json()["id"]
    reply = (await client.post(f"/api/assistant/conversations/{cid}/messages",
                               json={"text": "what's missing in my profile?"})).json()["messages"][-1]
    items = {i["label"]: i for i in reply["cards"][0]["items"]}
    assert not items["Expected CTC (in LPA)"]["done"] and "looks like rupees" in items["Expected CTC (in LPA)"]["how"]
    assert not items["Current CTC (in LPA)"]["done"]
