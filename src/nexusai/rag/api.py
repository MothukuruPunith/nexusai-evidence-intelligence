from uuid import UUID

from fastapi import APIRouter, Request

from nexusai.documents.api import engine_for
from nexusai.rag.schemas import Answer, Citation, Query
from nexusai.rag.service import answer, citation_for, source_chunk

router = APIRouter(tags=["rag"])


@router.post("/rag/query", response_model=Answer)
def rag_query(body: Query, request: Request):
    state = request.app.state
    return answer(
        engine_for(request),
        state.settings,
        state.embedder,
        state.generator,
        body,
        request.state.request_id,
    )


@router.get("/rag/citations/{chunk_id}", response_model=Citation)
def resolve_citation(chunk_id: UUID, request: Request):
    row = source_chunk(engine_for(request), str(chunk_id))
    return citation_for(row, row["text"])
