"""Command line.

  saathi chat        talk to the agent in the terminal (YAML schemes, nothing stored)
  saathi validate    check the scheme YAML files
  saathi seed        load YAML schemes into the database (never overwrites existing records)
  saathi coverage    schemes per state, drafts, stale and district-targeted records
  saathi sync-schemes  show (or with --apply, make) changes needed to match the YAML files
  saathi users set-role <email-or-phone> <role>
  saathi serve       run the web server
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from agents_core.llm import available_providers
from sqlalchemy import select

from .agent import build_agent
from .config import Settings, get_settings
from .schemes import SchemeDataError, load_schemes

CLI_USER = "cli-user"


async def _chat(settings: Settings, show_profile: bool) -> None:
    agent = build_agent(settings)
    print(f"Saathi ({settings.llm_settings().llm_provider}) — type in any language. 'exit' to quit.\n")
    while True:
        try:
            text = await asyncio.to_thread(input, "you> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if text.strip().lower() in {"exit", "quit"}:
            return
        if not text.strip():
            continue
        print(f"\nsaathi> {await agent.handle(CLI_USER, text)}\n")
        if show_profile:
            known = (await agent.profile(CLI_USER)).model_dump(exclude_none=True, mode="json")
            print(f"  [profile] {known}\n")


def _validate(directory: Path) -> int:
    try:
        schemes = load_schemes(directory)
    except SchemeDataError as exc:
        print(f"invalid scheme data: {exc}", file=sys.stderr)
        return 1
    drafts = [s.id for s in schemes if s.verified_on is None]
    print(f"{len(schemes)} schemes OK ({len(drafts)} unverified drafts: {', '.join(drafts) or 'none'})")
    return 0


def _sessionmaker(settings: Settings):
    from .db import create_engine, create_sessionmaker

    if settings.database_url is None:
        raise SystemExit("SAATHI_DATABASE_URL is not set")
    engine = create_engine(settings.database_url.get_secret_value())
    return engine, create_sessionmaker(engine)


async def _seed(settings: Settings, directory: Path) -> int:
    from .services.schemes import seed_schemes

    engine, sessionmaker = _sessionmaker(settings)
    try:
        async with sessionmaker() as db:
            added = await seed_schemes(db, directory)
    finally:
        await engine.dispose()
    print(f"seeded {added} new scheme(s)")
    return 0


async def _sync(settings: Settings, directory: Path, apply: bool) -> int:
    from .services.schemes import sync_schemes

    engine, sessionmaker = _sessionmaker(settings)
    try:
        async with sessionmaker() as db:
            changes = await sync_schemes(db, directory, apply=apply)
    finally:
        await engine.dispose()
    for scheme_id, action in changes:
        print(f"{action:16} {scheme_id}")
    if not changes:
        print("database already matches the scheme files")
    elif not apply:
        print(f"\n{len(changes)} change(s) not applied (dry run). Back up the database, then rerun with --apply.")
    else:
        print(f"\napplied {sum(a != 'skip (archived)' for _, a in changes)} change(s); earlier versions are kept as revisions")
    return 0


STALE_AFTER_DAYS = 183


def _coverage(directory: Path) -> int:
    """What is covered, and what needs attention, from the YAML files."""
    from collections import Counter
    from datetime import date

    try:
        schemes = load_schemes(directory)
    except SchemeDataError as exc:
        print(f"invalid scheme data: {exc}", file=sys.stderr)
        return 1
    by_area = Counter(s.state or "central" for s in schemes)
    verified = Counter(s.state or "central" for s in schemes if s.verified_on)
    print(f"{'area':42} schemes  verified")
    for area in sorted(by_area, key=lambda a: (a != "central", a)):
        print(f"{area:42} {by_area[area]:7}  {verified[area]:8}")
    print(f"{'total':42} {len(schemes):7}  {sum(verified.values()):8}\n")

    today = date.today()
    checks = {
        "drafts": [s.id for s in schemes if s.verified_on is None],
        f"stale (verified over {STALE_AFTER_DAYS} days ago)": [
            s.id for s in schemes if s.verified_on and (today - s.verified_on).days > STALE_AFTER_DAYS
        ],
        "verified without evidence entries (older records: see docs/scheme-verification-*.md)": [
            s.id for s in schemes if s.verified_on and not s.evidence
        ],
        "district-targeted": [s.id for s in schemes if any(_uses_field(r, "district") for r in s.eligibility)],
    }
    for label, ids in checks.items():
        print(f"{label}: {len(ids)}" + (f"\n  {', '.join(sorted(ids))}" if ids else ""))
    return 0


def _uses_field(rule, name: str) -> bool:
    return rule.field == name or any(_uses_field(sub, name) for sub in (rule.any or []) + (rule.all or []))


async def _set_role(settings: Settings, who: str, role: str) -> int:
    from .auth.otp import normalize_phone
    from .db import Role, User
    from .errors import BadRequest
    from .services.access import audit

    engine, sessionmaker = _sessionmaker(settings)
    try:
        async with sessionmaker() as db:
            if "@" in who:
                user = await db.scalar(select(User).where(User.email == who.strip().lower()))
            else:
                try:
                    user = await db.scalar(select(User).where(User.phone_e164 == normalize_phone(who)))
                except BadRequest as exc:
                    print(exc.message, file=sys.stderr)
                    return 1
            if user is None:
                print("no such user; they must sign in once first", file=sys.stderr)
                return 1
            user.role = Role(role)
            audit(db, None, "user.set_role_cli", "user", user.id, {"role": role})
            await db.commit()
    finally:
        await engine.dispose()
    print(f"role set to {role}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="saathi")
    sub = parser.add_subparsers(dest="command", required=True)

    chat = sub.add_parser("chat", help="chat with the agent in the terminal")
    chat.add_argument("--provider", choices=available_providers(), help="override SAATHI_LLM_PROVIDER")
    chat.add_argument("--show-profile", action="store_true", help="print what the agent has learned")

    validate = sub.add_parser("validate", help="check scheme YAML files")
    validate.add_argument("directory", nargs="?", type=Path)

    seed = sub.add_parser("seed", help="load YAML schemes into the database")
    seed.add_argument("directory", nargs="?", type=Path)

    coverage = sub.add_parser("coverage", help="scheme coverage by state, drafts and stale records")
    coverage.add_argument("directory", nargs="?", type=Path)

    sync = sub.add_parser("sync-schemes", help="update existing scheme records from the YAML files")
    sync.add_argument("directory", nargs="?", type=Path)
    sync.add_argument("--apply", action="store_true", help="make the changes (default: dry run)")

    users = sub.add_parser("users", help="manage users")
    users_sub = users.add_subparsers(dest="users_command", required=True)
    set_role = users_sub.add_parser("set-role", help="change a user's role")
    set_role.add_argument("who", help="email address or mobile number")
    set_role.add_argument("role", choices=["citizen", "helper", "admin"])

    serve = sub.add_parser("serve", help="run the web server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    settings = get_settings()

    if args.command == "chat":
        if args.provider:
            settings = settings.model_copy(update={"llm_provider": args.provider})
        asyncio.run(_chat(settings, args.show_profile))
        return 0
    if args.command == "validate":
        return _validate(args.directory or settings.schemes_dir)
    if args.command == "seed":
        return asyncio.run(_seed(settings, args.directory or settings.schemes_dir))
    if args.command == "coverage":
        return _coverage(args.directory or settings.schemes_dir)
    if args.command == "sync-schemes":
        return asyncio.run(_sync(settings, args.directory or settings.schemes_dir, args.apply))
    if args.command == "users":
        return asyncio.run(_set_role(settings, args.who, args.role))

    import uvicorn

    logging.getLogger().setLevel(logging.INFO)
    uvicorn.run("saathi.app:create_app", factory=True, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
