"""Stage 0: database extensions and worker heartbeat, no library records yet."""

import sqlalchemy as sa
from alembic import op

revision = "0001_runtime"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "runtime_heartbeats",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("role", sa.String(32), nullable=False, unique=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("runtime_heartbeats")
    # Extensions are shared database capabilities; never drop them on rollback.
