"""Generate, validate and store a tailored resume version for one job.

Each version gets its own folder, written once:

    artifacts/resumes/<company>/<job-id>/v<n>/resume_<role>.docx|.pdf
                                            job_description.txt
                                            tailoring_report.json
                                            comparison.diff
                                            manifest.json   (checksums, template, timestamps, validation)
"""

from __future__ import annotations

import difflib
import json
import logging
from pathlib import Path

from agents_core.llm import LLMError, LLMProvider
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import JobPosting, JobStatus, ResumeTailoringRun, ResumeVersion, utcnow
from ..domain import Bullet, ParsedJob
from ..errors import ServiceError
from ..llm_assist import rewrite_bullets, rewrite_summary
from ..resume.layout import render_previews
from ..resume.render import render_resume
from ..resume.tailor import TAILOR_VERSION, TEMPLATE_VERSION, render_text, tailor
from ..resume.validator import rewrite_problem, validate_facts, validate_files
from ..skills import extract_skills
from ..text import keywords, resume_filename, sha256_file, slug
from ..workflow.states import transition
from .audit import record
from .jobs import latest_match, load_candidate
from .resumes import active_master, document_of
from .settings_store import get_policy_state, get_profile

log = logging.getLogger(__name__)


async def generate(db: AsyncSession, settings: Settings, job: JobPosting, llm: LLMProvider | None = None,
                   *, actor: str = "system") -> ResumeVersion:
    master = await active_master(db, job.user_id)
    loaded = await load_candidate(db, job.user_id)
    if master is None or loaded is None:
        raise ServiceError("no_resume", "upload a master resume first", 409)
    candidate, _ = loaded
    match = await latest_match(db, job.id)
    family = (match.explanation or {}).get("role_family", "java_backend") if match else "java_backend"
    policy = (await get_policy_state(db, job.user_id)).policy
    profile = await get_profile(db, job.user_id)

    if job.status in (JobStatus.SHORTLISTED, JobStatus.RESUME_READY, JobStatus.AWAITING_APPROVAL,
                      JobStatus.READY_TO_APPLY, JobStatus.NEEDS_MANUAL):
        await transition(db, job, JobStatus.RESUME_PENDING, reason="generating tailored resume", actor=actor)
    elif job.status != JobStatus.RESUME_PENDING:
        raise ServiceError("bad_state", f"cannot tailor a resume while the job is '{job.status}'", 409)

    run = ResumeTailoringRun(user_id=job.user_id, job_id=job.id, master_id=master.id, template_version=TEMPLATE_VERSION)
    db.add(run)
    await db.flush()
    try:
        version = await _build(db, settings, job, master.id, document_of(master), candidate, profile, family,
                               policy.max_bullets_older_roles, llm if policy.use_llm_for_tailoring else None, run)
    except Exception as exc:
        log.exception("resume generation failed for job %s", job.id)
        run.status, run.error, run.finished_at = "failed", f"{exc.__class__.__name__}: {exc}"[:2000], utcnow()
        await transition(db, job, JobStatus.NEEDS_MANUAL, reason="resume generation failed")
        await record(db, job.user_id, "resume.failed", f"resume generation failed for job {job.id}", level="error",
                     entity=("job", job.id), details={"error": run.error})
        await db.commit()  # keep the failure on record even though the caller sees an error
        raise ServiceError("tailoring_failed", "resume generation failed; see the activity log", 500) from exc
    run.status, run.version_id, run.finished_at = "succeeded", version.id, utcnow()
    if version.valid:
        await transition(db, job, JobStatus.RESUME_READY, reason=f"resume v{version.version_no} passed validation")
    else:
        await transition(db, job, JobStatus.NEEDS_MANUAL, reason="tailored resume failed validation; review it")
    await record(db, job.user_id, "resume.generated", f"resume v{version.version_no} for job {job.id} "
                 f"({'valid' if version.valid else 'INVALID'})", actor=actor, entity=("resume_version", version.id),
                 details={"pdf_sha256": version.pdf_sha256, "docx_sha256": version.docx_sha256})
    return version


MAX_REWORDED = 14  # the most relevant bullets only: keeps the model call small


async def _reword_bullets(llm, result, parsed, master_doc) -> str | None:  # noqa: ANN001
    """Let the model reword the most relevant bullets; keep only rewrites that pass rewrite_problem."""
    doc = result.document
    relevant = set(parsed.required_skills) | set(parsed.preferred_skills)
    entries = [*doc.experience, *doc.projects]
    candidates = [(b.id, b.text) for e in entries for b in e.bullets
                  if set(extract_skills(b.text)) & relevant or keywords(b.text) & set(parsed.keywords)][:MAX_REWORDED]
    try:
        proposed = await rewrite_bullets(llm, candidates, parsed, result.keyword_coverage["covered"])
    except LLMError as exc:
        return f"LLM bullet rewording skipped: {exc}"
    kept, rejected = [], []
    for entry in entries:
        for i, bullet in enumerate(entry.bullets):
            new = proposed.get(bullet.id)
            if not new:
                continue
            if (problem := rewrite_problem(bullet.text, new)) is None:
                entry.bullets[i] = Bullet(id=bullet.id, text=new, source=bullet.text)
                kept.append({"original": bullet.text, "rewritten": new})
            elif problem != "unchanged":
                rejected.append({"original": bullet.text, "proposed": new, "reason": problem})
    result.rewrites, result.rejected_rewrites = kept, rejected
    if kept:  # the comparison shows the reworded text
        result.diff = "\n".join(difflib.unified_diff(render_text(master_doc).split("\n"), render_text(doc).split("\n"),
                                                     "master", "tailored", lineterm=""))
    if kept:
        result.changes.append(f"{len(kept)} bullet{'s' if len(kept) != 1 else ''} reworded by the LLM for this job; "
                              "each keeps every number and technology of the original")
    return f"{len(kept)} bullets reworded, {len(rejected)} rewordings rejected" if candidates else None


async def _build(db, settings, job, master_id, master_doc, candidate, profile, family, max_bullets, llm, run):  # noqa: ANN001
    parsed = ParsedJob.model_validate(job.parsed)
    result = tailor(master_doc, parsed, candidate, profile, role_family=family, max_bullets_older_roles=max_bullets)
    llm_note = None
    if llm is not None and not job.flags.get("prompt_injection"):
        try:
            candidate_summary = await rewrite_summary(llm, master_doc.summary, parsed, result.keyword_coverage["covered"])
        except LLMError as exc:
            llm_note = f"LLM summary skipped: {exc}"
        else:
            trial = result.document.model_copy(deep=True)
            trial.summary = candidate_summary
            check = validate_facts(master_doc, trial, profile, max_years=candidate.years_including_internships)
            if check.passed:
                result.document = trial
                result.changes.append("Summary reworded by the LLM and verified against the master")
                run.used_llm = True
            else:
                llm_note = "LLM summary rejected by validation: " + "; ".join(check.as_dict()["errors"])
        note = await _reword_bullets(llm, result, parsed, master_doc)
        run.used_llm = run.used_llm or bool(result.rewrites)
        llm_note = "; ".join(x for x in (llm_note, note) if x) or None
    version_no = (await db.scalar(select(func.max(ResumeVersion.version_no)).where(ResumeVersion.job_id == job.id)) or 0) + 1
    folder = settings.artifacts_dir / "users" / str(job.user_id) / "resumes" / slug(job.company) / f"job-{job.id}" / f"v{version_no}"
    if folder.exists():  # left by a run that crashed before its database row was committed
        folder.rename(folder.with_name(f"{folder.name}-orphan-{utcnow():%Y%m%d%H%M%S}"))
    folder.mkdir(parents=True)
    stem = Path(resume_filename(profile.full_name or master_doc.contact.name)).stem  # First_Last_Resume
    docx_path, pdf_path = folder / f"{stem}.docx", folder / f"{stem}.pdf"
    rendered = render_resume(result.document, docx_path, pdf_path)

    report = validate_facts(master_doc, result.document, profile, max_years=candidate.years_including_internships)
    validate_files(report, docx_path, pdf_path, result.document, parsed.required_skills + parsed.preferred_skills,
                   style=rendered.style, render=rendered)
    validation = report.as_dict()
    previews = render_previews(pdf_path, folder / "preview")
    layout = {"style": rendered.style.name, "body_pt": rendered.style.body_pt, "pages": rendered.pages,
              "last_page_fill": rendered.last_page_fill, "continued": rendered.continued,
              "previews": [str(x.relative_to(folder)) for x in previews],
              # Automated checks catch regressions, not every visual flaw: look at the previews when warned.
              "visual_review_recommended": bool(validation["warnings"]) or rendered.pages > rendered.style.target_pages}
    tailoring_report = {
        "role_family": family,
        "changes": result.changes,
        "omitted_bullets": result.omitted_bullets,
        "keyword_coverage": result.keyword_coverage,
        "gaps": [f"The job asks for {s}; your resume does not evidence it, so it was not added"
                 for s in result.keyword_coverage["missing_not_in_profile"]],
        "llm": llm_note or ("used" if run.used_llm else "not used"),
        "rewrites": result.rewrites,
        "rejected_rewrites": result.rejected_rewrites,
        "layout": layout,
    }
    (folder / "job_description.txt").write_text(f"{job.title} — {job.company}\n{job.url}\n\n{job.description_text}\n")
    (folder / "tailoring_report.json").write_text(json.dumps(tailoring_report, indent=2))
    (folder / "comparison.diff").write_text(result.diff + "\n")
    docx_sha, pdf_sha = sha256_file(str(docx_path)), sha256_file(str(pdf_path))
    created = utcnow()
    (folder / "manifest.json").write_text(json.dumps({
        "job_id": job.id, "company": job.company, "title": job.title, "version": version_no,
        "master_resume_id": master_id, "template_version": TEMPLATE_VERSION, "tailor_version": TAILOR_VERSION,
        "parser_version": parsed.parser_version, "generated_at": created.isoformat(),
        "files": {docx_path.name: docx_sha, pdf_path.name: pdf_sha},
        "description_sha256": job.description_sha256, "validation": validation, "layout": layout,
    }, indent=2))
    version = ResumeVersion(
        user_id=job.user_id,
        job_id=job.id, master_id=master_id, version_no=version_no, role_family=family,
        template_version=TEMPLATE_VERSION, folder=str(folder), docx_path=str(docx_path), pdf_path=str(pdf_path),
        docx_sha256=docx_sha, pdf_sha256=pdf_sha, content=result.document.model_dump(mode="json"),
        report={**tailoring_report, "diff": result.diff}, validation=validation, valid=report.passed, created_at=created,
    )
    db.add(version)
    await db.flush()
    return version


async def latest_version(db: AsyncSession, job_id: int, *, valid_only: bool = True) -> ResumeVersion | None:
    query = select(ResumeVersion).where(ResumeVersion.job_id == job_id)
    if valid_only:
        query = query.where(ResumeVersion.valid.is_(True))
    return await db.scalar(query.order_by(ResumeVersion.version_no.desc()).limit(1))
