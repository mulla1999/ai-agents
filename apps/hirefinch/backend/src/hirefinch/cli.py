"""Command line: ``hirefinch <command>``. Run from the workspace root so the root .env is used.

Commands that act on one person's data take ``--email`` (default: HIREFINCH_SUPERADMIN_EMAIL).
Passwords are always prompted for, never passed as arguments (they would land in shell history).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from pathlib import Path

import yaml
from sqlalchemy import select

from .config import get_settings
from .domain import AutomationPolicy, Preferences, Profile
from .runtime import Runtime, build_runtime


async def _user_id(rt: Runtime, email: str | None) -> int:
    from .db import AppUser
    from .services.accounts import normalize_email

    email = email or rt.settings.superadmin_email
    if not email:
        sys.exit("pass --email (or set HIREFINCH_SUPERADMIN_EMAIL)")
    async with rt.sessionmaker() as db:
        user = await db.scalar(select(AppUser).where(AppUser.email == normalize_email(email)))
    if user is None:
        sys.exit(f"no account for {email}; create one with `hirefinch create-superadmin` or sign up in the app")
    return user.id


def _prompt_password(confirm: bool = True) -> str:
    from .security.passwords import WeakPassword, check_strength

    while True:
        password = getpass.getpass("New password (12+ characters): ")
        try:
            check_strength(password)
        except WeakPassword as exc:
            print(f"  {exc}")
            continue
        if not confirm or getpass.getpass("Repeat it: ") == password:
            return password
        print("  the two entries differ")


async def _create_superadmin(args: argparse.Namespace) -> None:
    """Create (or promote) the superadmin, verified and active."""
    from .db import AppUser, Role, UserStatus, utcnow
    from .security.passwords import hash_password
    from .services.accounts import normalize_email
    from .services.audit import record

    rt = build_runtime(get_settings())
    email = normalize_email(args.email or rt.settings.superadmin_email or "")
    async with rt.sessionmaker() as db:
        user = await db.scalar(select(AppUser).where(AppUser.email == email))
        if user is None:
            user = AppUser(email=email, consent_at=utcnow())
            db.add(user)
        if not user.password_hash or args.reset_password:
            user.password_hash = hash_password(_prompt_password())
        user.role, user.status = Role.SUPERADMIN, UserStatus.ACTIVE
        user.email_verified_at = user.email_verified_at or utcnow()
        user.full_name = args.name or user.full_name
        await db.flush()
        await record(db, user.id, "account.superadmin", "superadmin created from the command line", actor="user")
        await db.commit()
        print(f"superadmin ready: {email} (id {user.id}). Set HIREFINCH_SUPERADMIN_EMAIL={email} in .env.")
    await rt.close()


async def _set_password(args: argparse.Namespace) -> None:
    from .db import AppUser
    from .security.passwords import hash_password
    from .services.accounts import end_all_sessions

    rt = build_runtime(get_settings())
    user_id = await _user_id(rt, args.email)
    async with rt.sessionmaker() as db:
        user = await db.get(AppUser, user_id)
        assert user is not None
        user.password_hash, user.failed_logins, user.locked_until = hash_password(_prompt_password()), 0, None
        await end_all_sessions(db, user_id)
        await db.commit()
    print("password changed; existing sessions ended")
    await rt.close()


async def _import_env(args: argparse.Namespace) -> None:
    """Copy the SMTP / LLM / Adzuna settings from .env into one account, encrypted. Run once."""
    from .services import integrations as integ

    rt = build_runtime(get_settings())
    s, llm = rt.settings, rt.settings.llm_settings()
    user_id = await _user_id(rt, args.email)
    done = []
    async with rt.sessionmaker() as db:
        if s.email_provider == "smtp" and s.smtp_host and s.email_from and s.smtp_password:
            await integ.save(db, s, rt.box, user_id, "email",
                             {"provider": "smtp", "host": s.smtp_host, "port": s.smtp_port, "username": s.smtp_username,
                              "from_address": s.email_from, "starttls": s.smtp_starttls},
                             {"password": s.smtp_password.get_secret_value()})
            done.append("email (SMTP)")
        if llm.llm_provider == "azure_openai" and llm.azure_openai_endpoint and llm.azure_openai_api_key:
            await integ.save(db, s, rt.box, user_id, "llm",
                             {"provider": "azure_openai", "endpoint": llm.azure_openai_endpoint,
                              "deployment": llm.azure_openai_deployment, "api_version": llm.azure_openai_api_version,
                              "temperature": llm.llm_temperature},
                             {"api_key": llm.azure_openai_api_key.get_secret_value()})
            done.append("AI provider (Azure OpenAI)")
        elif llm.llm_provider == "openai_compatible" and llm.openai_model and llm.openai_api_key:
            await integ.save(db, s, rt.box, user_id, "llm",
                             {"provider": "openai_compatible", "base_url": llm.openai_base_url, "model": llm.openai_model,
                              "temperature": llm.llm_temperature},
                             {"api_key": llm.openai_api_key.get_secret_value()})
            done.append("AI provider (OpenAI-compatible)")
        if s.adzuna_app_id and s.adzuna_app_key:
            await integ.save(db, s, rt.box, user_id, "adzuna", {"app_id": s.adzuna_app_id},
                             {"app_key": s.adzuna_app_key.get_secret_value()})
            done.append("Adzuna")
        await db.commit()
    print("imported: " + (", ".join(done) if done else "nothing (no complete settings in .env)"))
    if done:
        print("The app now reads these from your encrypted settings; you can remove them from .env.")
    await rt.close()


async def _load_config(args: argparse.Namespace) -> None:
    from .services import settings_store as store

    rt = build_runtime(get_settings())
    user_id = await _user_id(rt, args.email)
    async with rt.sessionmaker() as db:
        if args.profile:
            await store.save_profile(db, user_id, Profile.model_validate(yaml.safe_load(Path(args.profile).read_text()) or {}))
            print(f"profile loaded from {args.profile}")
        if args.preferences:
            prefs = Preferences.model_validate(yaml.safe_load(Path(args.preferences).read_text()) or {})
            await store.save_preferences(db, user_id, prefs)
            print(f"preferences loaded from {args.preferences}")
        if args.policy:
            policy = AutomationPolicy.model_validate(yaml.safe_load(Path(args.policy).read_text()) or {})
            if policy.mode != "supervised" or policy.auto_send_outreach:
                sys.exit("refusing: enable automatic mode in the Automation page, where it is confirmed and audited")
            await store.save_policy(db, user_id, policy)
            print(f"policy loaded from {args.policy}")
        await db.commit()
    await rt.close()


async def _upload(args: argparse.Namespace) -> None:
    from .services.resumes import activate, store_master

    rt = build_runtime(get_settings())
    user_id = await _user_id(rt, args.email)
    path = Path(args.path)
    async with rt.sessionmaker() as db:
        master = await store_master(db, rt.settings, user_id, path.read_bytes(), path.name)
        if args.activate:
            await activate(db, user_id, master.id)
        await db.commit()
        print(json.dumps({"id": master.id, "active": master.is_active, "warnings": master.parsed.get("warnings", [])}))
    await rt.close()


async def _user_rt(rt: Runtime, email: str | None):  # noqa: ANN202
    user_id = await _user_id(rt, email)
    async with rt.sessionmaker() as db:
        return await rt.for_user(db, user_id)


async def _run(args: argparse.Namespace) -> None:
    from .workflow.pipeline import run_discovery

    rt = build_runtime(get_settings())
    report = await run_discovery(await _user_rt(rt, args.email), source_key=args.source)
    print(json.dumps({"sources": report.sources, "new_jobs": report.new_jobs, "advanced": report.advanced,
                      "errors": report.errors}, indent=2))
    await rt.close()


async def _tick(_: argparse.Namespace) -> None:
    from .scheduler import ensure_tasks, tick

    rt = build_runtime(get_settings())
    await ensure_tasks(rt)
    for line in await tick(rt):
        print(line)
    await rt.close()


async def _rescore(args: argparse.Namespace) -> None:
    from .services.jobs import rescore
    from .workflow.pipeline import advance_all

    rt = build_runtime(get_settings())
    urt = await _user_rt(rt, args.email)
    async with rt.sessionmaker() as db:
        counts = await rescore(db, urt.user_id)
        await db.commit()
    report = await advance_all(urt)
    print(json.dumps({**counts, "advanced": report.advanced, "errors": report.errors}, indent=2))
    await rt.close()


async def _regenerate(args: argparse.Namespace) -> None:
    """New resume versions with the current template, for queued jobs (or one job). Old versions stay."""
    from .db import Application, JobPosting, JobStatus, Outcome
    from .services.applications import prepare
    from .services.tailoring import generate

    rt = build_runtime(get_settings())
    urt = await _user_rt(rt, args.email)
    async with rt.sessionmaker() as db:
        query = select(JobPosting).where(JobPosting.user_id == urt.user_id, JobPosting.status == JobStatus.AWAITING_APPROVAL)
        if args.job:
            query = select(JobPosting).where(JobPosting.user_id == urt.user_id, JobPosting.id == args.job)
        for job in (await db.scalars(query)).all():
            app = await db.scalar(select(Application).where(Application.job_id == job.id))
            if app is not None and app.outcome != Outcome.PENDING:
                print(f"job {job.id}: already submitted; its resume is kept as sent")
                continue
            version = await generate(db, rt.settings, job, urt.llm, actor="user")
            if version.valid:
                await prepare(db, urt, job, actor="user")
            await db.commit()
            layout = version.report.get("layout", {})
            print(f"job {job.id} {job.company}: v{version.version_no} {'valid' if version.valid else 'INVALID'} "
                  f"{layout.get('pages')}p {layout.get('style')} -> {version.pdf_path}")
    await rt.close()


async def _recover(_: argparse.Namespace) -> None:
    from .services.applications import recover_incomplete

    rt = build_runtime(get_settings())
    async with rt.sessionmaker() as db:
        print(f"{await recover_incomplete(db)} interrupted submission(s) marked for verification")
        await db.commit()
    await rt.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="hirefinch")
    sub = parser.add_subparsers(dest="command", required=True)

    def with_email(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--email", help="account to act for (default: HIREFINCH_SUPERADMIN_EMAIL)")
        return p

    sa = sub.add_parser("create-superadmin", help="create or promote the superadmin (password is prompted)")
    sa.add_argument("--email")
    sa.add_argument("--name")
    sa.add_argument("--reset-password", action="store_true")
    with_email(sub.add_parser("set-password", help="set an account's password (prompted)"))
    with_email(sub.add_parser("import-env-integrations", help="copy SMTP/LLM/Adzuna settings from .env into an account"))
    cfg = with_email(sub.add_parser("load-config", help="load profile/preferences/policy YAML into an account"))
    cfg.add_argument("--profile")
    cfg.add_argument("--preferences")
    cfg.add_argument("--policy")
    up = with_email(sub.add_parser("upload-resume", help="store a master resume (PDF or DOCX)"))
    up.add_argument("path")
    up.add_argument("--activate", action="store_true")
    run = with_email(sub.add_parser("run", help="discover from enabled sources and advance every job once"))
    run.add_argument("--source")
    sub.add_parser("tick", help="run scheduled tasks that are due, once (all users)")
    sub.add_parser("recover", help="mark interrupted submissions for verification (all users)")
    with_email(sub.add_parser("rescore", help="re-parse and re-score jobs not yet applied to"))
    regen = with_email(sub.add_parser("regenerate-resumes", help="new resume versions for queued jobs"))
    regen.add_argument("--job", type=int, help="only this job id")
    args = parser.parse_args()
    handler = {"create-superadmin": _create_superadmin, "set-password": _set_password,
               "import-env-integrations": _import_env, "load-config": _load_config, "upload-resume": _upload,
               "run": _run, "tick": _tick, "recover": _recover, "rescore": _rescore,
               "regenerate-resumes": _regenerate}[args.command]
    asyncio.run(handler(args))


if __name__ == "__main__":
    main()
