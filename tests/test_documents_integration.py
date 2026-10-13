"""Real model and FAISS tests in a disposable PostgreSQL database, isolated from user data."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from test_parsing import docx_bytes, pdf_bytes

from nexusai.core.config import Settings
from nexusai.database.documents import chunks, documents, generations, index_state, jobs
from nexusai.documents.embedding import Embedder
from nexusai.documents.errors import DocumentError
from nexusai.documents.index import search
from nexusai.documents.service import enqueue, retry
from nexusai.documents.worker import LOCK_ID, rebuild, run_once
from nexusai.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.model]


@pytest.fixture(scope="module")
def laboratory(tmp_path_factory):
    if os.environ.get("NEXUS_RUN_MODEL_TESTS") != "1":
        pytest.skip("Set NEXUS_RUN_MODEL_TESTS=1 after downloading the pinned embedding model")
    load_dotenv()
    name = "nexusai_test_" + uuid4().hex
    admin = create_engine(os.environ["NEXUS_ADMIN_DATABASE_URL"], isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.exec_driver_sql(f"CREATE DATABASE {name}")
    database_admin = create_engine(admin.url.set(database=name))
    writer_url = make_url(os.environ["NEXUS_DATABASE_URL"]).set(database=name)
    owner_url = make_url(os.environ["NEXUS_MIGRATION_DATABASE_URL"]).set(database=name)
    engine = create_engine(writer_url)
    directory = tmp_path_factory.mktemp("documents")
    settings = Settings(
        database_url=writer_url.render_as_string(hide_password=False),
        data_dir=directory,
        model_dir=Path("artifacts/embedding").resolve(),
    )
    try:
        with database_admin.begin() as conn:
            conn.exec_driver_sql(f"REVOKE ALL ON DATABASE {name} FROM PUBLIC")
            conn.exec_driver_sql(f"GRANT CONNECT ON DATABASE {name} TO nexus_owner,nexus_writer")
            conn.exec_driver_sql("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            conn.exec_driver_sql("CREATE SCHEMA app AUTHORIZATION nexus_owner")
            conn.exec_driver_sql("GRANT USAGE ON SCHEMA app TO nexus_writer")
            conn.exec_driver_sql(
                "ALTER DEFAULT PRIVILEGES FOR ROLE nexus_owner IN SCHEMA app "
                "GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO nexus_writer"
            )
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
            env={
                **os.environ,
                "NEXUS_MIGRATION_DATABASE_URL": owner_url.render_as_string(hide_password=False),
            },
            capture_output=True,
        )
        embedder = Embedder(settings.model_dir)
        yield engine, settings, embedder
    finally:
        engine.dispose()
        database_admin.dispose()
        with admin.connect() as conn:
            conn.exec_driver_sql(f"DROP DATABASE {name} WITH (FORCE)")
        admin.dispose()


def upload(laboratory, data, filename="policy.txt", category="unclassified"):
    engine, settings, _ = laboratory
    return enqueue(engine, settings.data_dir, filename, "", category, data)


def drain(laboratory):
    engine, settings, embedder = laboratory
    for _ in range(20):
        if not run_once(engine, settings, embedder):
            return
    pytest.fail("Worker did not empty the small test queue")


def test_real_embeddings_are_normalized_semantic_and_not_truncated(laboratory):
    _, _, embedder = laboratory
    vectors = embedder.encode(
        [
            "Employees get twenty days of annual leave.",
            "Staff vacation allowance is twenty days.",
            "The database listens on port 5432.",
        ]
    )
    assert vectors.shape == (3, 384)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
    assert vectors[0] @ vectors[1] > vectors[0] @ vectors[2]
    blocks = [{"text": "annual leave policy " * 300 + "FINAL_MARKER", "locator": "paragraph:1"}]
    pieces = embedder.chunks(blocks)
    assert len(pieces) > 1
    assert pieces[-1]["text"].endswith("FINAL_MARKER")
    for piece in pieces:
        assert piece["text"] == blocks[0]["text"][piece["start"] : piece["end"]]
        assert len(embedder.load().tokenizer(piece["text"])["input_ids"]) <= 256
    with pytest.raises(DocumentError, match="embedding_input_too_long"):
        embedder.encode(["word " * 300])


def test_ingestion_all_formats_duplicate_lineage_and_filtered_search(laboratory):
    engine, settings, embedder = laboratory
    samples = [
        (b"Employees receive 20 annual leave days.", "policy.txt", "hr_policy"),
        (b"month,revenue\nSeptember,85000", "sales.csv", "financial_report"),
        (pdf_bytes(), "policy.pdf", "hr_policy"),
        (docx_bytes(), "policy.docx", "hr_policy"),
    ]
    uploaded = [upload(laboratory, *sample) for sample in samples]
    duplicate = upload(laboratory, *samples[0])
    assert duplicate["duplicate"] is True
    assert duplicate["document_id"] == uploaded[0]["document_id"]
    drain(laboratory)
    with engine.connect() as conn:
        for item in uploaded:
            record = (
                conn.execute(select(documents).where(documents.c.id == item["document_id"]))
                .mappings()
                .one()
            )
            assert record["status"] == "ready"
            pieces = conn.execute(
                select(chunks).where(chunks.c.document_id == item["document_id"])
            ).mappings()
            for piece in pieces:
                block = record["blocks"][piece["block"]]
                assert piece["text"] == block["text"][piece["start"] : piece["end"]]
    result = search(
        engine,
        settings.data_dir,
        embedder,
        "How much revenue in September?",
        1,
        [uploaded[1]["document_id"]],
        "financial_report",
    )
    assert len(result["hits"]) == 1
    assert "85000" in result["hits"][0]["text"]
    assert result["hits"][0]["document_id"] == uploaded[1]["document_id"]
    # An impossible filter must remain empty, even for a very relevant global match.
    assert not search(
        engine,
        settings.data_dir,
        embedder,
        "annual leave",
        5,
        [uploaded[1]["document_id"]],
        "hr_policy",
    )["hits"]


def test_api_upload_job_chunks_and_search(laboratory):
    engine, settings, embedder = laboratory
    with TestClient(create_app(settings)) as client:
        client.app.state.embedder = embedder
        response = client.post(
            "/documents/upload",
            files={
                "file": (
                    "../../operations.txt",
                    b"Support hours are 09:00 to 17:00 on weekdays.",
                    "text/plain",
                )
            },
        )
        assert response.status_code == 202
        item = response.json()
        drain(laboratory)
        job = client.get(f"/jobs/{item['job_id']}").json()
        assert job["status"] == "succeeded"
        rows = client.get("/documents").json()
        assert (
            next(r for r in rows if r["id"] == item["document_id"])["filename"] == "operations.txt"
        )
        response = client.get(f"/documents/{item['document_id']}/chunks")
        assert response.status_code == 200
        assert response.json()[0]["text_sha256"]
        response = client.post(
            "/documents/search",
            json={"query": "What are support hours?", "document_ids": [item["document_id"]]},
        )
        assert response.status_code == 200
        assert "09:00" in response.json()["hits"][0]["text"]
        assert client.get(f"/jobs/{uuid4()}").status_code == 404
        assert client.post(f"/jobs/{item['job_id']}/retry").status_code == 409
        assert (
            client.post(
                "/documents/upload", files={"file": ("bad.pdf", b"not a pdf", "application/pdf")}
            ).status_code
            == 422
        )


def test_failed_job_is_explicit_and_retry_is_bounded(laboratory):
    engine, _, _ = laboratory
    item = upload(laboratory, b"%PDF-malformed", "broken.pdf")
    for attempt in range(3):
        drain(laboratory)
        with engine.connect() as conn:
            job = conn.execute(select(jobs).where(jobs.c.id == item["job_id"])).mappings().one()
            assert job["status"] == "failed"
            assert job["error"] == "malformed_document"
            assert job["attempts"] == attempt + 1
        if attempt < 2:
            retry(engine, item["job_id"])
    with pytest.raises(DocumentError, match="job_not_retryable"):
        retry(engine, item["job_id"])


def test_abandoned_job_recovered_and_worker_lock_is_exclusive(laboratory):
    engine, settings, embedder = laboratory
    item = upload(laboratory, b"Resumed ingestion retains its source.", "recover.txt")
    with engine.begin() as conn:
        conn.execute(
            jobs.update().where(jobs.c.id == item["job_id"]).values(status="running", attempts=1)
        )
    with engine.connect() as lock:
        lock.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK_ID})
        try:
            assert run_once(engine, settings, embedder) is False
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
            lock.commit()
    drain(laboratory)
    with engine.connect() as conn:
        record = conn.execute(select(jobs).where(jobs.c.id == item["job_id"])).mappings().one()
        assert record["status"] == "succeeded" and record["attempts"] == 2


def test_index_corruption_fails_closed_then_rebuilds_from_persisted_vectors(laboratory):
    engine, settings, embedder = laboratory
    item = upload(laboratory, b"Backups are retained for 45 days.", "retention.txt")
    drain(laboratory)
    before = search(
        engine, settings.data_dir, embedder, "backup retention", 1, [item["document_id"]], None
    )
    path = settings.data_dir / "indexes" / f"{before['generation_id']}.faiss"
    path.write_bytes(b"corrupt")
    with pytest.raises(DocumentError, match="index_missing_or_corrupt"):
        search(engine, settings.data_dir, embedder, "backup retention", 1, [], None)
    rebuild(engine, settings)
    # A fresh model/service instance reads persisted SQL+FAISS; no in-memory index reliance.
    after = search(
        engine,
        settings.data_dir,
        Embedder(settings.model_dir),
        "backup retention",
        1,
        [item["document_id"]],
        None,
    )
    assert after["hits"][0]["id"] == before["hits"][0]["id"]
    assert after["hits"][0]["score"] == pytest.approx(before["hits"][0]["score"], abs=1e-6)
    assert after["generation_id"] != before["generation_id"]


def test_failed_publication_does_not_expose_partial_document(laboratory, monkeypatch):
    engine, settings, embedder = laboratory
    with engine.connect() as conn:
        prior = conn.execute(select(index_state.c.generation_id)).scalar_one()
        prior_count = conn.execute(select(generations.c.id)).all()
    item = upload(
        laboratory, b"This must not be searchable after a failed publication.", "failure.txt"
    )

    def fail(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("nexusai.documents.worker.publish", fail)
    drain(laboratory)
    with engine.connect() as conn:
        assert conn.execute(select(index_state.c.generation_id)).scalar_one() == prior
        assert len(conn.execute(select(generations.c.id)).all()) == len(prior_count)
        assert (
            conn.execute(
                select(documents.c.status).where(documents.c.id == item["document_id"])
            ).scalar_one()
            == "failed"
        )
        assert not conn.execute(
            select(chunks).where(chunks.c.document_id == item["document_id"])
        ).all()
    assert not search(
        engine, settings.data_dir, embedder, "failed publication", 5, [item["document_id"]], None
    )["hits"]


def test_missing_model_is_a_real_failure(laboratory):
    engine, settings, _ = laboratory
    item = upload(laboratory, b"A model is needed to embed this document.", "missing-model.txt")
    assert run_once(engine, settings, Embedder(settings.data_dir / "absent-model"))
    with engine.connect() as conn:
        result = conn.execute(select(jobs).where(jobs.c.id == item["job_id"])).mappings().one()
        assert result["status"] == "failed"
        assert result["error"] == "embedding_model_missing_or_invalid"


def test_live_http_search_survives_first_model_load_and_repeated_requests(laboratory, tmp_path):
    import socket
    import time

    import httpx2

    engine, settings, _ = laboratory
    item = upload(laboratory, b"The escalation hotline operates 24 hours per day.", "hotline.txt")
    drain(laboratory)
    with socket.socket() as listener, (tmp_path / "server.log").open("w") as log:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "nexusai.main:app",
                "--fd",
                str(listener.fileno()),
                "--no-access-log",
            ],
            pass_fds=(listener.fileno(),),
            stdout=log,
            stderr=log,
            env={
                **os.environ,
                "NEXUS_DATABASE_URL": engine.url.render_as_string(hide_password=False),
                "NEXUS_DATA_DIR": str(settings.data_dir),
                "NEXUS_MODEL_DIR": str(settings.model_dir),
                "HF_HUB_OFFLINE": "1",
            },
        )
        try:
            with httpx2.Client(base_url=f"http://127.0.0.1:{port}", timeout=20) as client:
                deadline = time.monotonic() + 20
                while True:
                    assert process.poll() is None, "Live API process exited unexpectedly"
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx2.HTTPError:
                        pass
                    assert time.monotonic() < deadline, "Live API did not become ready"
                    time.sleep(0.1)
                for _ in range(3):
                    response = client.post(
                        "/documents/search",
                        json={
                            "query": "When is the escalation hotline available?",
                            "document_ids": [item["document_id"]],
                            "k": 1,
                        },
                    )
                    assert response.status_code == 200
                    assert "24 hours" in response.json()["hits"][0]["text"]
                assert process.poll() is None
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
