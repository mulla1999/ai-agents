"""store file locations relative to the data and artifacts folders

Revision ID: 8d2f1c4b7a90
Revises: cfeabb100e68
Create Date: 2026-11-01 23:50:00

Data only (the columns stay strings): absolute paths under this install's data_dir / artifacts_dir
become "data:..." / "artifacts:..." (see hirefinch.db.paths), so moving the install no longer breaks
them. A path from before the job-agent → hirefinch folder rename is mapped to the current folders too.
Downgrade writes full paths back.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hirefinch.config import Settings
from hirefinch.db import paths

revision: str = '8d2f1c4b7a90'
down_revision: str | None = 'cfeabb100e68'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = [("resume_master", "file_path"), ("resume_version", "folder"), ("resume_version", "docx_path"),
           ("resume_version", "pdf_path"), ("application", "submitted_file_path")]


def _convert(fn) -> None:  # noqa: ANN001
    settings = Settings()
    paths.configure(settings.data_dir, settings.artifacts_dir)
    bind = op.get_bind()
    for table, column in COLUMNS:
        rows = bind.execute(sa.text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")).all()
        for row_id, value in rows:
            new = fn(value)
            if new != value:
                bind.execute(sa.text(f"UPDATE {table} SET {column} = :v WHERE id = :id"), {"v": new, "id": row_id})


def upgrade() -> None:
    _convert(lambda v: paths.to_stored(v.replace("/apps/job-agent/", "/apps/hirefinch/")))


def downgrade() -> None:
    _convert(paths.from_stored)
