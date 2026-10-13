# Phase 2 validation — 13 October 2026

Historical record: **Phase 2 local validation gate passed.** Current Phase 3 results are in [PHASE-3-VALIDATION.md](PHASE-3-VALIDATION.md).

## Executed successfully

- Python 3.11.17 in an isolated workspace on macOS arm64; existing system Python unchanged.
- uv 0.13.0 resolved and locked dependencies in `uv.lock`. A second empty virtual environment installed successfully with `uv sync --locked` using cached downloads.
- Docker Engine 29.1.3 ran a newly created PostgreSQL container and named data volume. PostgreSQL reports **17.11 (Debian 17.11-1.pgdg12+2)**.
- PostgreSQL image digest is pinned in Compose: `sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826`.
- Bootstrap provisioned the owner, writer and analytics-reader roles. Alembic applied `0001_foundation`. Repeating bootstrap and upgrading to the already-current migration succeeded.
- **34 tests passed, zero skipped: 16 unit/API/configuration tests and 18 real PostgreSQL integration cases.** The final pytest run reported 0.40 seconds. See [JUnit results](test-results.xml); this is test-suite duration, not an application latency benchmark.
- The database allowed authorized reads/writes and rejected analytics writes, DDL, temporary tables, application-table reads, role switching, server file reads and program execution. Negative permission tests disabled the reader's default read-only setting before attempting prohibited operations, verifying ACL enforcement independently of that default.
- Newly created analytical tables and functions were inaccessible to the reader until explicitly granted. The application writer could not modify migration history. Temporary test tables were cleaned up.
- Database restart retained the migration revision and restored API readiness. Recreating the container with the pinned image also retained its named-volume data, and all 34 tests passed again.
- Live HTTP smoke checks: `/health/live`, `/docs`, `/openapi.json` and database-backed `/health` returned HTTP 200. Earlier, with PostgreSQL stopped, `/health` correctly returned HTTP 503 rather than reporting success.
- Ruff lint and formatting checks passed. Source distribution and wheel packaging succeeded during foundation setup; inspected archives excluded local credentials and runtime directories.
- `.env`, local environment directories and runtime data are ignored by Git. Credential generation is tested for private file permissions and refusal to overwrite existing credentials.

## Scope limits

- Migration downgrade/rollback has not been exercised. Upgrade from an empty database and repeat upgrade were verified.
- GitHub-hosted CI is configured but has not run remotely. Local validation does not claim a remote CI result.
- Container deployment currently covers PostgreSQL only. Full application packaging is a later phase.
- The analytics role is not an unrestricted SQL sandbox. Approved query templates, tool budgets and agent controls remain Phase 7 work.
- RAG, ML, DL, agents, document ingestion and Streamlit remain future phases. There are no model-quality benchmarks yet.

## Environment issue resolved

The initial session could not launch the stopped Docker engine. A native PostgreSQL fallback was blocked by sandbox shared-memory restrictions. After the user started Docker Desktop and socket access was renewed, the tests above ran against genuine containerized PostgreSQL. No permission result was replaced by a SQLite test or mocked database success.

## Reproduce on this machine

Run from the repository root with Docker Desktop running. Local credentials already exist in `.env`.

```sh
docker compose up -d --wait db
.venv/bin/python scripts/bootstrap_database.py
.venv/bin/alembic upgrade head
NEXUS_RUN_DB_TESTS=1 .venv/bin/pytest -q --junitxml=docs/test-results.xml
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

For a fresh checkout, follow README setup rather than assuming `.env` or `.venv` exists. Test reports are replaced when the test command runs; update this document if subsequent results differ.
