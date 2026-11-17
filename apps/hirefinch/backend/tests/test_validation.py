"""Validation on save, tolerance on load, and source settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hirefinch.db import AutomationPolicyRow, UserProfile
from hirefinch.domain import AutomationPolicy, Preferences, Profile
from hirefinch.errors import ServiceError
from hirefinch.services import settings_store as store
from hirefinch.services.source_config import validate_source_config


@pytest.mark.parametrize("fields", [
    {"phone": "call me"}, {"phone": "123"}, {"linkedin_url": "linkedin.com/in/x"},
    {"linkedin_url": "https://evil.example/in/riya"}, {"portfolio_url": "github"}, {"full_name": "x" * 121},
    {"verified_extra_skills": [{"name": "Go", "evidence": "repo"}, {"name": "go", "evidence": "course"}]},
    {"custom_answers": {"": "x"}},
])
def test_profile_rejects(fields):
    with pytest.raises(ValidationError):
        Profile(**fields)


def test_profile_accepts_and_tidies():
    p = Profile(phone=" +91 98765 43210 ", linkedin_url="https://www.linkedin.com/in/priya-sharma/", full_name="  Priya   Sharma ",
                authorized_to_work_in=["India", "india", " "], headline="")
    assert p.phone == "+91 98765 43210" and p.full_name == "Priya Sharma" and p.headline is None
    assert p.authorized_to_work_in == ["India"]


@pytest.mark.parametrize("fields", [
    {"target_roles": []}, {"work_modes": []}, {"min_compensation_lpa": 2000000}, {"target_compensation_lpa": (40, 30)},
    {"min_compensation_lpa": 50, "target_compensation_lpa": (30, 40)}, {"fx_rates_to_inr": {"usd": 84}},
    {"fx_rates_to_inr": {"USD": 0}}, {"max_experience_gap_years": 50}, {"target_roles": ["x" * 101]},
    {"excluded_keywords": [f"k{i}" for i in range(51)]},
])
def test_preferences_reject(fields):
    with pytest.raises(ValidationError):
        Preferences(**fields)


def test_preferences_dedupe():
    assert Preferences(target_roles=["Java Developer", "java developer", " "]).target_roles == ["Java Developer"]


@pytest.mark.parametrize("fields", [
    {"auto_apply_routes": ["manual"]}, {"notify": ["everything"]}, {"daily_application_limit": 10, "weekly_application_limit": 5},
    {"discovery_interval_minutes": 20000},
])
def test_policy_rejects(fields):
    with pytest.raises(ValidationError):
        AutomationPolicy(**fields)


async def test_one_bad_stored_field_keeps_everything_else(sessionmaker, user_id):
    async with sessionmaker() as db:
        db.add(UserProfile(user_id=user_id, profile={"full_name": "Riya", "notice_period_days": 9999, "phone": "abc"},
                           preferences={"target_roles": ["Java Developer"], "weights": {"technical": -5}}))
        db.add(AutomationPolicyRow(user_id=user_id, policy={"daily_application_limit": 7, "mode": "yolo"}))
        await db.commit()
        profile = await store.get_profile(db, user_id)
        prefs = await store.get_preferences(db, user_id)
        policy = (await store.get_policy_state(db, user_id)).policy
    assert profile.full_name == "Riya" and profile.notice_period_days is None  # only the bad field reset
    assert profile.phone == "abc"  # a rule added later applies on save, never blanks stored data
    assert prefs.target_roles == ["Java Developer"] and prefs.weights.technical == 30
    assert policy.daily_application_limit == 7 and policy.mode == "supervised"  # unknown mode falls back to the safe default


@pytest.mark.parametrize(("kind", "config", "match"), [
    ("greenhouse", {"boards": [{"token": "acme/../x"}]}, "not a board id"),
    ("greenhouse", {"boards": ["stripe"]}, "board 1"),
    ("greenhouse", {"boards": [{"token": "a"}, {"token": "A"}]}, "twice"),
    ("greenhouse", {"bords": []}, "unknown setting bords"),
    ("career_page", {"pages": ["http://careers.example.com"]}, "https"),
    ("adzuna", {"country": "india"}, "country"),
    ("themuse", {"pages": 50}, "1 to 10"),
    ("job_alerts", {"sites": ["monster"]}, "sites"),
    ("jooble", {"queries": "java"}, "list of text"),
])
def test_source_config_rejects(kind, config, match):
    with pytest.raises(ServiceError, match=match):
        validate_source_config(kind, config)


def test_source_config_cleans():
    out = validate_source_config("lever", {"boards": [{"token": " meesho ", "company": "  Meesho  "}], "region": "eu",
                                           "locations": [" Pune ", ""]})
    assert out == {"boards": [{"token": "meesho", "company": "Meesho"}], "region": "eu", "locations": ["Pune"]}


async def test_api_reports_problems(client):
    r = await client.put("/api/sources/greenhouse", json={"enabled": True, "config": {"boards": [{"token": "a b"}]}})
    assert r.status_code == 422 and "board id" in r.text
    r = await client.post("/api/jobs/import", json={"title": "Engineer", "company": "Acme", "url": "https://acme.io/j/1",
                                                     "description": "x" * 40, "apply_email": "jobs-at-acme"})
    assert r.status_code == 422 and "apply_email" in r.text
    r = await client.put("/api/profile", json={"linkedin_url": "my linkedin"})
    assert r.status_code == 422 and "LinkedIn" in r.text
    r = await client.put("/api/integrations/jooble", json={"config": {}, "secrets": {"api_key": "k" * 5000}})
    assert r.status_code == 422
