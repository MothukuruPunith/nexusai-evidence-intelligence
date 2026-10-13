# NexusAI engineering continuity

Read `README.md`, `docs/phase-3.md`, and `docs/TROUBLESHOOTING.md` before continuing feature work. The troubleshooting log is persistent project memory requested by the user: append material problems, failed attempts, fixes, and actual verification results.

Current implemented scope: phases 1–3. Consult the latest validation report before claiming a milestone complete. Phase 4 (grounded answer generation with citations) is next.

- Keep credentials, uploaded documents, local databases, model weights, caches and virtual environments out of Git.
- Do not import FAISS into the API, embedding or ingestion-worker process. Its native runtime is isolated in `faiss_process.py`; real HTTP tests must cover changes to this boundary.
- Do not use `KMP_DUPLICATE_LIB_OK` to conceal OpenMP conflicts.
- Rerun relevant tests after changes. Full local validation uses `NEXUS_RUN_DB_TESTS=1 NEXUS_RUN_MODEL_TESTS=1 HF_HUB_OFFLINE=1 .venv/bin/pytest -q` after setup.
- Do not count skipped model/database tests as verified. Preserve actual retrieval ranks and failures; similarity scores are not confidence probabilities.
- Use the dedicated Compose PostgreSQL instance. Integration fixtures may remove only their own temporary databases/tables.
- Advance through the agreed phases only after the current phase's validation gate passes.
