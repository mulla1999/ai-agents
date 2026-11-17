"""The citizen profile that scheme eligibility rules are evaluated against.

Every field is optional: ``None`` means "not known yet". Identity numbers (Aadhaar, PAN, bank
account) are deliberately absent — eligibility never needs them and we do not want to hold them.
"""

from __future__ import annotations

from datetime import date
from enum import Enum, StrEnum
from typing import Any, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

INDIAN_STATES: tuple[str, ...] = (
    "andhra_pradesh", "arunachal_pradesh", "assam", "bihar", "chhattisgarh", "goa", "gujarat",
    "haryana", "himachal_pradesh", "jharkhand", "karnataka", "kerala", "madhya_pradesh",
    "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland", "odisha", "punjab", "rajasthan",
    "sikkim", "tamil_nadu", "telangana", "tripura", "uttar_pradesh", "uttarakhand", "west_bengal",
    "andaman_and_nicobar_islands", "chandigarh", "dadra_and_nagar_haveli_and_daman_and_diu",
    "delhi", "jammu_and_kashmir", "ladakh", "lakshadweep", "puducherry",
)  # fmt: skip


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    TRANSGENDER = "transgender"


class SocialCategory(StrEnum):
    GENERAL = "general"
    OBC = "obc"
    SC = "sc"
    ST = "st"


class Occupation(StrEnum):
    FARMER = "farmer"
    AGRICULTURAL_LABOURER = "agricultural_labourer"
    ARTISAN = "artisan"
    UNORGANISED_WORKER = "unorganised_worker"
    SALARIED = "salaried"
    SELF_EMPLOYED = "self_employed"
    STUDENT = "student"
    HOMEMAKER = "homemaker"
    UNEMPLOYED = "unemployed"
    RETIRED = "retired"
    OTHER = "other"


class Residence(StrEnum):
    RURAL = "rural"
    URBAN = "urban"


def _field(description: str, question: str) -> Any:
    return Field(None, description=description, json_schema_extra={"question": question})


class UserProfile(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    # Field order is also the tie-break order when choosing the next question.
    state: str | None = _field("State or union territory of residence", "Which state do you live in?")
    # Lets admins write district-level ("zone-wise") rules, e.g. {field: district, op: in, value: [...]}.
    district: str | None = _field("District of residence", "Which district do you live in?")
    age: int | None = Field(
        None, ge=0, le=120, description="Age in years", json_schema_extra={"question": "How old are you?"}
    )
    occupation: Occupation | None = _field("Main occupation", "What work do you mainly do?")
    gender: Gender | None = _field("Gender", "Are you a man, a woman or transgender?")
    annual_family_income: int | None = Field(
        None,
        ge=0,
        description="Total yearly income of the whole family in rupees",
        json_schema_extra={"question": "Roughly how much does your whole family earn in a year?"},
    )
    social_category: SocialCategory | None = _field(
        "Social category", "Do you belong to the General, OBC, SC or ST category?"
    )
    residence: Residence | None = _field("Lives in a rural or urban area", "Do you live in a village or a town/city?")
    has_bank_account: bool | None = _field(
        "Has a savings bank or post office account", "Do you have a bank or post office savings account?"
    )
    is_income_tax_payer: bool | None = _field(
        "Anyone in the family paid income tax last year", "Did you or anyone in your family pay income tax last year?"
    )
    is_government_employee: bool | None = _field(
        "Is a serving or retired government employee or pensioner",
        "Are you, or were you, a government employee or pensioner?",
    )
    owns_cultivable_land: bool | None = _field(
        "Family owns farm land in its own name", "Does your family own farm land in its own name?"
    )
    is_bpl: bool | None = _field(
        "Household is listed as Below Poverty Line (BPL)", "Is your household on the BPL (Below Poverty Line) list?"
    )
    is_studying_post_matric: bool | None = _field(
        "Currently studying in class 11 or above (including college)",
        "Are you currently studying in class 11 or higher, or in college?",
    )
    plans_new_business: bool | None = _field(
        "Wants to start a new business", "Are you planning to start a new business?"
    )
    is_widow: bool | None = _field("Is a widow", "Are you a widow?")
    has_disability: bool | None = _field("Has a disability", "Do you have any disability?")

    @field_validator("state", mode="before")
    @classmethod
    def _normalise_state(cls, value: Any) -> Any:
        if value is None:
            return None
        key = str(value).strip().lower().replace("&", "and").replace("-", " ").replace(" ", "_")
        if key not in INDIAN_STATES:
            raise ValueError(f"unknown state {value!r}")
        return key

    @field_validator("district", mode="before")
    @classmethod
    def _normalise_district(cls, value: Any) -> Any:
        if value is None:
            return None
        name = " ".join(str(value).split()).lower()
        if not name or len(name) > 80:
            raise ValueError("district must be 1-80 characters")
        return name


def age_on(date_of_birth: date, today: date | None = None) -> int:
    today = today or date.today()
    return today.year - date_of_birth.year - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))


PROFILE_FIELDS: tuple[str, ...] = tuple(UserProfile.model_fields)


def question_hint(field_name: str) -> str:
    extra = UserProfile.model_fields[field_name].json_schema_extra or {}
    return str(extra.get("question", field_name))


def field_spec() -> str:
    """Human-readable description of every profile field, for the extraction prompt."""
    lines = []
    for name, info in UserProfile.model_fields.items():
        lines.append(f'- "{name}": {info.description}. Value: {_type_hint(name, info.annotation)}.')
    return "\n".join(lines)


def field_descriptors() -> list[dict[str, Any]]:
    """Machine-readable description of every profile field, so forms can be generated from it."""
    descriptors = []
    for name, info in UserProfile.model_fields.items():
        base = next(arg for arg in get_args(info.annotation) if arg is not type(None))
        if name == "state":
            kind, options = "state", list(INDIAN_STATES)
        elif isinstance(base, type) and issubclass(base, Enum):
            kind, options = "enum", [member.value for member in base]
        else:
            kind, options = {bool: "bool", int: "int"}.get(base, "text"), []
        descriptors.append(
            {"name": name, "label": info.description, "question": question_hint(name), "type": kind, "options": options}
        )
    return descriptors


def _type_hint(name: str, annotation: Any) -> str:
    if name == "state":
        return "one of " + ", ".join(INDIAN_STATES)
    base = next(arg for arg in get_args(annotation) if arg is not type(None))
    if isinstance(base, type) and issubclass(base, Enum):
        return "one of " + ", ".join(member.value for member in base)
    return {bool: "true or false", int: "integer"}.get(base, "text")
