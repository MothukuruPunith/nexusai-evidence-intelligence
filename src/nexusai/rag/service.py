from time import perf_counter

from sqlalchemy import select, text

from nexusai.database.documents import chunks, documents
from nexusai.documents.errors import DocumentError
from nexusai.documents.index import search
from nexusai.documents.storage import digest
from nexusai.rag.generator import PROMPT_VERSION, context_for
from nexusai.rag.schemas import Answer, Citation

LOCK_ID = 730034


def source_chunk(engine, chunk_id: str) -> dict:
    with engine.connect() as conn:
        row = (
            conn.execute(
                select(
                    chunks.c.id,
                    chunks.c.document_id,
                    chunks.c.block,
                    chunks.c.locator,
                    chunks.c.start,
                    chunks.c.end,
                    chunks.c.text,
                    documents.c.sha256,
                    documents.c.filename,
                    documents.c.blocks,
                )
                .join(documents)
                .where(chunks.c.id == chunk_id, documents.c.status == "ready")
            )
            .mappings()
            .first()
        )
    if row is None:
        raise DocumentError("citation_not_found", 404)
    try:
        block = row["blocks"][row["block"]]
        if (
            row["start"] < 0
            or row["end"] <= row["start"]
            or row["end"] > len(block["text"])
            or block["text"][row["start"] : row["end"]] != row["text"]
            or block["locator"] != row["locator"]
        ):
            raise ValueError("invalid span")
    except (KeyError, IndexError, TypeError, ValueError):
        raise DocumentError("citation_source_invalid", 503) from None
    return {k: v for k, v in row.items() if k != "blocks"}


def citation_for(row, quote: str) -> Citation:
    offset = row["text"].find(quote)
    if not quote.strip() or offset < 0:
        raise DocumentError("citation_quote_invalid", 503)
    return Citation(
        chunk_id=row["id"],
        document_id=row["document_id"],
        document_sha256=row["sha256"],
        chunk_sha256=digest(row["text"].encode()),
        filename=row["filename"],
        locator=row["locator"],
        block=row["block"],
        start=row["start"] + offset,
        end=row["start"] + offset + len(quote),
        quote=quote,
        url=f"/rag/citations/{row['id']}",
    )


def answer(engine, settings, embedder, generator, body, request_id):
    started = perf_counter()
    # One query at a time across API workers using the same database. Do not queue model calls.
    with engine.connect() as guard:
        acquired = guard.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}).scalar()
        if not acquired:
            raise DocumentError("generation_busy", 503)
        try:
            return _answer(engine, settings, embedder, generator, body, request_id, started)
        finally:
            guard.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})


def _answer(engine, settings, embedder, generator, body, request_id, started):
    result = search(
        engine,
        settings.data_dir,
        embedder,
        body.query,
        body.k,
        [str(v) for v in body.document_ids],
        body.category,
    )
    messages, sources, truncated = context_for(body.query, result["hits"])
    citations = []
    manifest = {}
    reason = "no_retrieved_evidence"
    if sources:
        draft, manifest = generator.generate(messages)
        reason = "model_abstained"
        for selection in draft.selections:
            source = next((s for s in sources if s["source"] == selection.source), None)
            if (
                source is None
                or not selection.quote.strip()
                or selection.quote not in source["text"]
            ):
                # Reject the entire draft, rather than returning a partly invalid answer.
                citations = []
                reason = "invalid_citation"
                break
            hit = result["hits"][int(selection.source[1:]) - 1]
            row = source_chunk(engine, hit["id"])
            if row["sha256"] != hit["sha256"] or row["text"] != hit["text"]:
                raise DocumentError("citation_source_changed", 503)
            citation = citation_for(row, selection.quote)
            if citation not in citations:
                citations.append(citation)
            reason = "exact_quotes_verified"
    rendered = "I could not return a source-verified answer from the selected documents."
    if citations:
        rendered = "Source excerpts:\n" + "\n".join(
            f'[{i}] "{c.quote}"' for i, c in enumerate(citations, 1)
        )
    return Answer(
        request_id=request_id,
        status="EXTRACTIVE" if citations else "ABSTAINED",
        answer=rendered,
        citations=citations,
        generation_id=result["generation_id"],
        model=manifest.get("model"),
        model_digest=manifest.get("digest"),
        prompt_version=PROMPT_VERSION,
        reason=reason,
        retrieved=len(result["hits"]),
        context_sources=len(sources),
        context_truncated=truncated,
        duration_ms=round((perf_counter() - started) * 1000, 2),
    )
