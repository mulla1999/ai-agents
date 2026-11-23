"""'all' rule groups and the Uttar Pradesh pilot schemes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from saathi.config import Settings
from saathi.profile import FamilyMember, UserProfile
from saathi.schemes import Status, evaluate, evaluate_all, load_schemes
from saathi.schemes.models import Rule

SCHEMES = {s.id: s for s in load_schemes(Settings().schemes_dir)}
UP_SCHEMES = {"up-old-age-pension", "up-widow-pension", "up-divyang-pension", "kanya-sumangala"}


def status(scheme_id: str, **facts) -> Status:
    return evaluate(SCHEMES[scheme_id], UserProfile(**facts)).status


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        ({"residence": "rural", "annual_family_income": 40_000}, Status.ELIGIBLE),
        ({"residence": "urban", "annual_family_income": 50_000}, Status.ELIGIBLE),  # over the village limit only
        ({"residence": "rural", "annual_family_income": 50_000, "is_bpl": False}, Status.NOT_ELIGIBLE),
        ({"residence": "urban", "annual_family_income": 60_000, "is_bpl": False}, Status.NOT_ELIGIBLE),
        ({"residence": "urban", "annual_family_income": 60_000, "is_bpl": True}, Status.ELIGIBLE),  # BPL route
        ({"annual_family_income": 40_000, "is_bpl": False}, Status.NEEDS_INFO),  # which limit applies?
        ({"annual_family_income": 90_000, "is_bpl": False}, Status.NOT_ELIGIBLE),  # over both: no need to ask
        ({"residence": "rural"}, Status.NEEDS_INFO),
    ],
)
def test_old_age_pension_income_limit_depends_on_village_or_town(facts, expected):
    assert status("up-old-age-pension", state="uttar_pradesh", age=65, **facts) is expected


def test_undecided_all_group_asks_for_the_missing_fields():
    match = evaluate(SCHEMES["up-old-age-pension"], UserProfile(state="uttar_pradesh", age=65, annual_family_income=40_000))
    assert match.missing_fields == {"residence", "is_bpl"}


def test_up_schemes_only_match_up_residents():
    for scheme_id in UP_SCHEMES:
        assert SCHEMES[scheme_id].state == "uttar_pradesh"
    assert status("up-widow-pension", state="bihar", gender="female", is_widow=True, age=40,
                  annual_family_income=60_000) is Status.NOT_ELIGIBLE  # fmt: skip
    assert status("up-widow-pension", state="uttar_pradesh", gender="female", is_widow=True, age=40,
                  annual_family_income=60_000) is Status.ELIGIBLE  # fmt: skip


def test_up_family_example():
    profile = UserProfile(
        state="uttar_pradesh", district="barabanki", age=38, gender="male", residence="rural",
        annual_family_income=45_000,
        family_members=[
            FamilyMember(relation="daughter", age=8),
            FamilyMember(relation="mother", age=67, is_widow=True),
            FamilyMember(relation="son", age=20, disability_percent=60),
        ],
    )  # fmt: skip
    eligible = {
        (m.scheme.id, m.member.relation.value if m.member else "self")
        for m in evaluate_all(SCHEMES.values(), profile)
        if m.status is Status.ELIGIBLE
    }
    assert {("kanya-sumangala", "daughter"), ("up-old-age-pension", "mother"), ("up-widow-pension", "mother"),
            ("up-divyang-pension", "son")} <= eligible  # fmt: skip
    assert not any(scheme in UP_SCHEMES for scheme, who in eligible if who == "self")


@pytest.mark.parametrize(
    "rule",
    [
        {"reason": "x", "all": []},
        {"reason": "x", "all": [{"reason": "y", "field": "age", "op": "gte", "value": 1}], "field": "age", "op": "eq"},
        {"reason": "x", "all": [{"reason": "y", "field": "age", "op": "gte", "value": 1}],
         "any": [{"reason": "y", "field": "age", "op": "gte", "value": 1}]},  # fmt: skip
    ],
)
def test_malformed_all_groups_are_rejected(rule):
    with pytest.raises(ValidationError):
        Rule.model_validate(rule)
