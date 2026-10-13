"""Single durable worker; session-level PostgreSQL lock prevents overlapping publication."""

import argparse
import time
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select, text

from nexusai.core.config import Settings
from nexusai.core.logging import configure_logging
from nexusai.database.documents import chunks, documents, jobs
from nexusai.database.health import check_database, create_database_engine
from nexusai.documents.embedding import SIGNATURE, Embedder
from nexusai.documents.errors import DocumentError
from nexusai.documents.index import publish
from nexusai.documents.storage import digest, parse_isolated

LOCK_ID = 730031


def run_once(engine, settings, embedder) -> bool:
    with engine.connect() as conn:
        locked = conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}
        ).scalar_one()
        conn.commit()
        if not locked:
            return False
        try:
            # No previous worker holds the lock, so any running job is abandoned.
            abandoned = (
                conn.execute(select(jobs).where(jobs.c.status == "running")).mappings().all()
            )
            for job in abandoned:
                status = "queued" if job["attempts"] < 3 else "failed"
                conn.execute(
                    jobs.update()
                    .where(jobs.c.id == job["id"])
                    .values(status=status, error="worker_interrupted", updated_at=func.now())
                )
                conn.execute(
                    documents.update()
                    .where(documents.c.id == job["document_id"])
                    .values(status=status)
                )
            job = (
                conn.execute(
                    select(jobs)
                    .where(jobs.c.status == "queued")
                    .order_by(jobs.c.created_at, jobs.c.id)
                    .limit(1)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if job is None:
                conn.commit()
                return False
            document = conn.execute(select(documents).where(documents.c.id == job["document_id"]))
            document = document.mappings().one()
            conn.execute(
                jobs.update()
                .where(jobs.c.id == job["id"])
                .values(
                    status="running",
                    attempts=jobs.c.attempts + 1,
                    error=None,
                    updated_at=func.now(),
                )
            )
            conn.execute(
                documents.update()
                .where(documents.c.id == document["id"])
                .values(status="processing")
            )
            conn.commit()
            try:
                path = settings.data_dir / "uploads" / f"{document['id']}.{document['kind']}"
                if digest(path.read_bytes()) != document["sha256"]:
                    raise DocumentError("source_checksum_mismatch")
                blocks = parse_isolated(path, document["kind"])
                pieces = embedder.chunks(blocks)
                if not pieces:
                    raise DocumentError("no_extractable_chunks")
                vectors = embedder.encode([piece["text"] for piece in pieces])
                conn.execute(chunks.delete().where(chunks.c.document_id == document["id"]))
                conn.execute(
                    chunks.insert(),
                    [
                        dict(
                            piece,
                            id=str(uuid5(NAMESPACE_URL, f"{document['id']}:{ordinal}")),
                            document_id=document["id"],
                            ordinal=ordinal,
                            vector=vectors[ordinal].tobytes(),
                            model_signature=SIGNATURE,
                        )
                        for ordinal, piece in enumerate(pieces)
                    ],
                )
                conn.execute(
                    documents.update()
                    .where(documents.c.id == document["id"])
                    .values(blocks=blocks, chunk_count=len(pieces))
                )
                publish(conn, settings.data_dir, document["id"])
                conn.execute(
                    documents.update()
                    .where(documents.c.id == document["id"])
                    .values(status="ready")
                )
                conn.execute(
                    jobs.update()
                    .where(jobs.c.id == job["id"])
                    .values(status="succeeded", updated_at=func.now())
                )
                conn.commit()
            except Exception as error:
                conn.rollback()
                code = error.code if isinstance(error, DocumentError) else "processing_failed"
                conn.execute(
                    jobs.update()
                    .where(jobs.c.id == job["id"])
                    .values(status="failed", error=code, updated_at=func.now())
                )
                conn.execute(
                    documents.update()
                    .where(documents.c.id == document["id"])
                    .values(status="failed")
                )
                conn.commit()
                configure_logging().error("ingestion failed", extra={"event": code})
            return True
        finally:
            conn.rollback()
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
            conn.commit()


def rebuild(engine, settings):
    with engine.connect() as conn:
        if not conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}
        ).scalar_one():
            raise DocumentError("worker_busy", 409)
        conn.commit()
        try:
            identifier = publish(conn, settings.data_dir)
            conn.commit()
            return identifier
        finally:
            conn.rollback()
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
            conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--rebuild-index", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    engine = create_database_engine(settings)
    if check_database(engine) != "ready":
        raise SystemExit("Database not ready; apply migrations before starting the worker")
    embedder = Embedder(settings.model_dir)
    try:
        if args.rebuild_index:
            print(rebuild(engine, settings))
            return
        while True:
            processed = run_once(engine, settings, embedder)
            if args.once:
                return
            if not processed:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
