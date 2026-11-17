"""Deterministic eligibility matching.

The LLM never decides eligibility. It only fills in the profile and explains results; this module
decides, so the same answers always produce the same verdict and every verdict can be traced to a rule.
"""

from __future__ import annotations

import operator
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from ..profile import PROFILE_FIELDS, UserProfile
from .models import Rule, Scheme

_OPS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "gte": operator.ge,
    "gt": operator.gt,
    "lte": operator.le,
    "lt": operator.lt,
    "in": lambda actual, expected: actual in expected,
    "not_in": lambda actual, expected: actual not in expected,
}


class Status(StrEnum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    NEEDS_INFO = "needs_info"


@dataclass(frozen=True)
class Match:
    scheme: Scheme
    status: Status
    missing_fields: frozenset[str] = frozenset()
    failed_reasons: tuple[str, ...] = ()


def _evaluate_rule(rule: Rule, profile: UserProfile) -> tuple[bool | None, frozenset[str]]:
    """Return (True | False | None-if-unknown, fields that would need to be known to decide)."""
    if rule.any is not None:
        results = [_evaluate_rule(sub, profile) for sub in rule.any]
        if any(ok is True for ok, _ in results):
            return True, frozenset()
        if all(ok is False for ok, _ in results):
            return False, frozenset()
        return None, frozenset().union(*(missing for ok, missing in results if ok is None))

    actual = getattr(profile, rule.field)
    if actual is None:
        return None, frozenset({rule.field})
    return bool(_OPS[rule.op](actual, rule.value)), frozenset()


def evaluate(scheme: Scheme, profile: UserProfile) -> Match:
    rules = list(scheme.eligibility)
    if scheme.level == "state":
        rules.insert(0, Rule(field="state", op="eq", value=scheme.state, reason=f"Must live in {scheme.state}"))

    missing: set[str] = set()
    failed: list[str] = []
    for rule in rules:
        ok, needed = _evaluate_rule(rule, profile)
        if ok is False:
            failed.append(rule.reason)
        elif ok is None:
            missing |= needed

    if failed:
        return Match(scheme, Status.NOT_ELIGIBLE, failed_reasons=tuple(failed))
    if missing:
        return Match(scheme, Status.NEEDS_INFO, missing_fields=frozenset(missing))
    return Match(scheme, Status.ELIGIBLE)


def evaluate_all(schemes: Iterable[Scheme], profile: UserProfile) -> list[Match]:
    return [evaluate(scheme, profile) for scheme in schemes]


def next_field_to_ask(matches: Sequence[Match], skip: Iterable[str] = ()) -> str | None:
    """The unknown field that would settle the most undecided schemes."""
    skipped = set(skip)
    counts = Counter(
        name
        for match in matches
        if match.status is Status.NEEDS_INFO
        for name in match.missing_fields
        if name not in skipped
    )
    if not counts:
        return None
    return max(counts, key=lambda name: (counts[name], -PROFILE_FIELDS.index(name)))
