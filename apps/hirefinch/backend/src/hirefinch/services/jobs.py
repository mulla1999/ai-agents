"""Job ingest (normalise, dedupe, parse, safety-scan), discovery runs and match evaluation."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..candidate import CandidateProfile, build_candidate
from ..config import Settings
from ..connectors.base import ConnectorAuthError, ConnectorError, SourceContext, Support
from ..connectors.catalog import BY_KEY, CATALOG
from ..db import ApprovalRequest, JobMatch, JobPosting, JobRequirement, JobSource, JobStatus, RecruiterContact, utcnow
from ..domain import ParsedJob, Preferences, RawJob
from ..errors import ServiceError
from ..jobs import dedupe
from ..jobs.matching import SCORER_VERSION, evaluate
from ..jobs.parser import parse_job
from ..jobs.safety import scan
from ..net import SafeFetcher
from ..text import canonical_url, html_to_text, normalize_company, normalize_title, sha256_text, slug
from ..workflow.states import transition
from .audit import record
from .resumes import active_master, document_of
from .settings_store import get_preferences, get_profile

log = logging.getLogger(__name__)

_APPLY_BY_EMAIL = re.compile(r"\b(send(ing)?|e-?mail(ing)?|mail(ing)?|shar(e|ing)|forward(ing)?|apply)\b[^\n]{0,80}?\b(resume|cv|profile|application)\b", re.I)
_PERSONAL = ("gmail.com", "yahoo.", "outlook.com", "hotmail.com", "rediffmail.com")


@dataclass
class IngestStats:
    new: int = 0
    updated: int = 0
    duplicates: int = 0
    rejected: int = 0
    too_old: int = 0  # outside the recency window (or undated)
    new_ids: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _valid_email(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return validate_email(value.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


async def ensure_sources(db: AsyncSession, user_id: int, *, mock: bool = True) -> None:
    existing = set((await db.scalars(select(JobSource.key).where(JobSource.user_id == user_id))).all())
    for spec in CATALOG:
        if spec.key == "mock" and not mock:
            continue  # the demo source does not exist in production
        if spec.key not in existing and spec.support is not Support.UNSUPPORTED:
            db.add(JobSource(user_id=user_id, key=spec.key, kind=spec.key, name=spec.name, enabled=spec.default_enabled,
                             config=dict(spec.default_config)))
    await db.flush()


def _snapshot(settings: Settings, job: JobPosting) -> None:
    folder = settings.artifacts_dir / "users" / str(job.user_id) / "job_descriptions" / slug(job.company)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"job-{job.id}.txt").write_text(
        f"Title: {job.title}\nCompany: {job.company}\nLocation: {job.location or '-'}\nURL: {job.url}\n"
        f"Source: {job.source.key if job.source else job.source_id}\nDiscovered: {job.discovered_at:%Y-%m-%d %H:%M UTC}\n"
        f"Description SHA-256: {job.description_sha256}\n\n{job.description_text}\n"
    )


def _apply_route(raw: RawJob, parsed: ParsedJob, text: str) -> tuple[str, str | None]:
    if raw.apply_method == "mock":
        return "mock", None
    email = _valid_email(raw.apply_email)
    if email is None and len(parsed.emails) == 1 and _APPLY_BY_EMAIL.search(text):
        email = _valid_email(parsed.emails[0])
    return ("email", email) if email else ("manual", None)


def _requirements(parsed: ParsedJob) -> list[JobRequirement]:
    rows = [JobRequirement(kind="required_skill", value=s) for s in parsed.required_skills]
    rows += [JobRequirement(kind="preferred_skill", value=s) for s in parsed.preferred_skills]
    rows += [JobRequirement(kind="education", value=e[:500]) for e in parsed.education]
    rows += [JobRequirement(kind="certification", value=c[:500]) for c in parsed.certifications]
    rows += [JobRequirement(kind="restriction", value=r) for r in parsed.restrictions]
    if parsed.experience_min is not None:
        span = f"{parsed.experience_min:g}" + (f"-{parsed.experience_max:g}" if parsed.experience_max else "+")
        rows.append(JobRequirement(kind="experience", value=f"{span} years"))
    return rows


def _apply_parse(job: JobPosting, raw: RawJob, text: str, hidden: str, parsed: ParsedJob) -> None:
    route, email = _apply_route(raw, parsed, text)
    safety = scan(text, hidden, company=raw.company, emails=[e for e in [email, *parsed.emails] if e])
    job.description_raw = raw.description[:200000]
    job.description_text = text[:100000]
    job.description_sha256 = sha256_text(text)
    job.parsed = parsed.model_dump(mode="json")
    job.work_mode = parsed.work_mode
    job.salary_min_lpa, job.salary_max_lpa, job.salary_text = parsed.salary_min_lpa, parsed.salary_max_lpa, parsed.salary_text
    job.experience_min, job.experience_max = parsed.experience_min, parsed.experience_max
    job.apply_method, job.apply_email = route, email
    job.apply_url = raw.apply_url or raw.url
    job.questions = list(raw.questions)
    job.requirements = _requirements(parsed)
    flags = dict(job.flags or {})
    flags.update(safety.as_flags())
    if raw.extra.get("truncated_description"):
        flags["truncated_description"] = True
    if raw.extra.get("mock_behavior"):
        flags["mock_behavior"] = raw.extra["mock_behavior"]
    if raw.extra.get("via"):
        flags["via"] = raw.extra["via"][:80]  # e.g. "LinkedIn job alert", shown with the job
    job.flags = flags


async def ingest(db: AsyncSession, settings: Settings, source: JobSource, raws: list[RawJob], prefs: Preferences) -> IngestStats:
    stats = IngestStats()
    cutoff = date.today() - timedelta(days=prefs.max_posting_age_days) if prefs.max_posting_age_days else None
    for raw in raws:
        if cutoff is not None and source.kind != "manual":
            if raw.posted_at is None and not prefs.include_undated:
                stats.too_old += 1
                continue
            if raw.posted_at is not None and raw.posted_at < cutoff:
                stats.too_old += 1
                continue
        title, company = raw.title.strip()[:300], raw.company.strip()[:300]
        if not title or not raw.url.startswith(("http://", "https://")) or not raw.external_id:
            stats.rejected += 1
            continue
        text, hidden = html_to_text(raw.description)
        canonical = canonical_url(raw.url)
        n_company, n_title = normalize_company(company), normalize_title(title)
        parsed = parse_job(raw, text, prefs.fx_rates_to_inr)

        job = await db.scalar(select(JobPosting).where(JobPosting.source_id == source.id,
                                                       JobPosting.external_id == raw.external_id[:255]))
        if job is not None:
            job.liveness = "active" if raw.is_active is not False else "expired"
            if job.description_sha256 != sha256_text(text):
                _apply_parse(job, raw, text, hidden, parsed)
                if job.status == JobStatus.MATCH_EVALUATED:
                    await transition(db, job, JobStatus.MATCH_EVALUATED, reason="description changed; re-evaluate")
                stats.updated += 1
            continue

        candidates = list((await db.scalars(select(JobPosting).where(JobPosting.user_id == source.user_id, or_(
            JobPosting.canonical_url == canonical,
            (JobPosting.normalized_company == n_company) & (JobPosting.normalized_title == n_title),
        )))).all())
        verdict = dedupe.classify(canonical_url=canonical, normalized_company=n_company, normalized_title=n_title,
                                  location=raw.location, description_text=text, posted_at=raw.posted_at,
                                  candidates=candidates)
        if verdict.kind == "same_url":
            stats.duplicates += 1
            continue

        job = JobPosting(
            user_id=source.user_id,
            source_id=source.id, external_id=raw.external_id[:255], url=raw.url[:2048], canonical_url=canonical[:2048],
            title=title, company=company or "Unknown", normalized_title=n_title, normalized_company=n_company,
            location=(raw.location or "")[:300] or None, employment_type=raw.employment_type, posted_at=raw.posted_at,
            deadline=raw.deadline, liveness="active" if raw.is_active else "unverified", flags={},
            description_raw="", description_text="", description_sha256="",
        )
        _apply_parse(job, raw, text, hidden, parsed)
        if verdict.kind in ("duplicate", "repost"):
            job.duplicate_of_id = verdict.job_id
            job.is_duplicate = verdict.kind == "duplicate"
            job.flags = {**job.flags, verdict.kind: True, "similarity": round(verdict.similarity, 2)}
        db.add(job)
        await db.flush()
        job.source = source
        if verdict.kind == "duplicate":
            stats.duplicates += 1
            await record(db, source.user_id, "job.duplicate", f"'{title}' at {company} duplicates job {verdict.job_id}",
                         entity=("job", job.id))
        else:
            stats.new += 1
            stats.new_ids.append(job.id)
        if raw.deadline and raw.deadline < date.today():
            job.liveness = "expired"
            await transition(db, job, JobStatus.EXPIRED, reason="application deadline has passed")
        await _add_recruiters(db, job, raw, parsed)
        _snapshot(settings, job)
    return stats


async def _add_recruiters(db: AsyncSession, job: JobPosting, raw: RawJob, parsed: ParsedJob) -> None:
    seen: set[str] = set()
    found = []
    if email := _valid_email(raw.recruiter_email):
        found.append((email, raw.recruiter_name, raw.recruiter_title, "connector"))
    for e in parsed.emails:
        if (email := _valid_email(e)) and email != job.apply_email:
            found.append((email, None, None, "job_description"))
    for email, name, title, source in found:
        if email in seen:
            continue
        seen.add(email)
        personal = email.split("@")[1].startswith(_PERSONAL)
        injected = bool(job.flags.get("prompt_injection")) and email in " ".join(job.flags.get("injection_snippets", []))
        verified = not personal and not injected and not job.flags.get("suspicious")
        note = ("listed in the official posting" if verified else
                "personal email domain" if personal else "appears in suspicious or injected text")
        if verified:
            job.flags = {**(job.flags or {}), "email_available": True}
        db.add(RecruiterContact(user_id=job.user_id, job_id=job.id, email=email, name=name, title=title, source=source, verified=verified,
                                verification_note=note))


async def import_manual(db: AsyncSession, settings: Settings, user_id: int, raw: RawJob) -> JobPosting:
    await ensure_sources(db, user_id, mock=settings.mock_enabled)
    source = await db.scalar(select(JobSource).where(JobSource.user_id == user_id, JobSource.key == "manual"))
    assert source is not None
    if raw.apply_method == "mock":
        raw.apply_method = None  # only the mock connector may use the mock route
    stats = await ingest(db, settings, source, [raw], await get_preferences(db, user_id))
    if stats.rejected:
        raise ServiceError("invalid_job", "a job needs a title and an http(s) URL", 422)
    job = await db.scalar(select(JobPosting).where(JobPosting.source_id == source.id,
                                                   JobPosting.external_id == raw.external_id[:255]))
    if job is None:
        # Same URL as a job we already have.
        job = await db.scalar(select(JobPosting).where(JobPosting.user_id == user_id,
                                                       JobPosting.canonical_url == canonical_url(raw.url)))
    assert job is not None
    await record(db, user_id, "job.imported", f"imported '{job.title}' at {job.company}", actor="user", entity=("job", job.id))
    return job


async def run_source(db: AsyncSession, settings: Settings, fetcher: SafeFetcher, source: JobSource,
                     credentials: dict | None = None) -> IngestStats:
    spec = BY_KEY.get(source.kind)
    if spec is None or spec.connector is None:
        raise ServiceError("unsupported_source", f"{source.name} cannot be fetched automatically", 400)
    if source.kind == "mock" and not settings.mock_enabled:
        raise ServiceError("unsupported_source", "the demo source is not available here", 400)
    prefs = await get_preferences(db, source.user_id)
    connector = spec.connector()
    ctx = SourceContext(settings=settings, fetcher=fetcher.with_hosts(set(connector.api_hosts)), preferences=prefs,
                        config=source.config or {}, credentials=(credentials or {}).get(source.kind, {}))
    source.last_run_at = utcnow()
    try:
        result = await connector.fetch(ctx)
    except ConnectorAuthError as exc:
        source.last_status, source.last_error, source.auth_ok = "auth_failed", str(exc)[:1000], False
        await record(db, source.user_id, "source.auth_failed", f"{source.name}: {exc}", level="error", entity=("job_source", source.id))
        raise
    except ConnectorError as exc:
        source.last_status, source.last_error = "failed", str(exc)[:1000]
        await record(db, source.user_id, "source.failed", f"{source.name}: {exc}", level="warning", entity=("job_source", source.id),
                     details={"retryable": exc.retryable})
        raise
    stats = await ingest(db, settings, source, result.jobs, prefs)
    stats.warnings = result.warnings
    source.last_status, source.auth_ok = ("ok_with_warnings" if result.warnings else "ok"), True
    source.last_error = "; ".join(result.warnings)[:1000] or None
    await record(db, source.user_id, "source.run", f"{source.name}: {stats.new} new, {stats.updated} updated, "
                 f"{stats.duplicates} duplicates, {stats.rejected} rejected, {stats.too_old} older than the window", entity=("job_source", source.id),
                 details={"warnings": result.warnings[:10]})
    return stats


async def load_candidate(db: AsyncSession, user_id: int) -> tuple[CandidateProfile, int] | None:
    master = await active_master(db, user_id)
    if master is None:
        return None
    return build_candidate(document_of(master), await get_profile(db, user_id)), master.id


async def evaluate_job(db: AsyncSession, job: JobPosting, candidate: CandidateProfile | None = None,
                       master_id: int | None = None) -> JobMatch:
    if candidate is None:
        loaded = await load_candidate(db, job.user_id)
        if loaded is None:
            raise ServiceError("no_resume", "upload a master resume before evaluating jobs", 409)
        candidate, master_id = loaded
    prefs = await get_preferences(db, job.user_id)
    profile = await get_profile(db, job.user_id)
    parsed = ParsedJob.model_validate(job.parsed)
    result = evaluate(title=job.title, company=job.company, location=job.location, parsed=parsed,
                      description=job.description_text, candidate=candidate, prefs=prefs, flags=job.flags,
                      willing_to_relocate=profile.willing_to_relocate)
    match = JobMatch(user_id=job.user_id, job_id=job.id, master_id=master_id, scorer_version=SCORER_VERSION, score=result.score,
                     band=result.band, confidence=result.confidence, recommended=result.recommended,
                     breakdown=result.breakdown(), explanation=result.explanation, disqualifiers=result.disqualifiers)
    db.add(match)
    if job.status in (JobStatus.DISCOVERED, JobStatus.MATCH_EVALUATED):
        await transition(db, job, JobStatus.MATCH_EVALUATED, reason=f"score {result.score:g} ({result.band})")
    await db.flush()
    return match


async def latest_match(db: AsyncSession, job_id: int) -> JobMatch | None:
    return await db.scalar(select(JobMatch).where(JobMatch.job_id == job_id).order_by(JobMatch.id.desc()).limit(1))


RESCORABLE = (JobStatus.DISCOVERED, JobStatus.MATCH_EVALUATED, JobStatus.SHORTLISTED, JobStatus.RESUME_READY,
              JobStatus.AWAITING_APPROVAL)


async def rescore(db: AsyncSession, user_id: int) -> dict[str, int]:
    """Re-parse and re-score jobs not yet applied to, after a parser or scorer change.

    Queued jobs that no longer qualify are withdrawn (reversible from the tracker), never deleted.
    Jobs with an application in progress or submitted are not touched.
    """
    from .settings_store import get_policy_state  # local: avoids a cycle with settings_store users

    loaded = await load_candidate(db, user_id)
    if loaded is None:
        raise ServiceError("no_resume", "upload a master resume first", 409)
    candidate, master_id = loaded
    prefs = await get_preferences(db, user_id)
    policy = (await get_policy_state(db, user_id)).policy
    counts = {"rescored": 0, "withdrawn": 0}
    jobs = (await db.scalars(select(JobPosting).where(JobPosting.user_id == user_id, JobPosting.status.in_(RESCORABLE),
                                                      JobPosting.is_duplicate.is_(False)))).all()
    for job in jobs:
        text, hidden = html_to_text(job.description_raw)
        raw = RawJob(external_id=job.external_id, url=job.url, title=job.title, company=job.company,
                     description=job.description_raw, location=job.location, work_mode=job.work_mode,  # type: ignore[arg-type]
                     apply_email=job.apply_email, apply_url=job.apply_url, questions=list(job.questions or []))
        parsed = parse_job(raw, text, prefs.fx_rates_to_inr)
        if parsed.salary_max_lpa is None and job.salary_max_lpa is not None:  # salary came from the connector
            parsed.salary_min_lpa, parsed.salary_max_lpa, parsed.salary_text = job.salary_min_lpa, job.salary_max_lpa, job.salary_text
        job.parsed = parsed.model_dump(mode="json")
        job.requirements = _requirements(parsed)
        job.experience_min, job.experience_max = parsed.experience_min, parsed.experience_max
        match = await evaluate_job(db, job, candidate, master_id)
        counts["rescored"] += 1
        qualifies = match.band in ("high", "good") and match.score >= policy.shortlist_min_score
        if job.status in (JobStatus.SHORTLISTED, JobStatus.RESUME_READY, JobStatus.AWAITING_APPROVAL) and not qualifies:
            await transition(db, job, JobStatus.WITHDRAWN, reason=f"re-scored {match.score:g} ({match.band}); restore it if you disagree")
            for req in (await db.scalars(select(ApprovalRequest).where(ApprovalRequest.job_id == job.id,
                                                                      ApprovalRequest.status == "pending"))).all():
                req.status, req.decided_at, req.decision_note = "superseded", utcnow(), "job re-scored"
            counts["withdrawn"] += 1
    await record(db, user_id, "jobs.rescored", f"{counts['rescored']} jobs re-scored, {counts['withdrawn']} withdrawn from the queue",
                 details=counts)
    return counts
