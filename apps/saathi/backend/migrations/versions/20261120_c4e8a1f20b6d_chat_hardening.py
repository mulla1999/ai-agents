"""chat hardening: per-citizen chat lease, WhatsApp de-duplication, consent prompt time

Revision ID: c4e8a1f20b6d
Revises: 031d471fee4c
Create Date: 2026-11-20 10:00:00.000000

Additive only (two new tables, one nullable column, one index), so it is safe to apply to a live
database and to roll back.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a1f20b6d"
down_revision: str | None = "031d471fee4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_locks",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("token", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_chat_locks")),
    )
    op.create_table(
        "whatsapp_inbound",
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("message_id", name=op.f("pk_whatsapp_inbound")),
    )
    op.create_index(op.f("ix_whatsapp_inbound_received_at"), "whatsapp_inbound", ["received_at"], unique=False)
    op.add_column("citizens", sa.Column("consent_prompted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_messages_role_created", "messages", ["role", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_messages_role_created", table_name="messages")
    op.drop_column("citizens", "consent_prompted_at")
    op.drop_index(op.f("ix_whatsapp_inbound_received_at"), table_name="whatsapp_inbound")
    op.drop_table("whatsapp_inbound")
    op.drop_table("chat_locks")
