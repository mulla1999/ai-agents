"""scheme applies_to: person-level or household-level schemes

Revision ID: d9f3b2c71e04
Revises: c4e8a1f20b6d
Create Date: 2026-11-20 14:00:00.000000

Adds one column with a default, then marks the seeded household schemes. Only the `applies_to`
value of those ids is touched; no other scheme data changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9f3b2c71e04"
down_revision: str | None = "c4e8a1f20b6d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOUSEHOLD_SCHEMES = ("pm-kisan", "pmay-g", "pm-kmy", "pm-vishwakarma")


def upgrade() -> None:
    op.add_column(
        "schemes", sa.Column("applies_to", sa.String(length=16), server_default="person", nullable=False)
    )
    schemes = sa.table("schemes", sa.column("id", sa.String), sa.column("applies_to", sa.String))
    op.execute(schemes.update().where(schemes.c.id.in_(HOUSEHOLD_SCHEMES)).values(applies_to="household"))


def downgrade() -> None:
    op.drop_column("schemes", "applies_to")
