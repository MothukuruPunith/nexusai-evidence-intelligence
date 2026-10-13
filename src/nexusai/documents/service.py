from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from nexusai.database.documents import documents, jobs
from nexusai.documents.errors import DocumentError
from nexusai.documents.parser import validate_upload
from nexusai.documents.storage import atomic_write, digest


def enqueue(engine, data_dir: Path, filename: str, content_type: str, category: str, data: bytes):
    kind = validate_upload(data, filename, content_type)
    content_hash = digest(data)
    identifier, job_id = str(uuid4()), str(uuid4())
    safe_name = filename.replace("\\", "/").split("/")[-1]
    safe_name = "".join(c for c in safe_name if ord(c) >= 32)[:255] or f"document.{kind}"
    path = data_dir / "uploads" / f"{identifier}.{kind}"

    def existing(conn):
        return (
            conn.execute(
                select(documents.c.id.label("document_id"), jobs.c.id.label("job_id"))
                .join(jobs)
                .where(documents.c.sha256 == content_hash, documents.c.kind == kind)
            )
            .mappings()
            .first()
        )

    with engine.connect() as conn:
        duplicate = existing(conn)
        if duplicate:
            return {**duplicate, "duplicate": True}
    atomic_write(path, data)
    try:
        with engine.begin() as conn:
            # Capacity is protected across concurrent uploads; the local corpus stays bounded.
            conn.exec_driver_sql("SELECT pg_advisory_xact_lock(730032)")
            if conn.execute(select(func.count()).select_from(documents)).scalar_one() >= 200:
                raise DocumentError("document_capacity", 409)
            conn.execute(
                documents.insert().values(
                    id=identifier,
                    sha256=content_hash,
                    filename=safe_name,
                    kind=kind,
                    category=category,
                    status="queued",
                )
            )
            conn.execute(jobs.insert().values(id=job_id, document_id=identifier, status="queued"))
    except IntegrityError:
        path.unlink(missing_ok=True)
        with engine.connect() as conn:
            duplicate = existing(conn)
            if duplicate:
                return {**duplicate, "duplicate": True}
        raise
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"document_id": identifier, "job_id": job_id, "duplicate": False}


def retry(engine, job_id: str):
    with engine.begin() as conn:
        job = (
            conn.execute(select(jobs).where(jobs.c.id == job_id).with_for_update())
            .mappings()
            .first()
        )
        if job is None:
            raise DocumentError("job_not_found", 404)
        if job["status"] != "failed" or job["attempts"] >= 3:
            raise DocumentError("job_not_retryable", 409)
        conn.execute(
            jobs.update()
            .where(jobs.c.id == job_id)
            .values(status="queued", error=None, updated_at=func.now())
        )
        conn.execute(
            documents.update().where(documents.c.id == job["document_id"]).values(status="queued")
        )
    return {"job_id": job_id, "status": "queued"}
