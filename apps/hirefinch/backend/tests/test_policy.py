"""State transitions, application questions and the approval policy."""

from __future__ import annotations

from datetime import date

import pytest

from hirefinch.applications.answers import classify, prepare_answer
from hirefinch.applications.policy import PolicyInput, decide
from hirefinch.candidate import build_candidate
from hirefinch.domain import ApplicationMode, AutomationPolicy, Preferences, Profile
from hirefinch.workflow.states import TRANSITIONS, can_transition


def test_state_machine():
    assert can_transition("discovered", "match_evaluated")
    assert can_transition("application_in_progress", "applied")
    assert not can_transition("discovered", "applied")
    assert not can_transition("applied", "ready_to_apply")  # never back into submission
    assert not can_transition("rejected", "applied")
    assert TRANSITIONS  # every status has an entry
    from hirefinch.db import JobStatus

    assert set(TRANSITIONS) == set(JobStatus)


@pytest.mark.parametrize("question,category", [
    ("What is your gender?", "gender"),
    ("Do you identify as a person with a disability?", "disability"),
    ("What is your religion?", "demographic"),
    ("I hereby certify that the information provided is true", "legal_declaration"),
    ("Expected CTC (LPA)", "expected_salary"),
    ("What is your current CTC?", "current_salary"),
    ("Will you now or in the future require visa sponsorship?", "sponsorship"),
    ("Are you legally authorized to work in India?", "work_authorization"),
    ("What is your notice period?", "notice_period"),
    ("How many years of experience do you have?", "experience_years"),
    ("Why do you want to work here?", "free_text"),
    ("Email address", "email"),
    ("Please complete the CAPTCHA", "captcha"),
])
def test_question_classification(question, category):
    assert classify(question) == category


def test_answers_come_only_from_verified_facts(resume_doc):
    candidate = build_candidate(resume_doc, Profile(), today=date(2026, 9, 1))
    blank = Profile()
    for q in ("Expected CTC", "What is your notice period?", "Do you require sponsorship?", "What is your gender?",
              "I agree to the terms and conditions", "Why us?", "How many years of Java experience do you have?"):
        answer = prepare_answer(q, blank, candidate)
        assert answer.needs_user and answer.answer is None, q
    assert prepare_answer("Email address", blank, candidate).answer == "riya.sharma@example.com"
    assert prepare_answer("Total years of experience", blank, candidate).answer == "4.1"
    filled = Profile(expected_ctc_lpa=36, notice_period_days=30, requires_sponsorship=False, authorized_to_work_in=["India"])
    assert prepare_answer("Expected CTC", filled, candidate).answer == "36 LPA"
    assert prepare_answer("Expected CTC", filled, candidate).sensitive
    assert prepare_answer("Are you authorized to work in India?", filled, candidate).answer == "Yes"
    # Self-identification is never inferred: only what you set in Profile is used, and it stays sensitive.
    me = Profile.model_validate({"self_identification": {"gender": "Prefer not to say"}})
    answer = prepare_answer("What is your gender?", me, candidate)
    assert answer.answer == "Prefer not to say" and answer.sensitive and answer.source == "user"
    assert prepare_answer("What is your religion?", Profile(custom_answers={"religion": "x"}), candidate).needs_user
    # Nationality: only what you wrote yourself, never guessed.
    assert prepare_answer("Nationality", blank, candidate).needs_user
    assert prepare_answer("Nationality", Profile(custom_answers={"nationality": "Indian"}), candidate).answer == "Indian"
    # Declarations only when you allowed them.
    assert prepare_answer("I agree to the terms and conditions", Profile.model_validate(
        {"common_answers": {"accept_declarations": True}}), candidate).answer == "Yes"
    # From your resume: previous employers.
    assert prepare_answer("Have you previously worked at or consulted for Acme?", blank, candidate, company="Acme").answer == "No"


def _input(**overrides) -> PolicyInput:
    base = dict(mode=ApplicationMode.AUTOMATIC, policy=AutomationPolicy(mode=ApplicationMode.AUTOMATIC, auto_apply_routes=["mock", "email"]),
                score=92.0, band="high", recommended=True, role_fit=0.9, route="mock", route_ready=None, expired=False,
                previous_application=False, resume_valid=True, unanswered=[], flags={}, applied_today=0,
                applied_this_week=0, emergency_stop=False)
    base.update(overrides)
    return PolicyInput(**base)


def test_automatic_only_when_every_condition_holds():
    assert decide(_input()).automatic


@pytest.mark.parametrize("override", [
    {"mode": ApplicationMode.SUPERVISED}, {"score": 80.0}, {"recommended": False}, {"route": "manual"},
    {"expired": True}, {"previous_application": True}, {"resume_valid": False}, {"unanswered": ["Expected CTC"]},
    {"flags": {"prompt_injection": True}}, {"flags": {"suspicious": True, "suspicious_reasons": ["fee"]}},
    {"applied_today": 5}, {"applied_this_week": 20}, {"emergency_stop": True}, {"band": "disqualified"},
    {"route_ready": "no real email provider"}, {"role_fit": 0.2},
])
def test_any_failed_condition_requires_approval(override):
    assert not decide(_input(**override)).automatic


def test_policy_defaults_are_safe():
    policy = AutomationPolicy()
    assert policy.mode is ApplicationMode.SUPERVISED and not policy.auto_send_outreach
    with pytest.raises(ValueError):
        AutomationPolicy(auto_apply_min_score=40)
    with pytest.raises(ValueError):
        Preferences(thresholds={"high": 50, "good": 70, "review": 55})
    with pytest.raises(ValueError):
        Preferences(weights={"technical": 0, "experience": 0, "role": 0, "domain": 0, "location": 0, "compensation": 0})
