"""archive old master resumes instead of deleting them when tailored resumes depend on them

Revision ID: 4b1e9a7c3d25
Revises: 8d2f1c4b7a90
Create Date: 2026-11-02 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '4b1e9a7c3d25'
down_revision: str | None = '8d2f1c4b7a90'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('resume_master') as batch:
        batch.add_column(sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('resume_master') as batch:
        batch.drop_column('archived_at')
