"""Request and response bodies."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..db import Application, ApplicationStatus, Citizen, Role, SchemeRecord, SchemeStatus, User
from ..schemes import Match
from ..services.applications import TRANSITIONS
from ..services.citizens import CitizenDetails


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth / users ---------------------------------------------------------------------------


class UserOut(_Out):
    id: uuid.UUID
    role: Role
    display_name: str | None
    email: str | None
    phone: str | None
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    sign_in_methods: list[str] | None = None

    @classmethod
    def of(cls, user: User, sign_in_methods: list[str] | None = None) -> UserOut:
        phone = f"+91 ******{user.phone_e164[-4:]}" if user.phone_e164 else None
        return cls(
            sign_in_methods=sign_in_methods,
            id=user.id,
            role=user.role,
            display_name=user.display_name,
            email=user.email,
            phone=phone,
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )


class AuthConfigOut(BaseModel):
    google_enabled: bool
    otp_enabled: bool = True
    whatsapp_login_enabled: bool = False


class WhatsAppLoginStartOut(BaseModel):
    code: str
    link: str
    expires_in_seconds: int


class WhatsAppLoginPollOut(BaseModel):
    status: str  # "pending" | "signed_in"
    user: UserOut | None = None


class OtpRequestIn(BaseModel):
    phone: str = Field(min_length=10, max_length=20)


class OtpVerifyIn(BaseModel):
    phone: str = Field(min_length=10, max_length=20)
    code: str = Field(pattern=r"^\s*\d{6}\s*$")


class RegisterIn(CitizenDetails):
    phone: str = Field(min_length=10, max_length=20)
    code: str = Field(pattern=r"^\s*\d{6}\s*$")
    consent: Literal[True]  # registering collects personal data, so consent is required


class UserUpdateIn(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    display_name: str | None = Field(default=None, max_length=120)


# --- citizens -------------------------------------------------------------------------------


class CitizenOut(_Out):
    id: uuid.UUID
    display_name: str
    profile: dict[str, Any]
    language: str | None
    date_of_birth: date | None
    contact_email: str | None
    pincode: str | None
    locality: str | None
    address_line: str | None
    consent_version: str | None
    consent_at: datetime | None
    is_self: bool
    managed_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, citizen: Citizen, viewer: User) -> CitizenOut:
        return cls(
            id=citizen.id,
            display_name=citizen.display_name,
            profile=citizen.profile or {},
            language=citizen.language,
            date_of_birth=citizen.date_of_birth,
            contact_email=citizen.contact_email,
            pincode=citizen.pincode,
            locality=citizen.locality,
            address_line=citizen.address_line,
            consent_version=citizen.consent_version,
            consent_at=citizen.consent_at,
            is_self=citizen.user_id == viewer.id,
            managed_by_user_id=citizen.managed_by_user_id,
            created_at=citizen.created_at,
            updated_at=citizen.updated_at,
        )


class CitizenCreateIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    language: str | None = Field(default=None, max_length=80)


class ProfileFieldOut(BaseModel):
    name: str
    label: str
    question: str
    type: str  # "enum" | "bool" | "int" | "state"
    options: list[str] = []


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatOut(BaseModel):
    reply: str
    profile: dict[str, Any]


class MessageOut(_Out):
    role: str
    content: str
    created_at: datetime


# --- schemes --------------------------------------------------------------------------------


class SchemeOut(BaseModel):
    id: str
    name: str
    level: str
    state: str | None
    ministry: str
    tags: list[str]
    summary: str
    benefits: str
    eligibility: list[dict[str, Any]]
    documents: list[str]
    notes: list[str]
    how_to_apply: str
    apply_url: str | None
    source_url: str
    status: SchemeStatus
    verified_on: date | None
    version: int
    updated_at: datetime

    @classmethod
    def of(cls, record: SchemeRecord) -> SchemeOut:
        return cls.model_validate(record, from_attributes=True)


class SchemeRevisionOut(_Out):
    version: int
    data: dict[str, Any]
    changed_by_user_id: uuid.UUID | None
    changed_at: datetime


class MatchOut(BaseModel):
    scheme_id: str
    scheme_name: str
    summary: str
    benefits: str
    tags: list[str]
    level: str
    state: str | None
    status: str
    missing_fields: list[str]
    failed_reasons: list[str]

    @classmethod
    def of(cls, match: Match) -> MatchOut:
        return cls(
            scheme_id=match.scheme.id,
            scheme_name=match.scheme.name,
            summary=match.scheme.summary,
            benefits=match.scheme.benefits,
            tags=match.scheme.tags,
            level=match.scheme.level,
            state=match.scheme.state,
            status=match.status.value,
            missing_fields=sorted(match.missing_fields),
            failed_reasons=list(match.failed_reasons),
        )


# --- applications ---------------------------------------------------------------------------


class ApplicationEventOut(_Out):
    from_status: str | None
    to_status: str
    note: str | None
    created_at: datetime


class ApplicationOut(BaseModel):
    id: uuid.UUID
    citizen_id: uuid.UUID
    scheme_id: str
    scheme_name: str
    apply_url: str | None
    status: ApplicationStatus
    next_statuses: list[ApplicationStatus]
    portal_reference: str | None
    checklist: dict[str, bool]
    notes: str | None
    created_at: datetime
    updated_at: datetime
    events: list[ApplicationEventOut]

    @classmethod
    def of(cls, application: Application, scheme: SchemeRecord) -> ApplicationOut:
        return cls(
            id=application.id,
            citizen_id=application.citizen_id,
            scheme_id=scheme.id,
            scheme_name=scheme.name,
            apply_url=scheme.apply_url,
            status=application.status,
            next_statuses=sorted(TRANSITIONS[application.status]),
            portal_reference=application.portal_reference,
            checklist=application.checklist,
            notes=application.notes,
            created_at=application.created_at,
            updated_at=application.updated_at,
            events=[ApplicationEventOut.model_validate(e) for e in application.events],
        )


class ApplicationCreateIn(BaseModel):
    scheme_id: str = Field(min_length=1, max_length=80)


class ApplicationUpdateIn(BaseModel):
    status: ApplicationStatus | None = None
    note: str | None = Field(default=None, max_length=500)
    checklist: dict[str, bool] | None = None
    portal_reference: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


# --- admin ----------------------------------------------------------------------------------


class StatsOut(BaseModel):
    users_by_role: dict[str, int]
    citizens: int
    citizens_with_consent: int
    applications_by_status: dict[str, int]
    schemes_by_status: dict[str, int]
    chat_messages_last_7_days: int
