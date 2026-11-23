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
    STREET_VENDOR = "street_vendor"
    CONSTRUCTION_WORKER = "construction_worker"
    DOMESTIC_WORKER = "domestic_worker"
    FISHER = "fisher"
    OTHER = "other"


class Residence(StrEnum):
    RURAL = "rural"
    URBAN = "urban"


class RationCard(StrEnum):
    """Ration card under the National Food Security Act."""

    AAY = "aay"  # Antyodaya Anna Yojana (poorest households)
    PHH = "phh"  # Priority Household
    NON_PRIORITY = "non_priority"  # other state cards (APL / NPHH)
    NONE = "none"


class Relation(StrEnum):
    SPOUSE = "spouse"
    SON = "son"
    DAUGHTER = "daughter"
    FATHER = "father"
    MOTHER = "mother"
    OTHER = "other"


_RELATION_GENDER = {
    Relation.SON: Gender.MALE, Relation.FATHER: Gender.MALE,
    Relation.DAUGHTER: Gender.FEMALE, Relation.MOTHER: Gender.FEMALE,
}  # fmt: skip
MAX_FAMILY_MEMBERS = 12


class FamilyMember(BaseModel):
    """Someone in the household that schemes can be checked for. No names or ID numbers: only the
    facts that eligibility rules use. Household facts (state, income, category, ...) come from the
    person's own profile."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    relation: Relation
    age: int | None = Field(None, ge=0, le=120)
    gender: Gender | None = None
    is_studying_post_matric: bool | None = None
    is_widow: bool | None = None
    is_pregnant_or_lactating: bool | None = None
    disability_percent: int | None = Field(None, ge=0, le=100)
    is_government_employee: bool | None = None
    has_paid_income_tax: bool | None = None
    current_class: int | None = Field(None, ge=0, le=12)  # 0 = not in school
    is_pregnant: bool | None = None

    def label(self) -> str:
        return f"{self.relation.value}, age {self.age}" if self.age is not None else self.relation.value


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
    # Personal, unlike is_income_tax_payer (anyone in the family): APY, PM-SYM and PM-KMY exclude
    # only the applicant, so a taxpayer's husband or wife can still join.
    has_paid_income_tax: bool | None = _field(
        "Has personally ever paid income tax", "Have you yourself ever paid income tax?"
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
    disability_percent: int | None = Field(
        None,
        ge=0,
        le=100,
        description="Disability percentage on the disability certificate",
        json_schema_extra={"question": "What disability percentage is written on the disability certificate?"},
    )
    is_pregnant_or_lactating: bool | None = _field(
        "Is pregnant or breastfeeding a baby", "Are you pregnant, or breastfeeding a baby?"
    )
    ration_card: RationCard | None = _field(
        "Type of ration card the household has (AAY, Priority Household, other, or none)",
        "What kind of ration card does your family have: Antyodaya (AAY), Priority Household (PHH), another card, or none?",
    )
    has_pucca_house: bool | None = _field(
        "Household lives in its own pucca (brick/concrete) house",
        "Does your family live in its own pucca house (brick or concrete walls and roof)?",
    )
    has_lpg_connection: bool | None = _field(
        "Household has an LPG gas connection", "Does your household have an LPG gas connection?"
    )
    land_holding_hectares: float | None = Field(
        None,
        ge=0,
        le=10_000,
        description="Farm land owned by the family, in hectares (1 hectare = about 2.5 acres)",
        json_schema_extra={"question": "How much farm land does your family own (in acres or hectares)?"},
    )
    has_epf_esic_or_nps: bool | None = _field(
        "Is a member of EPF, ESIC or NPS (a formal pension or insurance scheme through work)",
        "Do you have EPF/PF, ESIC or NPS through your work?",
    )
    current_class: int | None = Field(
        None,
        ge=0,
        le=12,
        description="School class the person is studying in now (1 to 12), or 0 if not in school",
        json_schema_extra={"question": "Are you in school now? If yes, which class?"},
    )
    is_pregnant: bool | None = _field("Is pregnant now", "Are you pregnant now?")
    owns_house: bool | None = _field("Family owns the house it lives in", "Does your family own the house you live in?")
    has_electricity_connection: bool | None = _field(
        "Home has its own electricity connection from the power company",
        "Does your home have its own electricity connection (meter) from the power company?",
    )
    main_earner_died: bool | None = _field(
        "The family's main earner has died (in the last few years)",
        "Has the main earning member of your family died in the last few years?",
    )
    # Not a rule field: each member is checked against the schemes as a person of their own.
    family_members: list[FamilyMember] = Field(default_factory=list, max_length=MAX_FAMILY_MEMBERS)

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


# Facts that belong to the whole household, so family members share them with the person.
HOUSEHOLD_FIELDS: tuple[str, ...] = (
    "state", "district", "annual_family_income", "social_category", "residence", "is_income_tax_payer",
    "owns_cultivable_land", "land_holding_hectares", "is_bpl", "ration_card", "has_pucca_house",
    "has_lpg_connection", "owns_house", "has_electricity_connection", "main_earner_died",
)  # fmt: skip


ADULT_NOT_IN_SCHOOL_AGE = 21


def with_inferred_facts(profile: UserProfile) -> UserProfile:
    """Fill facts that follow from others, so people are not asked irrelevant questions.

    Someone 21 or older who has not said they are in school is taken to be out of school (class 0), so
    a farmer of 32 is not asked which class he is in and school scholarships are ruled out for him.
    """
    if profile.current_class is None and profile.age is not None and profile.age >= ADULT_NOT_IN_SCHOOL_AGE:
        return profile.model_copy(update={"current_class": 0})
    return profile


def member_profile(profile: UserProfile, member: FamilyMember) -> UserProfile:
    """The profile a family member is checked with: shared household facts plus their own."""
    data = {name: getattr(profile, name) for name in HOUSEHOLD_FIELDS}
    data.update(member.model_dump(exclude={"relation"}, exclude_none=True))
    gender = member.gender or _RELATION_GENDER.get(member.relation)
    if gender is None and member.relation is Relation.SPOUSE and profile.gender in (Gender.MALE, Gender.FEMALE):
        gender = Gender.FEMALE if profile.gender is Gender.MALE else Gender.MALE
    data["gender"] = gender
    if member.disability_percent is not None:
        data["has_disability"] = member.disability_percent > 0
    return with_inferred_facts(UserProfile.model_validate(data))


def merge_family(existing: list[FamilyMember], incoming: list[FamilyMember]) -> list[FamilyMember]:
    """Add newly mentioned members, or fill in facts about one already known (same relation, and
    the same age when both ages are known)."""
    merged = [member.model_copy() for member in existing]
    for new in incoming:
        same = next(
            (
                m for m in merged
                if m.relation is new.relation and (m.age is None or new.age is None or m.age == new.age)
            ),
            None,
        )  # fmt: skip
        if same is None:
            if len(merged) < MAX_FAMILY_MEMBERS:
                merged.append(new)
            continue
        for name, value in new.model_dump(exclude={"relation"}, exclude_none=True).items():
            setattr(same, name, value)
    return merged


def age_on(date_of_birth: date, today: date | None = None) -> int:
    today = today or date.today()
    return today.year - date_of_birth.year - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))


# Fields a rule can test and a question can ask about (everything except the family list).
PROFILE_FIELDS: tuple[str, ...] = tuple(name for name in UserProfile.model_fields if name != "family_members")


def question_hint(field_name: str) -> str:
    extra = UserProfile.model_fields[field_name].json_schema_extra or {}
    return str(extra.get("question", field_name))


def field_spec() -> str:
    """Human-readable description of every profile field, for the extraction prompt."""
    lines = []
    for name in PROFILE_FIELDS:
        info = UserProfile.model_fields[name]
        lines.append(f'- "{name}": {info.description}. Value: {_type_hint(name, info.annotation)}.')
    return "\n".join(lines)


def field_descriptors() -> list[dict[str, Any]]:
    """Machine-readable description of every profile field, so forms can be generated from it."""
    descriptors = []
    for name in PROFILE_FIELDS:
        info = UserProfile.model_fields[name]
        base = next(arg for arg in get_args(info.annotation) if arg is not type(None))
        if name == "state":
            kind, options = "state", list(INDIAN_STATES)
        elif isinstance(base, type) and issubclass(base, Enum):
            kind, options = "enum", [member.value for member in base]
        else:
            kind, options = {bool: "bool", int: "int", float: "number"}.get(base, "text"), []
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
    return {bool: "true or false", int: "integer", float: "number"}.get(base, "text")
