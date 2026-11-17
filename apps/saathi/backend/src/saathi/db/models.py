"""Database tables. See docs/architecture.md §4 for the design rationale."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow


class Role(StrEnum):
    CITIZEN = "citizen"
    HELPER = "helper"
    ADMIN = "admin"


class AuthProvider(StrEnum):
    GOOGLE = "google"
    PHONE = "phone"


class Channel(StrEnum):
    WEB = "web"
    WHATSAPP = "whatsapp"


class SchemeStatus(StrEnum):
    DRAFT = "draft"
    VERIFIED = "verified"
    ARCHIVED = "archived"


class ApplicationStatus(StrEnum):
    INTERESTED = "interested"
    DOCUMENTS_READY = "documents_ready"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    BENEFIT_RECEIVED = "benefit_received"
    WITHDRAWN = "withdrawn"


def _enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=24,
        values_callable=lambda members: [m.value for m in members],
    )


def _created() -> Any:
    return mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


def _updated() -> Any:
    return mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), default=Role.CITIZEN)
    display_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    phone_e164: Mapped[str | None] = mapped_column(String(16), unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    identities: Mapped[list[AuthIdentity]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[AuthProvider] = mapped_column(_enum(AuthProvider, "auth_provider"))
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created()

    user: Mapped[User] = relationship(back_populates="identities")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = _created()
    user_agent: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship()


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    __table_args__ = (Index("ix_otp_challenges_phone_created", "phone_e164", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    phone_e164: Mapped[str] = mapped_column(String(16))
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(45), index=True)
    created_at: Mapped[datetime] = _created()


class WhatsAppLogin(Base):
    """'Sign in with WhatsApp': the browser shows a code, the person sends it to the bot from WhatsApp.

    The browser that started the sign-in holds a random token (only its hash is stored), so the
    session can only be collected by that browser.
    """

    __tablename__ = "whatsapp_logins"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(6), index=True)
    browser_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    phone_e164: Mapped[str | None] = mapped_column(String(16))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(45), index=True)
    created_at: Mapped[datetime] = _created()


class Citizen(Base):
    __tablename__ = "citizens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Set when the citizen signs in themselves; NULL for people registered by a helper.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    managed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(120))
    # The eligibility profile (saathi.profile.UserProfile). Never holds identity numbers.
    profile: Mapped[dict[str, Any]] = mapped_column(default=dict)
    language: Mapped[str | None] = mapped_column(String(80))
    # Personal and address details (the eligibility-relevant ones are mirrored into ``profile``:
    # state, district, gender, residence, and age from date_of_birth).
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    # Typed by the person and NOT verified, so it is never used for sign-in or account linking.
    contact_email: Mapped[str | None] = mapped_column(String(320))
    pincode: Mapped[str | None] = mapped_column(String(6), index=True)
    locality: Mapped[str | None] = mapped_column(String(120))  # village / town / city
    address_line: Mapped[str | None] = mapped_column(String(255))
    consent_version: Mapped[str | None] = mapped_column(String(32))
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="citizen", cascade="all, delete-orphan", passive_deletes=True
    )
    applications: Mapped[list[Application]] = relationship(
        back_populates="citizen", cascade="all, delete-orphan", passive_deletes=True
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("citizen_id", "channel"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    citizen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("citizens.id", ondelete="CASCADE"))
    channel: Mapped[Channel] = mapped_column(_enum(Channel, "channel"), default=Channel.WEB)
    state: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    citizen: Mapped[Citizen] = relationship(back_populates="conversations")
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )


class ChatMessage(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)  # PII-redacted
    created_at: Mapped[datetime] = _created()

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class SchemeRecord(Base):
    __tablename__ = "schemes"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    level: Mapped[str] = mapped_column(String(16))
    state: Mapped[str | None] = mapped_column(String(64))
    ministry: Mapped[str] = mapped_column(String(255))
    tags: Mapped[list[Any]] = mapped_column(default=list)
    summary: Mapped[str] = mapped_column(Text)
    benefits: Mapped[str] = mapped_column(Text)
    eligibility: Mapped[list[Any]] = mapped_column(default=list)
    documents: Mapped[list[Any]] = mapped_column(default=list)
    notes: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'"))
    how_to_apply: Mapped[str] = mapped_column(Text)
    apply_url: Mapped[str | None] = mapped_column(String(500))
    source_url: Mapped[str] = mapped_column(String(500))
    status: Mapped[SchemeStatus] = mapped_column(_enum(SchemeStatus, "scheme_status"), default=SchemeStatus.DRAFT)
    verified_on: Mapped[date | None] = mapped_column(Date)
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = _updated()
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class SchemeRevision(Base):
    __tablename__ = "scheme_revisions"
    __table_args__ = (UniqueConstraint("scheme_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scheme_id: Mapped[str] = mapped_column(ForeignKey("schemes.id", ondelete="CASCADE"))
    version: Mapped[int]
    data: Mapped[dict[str, Any]]
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    changed_at: Mapped[datetime] = _created()


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("citizen_id", "scheme_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    citizen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("citizens.id", ondelete="CASCADE"))
    scheme_id: Mapped[str] = mapped_column(ForeignKey("schemes.id", ondelete="RESTRICT"), index=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        _enum(ApplicationStatus, "application_status"), default=ApplicationStatus.INTERESTED
    )
    portal_reference: Mapped[str | None] = mapped_column(String(100))
    checklist: Mapped[dict[str, Any]] = mapped_column(default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    citizen: Mapped[Citizen] = relationship(back_populates="applications")
    events: Mapped[list[ApplicationEvent]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="ApplicationEvent.created_at"
    )


class ApplicationEvent(Base):
    __tablename__ = "application_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_entity", "entity_type", "entity_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = _created()
