import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData(schema="app")
documents = sa.Table(
    "documents",
    metadata,
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
)
jobs = sa.Table(
    "ingestion_jobs",
    metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("document_id", sa.ForeignKey("app.documents.id"), nullable=False, unique=True),
    sa.Column("status", sa.String(20), nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("error", sa.String(100)),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.CheckConstraint("status IN ('queued','running','succeeded','failed')"),
)
chunks = sa.Table(
    "chunks",
    metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("document_id", sa.ForeignKey("app.documents.id"), nullable=False, index=True),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("block", sa.Integer, nullable=False),
    sa.Column("locator", sa.Text, nullable=False),
    sa.Column("start", sa.Integer, nullable=False),
    sa.Column("end", sa.Integer, nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("vector", sa.LargeBinary, nullable=False),
    sa.Column("model_signature", sa.Text, nullable=False),
)
generations = sa.Table(
    "index_generations",
    metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("sha256", sa.String(64), nullable=False),
    sa.Column("chunk_ids", JSONB, nullable=False),
    sa.Column("model_signature", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)
index_state = sa.Table(
    "index_state",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("generation_id", sa.ForeignKey("app.index_generations.id"), nullable=False),
    sa.CheckConstraint("id = 1"),
)
