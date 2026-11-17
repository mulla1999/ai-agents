"""Per-user settings: profile, preferences, automation policy, job sources and integrations."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from agents_core.llm import Message
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select

from ..connectors.base import Support
from ..connectors.catalog import BY_KEY, CATALOG
from ..db import JobSource
from ..domain import AutomationPolicy, Preferences, Profile
from ..errors import ServiceError
from ..notifications.email import OutgoingEmail, message_id_for
from ..services import company_finder
from ..services import integrations as integ
from ..services import settings_store as store
from ..services.audit import record
from ..services.source_config import validate_source_config
from ..services.jobs import ensure_sources, load_candidate, run_source
from ..services.notify import notify_automation_stopped
from ..workflow.pipeline import advance_all, run_discovery
from .deps import DB, RT, URT, CurrentUser, iso
from ..config import BRAND

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/profile")
async def get_profile(db: DB, user: CurrentUser) -> dict:
    loaded = await load_candidate(db, user.id)
    summary = None
    if loaded:
        c, _ = loaded
        summary = {"name": c.name, "years_experience": c.years_experience,
                   "years_including_internships": c.years_including_internships, "current_title": c.current_title,
                   "current_company": c.current_company, "skills": sorted(c.skills), "has_cs_degree": c.has_cs_degree}
    return {"profile": (await store.get_profile(db, user.id)).model_dump(mode="json"),
            "preferences": (await store.get_preferences(db, user.id)).model_dump(mode="json"), "candidate": summary}


@router.put("/profile")
async def put_profile(profile: Profile, db: DB, user: CurrentUser) -> dict:
    await store.save_profile(db, user.id, profile)
    await db.commit()
    return profile.model_dump(mode="json")


@router.put("/preferences")
async def put_preferences(preferences: Preferences, db: DB, user: CurrentUser) -> dict:
    await store.save_preferences(db, user.id, preferences)
    await db.commit()
    return preferences.model_dump(mode="json")


@router.get("/automation")
async def get_automation(db: DB, user: CurrentUser) -> dict:
    state = await store.get_policy_state(db, user.id)
    limits = await integ.platform_config(db, "limits")
    return {"policy": state.policy.model_dump(mode="json"), "paused": state.paused,
            "emergency_stop": state.emergency_stop, "stop_reason": state.stop_reason,
            "confirmation_phrase": store.AUTOMATIC_CONFIRMATION, "limits": limits}


class PolicyBody(BaseModel):
    policy: AutomationPolicy
    confirmation: str | None = Field(default=None, max_length=100)


@router.put("/automation")
async def put_automation(body: PolicyBody, db: DB, user: CurrentUser) -> dict:
    limits = await integ.platform_config(db, "limits")
    if body.policy.discovery_interval_minutes < limits["min_discovery_minutes"]:
        raise ServiceError("limit", f"discovery can run at most every {limits['min_discovery_minutes']} minutes here", 422)
    try:
        await store.save_policy(db, user.id, body.policy, confirmation=body.confirmation)
    except store.PolicyError as exc:
        raise ServiceError("confirmation_required", str(exc), 422) from exc
    await db.commit()
    return await get_automation(db, user)


class ControlBody(BaseModel):
    action: str = Field(pattern="^(pause|resume|stop|clear_stop)$")
    reason: str | None = Field(default=None, max_length=300)


@router.post("/automation/control")
async def control(body: ControlBody, db: DB, user: CurrentUser) -> dict:
    if body.action in ("pause", "resume"):
        await store.set_paused(db, user.id, body.action == "pause")
    elif body.action == "stop":
        await store.set_emergency_stop(db, user.id, True, body.reason or "stopped from the dashboard")
        await notify_automation_stopped(db, user.id, body.reason or "emergency stop pressed")
    else:
        await store.set_emergency_stop(db, user.id, False)
    await db.commit()
    return await get_automation(db, user)


@router.post("/automation/run")
async def run_now(request: Request, rt: URT, source: str | None = None) -> dict:
    """Manual refresh: discover from your enabled sources (or one) and advance every job."""
    if not await request.app.state.runtime.limiter.hit(f"run-now:{rt.user_id}", 6, 3600):
        raise ServiceError("rate_limited", "discovery already ran several times this hour; it also runs on its own schedule", 429)
    report = await run_discovery(rt, source_key=source)
    return {"sources": report.sources, "new_jobs": report.new_jobs, "advanced": report.advanced, "errors": report.errors}


@router.post("/automation/advance")
async def advance_now(rt: URT) -> dict:
    report = await advance_all(rt)
    return {"advanced": report.advanced, "errors": report.errors}


# ---------------------------------------------------------------- job sources


async def _sources(db, user_id: int, mock: bool) -> list[dict[str, Any]]:  # noqa: ANN001
    await ensure_sources(db, user_id, mock=mock)
    await db.commit()
    rows = {s.key: s for s in (await db.scalars(select(JobSource).where(JobSource.user_id == user_id))).all()}
    out = []
    for spec in CATALOG:
        if spec.key == "mock" and not mock:
            continue
        row = rows.get(spec.key)
        out.append({
            "key": spec.key, "name": spec.name, "support": spec.support, "description": spec.description,
            "needs_integration": list(spec.env_vars), "enabled": bool(row and row.enabled),
            "config": row.config if row else None, "schedule_minutes": row.schedule_minutes if row else None,
            "last_run_at": iso(row.last_run_at) if row else None, "last_status": row.last_status if row else None,
            "last_error": row.last_error if row else None, "auth_ok": row.auth_ok if row else None,
            "configurable": spec.connector is not None,
        })
    return out


@router.get("/sources")
async def list_sources(db: DB, rt: URT) -> list[dict]:
    return await _sources(db, rt.user_id, rt.settings.mock_enabled)


class SourceBody(BaseModel):
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)
    schedule_minutes: int | None = Field(default=None, ge=15, le=10080)


@router.put("/sources/{key}")
async def put_source(key: str, body: SourceBody, db: DB, rt: URT) -> list[dict]:
    spec = BY_KEY.get(key)
    if spec is None or spec.connector is None or (key == "mock" and not rt.settings.mock_enabled):
        raise ServiceError("unsupported_source", "this source cannot be automated", 400)
    if len(str(body.config)) > 20000:
        raise ServiceError("too_large", "source configuration is too large", 413)
    body.config = validate_source_config(key, body.config)
    limits = await integ.platform_config(db, "limits")
    if len(body.config.get("boards") or []) > limits["max_boards_per_source"]:
        raise ServiceError("limit", f"at most {limits['max_boards_per_source']} companies per source", 422)
    if len(body.config.get("pages") or []) > limits["max_career_pages"]:
        raise ServiceError("limit", f"at most {limits['max_career_pages']} career pages", 422)
    if body.schedule_minutes is not None and body.schedule_minutes < limits["min_discovery_minutes"]:
        raise ServiceError("limit", f"sources can run at most every {limits['min_discovery_minutes']} minutes", 422)
    await ensure_sources(db, rt.user_id, mock=rt.settings.mock_enabled)
    row = await db.scalar(select(JobSource).where(JobSource.user_id == rt.user_id, JobSource.key == key))
    assert row is not None
    row.enabled, row.config, row.schedule_minutes = body.enabled, body.config, body.schedule_minutes
    row.auth_ok = None  # re-test after a change
    await record(db, rt.user_id, "config.source", f"{spec.name}: enabled={body.enabled}", actor="user",
                 entity=("job_source", row.id))
    await db.commit()
    return await _sources(db, rt.user_id, rt.settings.mock_enabled)


@router.get("/sources/find-company")
async def find_company(q: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=300)],
                       request: Request, db: DB, rt: URT) -> dict:
    """Which job boards (Greenhouse, Lever, Ashby, SmartRecruiters) a company has, and whether you follow it."""
    if not await request.app.state.runtime.limiter.hit(f"find-company:{rt.user_id}", 30, 3600):
        raise ServiceError("rate_limited", "too many company searches this hour; try again later", 429)
    results = await company_finder.find(rt.fetcher, q)
    rows = {s.key: s for s in (await db.scalars(select(JobSource).where(JobSource.user_id == rt.user_id))).all()}
    for r in results:
        boards = ((rows[r["kind"]].config or {}).get("boards") or []) if r["kind"] in rows else []
        r["added"] = any(str(b.get("token", "")).lower() == r["token"].lower() for b in boards)
    return {"results": results}


class BoardBody(BaseModel):
    token: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    company: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


@router.post("/sources/{key}/boards")
async def add_board(key: str, body: BoardBody, db: DB, rt: URT) -> list[dict]:
    """Follow one more company on a board source (and switch the source on)."""
    if key not in company_finder.KINDS:
        raise ServiceError("unsupported_source", "companies can be added to Greenhouse, Lever, Ashby or SmartRecruiters", 400)
    await ensure_sources(db, rt.user_id, mock=rt.settings.mock_enabled)
    row = await db.scalar(select(JobSource).where(JobSource.user_id == rt.user_id, JobSource.key == key))
    assert row is not None
    config = dict(row.config or {})
    boards = list(config.get("boards") or [])
    if not any(str(b.get("token", "")).lower() == body.token.lower() for b in boards):
        boards.append({"token": body.token, "company": body.company})
    config = validate_source_config(key, {**config, "boards": boards})
    limits = await integ.platform_config(db, "limits")
    if len(config["boards"]) > limits["max_boards_per_source"]:
        raise ServiceError("limit", f"at most {limits['max_boards_per_source']} companies per source", 422)
    row.config, row.enabled = config, True
    await record(db, rt.user_id, "config.source", f"{BY_KEY[key].name}: added {body.company}", actor="user",
                 entity=("job_source", row.id))
    await db.commit()
    return await _sources(db, rt.user_id, rt.settings.mock_enabled)


@router.post("/sources/{key}/test")
async def test_source(key: str, request: Request, db: DB, rt: URT) -> dict:
    if not await request.app.state.runtime.limiter.hit(f"source-test:{rt.user_id}", 20, 3600):
        raise ServiceError("rate_limited", "too many source tests this hour; try again later", 429)
    spec = BY_KEY.get(key)
    if spec is None or spec.connector is None or (key == "mock" and not rt.settings.mock_enabled):
        raise ServiceError("unsupported_source", "this source cannot be automated", 400)
    await ensure_sources(db, rt.user_id, mock=rt.settings.mock_enabled)
    row = await db.scalar(select(JobSource).where(JobSource.user_id == rt.user_id, JobSource.key == key))
    assert row is not None
    try:
        stats = await run_source(db, rt.settings, rt.fetcher, row, rt.credentials)
    except Exception as exc:  # report any connector failure to the UI
        await db.commit()
        return {"ok": False, "message": str(exc)[:500]}
    await db.commit()
    return {"ok": True, "message": f"{stats.new} new, {stats.updated} updated, {stats.duplicates} duplicates",
            "warnings": stats.warnings}


# ---------------------------------------------------------------- your integrations (email, AI, Adzuna)


@router.get("/integrations")
async def integrations(db: DB, rt: URT, app_rt: RT) -> dict:
    views = {kind: integ.public_view(await integ.get_row(db, rt.user_id, kind), kind, app_rt.box) for kind in integ.KINDS}
    views["llm"]["verified_this_session"] = rt.llm_verified
    views["email"]["mode"] = ("configured" if rt.sender.configured and rt.sender.delivers else
                              "local mailbox (nothing is sent)" if rt.sender.configured else "not set up")
    profile = await store.get_profile(db, rt.user_id)
    return {"integrations": views, "sources": await _sources(db, rt.user_id, rt.settings.mock_enabled),
            "notification_email_set": profile.notification_email is not None,
            "unsupported": [{"key": s.key, "name": s.name, "reason": s.description} for s in CATALOG
                            if s.support in (Support.UNSUPPORTED, Support.MANUAL)]}


class IntegrationBody(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict, max_length=20)
    # Write-only. Leave a field blank to keep what is stored.
    secrets: dict[str, Annotated[str, StringConstraints(max_length=4096)] | None] = Field(default_factory=dict, max_length=5)


@router.put("/integrations/{kind}")
async def put_integration(kind: str, body: IntegrationBody, db: DB, rt: URT, app_rt: RT) -> dict:
    row = await integ.save(db, rt.settings, app_rt.box, rt.user_id, kind, body.config, body.secrets)
    await db.commit()
    if kind == "llm":
        app_rt.mark_llm_verified(rt.user_id, False)
    return integ.public_view(row, kind, app_rt.box)


@router.delete("/integrations/{kind}")
async def delete_integration(kind: str, db: DB, rt: URT, app_rt: RT) -> dict:
    await integ.delete(db, rt.user_id, kind)
    await db.commit()
    return integ.public_view(None, kind, app_rt.box)


class ModelsBody(BaseModel):
    provider: str = Field(pattern="^(gemini|openai_compatible)$")
    api_key: str | None = Field(default=None, max_length=400)  # blank: use the saved key
    base_url: str | None = Field(default=None, max_length=500)


@router.post("/integrations/llm/models")
async def llm_models(body: ModelsBody, request: Request, db: DB, rt: URT, app_rt: RT) -> dict:
    """The models this key can use, recommended first. Nothing is saved."""
    from ..security.hosts import UnsafeHost, ensure_https_endpoint
    from ..services import llm_models

    if not await request.app.state.runtime.limiter.hit(f"llm-models:{rt.user_id}", 30, 3600):
        raise ServiceError("rate_limited", "too many model lookups; try again later", 429)
    key = (body.api_key or "").strip()
    if not key:
        row = await integ.get_row(db, rt.user_id, "llm")
        if row is not None and row.config.get("provider") == body.provider:
            key = app_rt.box.open(row.secret).get("api_key", "")
    if not key:
        raise ServiceError("no_key", "enter your API key first", 422)
    if body.provider == "gemini":
        models = await llm_models.gemini_models(key)
    else:
        try:
            base = ensure_https_endpoint(body.base_url or "https://api.openai.com/v1", allow_private=rt.settings.allow_private_hosts)
        except UnsafeHost as exc:
            raise ServiceError("unsafe_host", str(exc), 422) from exc
        models = await llm_models.openai_compatible_models(rt.http, base, key)
    return {"models": [m.as_dict() for m in models], "recommended": next((m.id for m in models if m.recommended), None)}


@router.post("/integrations/llm/test")
async def test_llm(db: DB, rt: URT, app_rt: RT) -> dict:
    if rt.llm is None:
        return {"ok": False, "message": rt.llm_error or "no AI provider set up"}
    try:
        reply = await asyncio.wait_for(rt.llm.complete_json([Message("user", 'Reply with the JSON {"ok": true}.')]), 30)
    except Exception as exc:  # report, never raise: this is a diagnostic
        app_rt.mark_llm_verified(rt.user_id, False)
        return {"ok": False, "message": f"{exc.__class__.__name__}: {str(exc)[:200]}"}
    ok = reply.get("ok") is True
    app_rt.mark_llm_verified(rt.user_id, ok)
    if ok:
        await integ.mark_verified(db, rt.user_id, "llm")
        await db.commit()
    return {"ok": ok, "message": f"{rt.llm.name} answered"}


@router.post("/integrations/websearch/test")
async def test_websearch(db: DB, rt: URT) -> dict:
    from ..services.websearch import search_jobs

    try:
        hits = await search_jobs(rt.fetcher, rt.credentials.get("websearch"), "software engineer", "India", limit=3)
    except ServiceError as exc:
        return {"ok": False, "message": exc.message}
    await integ.mark_verified(db, rt.user_id, "websearch")
    await db.commit()
    return {"ok": True, "message": f"search works: {len(hits)} results for a sample query"}


@router.post("/integrations/email/test")
async def test_email(db: DB, rt: URT) -> dict:
    profile = await store.get_profile(db, rt.user_id)
    if not profile.notification_email:
        raise ServiceError("no_recipient", "set a notification email in Profile first", 409)
    mail = OutgoingEmail(to=str(profile.notification_email), subject=f"{BRAND} test email",
                         body=f"This is a test from {BRAND}. Your email settings work.",
                         message_id=message_id_for(f"test-u{rt.user_id}-{asyncio.get_running_loop().time():.0f}"))
    try:
        result = await rt.sender.send(mail)
    except Exception as exc:
        return {"ok": False, "message": str(exc)[:300]}
    await integ.mark_verified(db, rt.user_id, "email")
    await record(db, rt.user_id, "integration.email_test", f"test email via {result.provider}", actor="user")
    await db.commit()
    return {"ok": True, "message": result.detail}
