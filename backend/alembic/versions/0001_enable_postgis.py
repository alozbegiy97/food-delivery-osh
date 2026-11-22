"""Enable the PostGIS extension.

Stage 1 baseline: no domain tables yet (they are created in Stage 2).
The database containers do not run the image's own PostGIS init scripts,
so this migration is the single place where the extension is installed.

Revision ID: 0001_enable_postgis
Revises:
Create Date: 2026-11-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_enable_postgis"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS postgis")
