from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from nexusai.database.documents import chunks, documents, generations, index_state, jobs
from nexusai.documents.errors import DocumentError
from nexusai.documents.index import search
from nexusai.documents.parser import MAX_BYTES
from nexusai.documents.service import enqueue, retry
from nexusai.documents.storage import digest

Category = Literal[
    "unclassified",
    "financial_report",
    "invoice",
    "contract",
    "hr_policy",
    "business_proposal",
    "technical_documentation",
]
router = APIRouter(tags=["documents"])


class UploadResult(BaseModel):
    document_id: UUID
    job_id: UUID
    duplicate: bool


class DocumentRecord(BaseModel):
    id: UUID
    sha256: str
    filename: str
    kind: str
    category: Category
    status: str
    chunk_count: int
    created_at: datetime


class JobRecord(BaseModel):
    id: UUID
    document_id: UUID
    status: str
    attempts: int
    error: str | None
    created_at: datetime
    updated_at: datetime


class RetryResult(BaseModel):
    job_id: UUID
    status: str


class ChunkRecord(BaseModel):
    id: UUID
    document_id: UUID
    block: int
    locator: str
    start: int
    end: int
    text: str
    text_sha256: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    k: int = Field(default=5, ge=1, le=20)
    document_ids: list[UUID] = Field(default_factory=list, max_length=200)
    category: Category | None = None


class SearchHit(BaseModel):
    id: UUID
    document_id: UUID
    locator: str
    start: int
    end: int
    text: str
    filename: str
    sha256: str
    category: Category
    score: float


class SearchResult(BaseModel):
    generation_id: UUID | None
    hits: list[SearchHit]


class IndexStatus(BaseModel):
    generation_id: UUID | None
    chunk_count: int
    model_signature: str | None


def engine_for(request: Request):
    engine = request.app.state.engine
    if engine is None:
        raise DocumentError("database_not_configured", 503)
    return engine


@router.post("/documents/upload", response_model=UploadResult, status_code=202)
async def upload(
    request: Request,
    file: Annotated[UploadFile, File()],
    category: Annotated[Category, Form()] = "unclassified",
):
    try:
        data = await file.read(MAX_BYTES + 1)
        return await run_in_threadpool(
            enqueue,
            engine_for(request),
            request.app.state.settings.data_dir,
            file.filename or "",
            file.content_type or "",
            category,
            data,
        )
    finally:
        await file.close()


@router.get("/documents", response_model=list[DocumentRecord])
def list_documents(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    with engine_for(request).connect() as conn:
        return list(
            conn.execute(
                select(*[c for c in documents.c if c.name != "blocks"])
                .order_by(documents.c.created_at, documents.c.id)
                .offset(offset)
                .limit(limit)
            ).mappings()
        )


@router.get("/documents/{document_id}/chunks", response_model=list[ChunkRecord])
def document_chunks(
    document_id: UUID,
    request: Request,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    with engine_for(request).connect() as conn:
        document = conn.execute(
            select(documents.c.status).where(documents.c.id == str(document_id))
        ).scalar_one_or_none()
        if document is None:
            raise DocumentError("document_not_found", 404)
        if document != "ready":
            raise DocumentError("document_not_ready", 409)
        rows = conn.execute(
            select(*[c for c in chunks.c if c.name not in {"vector", "model_signature", "ordinal"}])
            .where(chunks.c.document_id == str(document_id))
            .order_by(chunks.c.ordinal)
            .offset(offset)
            .limit(limit)
        ).mappings()
        return [{**row, "text_sha256": digest(row["text"].encode())} for row in rows]


@router.get("/jobs/{job_id}", response_model=JobRecord)
def get_job(job_id: UUID, request: Request):
    with engine_for(request).connect() as conn:
        result = conn.execute(select(jobs).where(jobs.c.id == str(job_id))).mappings().first()
        if result is None:
            raise DocumentError("job_not_found", 404)
        return result


@router.post("/jobs/{job_id}/retry", response_model=RetryResult, status_code=202)
def retry_job(job_id: UUID, request: Request):
    return retry(engine_for(request), str(job_id))


@router.get("/index/status", response_model=IndexStatus)
def status(request: Request):
    with engine_for(request).connect() as conn:
        generation = conn.execute(select(generations).join(index_state)).mappings().first()
        return {
            "generation_id": generation["id"] if generation else None,
            "chunk_count": len(generation["chunk_ids"]) if generation else 0,
            "model_signature": generation["model_signature"] if generation else None,
        }


@router.post("/documents/search", response_model=SearchResult)
def search_documents(body: SearchRequest, request: Request):
    return search(
        engine_for(request),
        request.app.state.settings.data_dir,
        request.app.state.embedder,
        body.query,
        body.k,
        [str(value) for value in body.document_ids],
        body.category,
    )
