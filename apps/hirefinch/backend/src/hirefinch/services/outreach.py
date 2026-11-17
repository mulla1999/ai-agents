"""Recruiter outreach: personalised drafts from verified facts, sent only to verified addresses.

Rules enforced here, not in the UI:
* only contacts listed in the posting, returned by a connector, or added by you; never guessed
* a contact is sendable only when ``verified`` (personal domains and addresses found in
  suspicious or injected text are not)
* one email per recipient per job, ever (unique dedupe key); a daily cap
* drafts by default; automatic sending only when you enabled it with the confirmation phrase
* the attachment is the resume version submitted for that job, verified by checksum
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import (
    Application,
    ApprovalRequest,
    EmailDelivery,
    EmailDraft,
    JobPosting,
    JobStatus,
    RecruiterContact,
    ResumeMaster,
    ResumeVersion,
    utcnow,
)
from ..errors import ServiceError
from ..notifications.email import Attachment, EmailError, OutgoingEmail, message_id_for
from ..notifications.outbox import enqueue
from ..runtime import UserRuntime as Runtime
from ..workflow.states import transition
from ..workflow.timing import next_send_time
from .audit import record
from .email_compose import EmailFacts, compose, plain_text, render_html
from ..text import format_phone, full_url, resume_filename
from .jobs import latest_match, load_candidate
from .resumes import active_master
from .integrations import platform_config
from .settings_store import get_policy_state, get_profile
from .tailoring import latest_version


def dedupe_key(job_id: int, email: str) -> str:
    return f"outreach:{job_id}:{email.lower()}"


async def add_contact(db: AsyncSession, job: JobPosting, email: str, name: str | None, title: str | None,
                      note: str | None) -> RecruiterContact:
    try:
        normalized = validate_email(email, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ServiceError("invalid_email", str(exc), 422) from exc
    existing = await db.scalar(select(RecruiterContact).where(RecruiterContact.job_id == job.id,
                                                              RecruiterContact.email == normalized))
    if existing is not None:
        return existing
    contact = RecruiterContact(user_id=job.user_id, job_id=job.id, email=normalized, name=(name or None), title=(title or None),
                               source="user", verified=True, verification_note=(note or "added by you")[:500])
    db.add(contact)
    await db.flush()
    await record(db, job.user_id, "recruiter.added", f"recruiter contact added for job {job.id}", actor="user",
                 entity=("recruiter", contact.id))
    return contact


async def _attachment_version(db: AsyncSession, job: JobPosting) -> ResumeVersion | None:
    app = await db.scalar(select(Application).where(Application.job_id == job.id))
    if app is not None and app.resume_version_id and app.submitted_at is not None:
        return await db.get(ResumeVersion, app.resume_version_id)  # the one actually submitted
    return await latest_version(db, job.id)


def _attachment_name(draft_row: EmailDraft, path: str, profile) -> str:  # noqa: ANN001
    """Always the standard ATS name (First_Last_Resume.pdf), whichever version is attached."""
    return resume_filename(profile.full_name, Path(path).suffix)


async def _attachment(db: AsyncSession, draft_row: EmailDraft) -> tuple[str, str]:
    """The exact file the draft attaches, with the checksum it must still match when sent."""
    if draft_row.attachment_source == "master":
        master = await db.get(ResumeMaster, draft_row.master_id) if draft_row.master_id else None
        if master is None or master.user_id != draft_row.user_id:
            raise ServiceError("invalid_resume", "the base resume for this email no longer exists", 409)
        return master.file_path, master.sha256  # the uploaded original, never modified
    version = await db.get(ResumeVersion, draft_row.resume_version_id) if draft_row.resume_version_id else None
    if version is None or not version.valid:
        raise ServiceError("invalid_resume", "the attached resume is missing or invalid", 409)
    if draft_row.attachment_format == "pdf":
        return version.pdf_path, version.pdf_sha256
    return version.docx_path, version.docx_sha256


async def _compose_for(db: AsyncSession, rt: Runtime, job: JobPosting, contact: RecruiterContact | None, *, tailored: bool):  # noqa: ANN202
    """Subject and body for an email about this job, in your email style, from verified facts."""
    loaded = await load_candidate(db, job.user_id)
    if loaded is None:
        raise ServiceError("no_resume", "upload a master resume first", 409)
    candidate, _ = loaded
    profile = await get_profile(db, job.user_id)
    match = await latest_match(db, job.id)
    strongest = [s["skill"] for s in ((match.explanation or {}).get("strongest_skills", []) if match else [])][:4]
    projects = [p["project"] for p in ((match.explanation or {}).get("relevant_projects", []) if match else [])][:2]
    name = profile.full_name or candidate.name
    linkedin = profile.linkedin_url or next((link for link in candidate.resume.contact.links if "linkedin" in link.lower()), None)
    facts = EmailFacts(
        name=name, job_title=job.title, company=job.company, job_url=job.canonical_url,
        first_name=(contact.name or "").split()[0] if contact and contact.name else None,
        current_title=candidate.current_title, current_company=candidate.current_company,
        years=f"{candidate.years_experience:g}" if candidate.years_experience else None,
        skills=strongest, projects=projects, tailored=tailored,
        email=str(profile.contact_email or candidate.resume.contact.email or "") or None,
        phone=format_phone(profile.phone or candidate.resume.contact.phone), linkedin=full_url(linkedin),
        job_focus="; ".join(((job.parsed or {}).get("responsibilities") or [])[:6]) if isinstance(job.parsed, dict) else "",
    )
    policy = (await get_policy_state(db, job.user_id)).policy
    composed = await compose(facts, profile.email_style, rt.llm,
                             allow_ai=policy.use_llm_for_tailoring and not job.flags.get("prompt_injection"))
    return composed


async def recompose(db: AsyncSession, rt: Runtime, draft_row: EmailDraft, *, force: bool = False) -> bool:
    """Rewrite an unsent draft in the current wording and signature. Only drafts still in the agent's
    old template are touched; a draft you edited yourself is left as it is."""
    if draft_row.status not in ("draft", "failed", "scheduled"):
        return False
    old_markers = ("tailored to this role", "I am interested in the", "I have attached my resume. I would welcome a conversation")
    if not force and not any(m in draft_row.body for m in old_markers):
        return False
    job = await db.get(JobPosting, draft_row.job_id)
    contact = await db.get(RecruiterContact, draft_row.recruiter_id) if draft_row.recruiter_id else None
    composed = await _compose_for(db, rt, job, contact, tailored=draft_row.attachment_source == "tailored")
    draft_row.subject, draft_row.body = composed.subject, composed.body
    await record(db, draft_row.user_id, "outreach.recomposed", f"email {draft_row.id} rewritten in the new style",
                 entity=("email_draft", draft_row.id))
    return True


async def draft(db: AsyncSession, rt: Runtime, job: JobPosting, contact: RecruiterContact, *,
                allow_base: bool = True) -> EmailDraft:
    """Draft one email to a verified contact. Attaches the tailored resume for the job, or, when the
    job has none, your base (master) resume."""
    key = dedupe_key(job.id, contact.email)
    existing = await db.scalar(select(EmailDraft).where(EmailDraft.dedupe_key == key))
    if existing is not None:
        return existing
    version = await _attachment_version(db, job)
    master = None
    if version is None:
        master = await active_master(db, job.user_id) if allow_base else None
        if master is None:
            raise ServiceError("no_resume_version", "generate a tailored resume for this job first", 409)
    composed = await _compose_for(db, rt, job, contact, tailored=version is not None)
    subject, body = composed.subject, composed.body
    row = EmailDraft(user_id=job.user_id, kind="outreach", job_id=job.id, recruiter_id=contact.id, to_email=contact.email,
                     subject=subject, body=body, resume_version_id=version.id if version else None,
                     attachment_source="tailored" if version else "master", master_id=master.id if master else None,
                     attachment_format="pdf", dedupe_key=key, deliveries=[])
    try:
        async with db.begin_nested():
            db.add(row)
    except IntegrityError:
        return await db.scalar(select(EmailDraft).where(EmailDraft.dedupe_key == key))  # type: ignore[return-value]
    await record(db, job.user_id, "outreach.drafted", f"outreach draft for job {job.id}", entity=("email_draft", row.id))
    return row


async def update_draft(db: AsyncSession, draft_row: EmailDraft, subject: str, body: str) -> None:
    if draft_row.status != "draft":
        raise ServiceError("bad_state", "only drafts can be edited", 409)
    draft_row.subject, draft_row.body = subject.strip()[:300], body.strip()[:10000]
    await record(db, draft_row.user_id, "outreach.edited", f"draft {draft_row.id} edited", actor="user", entity=("email_draft", draft_row.id))


async def sent_today(db: AsyncSession, user_id: int) -> int:
    return int(await db.scalar(select(func.count(EmailDraft.id)).where(EmailDraft.user_id == user_id,
        EmailDraft.status == "sent", EmailDraft.updated_at >= utcnow() - timedelta(days=1))) or 0)


async def send(db: AsyncSession, rt: Runtime, draft_row: EmailDraft, *, actor: str) -> EmailDraft:
    state = await get_policy_state(db, draft_row.user_id)
    if state.emergency_stop:
        raise ServiceError("emergency_stop", "emergency stop is engaged", 423)
    if draft_row.status == "sent":
        raise ServiceError("already_sent", "this email was already sent", 409)
    if draft_row.status not in ("draft", "failed", "scheduled"):
        raise ServiceError("bad_state", f"draft is '{draft_row.status}'", 409)
    if actor == "system" and not state.policy.auto_send_outreach:
        raise ServiceError("not_enabled", "automatic outreach is off", 409)
    contact = await db.get(RecruiterContact, draft_row.recruiter_id) if draft_row.recruiter_id else None
    if contact is None or not contact.verified or contact.email != draft_row.to_email:
        raise ServiceError("unverified_recipient", "the recipient is not a verified contact for this job", 409)
    # Your own limit, and a platform-wide cap the superadmin sets, so no account can send bulk mail.
    cap = min(state.policy.outreach_daily_limit, int((await platform_config(db, "limits"))["daily_outreach_cap"]))
    if await sent_today(db, draft_row.user_id) >= cap:
        raise ServiceError("limit", f"daily outreach limit of {cap} reached", 429)
    note = None if rt.sender.delivers else "local mailbox: written to disk, not sent"
    path, sha = await _attachment(db, draft_row)
    profile = await get_profile(db, draft_row.user_id)
    mail = OutgoingEmail(to=draft_row.to_email, subject=draft_row.subject, body=plain_text(draft_row.body),
                         message_id=message_id_for(draft_row.dedupe_key.replace(":", "-")),
                         attachments=[Attachment(path=path, filename=_attachment_name(draft_row, path, profile), sha256=sha)],
                         reply_to=str(profile.contact_email) if profile.contact_email else None,
                         html=render_html(draft_row.body) if profile.email_style.html else None)
    draft_row.status = "sending"
    await db.commit()  # a crash now leaves "sending", which is never resent automatically
    try:
        result = await rt.sender.send(mail)
    except EmailError as exc:
        draft_row.status = "failed"
        draft_row.deliveries.append(EmailDelivery(draft_id=draft_row.id, provider=rt.sender.name, message_id=mail.message_id,
                                                  status="failed", attachment_sha256=sha, error=str(exc)[:1000]))
        await record(db, draft_row.user_id, "outreach.failed", f"outreach {draft_row.id} failed: {exc}", level="warning",
                     entity=("email_draft", draft_row.id))
        await db.commit()
        raise ServiceError("send_failed", str(exc), 502) from exc
    draft_row.status = "sent"
    draft_row.follow_up_status = "due"
    draft_row.deliveries.append(EmailDelivery(draft_id=draft_row.id, provider=result.provider, message_id=result.message_id,
                                              status="accepted", attachment_sha256=sha, error=note))
    request = await db.scalar(select(ApprovalRequest).where(ApprovalRequest.kind == "outreach",
                                                            ApprovalRequest.target_id == draft_row.id,
                                                            ApprovalRequest.status == "pending"))
    if request is not None:
        request.status, request.decided_at = "approved", utcnow()
    job = await db.get(JobPosting, draft_row.job_id)
    if job is not None and job.status == JobStatus.APPLIED:
        await transition(db, job, JobStatus.RECRUITER_CONTACTED, reason=f"emailed {draft_row.to_email}")
    await record(db, draft_row.user_id, "outreach.sent", f"outreach {draft_row.id} sent via {result.provider}", actor=actor,
                 entity=("email_draft", draft_row.id), details={"attachment_sha256": sha, "detail": result.detail})
    await enqueue(db, draft_row.user_id, "outreach_sent", f"outreach-sent-{draft_row.id}",
                  f"Recruiter emailed: {job.title if job else ''} at {job.company if job else ''}",
                  f"Sent to {draft_row.to_email} at {utcnow():%Y-%m-%d %H:%M UTC} via {result.provider}.\n"
                  f"Subject: {draft_row.subject}\nAttachment SHA-256: {sha[:12]}…\n{result.detail}")
    await db.commit()
    return draft_row


async def schedule(db: AsyncSession, draft_row: EmailDraft, policy) -> None:  # noqa: ANN001
    """Automatic outreach: send in the next window, after the review hold, unless you cancel."""
    draft_row.status = "scheduled"
    draft_row.scheduled_for = next_send_time(utcnow() + timedelta(minutes=policy.auto_review_minutes), policy)
    await record(db, draft_row.user_id, "outreach.scheduled", f"email {draft_row.id} scheduled", entity=("email_draft", draft_row.id))


async def request_approval(db: AsyncSession, draft_row: EmailDraft, reason: str) -> None:
    existing = await db.scalar(select(ApprovalRequest).where(ApprovalRequest.kind == "outreach",
                                                             ApprovalRequest.target_id == draft_row.id))
    if existing is None:
        db.add(ApprovalRequest(user_id=draft_row.user_id, kind="outreach", job_id=draft_row.job_id, target_id=draft_row.id, reasons=[reason]))
        await enqueue(db, draft_row.user_id, "approval_required", f"outreach-approval-{draft_row.id}",
                      f"Recruiter email ready for review: {draft_row.subject}",
                      f"A draft to {draft_row.to_email} is waiting in Recruiter Outreach.\nReason: {reason}")


async def cancel(db: AsyncSession, draft_row: EmailDraft) -> None:
    if draft_row.status not in ("draft", "failed", "scheduled"):
        raise ServiceError("bad_state", f"cannot cancel a '{draft_row.status}' email", 409)
    draft_row.status = "cancelled"
    request = await db.scalar(select(ApprovalRequest).where(ApprovalRequest.kind == "outreach",
                                                            ApprovalRequest.target_id == draft_row.id,
                                                            ApprovalRequest.status == "pending"))
    if request is not None:
        request.status, request.decided_at = "rejected", utcnow()
    await record(db, draft_row.user_id, "outreach.cancelled", f"draft {draft_row.id} cancelled", actor="user", entity=("email_draft", draft_row.id))
