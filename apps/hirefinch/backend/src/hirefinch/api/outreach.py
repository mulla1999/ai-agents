"""Recruiter contacts, outreach drafts, sending and follow-ups."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import EmailDraft, JobPosting, RecruiterContact
from ..errors import ServiceError
from ..services import outreach as service
from .deps import DB, URT, CurrentUser, contact_out, draft_out, get_owned

router = APIRouter(prefix="/api/outreach", tags=["outreach"])


@router.get("")
async def overview(db: DB, user: CurrentUser) -> dict:
    contacts = (await db.scalars(select(RecruiterContact).where(RecruiterContact.user_id == user.id)
                                 .order_by(RecruiterContact.created_at.desc()).limit(300))).all()
    drafts = (await db.scalars(select(EmailDraft).where(EmailDraft.user_id == user.id)
                               .order_by(EmailDraft.updated_at.desc()).limit(300))).all()
    jobs = {j.id: j for j in (await db.scalars(select(JobPosting).where(
        JobPosting.id.in_({c.job_id for c in contacts} | {d.job_id for d in drafts})))).all()}

    def label(job_id: int) -> dict:
        job = jobs.get(job_id)
        return {"job_title": job.title if job else "", "company": job.company if job else "", "job_status": job.status if job else ""}

    return {"contacts": [{**contact_out(c), **label(c.job_id)} for c in contacts],
            "drafts": [{**draft_out(d), **label(d.job_id)} for d in drafts]}


class ContactBody(BaseModel):
    email: str = Field(max_length=320)
    name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    note: str = Field(min_length=5, max_length=500, description="where you found this address")


@router.post("/jobs/{job_id}/contacts", status_code=201)
async def add_contact(job_id: int, body: ContactBody, db: DB, user: CurrentUser) -> dict:
    job = await get_owned(db, JobPosting, job_id, user, "job")
    contact = await service.add_contact(db, job, body.email, body.name, body.title, body.note)
    await db.commit()
    return contact_out(contact)


@router.post("/contacts/{contact_id}/draft", status_code=201)
async def create_draft(contact_id: int, db: DB, rt: URT, user: CurrentUser) -> dict:
    contact = await get_owned(db, RecruiterContact, contact_id, user, "contact")
    if not contact.verified:
        raise ServiceError("unverified_recipient", f"not drafting to an unverified address ({contact.verification_note})", 409)
    job = await get_owned(db, JobPosting, contact.job_id, user, "job")
    draft = await service.draft(db, rt, job, contact)
    await db.commit()
    return draft_out(draft)


class DraftBody(BaseModel):
    subject: str = Field(min_length=3, max_length=300)
    body: str = Field(min_length=20, max_length=10000)


@router.put("/drafts/{draft_id}")
async def edit_draft(draft_id: int, body: DraftBody, db: DB, user: CurrentUser) -> dict:
    draft = await get_owned(db, EmailDraft, draft_id, user, "draft")
    await service.update_draft(db, draft, body.subject, body.body)
    await db.commit()
    return draft_out(draft)


@router.post("/drafts/{draft_id}/send")
async def send_draft(draft_id: int, db: DB, rt: URT, user: CurrentUser) -> dict:
    draft = await get_owned(db, EmailDraft, draft_id, user, "draft")
    await service.send(db, rt, draft, actor="user")
    return draft_out(draft)


@router.post("/drafts/{draft_id}/cancel")
async def cancel_draft(draft_id: int, db: DB, user: CurrentUser) -> dict:
    draft = await get_owned(db, EmailDraft, draft_id, user, "draft")
    await service.cancel(db, draft)
    await db.commit()
    return draft_out(draft)


class FollowUpBody(BaseModel):
    status: str = Field(pattern="^(none|due|done|replied)$")


@router.post("/drafts/{draft_id}/follow-up")
async def follow_up(draft_id: int, body: FollowUpBody, db: DB, user: CurrentUser) -> dict:
    draft = await get_owned(db, EmailDraft, draft_id, user, "draft")
    draft.follow_up_status = body.status
    await db.commit()
    return draft_out(draft)
