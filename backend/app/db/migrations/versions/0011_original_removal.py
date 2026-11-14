"""Keep a durable tombstone for explicitly removed original files."""

import sqlalchemy as sa
from alembic import op

revision = "0011_original_removal"
down_revision = "0010_operations"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assets", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("assets", "purged_at")
