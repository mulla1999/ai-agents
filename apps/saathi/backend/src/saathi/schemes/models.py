"""Scheme records and their machine-checkable eligibility rules (one YAML file per scheme)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from ..profile import INDIAN_STATES, PROFILE_FIELDS

Op = Literal["eq", "ne", "in", "not_in", "gte", "gt", "lte", "lt"]


class Rule(BaseModel):
    """Either a comparison on one profile field, or an ``any`` group where one sub-rule must hold."""

    model_config = ConfigDict(extra="forbid")

    reason: str
    field: str | None = None
    op: Op | None = None
    value: Any = None
    any: list[Rule] | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Rule:
        if self.any is not None:
            if self.field or self.op:
                raise ValueError("a rule has either 'any' or 'field'/'op', not both")
            if not self.any:
                raise ValueError("'any' needs at least one rule")
            return self
        if not self.field or not self.op:
            raise ValueError("a rule needs 'field' and 'op'")
        if self.field not in PROFILE_FIELDS:
            raise ValueError(f"unknown profile field {self.field!r}")
        if self.op in ("in", "not_in") and not isinstance(self.value, list):
            raise ValueError(f"'{self.op}' needs a list value")
        return self


class Scheme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    level: Literal["central", "state"]
    state: str | None = None
    # "person": checked for the person and for each family member (pensions, scholarships, ...).
    # "household": one benefit per family, checked only for the person (PM-KISAN, housing, ...).
    applies_to: Literal["person", "household"] = "person"
    ministry: str
    tags: list[str] = []
    summary: str
    benefits: str
    eligibility: list[Rule]
    documents: list[str]
    # Conditions and caveats the rules cannot express (cut-off dates, one-per-family, ...).
    # Shown to users and given to the agent, so they are told before applying.
    notes: list[str] = []
    how_to_apply: str
    apply_url: str | None = None
    source_url: str
    # None means the record is a draft that nobody has yet checked against the official source.
    verified_on: date | None = None

    @model_validator(mode="after")
    def _check_state(self) -> Scheme:
        if self.level == "state" and self.state not in INDIAN_STATES:
            raise ValueError("state schemes need a valid 'state'")
        if self.level == "central" and self.state is not None:
            raise ValueError("central schemes must not set 'state'")
        return self


Rule.model_rebuild()
