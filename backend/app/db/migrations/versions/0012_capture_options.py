"""Explicit capture context, preparation and checked-example preferences."""

import sqlalchemy as sa
from alembic import op

revision = "0012_capture_options"
down_revision = "0011_original_removal"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "documents", sa.Column("processing_options", sa.JSON(), nullable=False, server_default="{}")
    )


def downgrade():
    op.drop_column("documents", "processing_options")
