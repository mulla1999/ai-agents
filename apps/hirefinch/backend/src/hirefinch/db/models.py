"""Database schema. Status columns are plain strings validated in Python (see ``workflow.states``),
which keeps migrations simple when a status is added.

Idempotency lives in the schema: one application per job, unique attempt numbers per application,
unique dedupe keys for outbound email and notifications.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow
from .paths import StoredPath


def _ts(**kwargs: Any) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, **kwargs)


class JobStatus(StrEnum):
    DISCOVERED = "discovered"
    MATCH_EVALUATED = "match_evaluated"
    SHORTLISTED = "shortlisted"
    RESUME_PENDING = "resume_pending"
    RESUME_READY = "resume_ready"
    AWAITING_APPROVAL = "awaiting_approval"
    READY_TO_APPLY = "ready_to_apply"
    APPLICATION_IN_PROGRESS = "application_in_progress"
    APPLIED = "applied"
    RECRUITER_CONTACTED = "recruiter_contacted"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"
    APPLICATION_FAILED = "application_failed"
    NEEDS_MANUAL = "needs_manual"


class Outcome(StrEnum):
    """How sure we are an application or email reached the other side."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"
    FAILED = "failed"


class AttemptStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    UNCERTAIN = "uncertain"
    UNKNOWN = "unknown"  # we lost track (timeout, crash): verify before retrying
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"


class Role(StrEnum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    USER = "user"


class UserStatus(StrEnum):
    PENDING = "pending_verification"
    ACTIVE = "active"
    DISABLED = "disabled"


class AppUser(Base):
    """An account. Passwords are stored as scrypt hashes; ``password_hash`` is empty until set."""

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(16), default=Role.USER)
    status: Mapped[str] = mapped_column(String(24), default=UserStatus.PENDING)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Two-factor sign-in: the TOTP secret is encrypted like other secrets; recovery codes are hashed.
    totp_secret: Mapped[str | None] = mapped_column(Text)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_last_step: Mapped[int | None] = mapped_column(Integer)  # a code is accepted once
    recovery_codes: Mapped[list[Any]] = mapped_column(default=list)
    # "Sign in with Google": Google's stable account id, once linked.
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Retention: when the inactivity warning went out (cleared on the next sign-in).
    retention_warned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    """Server-side login session. The browser holds a random token; only its SHA-256 is stored."""

    __tablename__ = "user_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = _ts()
    user_agent: Mapped[str | None] = mapped_column(String(255))


class AuthToken(Base):
    """Single-use email verification and password-reset tokens (hashed)."""

    __tablename__ = "auth_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(24))  # verify_email | reset_password
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()


class UserIntegration(Base):
    """A user's own connection settings (email, LLM, job-source keys).

    ``config`` holds only non-secret fields. Secret fields are encrypted together in ``secret`` and
    never returned by the API.
    """

    __tablename__ = "user_integration"
    __table_args__ = (UniqueConstraint("user_id", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # email | llm | adzuna
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    secret: Mapped[str | None] = mapped_column(Text)  # Fernet token
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _ts(onupdate=utcnow)


class PlatformSetting(Base):
    """Settings the superadmin manages (system email, registration, limits). Same secret rules."""

    __tablename__ = "platform_setting"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    secret: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = _ts(onupdate=utcnow)


class UserProfile(Base):
    """One row per user: editable profile and job preferences."""

    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), unique=True)
    profile: Mapped[dict[str, Any]] = mapped_column(default=dict)
    preferences: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[datetime] = _ts(onupdate=utcnow)


class AutomationPolicyRow(Base):
    """One row per user. ``paused`` stops scheduled work; ``emergency_stop`` also blocks every
    outbound action, including ones you approved, until cleared."""

    __tablename__ = "automation_policy"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), unique=True)
    policy: Mapped[dict[str, Any]] = mapped_column(default=dict)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    stop_reason: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = _ts(onupdate=utcnow)


class ResumeMaster(Base):
    """An uploaded master resume. The file is stored read-only and never modified."""

    __tablename__ = "resume_master"
    __table_args__ = (UniqueConstraint("user_id", "sha256"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(StoredPath(1024))
    file_format: Mapped[str] = mapped_column(String(8))
    sha256: Mapped[str] = mapped_column(String(64))
    parsed: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Your corrections to the parse; when set, used instead of ``parsed``.
    corrected: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_at: Mapped[datetime] = _ts()
    # Set when you delete a resume that tailored resumes were made from: it is hidden, but kept so
    # their history and files stay valid. A resume nothing was made from is deleted outright.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobSource(Base):
    __tablename__ = "job_source"
    __table_args__ = (UniqueConstraint("user_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    schedule_minutes: Mapped[int | None] = mapped_column(Integer)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    auth_ok: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _ts()


class JobPosting(Base):
    __tablename__ = "job_posting"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id"),
        Index("ix_job_posting_canonical_url", "canonical_url"),
        Index("ix_job_posting_identity", "normalized_company", "normalized_title"),
        Index("ix_job_posting_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("job_source.id", ondelete="RESTRICT"))
    external_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(2048))
    canonical_url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(300))
    normalized_title: Mapped[str] = mapped_column(String(300))
    normalized_company: Mapped[str] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300))
    work_mode: Mapped[str | None] = mapped_column(String(16))
    employment_type: Mapped[str | None] = mapped_column(String(64))
    salary_min_lpa: Mapped[float | None] = mapped_column(Float)
    salary_max_lpa: Mapped[float | None] = mapped_column(Float)
    salary_text: Mapped[str | None] = mapped_column(String(200))
    experience_min: Mapped[float | None] = mapped_column(Float)
    experience_max: Mapped[float | None] = mapped_column(Float)
    posted_at: Mapped[date | None] = mapped_column(Date)
    deadline: Mapped[date | None] = mapped_column(Date)
    description_raw: Mapped[str] = mapped_column(Text)  # as received, never rendered as HTML
    description_text: Mapped[str] = mapped_column(Text)
    description_sha256: Mapped[str] = mapped_column(String(64))
    parsed: Mapped[dict[str, Any]] = mapped_column(default=dict)
    apply_method: Mapped[str] = mapped_column(String(16), default="manual")  # mock | email | manual
    apply_url: Mapped[str | None] = mapped_column(String(2048))
    apply_email: Mapped[str | None] = mapped_column(String(320))
    questions: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.DISCOVERED)
    status_reason: Mapped[str | None] = mapped_column(String(500))
    liveness: Mapped[str] = mapped_column(String(16), default="unverified")  # active | expired | unverified
    flags: Mapped[dict[str, Any]] = mapped_column(default=dict)  # suspicious, prompt_injection, repost ...
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("job_posting.id", ondelete="SET NULL"))
    # True for cross-posts of an existing job (hidden by default); reposts keep False but link duplicate_of_id.
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    discovered_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts(onupdate=utcnow)

    source: Mapped[JobSource] = relationship(lazy="joined")
    requirements: Mapped[list[JobRequirement]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )


class JobRequirement(Base):
    __tablename__ = "job_requirement"
    __table_args__ = (Index("ix_job_requirement_job", "job_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_posting.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))  # required_skill | preferred_skill | education | certification | experience | restriction
    value: Mapped[str] = mapped_column(String(500))

    job: Mapped[JobPosting] = relationship(back_populates="requirements")


class JobMatch(Base):
    """One row per evaluation; the latest is current. Old rows show how a score changed."""

    __tablename__ = "job_match"
    __table_args__ = (Index("ix_job_match_job", "job_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_posting.id", ondelete="CASCADE"))
    master_id: Mapped[int | None] = mapped_column(ForeignKey("resume_master.id", ondelete="SET NULL"))
    scorer_version: Mapped[str] = mapped_column(String(16))
    score: Mapped[float] = mapped_column(Float)
    band: Mapped[str] = mapped_column(String(16))  # high | good | review | low | disqualified
    confidence: Mapped[str] = mapped_column(String(8))
    recommended: Mapped[bool] = mapped_column(Boolean)
    breakdown: Mapped[dict[str, Any]] = mapped_column(default=dict)
    explanation: Mapped[dict[str, Any]] = mapped_column(default=dict)
    disqualifiers: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = _ts()


class InterviewPrep(Base):
    """Interview preparation for one job: likely questions, your stories (built only from your resume)
    and questions to ask. Regenerating replaces it."""

    __tablename__ = "interview_prep"
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_posting.id", ondelete="CASCADE"))
    content: Mapped[dict[str, Any]] = mapped_column(default=dict)
    used_llm: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()


class ResumeTailoringRun(Base):
    __tablename__ = "resume_tailoring_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_posting.id", ondelete="CASCADE"))
    master_id: Mapped[int] = mapped_column(ForeignKey("resume_master.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | succeeded | failed
    template_version: Mapped[str] = mapped_column(String(32))
    used_llm: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    version_id: Mapped[int | None] = mapped_column(ForeignKey("resume_version.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = _ts()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResumeVersion(Base):
    """An immutable tailored resume. Files live in their own folder and are never rewritten; the
    checksums let every email prove it attached exactly this file."""

    __tablename__ = "resume_version"
    __table_args__ = (UniqueConstraint("job_id", "version_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_posting.id", ondelete="CASCADE"))
    master_id: Mapped[int] = mapped_column(ForeignKey("resume_master.id", ondelete="RESTRICT"))
    version_no: Mapped[int] = mapped_column(Integer)
    role_family: Mapped[str] = mapped_column(String(32))
    template_version: Mapped[str] = mapped_column(String(32))
    folder: Mapped[str] = mapped_column(StoredPath(1024))
    docx_path: Mapped[str] = mapped_column(StoredPath(1024))
    pdf_path: Mapped[str] = mapped_column(StoredPath(1024))
    docx_sha256: Mapped[str] = mapped_column(String(64))
    pdf_sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict[str, Any]] = mapped_column(default=dict)
    report: Mapped[dict[str, Any]] = mapped_column(default=dict)
    validation: Mapped[dict[str, Any]] = mapped_column(default=dict)
    valid: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _ts()


class Application(Base):
    __tablename__ = "application"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_posting.id", ondelete="RESTRICT"), unique=True)
    resume_version_id: Mapped[int | None] = mapped_column(ForeignKey("resume_version.id", ondelete="RESTRICT"))
    route: Mapped[str] = mapped_column(String(16))  # mock | email | manual
    mode: Mapped[str] = mapped_column(String(16))  # supervised | automatic
    outcome: Mapped[str] = mapped_column(String(16), default=Outcome.PENDING)
    submitted_format: Mapped[str] = mapped_column(String(8), default="pdf")
    submitted_file_path: Mapped[str | None] = mapped_column(StoredPath(1024))
    submitted_file_sha256: Mapped[str | None] = mapped_column(String(64))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_ref: Mapped[str | None] = mapped_column(String(300))
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(32))
    pause_reasons: Mapped[list[Any]] = mapped_column(default=list)
    # Automatic applications wait until this moment (next send window, after the review hold).
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts(onupdate=utcnow)

    job: Mapped[JobPosting] = relationship(lazy="joined")
    answers: Mapped[list[ApplicationAnswer]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    attempts: Mapped[list[ApplicationAttempt]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="ApplicationAttempt.attempt_no"
    )


class ApplicationAnswer(Base):
    __tablename__ = "application_answer"
    __table_args__ = (UniqueConstraint("application_id", "question"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(String(1000))
    category: Mapped[str] = mapped_column(String(32))
    answer: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16))  # profile | user | none
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_user: Mapped[bool] = mapped_column(Boolean, default=False)


class ApplicationAttempt(Base):
    """Committed *before* the external call, so a crash leaves a STARTED row that recovery turns
    into UNKNOWN rather than a silent resubmission."""

    __tablename__ = "application_attempt"
    __table_args__ = (UniqueConstraint("application_id", "attempt_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default=AttemptStatus.STARTED)
    trigger: Mapped[str] = mapped_column(String(16))  # automatic | approved | retry
    error: Mapped[str | None] = mapped_column(Text)
    response: Mapped[dict[str, Any]] = mapped_column(default=dict)
    started_at: Mapped[datetime] = _ts()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecruiterContact(Base):
    __tablename__ = "recruiter_contact"
    __table_args__ = (UniqueConstraint("job_id", "email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_posting.id", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    source: Mapped[str] = mapped_column(String(32))  # job_description | connector | user
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _ts()


class EmailDraft(Base):
    __tablename__ = "email_draft"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # outreach | application
    job_id: Mapped[int] = mapped_column(ForeignKey("job_posting.id", ondelete="CASCADE"))
    recruiter_id: Mapped[int | None] = mapped_column(ForeignKey("recruiter_contact.id", ondelete="SET NULL"))
    to_email: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    resume_version_id: Mapped[int | None] = mapped_column(ForeignKey("resume_version.id", ondelete="RESTRICT"))
    # "tailored" (a resume version for this job) or "master" (your base resume, when the job has an
    # email address but no tailored resume).
    attachment_source: Mapped[str] = mapped_column(String(16), default="tailored")
    master_id: Mapped[int | None] = mapped_column(ForeignKey("resume_master.id", ondelete="SET NULL"))
    attachment_format: Mapped[str] = mapped_column(String(8), default="pdf")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | scheduled | sending | sent | failed | cancelled
    # Automatic outreach waits until this moment (next send window, after the review hold).
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # One outreach per recipient per job, ever.
    dedupe_key: Mapped[str] = mapped_column(String(400), unique=True)
    follow_up_status: Mapped[str] = mapped_column(String(16), default="none")  # none | due | done | replied
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts(onupdate=utcnow)

    deliveries: Mapped[list[EmailDelivery]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class EmailDelivery(Base):
    __tablename__ = "email_delivery"

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("email_draft.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(16))
    message_id: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16))  # accepted | failed
    attachment_sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = _ts()


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (Index("ix_notification_outbox_due", "status", "next_attempt_at"), UniqueConstraint("user_id", "dedupe_key"))

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    dedupe_key: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    # [{"path", "filename", "sha256"}]: verified again just before sending.
    attachments: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | sent | dead | held
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = _ts()
    last_error: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _ts()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalRequest(Base):
    __tablename__ = "approval_request"
    __table_args__ = (Index("ix_approval_request_status", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # application | outreach
    job_id: Mapped[int] = mapped_column(ForeignKey("job_posting.id", ondelete="CASCADE"))
    target_id: Mapped[int] = mapped_column(Integer)  # application.id or email_draft.id
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected | superseded
    reasons: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = _ts()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(500))


class ScheduledTask(Base):
    __tablename__ = "scheduled_task"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(32))  # discovery | outbox | digest | reconcile
    interval_minutes: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime] = _ts()
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))
    last_error: Mapped[str | None] = mapped_column(Text)


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (Index("ix_audit_event_at", "at"), Index("ix_audit_event_action", "action"))

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = _ts()
    actor: Mapped[str] = mapped_column(String(16))  # user | system | scheduler
    action: Mapped[str] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(8), default="info")  # info | warning | error
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(String(1000))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)


# ---------------------------------------------------------------- assistant (chat)


class ChatConversation(Base):
    __tablename__ = "chat_conversation"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="New chat")
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts(onupdate=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_message"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("chat_conversation.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    # Structured parts shown with the message: job cards, search results, drafts, suggestions.
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = _ts()


class ChatAction(Base):
    """Something the assistant proposed that acts on the world or on your data (apply, send an
    email, change your profile). It runs only when you confirm it, and only once."""

    __tablename__ = "chat_action"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("chat_conversation.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # apply | send_email | update_profile
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    summary: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | done | failed | cancelled | expired
    result: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiToken(Base):
    """A key for the browser extension: read your ready applications and mark one applied, nothing
    else. Stored as a SHA-256 hash; shown once when created; revocable; expires."""

    __tablename__ = "api_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(12))  # shown in the list so you can tell keys apart
    scope: Mapped[str] = mapped_column(String(32), default="autofill")
    created_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
