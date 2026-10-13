from pathlib import Path
from uuid import uuid4

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from nexusai.database.documents import chunks, documents, generations, index_state
from nexusai.documents import native
from nexusai.documents.embedding import SIGNATURE
from nexusai.documents.errors import DocumentError
from nexusai.documents.storage import atomic_write, digest

MAX_CHUNKS = 10_000


def publish(conn, data_dir: Path, pending_document: str | None = None) -> str:
    """Caller holds the exclusive worker lock. File durable first; SQL pointer published last."""
    allowed = documents.c.status == "ready"
    if pending_document:
        allowed = allowed | (documents.c.id == pending_document)
    rows = conn.execute(
        select(chunks.c.id, chunks.c.vector, chunks.c.model_signature)
        .join(documents)
        .where(allowed)
        .order_by(chunks.c.id)
        .limit(MAX_CHUNKS + 1)
    ).all()
    if len(rows) > MAX_CHUNKS:
        raise DocumentError("corpus_chunk_capacity")
    if any(row.model_signature != SIGNATURE for row in rows):
        raise DocumentError("embedding_revision_mismatch", 503)
    vectors = np.empty((0, 384), dtype="float32")
    if rows:
        vectors = np.stack([np.frombuffer(row.vector, dtype="float32") for row in rows])
        if vectors.shape != (len(rows), 384) or not np.isfinite(vectors).all():
            raise DocumentError("invalid_stored_vectors", 503)
    payload = native.build(vectors)
    identifier = str(uuid4())
    atomic_write(data_dir / "indexes" / f"{identifier}.faiss", payload)
    conn.execute(
        generations.insert().values(
            id=identifier,
            sha256=digest(payload),
            chunk_ids=[row.id for row in rows],
            model_signature=SIGNATURE,
        )
    )
    conn.execute(
        insert(index_state)
        .values(id=1, generation_id=identifier)
        .on_conflict_do_update(
            index_elements=[index_state.c.id], set_={"generation_id": identifier}
        )
    )
    return identifier


def search(
    engine,
    data_dir: Path,
    embedder,
    query: str,
    k: int,
    document_ids: list[str],
    category: str | None,
) -> dict:
    with engine.connect() as conn:
        generation = conn.execute(select(generations).join(index_state)).mappings().first()
        if generation is None:
            return {"generation_id": None, "hits": []}
        if generation["model_signature"] != SIGNATURE:
            raise DocumentError("embedding_revision_mismatch", 503)
        selected = select(
            chunks.c.id,
            chunks.c.document_id,
            chunks.c.locator,
            chunks.c.start,
            chunks.c.end,
            chunks.c.text,
            documents.c.filename,
            documents.c.sha256,
            documents.c.category,
        )
        selected = selected.join(documents).where(documents.c.status == "ready")
        if document_ids:
            selected = selected.where(documents.c.id.in_(document_ids))
        if category:
            selected = selected.where(documents.c.category == category)
        rows = {row["id"]: dict(row) for row in conn.execute(selected).mappings()}
    try:
        payload = (data_dir / "indexes" / f"{generation['id']}.faiss").read_bytes()
        if digest(payload) != generation["sha256"]:
            raise ValueError("checksum mismatch")
    except (OSError, ValueError, RuntimeError):
        raise DocumentError("index_missing_or_corrupt", 503) from None
    # Filter the candidate universe before ranking; post-filtering global top-k loses recall.
    positions = [i for i, identifier in enumerate(generation["chunk_ids"]) if identifier in rows]
    if not positions:
        return {"generation_id": generation["id"], "hits": []}
    scores, ranks = native.nearest(
        payload, positions, embedder.encode([query]), k, len(generation["chunk_ids"])
    )
    hits = []
    for score, rank in zip(scores, ranks, strict=True):
        row = rows[generation["chunk_ids"][positions[int(rank)]]]
        hits.append({**row, "score": float(score)})
    return {"generation_id": generation["id"], "hits": hits}
