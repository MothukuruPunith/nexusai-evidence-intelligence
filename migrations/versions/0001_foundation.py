"""Establish the application schema marker. Domain tables arrive with their features."""

import sqlalchemy as sa
from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_metadata",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        schema="app",
    )
    # Runtime connections can inspect, but must never mutate migration history.
    op.execute("REVOKE INSERT,UPDATE,DELETE ON app.alembic_version FROM nexus_writer")


def downgrade() -> None:
    op.drop_table("system_metadata", schema="app")
