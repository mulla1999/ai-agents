"""multi user accounts

Revision ID: 672eb0cc7f26
Revises: 25476ac9b9a1
Create Date: 2026-10-27 17:49:44.746974
"""

from collections.abc import Sequence

import os
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '672eb0cc7f26'
down_revision: str | None = '25476ac9b9a1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OWNED = ("application", "approval_request", "automation_policy", "email_draft", "job_match", "job_posting",
         "job_source", "notification_outbox", "recruiter_contact", "resume_master", "resume_tailoring_run",
         "resume_version", "user_profile")


def upgrade() -> None:
    # 1. accounts, sessions, tokens, per-user integrations, platform settings
    op.create_table('app_user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=True),
    sa.Column('password_hash', sa.String(length=300), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('consent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failed_logins', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_app_user')),
    sa.UniqueConstraint('email', name=op.f('uq_app_user_email'))
    )
    op.create_table('platform_setting',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('config', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('secret', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_platform_setting')),
    sa.UniqueConstraint('key', name=op.f('uq_platform_setting_key'))
    )
    op.create_table('auth_token',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('purpose', sa.String(length=24), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_auth_token_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_token')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_auth_token_token_hash'))
    )
    with op.batch_alter_table('auth_token', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_auth_token_user_id'), ['user_id'], unique=False)

    op.create_table('user_integration',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('config', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('secret', sa.Text(), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_integration_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_integration')),
    sa.UniqueConstraint('user_id', 'kind', name=op.f('uq_user_integration_user_id_kind'))
    )
    with op.batch_alter_table('user_integration', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_integration_user_id'), ['user_id'], unique=False)

    op.create_table('user_session',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_session_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_session')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_user_session_token_hash'))
    )
    with op.batch_alter_table('user_session', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_session_user_id'), ['user_id'], unique=False)


    # 2. user_id columns, nullable while existing rows are adopted
    for table in (*OWNED, "audit_event"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))

    # 3. data from before accounts belongs to the superadmin (HIREFINCH_SUPERADMIN_EMAIL). The account
    #    is created without a password; set one with `hirefinch create-superadmin`.
    bind = op.get_bind()
    has_rows = any(bind.execute(sa.text(f"SELECT 1 FROM {t} LIMIT 1")).first() for t in OWNED)
    if has_rows:
        email = (os.environ.get("HIREFINCH_SUPERADMIN_EMAIL") or _env_file_value("HIREFINCH_SUPERADMIN_EMAIL")
                 or "owner@localhost.invalid").strip().lower()
        now = datetime.now(UTC)
        owner = bind.execute(sa.text("SELECT id FROM app_user WHERE email = :e"), {"e": email}).scalar()
        if owner is None:
            bind.execute(sa.text(
                "INSERT INTO app_user (email, role, status, email_verified_at, consent_at, failed_logins, created_at) "
                "VALUES (:e, 'superadmin', 'active', :n, :n, 0, :n)"), {"e": email, "n": now})
            owner = bind.execute(sa.text("SELECT id FROM app_user WHERE email = :e"), {"e": email}).scalar()
        for table in (*OWNED, "audit_event"):
            bind.execute(sa.text(f"UPDATE {table} SET user_id = :o WHERE user_id IS NULL"), {"o": owner})

    # 4. required owner, foreign keys, indexes and per-user uniqueness
    unique_single = {"automation_policy", "user_profile"}
    replaced = {"job_source": ("uq_job_source_key", ["user_id", "key"]),
                "notification_outbox": ("uq_notification_outbox_dedupe_key", ["user_id", "dedupe_key"]),
                "resume_master": ("uq_resume_master_sha256", ["user_id", "sha256"])}
    for table in (*OWNED, "audit_event"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            if table != "audit_event":
                batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
            batch_op.create_foreign_key(batch_op.f(f"fk_{table}_user_id_app_user"), "app_user", ["user_id"], ["id"],
                                        ondelete="CASCADE")
            if table in unique_single:
                batch_op.create_unique_constraint(batch_op.f(f"uq_{table}_user_id"), ["user_id"])
            else:
                batch_op.create_index(batch_op.f(f"ix_{table}_user_id"), ["user_id"], unique=False)
            if table in replaced:
                old, cols = replaced[table]
                batch_op.drop_constraint(batch_op.f(old), type_="unique")
                batch_op.create_unique_constraint(batch_op.f(f"uq_{table}_{'_'.join(cols)}"), cols)


def _env_file_value(key: str) -> str | None:
    """HIREFINCH_SUPERADMIN_EMAIL from the workspace .env when it is not exported."""
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[5] / ".env"):
        if candidate.is_file():
            for line in candidate.read_text().splitlines():
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip() or None
    return None


def downgrade() -> None:
    raise NotImplementedError("restore the pre-migration backup instead; accounts cannot be merged back into one")
