# Phase 2: understanding the foundation

## What each component does

FastAPI defines the HTTP contract. Pydantic Settings loads configuration and masks database secrets in ordinary object representations. An application factory lets tests create isolated instances. The lifespan context owns database pools and disposes them at shutdown; creating an app does not create schema tables automatically.

PostgreSQL persists application state. Four roles separate one-time provisioning, migrations, runtime writes, and analytics reads. The reader's default read-only setting is useful but can be changed by that reader: database ACLs are the actual write boundary. Permissions are tested even after disabling the default. Reader access to future analytical tables is opt-in, so a newly created sensitive table is not exposed automatically.

Alembic applies explicit, versioned migrations. The first migration creates an application metadata table; future tables arrive with features. The API checks the recorded revision before declaring readiness. The writer can read migration history but cannot edit it.

Liveness answers “is this process responding?” Readiness answers “can this phase's backend use its expected schema?” Keeping them separate avoids falsely declaring a disconnected application healthy. Readiness diagnostics are coarse to avoid leaking connection credentials.

The repository uses a `src/` package layout so imports resolve through the installed package, not accidental working-directory behavior. uv locks transitive dependencies and installs an isolated Python 3.11 environment. Model libraries are intentionally added only with their implementation phases.

## Common mistakes and alternatives

- `Base.metadata.create_all()` is convenient for prototypes but does not replace versioned migrations.
- SQLite is useful for isolated tests but cannot demonstrate PostgreSQL privilege enforcement.
- A `SELECT` prefix check does not make SQL safe. Later tools will accept predefined query IDs and validated parameters.
- Read-only defaults alone do not remove table privileges or temporary-table rights.
- Catching an exception and reporting success hides failure. This API returns degraded readiness or a structured error, with request IDs and sanitized logs.
- Logging raw exceptions, URLs, request bodies or query strings can leak secrets. The application logger serializes only approved operational fields.

## Interview explanation

“I separated schema ownership, ingestion writes and analytical reads before implementing the agent. My integration tests try prohibited operations using the actual analytics login, including after disabling its read-only default. Health endpoints distinguish a running process from a usable schema, and a clean checkout uses locked dependencies and explicit migrations.”

All 18 PostgreSQL integration cases passed locally. See [VALIDATION.md](VALIDATION.md) for executed evidence and remaining scope limits.

## Dependency compatibility note

The installed Starlette release uses HTTPX2 for its test client. Phase 2 therefore uses `httpx2` instead of the original HTTPX test dependency; this removed a deprecation warning. See [official TestClient documentation](https://www.starlette.io/testclient/). Exact tested package versions are recorded in `uv.lock`.
