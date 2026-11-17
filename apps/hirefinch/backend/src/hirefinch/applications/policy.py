"""Approval policy: may this application be submitted automatically, and if not, why?

Deterministic and conservative. ``manual_reasons`` always require you, whatever the mode;
``auto_blockers`` only stop automatic submission (you can still approve it yourself).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import ApplicationMode, AutomationPolicy

# Routes able to submit without a person. "manual" never is.
AUTOMATABLE_ROUTES = frozenset({"email", "mock"})


@dataclass
class PolicyInput:
    mode: ApplicationMode
    policy: AutomationPolicy
    score: float | None
    band: str | None
    recommended: bool
    role_fit: float | None
    route: str
    route_ready: str | None  # None when the route can be used now, else why not
    expired: bool
    previous_application: bool
    resume_valid: bool
    unanswered: list[str]
    flags: dict
    applied_today: int
    applied_this_week: int
    emergency_stop: bool


@dataclass
class Decision:
    manual_reasons: list[str] = field(default_factory=list)
    auto_blockers: list[str] = field(default_factory=list)

    @property
    def automatic(self) -> bool:
        return not self.manual_reasons and not self.auto_blockers


def decide(p: PolicyInput) -> Decision:
    d = Decision()
    if p.emergency_stop:
        d.manual_reasons.append("emergency stop is engaged")
    if p.previous_application:
        d.manual_reasons.append("you already applied to this job or a duplicate of it")
    if p.expired:
        d.manual_reasons.append("the job has expired")
    if not p.resume_valid:
        d.manual_reasons.append("the tailored resume has not passed validation")
    if p.route_ready:
        d.manual_reasons.append(p.route_ready)
    if p.route == "manual":
        d.manual_reasons.append("this job is applied to on the employer's site; apply there yourself, then confirm here")
    d.manual_reasons += [f"question needs you: {q}" for q in p.unanswered]
    if p.flags.get("prompt_injection"):
        d.manual_reasons.append("the posting contains text that tries to instruct an AI")
    if p.flags.get("suspicious"):
        d.manual_reasons.append("the posting looks suspicious: " + "; ".join(p.flags.get("suspicious_reasons", [])))
    if p.band == "disqualified":
        d.manual_reasons.append("the job is outside your criteria (disqualified)")

    pol = p.policy
    if p.mode is not ApplicationMode.AUTOMATIC:
        d.auto_blockers.append("supervised mode: every application needs your approval")
    if p.score is None or p.score < pol.auto_apply_min_score:
        d.auto_blockers.append(f"score {p.score or 0:g} is below the automatic threshold {pol.auto_apply_min_score}")
    if not p.recommended:
        d.auto_blockers.append("the match is not recommended")
    if p.role_fit is not None and p.role_fit < 0.5:
        d.auto_blockers.append("the role is not close to your target roles")
    if p.route not in AUTOMATABLE_ROUTES or p.route not in pol.auto_apply_routes:
        d.auto_blockers.append(f"route '{p.route}' is not enabled for automatic applications")
    if p.applied_today >= pol.daily_application_limit:
        d.auto_blockers.append(f"daily limit of {pol.daily_application_limit} applications reached")
    if p.applied_this_week >= pol.weekly_application_limit:
        d.auto_blockers.append(f"weekly limit of {pol.weekly_application_limit} applications reached")
    return d
