"""Real PostgreSQL/embedding tests. Only the explicit LLM test needs Ollama."""

# ruff: noqa: F811

import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from test_documents_integration import drain, laboratory, upload  # noqa: F401

from nexusai.database.documents import chunks
from nexusai.main import create_app
from nexusai.rag.generator import MODEL
from nexusai.rag.schemas import Draft
from nexusai.rag.service import LOCK_ID

pytestmark = [pytest.mark.integration, pytest.mark.model]


@pytest.fixture
def policy(laboratory):
    item = upload(laboratory, b"Permanent staff receive 23 days of annual leave.", "rag-policy.txt")
    drain(laboratory)
    return item


def test_real_retrieval_and_resolvable_citations(laboratory, policy):
    engine, settings, embedder = laboratory
    draft = Draft(selections=[{"source": "S1", "quote": "23 days of annual leave."}])
    with TestClient(create_app(settings)) as client:
        client.app.state.embedder = embedder
        client.app.state.generator = SimpleNamespace(generate=lambda _: (draft, {"model": MODEL}))
        response = client.post(
            "/rag/query",
            json={"query": "How many annual leave days?", "document_ids": [policy["document_id"]]},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "EXTRACTIVE"
        citation = result["citations"][0]
        resolved = client.get(citation["url"])
        assert resolved.status_code == 200
        source = resolved.json()
        offset = citation["start"] - source["start"]
        assert source["quote"][offset : offset + len(citation["quote"])] == citation["quote"]
        assert source["document_sha256"] == citation["document_sha256"]
        assert source["chunk_sha256"] == citation["chunk_sha256"]
        assert result["support_assessment"] == "NOT_ASSESSED"
        with engine.connect() as lock:
            lock.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
            try:
                busy = client.post("/rag/query", json={"query": "leave days"})
                assert busy.status_code == 503
                assert busy.json()["error"] == "generation_busy"
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
        # Reject corrupted stored spans, even though the chunk ID is genuine.
        with engine.begin() as conn:
            original = conn.execute(
                select(chunks.c.start).where(chunks.c.id == citation["chunk_id"])
            ).scalar_one()
            conn.execute(
                chunks.update().where(chunks.c.id == citation["chunk_id"]).values(start=9999)
            )
        try:
            broken = client.get(citation["url"])
            assert broken.status_code == 503
            assert broken.json()["error"] == "citation_source_invalid"
        finally:
            with engine.begin() as conn:
                conn.execute(
                    chunks.update()
                    .where(chunks.c.id == citation["chunk_id"])
                    .values(start=original)
                )


@pytest.mark.llm
def test_real_local_llm_answer_and_abstention(laboratory, policy):
    if os.environ.get("NEXUS_RUN_LLM_TESTS") != "1":
        pytest.skip("Set NEXUS_RUN_LLM_TESTS=1 after local Qwen setup")
    _, settings, embedder = laboratory
    with TestClient(create_app(settings)) as client:
        client.app.state.embedder = embedder
        response = client.post(
            "/rag/query",
            json={
                "query": "How many annual leave days do permanent staff receive?",
                "document_ids": [policy["document_id"]],
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "EXTRACTIVE", result
        assert "23" in result["answer"]
        assert result["model"] == MODEL
        assert len(result["model_digest"]) == 64
        for citation in result["citations"]:
            assert citation["quote"] in client.get(citation["url"]).json()["quote"]
        missing = client.post(
            "/rag/query",
            json={
                "query": "What is the CEO's favourite colour?",
                "document_ids": [policy["document_id"]],
            },
        )
        assert missing.status_code == 200, missing.text
        assert missing.json()["status"] == "ABSTAINED", missing.json()
