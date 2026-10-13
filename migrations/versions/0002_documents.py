"""Durable ingestion jobs, source lineage, vectors and published index generations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_documents"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("blocks", JSONB, nullable=False, server_default="[]"),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("sha256", "kind"),
        sa.CheckConstraint("status IN ('queued','processing','ready','failed')"),
        schema="app",
    )
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("app.documents.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed')"),
        schema="app",
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("app.documents.id"), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("block", sa.Integer, nullable=False),
        sa.Column("locator", sa.Text, nullable=False),
        sa.Column("start", sa.Integer, nullable=False),
        sa.Column("end", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("vector", sa.LargeBinary, nullable=False),
        sa.Column("model_signature", sa.Text, nullable=False),
        schema="app",
    )
    op.create_index("ix_app_chunks_document_id", "chunks", ["document_id"], schema="app")
    op.create_table(
        "index_generations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("chunk_ids", JSONB, nullable=False),
        sa.Column("model_signature", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="app",
    )
    op.create_table(
        "index_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "generation_id",
            sa.String(36),
            sa.ForeignKey("app.index_generations.id"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1"),
        schema="app",
    )


def downgrade():
    for table in ("index_state", "index_generations", "chunks", "ingestion_jobs", "documents"):
        op.drop_table(table, schema="app")
