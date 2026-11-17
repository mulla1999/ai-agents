import pytest
from pydantic import ValidationError

from saathi.profile import UserProfile
from saathi.schemes import Rule, Scheme, Status, evaluate, next_field_to_ask


def make_scheme(rules: list[dict], **overrides) -> Scheme:
    data = {
        "id": "test",
        "name": "Test scheme",
        "level": "central",
        "ministry": "Test",
        "summary": "s",
        "benefits": "b",
        "eligibility": rules,
        "documents": [],
        "how_to_apply": "h",
        "source_url": "https://example.org",
    }
    return Scheme.model_validate({**data, **overrides})


PENSION = make_scheme(
    [
        {"field": "age", "op": "gte", "value": 18, "reason": "adult"},
        {"field": "age", "op": "lte", "value": 40, "reason": "under 41"},
        {"field": "has_bank_account", "op": "eq", "value": True, "reason": "bank"},
    ]
)

WOMEN_OR_SCST = make_scheme(
    [
        {
            "reason": "SC/ST or woman",
            "any": [
                {"field": "social_category", "op": "in", "value": ["sc", "st"], "reason": "sc/st"},
                {"field": "gender", "op": "eq", "value": "female", "reason": "woman"},
            ],
        }
    ]
)


def test_eligible_when_all_rules_hold():
    match = evaluate(PENSION, UserProfile(age=30, has_bank_account=True))
    assert match.status is Status.ELIGIBLE


def test_not_eligible_reports_failed_reason():
    match = evaluate(PENSION, UserProfile(age=55))
    assert match.status is Status.NOT_ELIGIBLE
    assert match.failed_reasons == ("under 41",)


def test_needs_info_lists_missing_fields():
    match = evaluate(PENSION, UserProfile(age=30))
    assert match.status is Status.NEEDS_INFO
    assert match.missing_fields == {"has_bank_account"}


def test_any_group_passes_on_one_true_branch_even_if_other_unknown():
    assert evaluate(WOMEN_OR_SCST, UserProfile(gender="female")).status is Status.ELIGIBLE


def test_any_group_fails_only_when_all_branches_fail():
    assert evaluate(WOMEN_OR_SCST, UserProfile(gender="male")).missing_fields == {"social_category"}
    match = evaluate(WOMEN_OR_SCST, UserProfile(gender="male", social_category="general"))
    assert match.status is Status.NOT_ELIGIBLE


def test_state_scheme_requires_matching_state():
    scheme = make_scheme([], level="state", state="bihar")
    assert evaluate(scheme, UserProfile()).missing_fields == {"state"}
    assert evaluate(scheme, UserProfile(state="Bihar")).status is Status.ELIGIBLE
    assert evaluate(scheme, UserProfile(state="Kerala")).status is Status.NOT_ELIGIBLE


def test_next_field_prefers_field_that_unblocks_most_schemes():
    matches = [evaluate(PENSION, UserProfile()), evaluate(WOMEN_OR_SCST, UserProfile())]
    # age and has_bank_account each block one scheme; gender/social_category block the other.
    # Ties are broken by profile field order, where age comes first.
    assert next_field_to_ask(matches) == "age"
    assert next_field_to_ask(matches, skip={"age", "has_bank_account", "gender", "social_category"}) is None


def test_ruled_out_schemes_do_not_generate_questions():
    matches = [evaluate(PENSION, UserProfile(age=70))]
    assert next_field_to_ask(matches) is None


def test_rule_rejects_unknown_field():
    with pytest.raises(ValidationError):
        Rule(field="caste", op="eq", value="sc", reason="x")


def test_profile_normalises_state_and_rejects_unknown():
    assert UserProfile(state="Uttar Pradesh").state == "uttar_pradesh"
    with pytest.raises(ValidationError):
        UserProfile(state="Atlantis")
