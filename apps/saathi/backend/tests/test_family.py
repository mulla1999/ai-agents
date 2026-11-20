"""Family members, household-level schemes and the new profile fields."""

from __future__ import annotations

from agents_core.llm.testing import ScriptedLLM

from saathi.agent import Agent, InMemorySessionStore
from saathi.config import Settings
from saathi.profile import FamilyMember, Gender, Relation, UserProfile, field_descriptors, member_profile, merge_family
from saathi.schemes import Status, evaluate_all, load_schemes, next_field_to_ask
from saathi.services.conversations import profile_from_json, profile_to_json

SCHEMES = load_schemes(Settings().schemes_dir)


def eligible_for(matches, scheme_id):
    return [m.member.label() if m.member else "self" for m in matches if m.scheme.id == scheme_id and m.status is Status.ELIGIBLE]


def household(**extra) -> UserProfile:
    return UserProfile(
        state="bihar", age=35, gender="male", occupation="farmer", residence="rural", social_category="sc",
        annual_family_income=90_000, is_bpl=True, has_bank_account=True, is_income_tax_payer=False, has_paid_income_tax=False,
        is_government_employee=False, owns_cultivable_land=True, land_holding_hectares=1.2,
        has_epf_esic_or_nps=False, has_pucca_house=False, has_lpg_connection=False, ration_card="phh", **extra,
    )  # fmt: skip


def test_member_profile_shares_household_facts_only():
    profile = household()
    wife = member_profile(profile, FamilyMember(relation=Relation.SPOUSE, age=28, is_pregnant_or_lactating=True))
    assert (wife.state, wife.is_bpl, wife.social_category, wife.ration_card) == ("bihar", True, "sc", "phh")
    assert wife.gender is Gender.FEMALE  # spouse of a man, unless stated
    assert wife.age == 28 and wife.is_pregnant_or_lactating is True
    assert wife.occupation is None and wife.has_bank_account is None  # personal facts are not copied

    daughter = member_profile(profile, FamilyMember(relation=Relation.DAUGHTER, age=6))
    assert daughter.gender is Gender.FEMALE


def test_schemes_are_found_for_family_members():
    profile = household(
        family_members=[
            FamilyMember(relation="spouse", age=28, is_pregnant_or_lactating=True, is_government_employee=False),
            FamilyMember(relation="daughter", age=6),
            FamilyMember(relation="mother", age=72, is_widow=True),
        ]
    )
    matches = evaluate_all(SCHEMES, profile)

    assert eligible_for(matches, "pmmvy") == ["spouse, age 28"]
    assert eligible_for(matches, "sukanya-samriddhi") == ["daughter, age 6"]
    assert set(eligible_for(matches, "ayushman-vay-vandana")) == {"mother, age 72"}
    assert set(eligible_for(matches, "pm-ujjwala")) == {"spouse, age 28", "mother, age 72"}
    assert "mother, age 72" in eligible_for(matches, "ignoaps")
    # Household schemes are checked once, for the person only.
    assert eligible_for(matches, "pm-kisan") == ["self"]
    assert eligible_for(matches, "pmay-g") == ["self"]
    assert eligible_for(matches, "pm-kmy") == ["self"]  # 1.2 ha, age 35


def test_family_members_may_qualify_but_never_create_questions():
    alone = UserProfile(age=30, gender="male")
    profile = alone.model_copy(update={"family_members": [FamilyMember(relation="spouse", is_pregnant_or_lactating=True)]})
    matches = evaluate_all(SCHEMES, profile)

    [pmmvy] = [m for m in matches if m.scheme.id == "pmmvy" and m.member is not None]
    assert pmmvy.status is Status.NEEDS_INFO and "is_government_employee" in pmmvy.missing_fields
    assert not any(m.member is not None and m.status is Status.NOT_ELIGIBLE for m in matches)
    assert next_field_to_ask(matches) == next_field_to_ask(evaluate_all(SCHEMES, alone))


def test_merge_family_adds_and_fills_in():
    known = [FamilyMember(relation="daughter", age=6)]
    merged = merge_family(known, [FamilyMember(relation="daughter", age=6, is_studying_post_matric=False),
                                  FamilyMember(relation="daughter", age=15), FamilyMember(relation="father")])  # fmt: skip
    assert [m.label() for m in merged] == ["daughter, age 6", "daughter, age 15", "father"]
    assert merged[0].is_studying_post_matric is False
    assert known[0].is_studying_post_matric is None  # the input list is not changed


def test_profile_json_round_trip_and_bad_members_dropped():
    profile = household(family_members=[FamilyMember(relation="son", age=4)])
    data = profile_to_json(profile)
    assert data["family_members"] == [{"relation": "son", "age": 4}]
    assert profile_from_json(data) == profile
    assert "family_members" not in profile_to_json(UserProfile(age=3))

    damaged = {**data, "age": -5, "family_members": [{"relation": "son", "age": 4}, {"relation": "cousin"}]}
    restored = profile_from_json(damaged)
    assert restored.age is None and [m.label() for m in restored.family_members] == ["son, age 4"]


def test_new_fields_reach_the_web_form():
    kinds = {f["name"]: f["type"] for f in field_descriptors()}
    assert kinds["land_holding_hectares"] == "number"
    assert kinds["ration_card"] == "enum" and kinds["disability_percent"] == "int"
    assert "family_members" not in kinds


async def test_chat_adds_family_members_and_names_who_qualifies():
    llm = ScriptedLLM(
        [
            {"language": "Hindi", "updates": {"family_members": [{"relation": "daughter", "age": 6}, {"relation": "x"}]}},
            {"language": "Hindi", "updates": {"family_members": [{"relation": "mother", "age": 75}]}, "intent": "show_results"},
        ]
    )
    agent = Agent(llm, SCHEMES, InMemorySessionStore())

    await agent.handle("u1", "मेरी 6 साल की बेटी है")
    await agent.handle("u1", "मेरी माँ 75 साल की हैं, योजनाएँ दिखाओ")

    profile = await agent.profile("u1")
    assert [m.label() for m in profile.family_members] == ["daughter, age 6", "mother, age 75"]  # bad entry ignored
    extraction_prompt = llm.calls[2][0][0].content
    assert '"relation": "daughter"' in extraction_prompt  # known members are shown to the extractor
    answer = llm.text_prompts()[-1]
    assert "your daughter, age 6" in answer and "your mother, age 75" in answer


async def test_eligibility_api_labels_family_members(citizen_client):
    me = (await citizen_client.get("/api/me/citizen")).json()
    await citizen_client.post(f"/api/citizens/{me['id']}/consent")
    body = {"age": 35, "gender": "male", "family_members": [{"relation": "daughter", "age": 3}]}
    assert (await citizen_client.put(f"/api/citizens/{me['id']}/profile", json=body)).status_code == 200

    matches = (await citizen_client.get(f"/api/citizens/{me['id']}/eligibility")).json()
    [ssy] = [m for m in matches if m["scheme_id"] == "sukanya-samriddhi" and m["status"] == "eligible"]
    assert ssy["member"] == {"index": 0, "relation": "daughter", "age": 3}

    too_many = {"family_members": [{"relation": "son"}] * 13}
    assert (await citizen_client.put(f"/api/citizens/{me['id']}/profile", json=too_many)).status_code == 422
