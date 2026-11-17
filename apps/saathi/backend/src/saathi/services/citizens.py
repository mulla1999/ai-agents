"""Personal and address details of a citizen, and the eligibility profile derived from them."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..db import Citizen
from ..profile import Gender, Residence, UserProfile, age_on
from .conversations import profile_from_json, profile_to_json

_EMAIL = r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$"


class CitizenDetails(BaseModel):
    """What a person tells us about themselves when registering or editing their details."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str = Field(min_length=1, max_length=120)
    date_of_birth: date | None = None
    gender: Gender | None = None
    contact_email: str | None = Field(default=None, max_length=320, pattern=_EMAIL)
    state: str | None = None
    district: str | None = Field(default=None, max_length=80)
    pincode: str | None = Field(default=None, pattern=r"^[1-9]\d{5}$")
    locality: str | None = Field(default=None, max_length=120)
    address_line: str | None = Field(default=None, max_length=255)
    residence: Residence | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("date_of_birth")
    @classmethod
    def _plausible_birth_date(cls, value: date | None) -> date | None:
        if value is not None and not 0 <= age_on(value) <= 120:
            raise ValueError("date of birth must be in the past and within 120 years")
        return value

    @field_validator("state", "district")
    @classmethod
    def _valid_place(cls, value: str | None, info: Any) -> str | None:
        # Reuse the profile's normalisation (e.g. "Uttar Pradesh" -> "uttar_pradesh").
        return getattr(UserProfile(**{info.field_name: value}), info.field_name) if value else None


def apply_details(citizen: Citizen, details: CitizenDetails) -> None:
    citizen.display_name = details.display_name
    citizen.date_of_birth = details.date_of_birth
    citizen.contact_email = details.contact_email.lower() if details.contact_email else None
    citizen.pincode = details.pincode
    citizen.locality = details.locality
    citizen.address_line = details.address_line

    profile = profile_from_json(citizen.profile)
    profile.state = details.state
    profile.district = details.district
    profile.gender = details.gender
    profile.residence = details.residence
    if details.date_of_birth is not None:
        profile.age = age_on(details.date_of_birth)
    citizen.profile = profile_to_json(profile)


def effective_profile(citizen: Citizen) -> UserProfile:
    """The stored profile, with age always computed fresh from the date of birth when we have one."""
    profile = profile_from_json(citizen.profile)
    if citizen.date_of_birth is not None:
        profile.age = age_on(citizen.date_of_birth)
    return profile
