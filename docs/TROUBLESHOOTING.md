# Engineering problem and resolution log

This is persistent project memory. Update it when a failure changes the implementation or validation method. Record failed approaches as well as the final fix; do not turn planned checks into measured results.

## 1. Python version and reproducible setup — 13 October 2026

**Observed:** system Python was 3.13; the selected project runtime was 3.11. uv was not on PATH.

**Resolution:** installed uv in a workspace-local bootstrap environment and used it to install Python 3.11.17 and the project environment. Cache/runtime locations were kept inside the workspace. A convenience link in the home-directory binary folder could not be created; commands used the explicit installed paths instead. No system Python was replaced.

**Verification:** locked installation into a second empty environment succeeded; package build and foundation tests passed. Fresh users install uv normally; the already-created `.venv/bin/` executables work here without a global uv command.

## 2. Docker access and unavailable database — 13 October 2026

**Observed:** Docker CLI existed but socket access was denied by the sandbox. After access was granted, the engine was stopped. Launch attempts from the assistant session failed or timed out.

**Failed alternative:** PostgreSQL 17.9 was built from a checksum-verified official source archive in scratch space. Initialization failed because the sandbox denied shared memory (`shmget`). This was not a PostgreSQL permission-test pass.

**Resolution:** the user started Docker Desktop. Docker socket/network access was renewed when the turn-scoped grant expired. The dedicated Compose service then initialized PostgreSQL 17.11.

**Verification:** role provisioning, migration upgrade, repeat setup, container restart/persistence and 18 real database permission cases passed. Use the existing Docker service rather than retrying native initialization in this sandbox.

## 3. Deprecated HTTP testing dependency — 13 October 2026

**Observed:** the installed Starlette release warned that its old HTTPX test-client backend was deprecated.

**Resolution:** changed the development dependency to HTTPX2, following the official TestClient documentation, and refreshed `uv.lock`.

**Verification:** tests completed without that deprecation warning. Do not switch back just because older tutorials use HTTPX.

## 4. Function privileges are not safely revoked per schema — 13 October 2026

**Identified during review:** a per-schema default-privilege revoke does not remove the global default PUBLIC function-execution privilege.

**Resolution:** revoke PUBLIC EXECUTE globally for functions subsequently created by the schema owner. Analytical table access also remains explicitly granted rather than automatically exposed.

**Verification:** an integration test creates a function and confirms the analytics reader cannot execute it. Other negative tests disable the reader's read-only default and still require PostgreSQL privilege-denied errors. Read-only defaults alone are not the security boundary.

## 5. PyTorch + FAISS native OpenMP crashes — 13–14 October 2026

**Observed:** the first real embedding test run segfaulted. Isolated commands showed model inference worked without FAISS and could work when PyTorch was imported first. Calling FAISS's thread configuration in the shared process also aborted.

**Initially insufficient fix:** centralized PyTorch-before-FAISS import order. All 61 tests passed, but the actual Uvicorn server aborted on its first search with `OMP: Error #15`, indicating duplicate `libomp.dylib` initialization. This demonstrated that the in-process test client did not cover native initialization under real serving conditions.

**Final resolution:** FAISS now runs only in `faiss_process.py`, a separate subprocess. The API and embedding worker never import FAISS. Native calls have a 20-second deadline and a two-operation concurrency cap. Crashes/timeouts map to service errors. PyTorch remains in the parent process; stored vectors and file checksums preserve reproducibility across the boundary.

**Verification:** added a fresh real-Uvicorn process test that performs first-load and repeated HTTP searches, plus separate-process index and failure-translation checks. All 65 tests passed. The independent live demo subsequently completed upload, worker processing and evidence retrieval.

**Do not regress:** never enable `KMP_DUPLICATE_LIB_OK`; do not add an in-process FAISS import to the API, worker or embedding module. A successful import-order experiment is not proof of live-server safety. Upstream context: [PyTorch issue 149201](https://github.com/pytorch/pytorch/issues/149201).

## 6. Interrupted test run left an empty test database — 14 October 2026

**Observed:** the native crash prevented fixture teardown, leaving the uniquely named database created by that test session.

**Resolution:** inspected that exact database, confirmed its document/job/chunk/index tables were empty, then removed it. No production or unrelated database was removed. Successful subsequent fixtures dispose connections and remove only their own random database.

**Lesson:** normal fixture cleanup cannot run after a native abort. Keep test environments isolated and inspect remnants before removing them.

## 7. Dense search confused nearby ISO dates — 14 October 2026

**Observed:** the live demo's “September 2025 revenue” query ranked the August row above September when dates were encoded as `2025-08-31` and `2025-09-30`. The initial top-1 assertion failed.

**Current handling:** preserve that failure of top-1 ranking. The demo requests a normal top-5 evidence set, verifies the expected source is present, and records its actual rank and `top_hit_matches` value. September ranked second in the recorded run; this is not presented as a ranking fix or a benchmark success.

**Future work:** evaluate explicit temporal filtering and hybrid keyword/semantic retrieval on a fixed development set in the retrieval-improvement phase. Numeric reports must later use typed calculations, not whichever row happens to rank first.

## 8. Account usage interruption — 13–14 October 2026

**Observed:** automatic approval review could not execute a process-inspection command after the account usage limit was reached. The action was not executed.

**Resolution:** continued after the user requested resumption and access was available again. Checked persisted test results, database state and running services before proceeding. Do not bypass approval checks through another tool.

## 9. Avoid unnecessary Linux CUDA dependencies — 14 October 2026

**Identified:** default PyTorch resolution included Linux CUDA packages although this phase uses CPU inference.

**Resolution:** uv now selects the official CPU PyTorch index on Linux, while macOS uses the normal native wheel. Updated the lockfile.

**Verification:** the clean Apple Silicon environment passed all 65 tests. [GitHub Actions on Ubuntu](https://github.com/MothukuruPunith/nexusai-evidence-intelligence/actions/runs/38451056893) then successfully installed the locked CPU environment and completed lint, database setup, model download and the full test command for commit `1b42939`.

## 10. Qwen download stalled on IPv6 - 14 October 2026

**Observed:** Ollama downloaded part of the 2.5 GB Qwen model, then repeatedly timed out connecting to an IPv6 storage address.

**Resolution:** downloaded the same official registry manifest and blobs over HTTPS with IPv4, resumed the partial transfer, and checked every blob's SHA-256 and size against the manifest before installation. The installed model digest is `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`. No replacement model or unverified third-party weights were used.

**Additional issue:** starting an empty Ollama server during the manual installation pruned the not-yet-referenced config blob. Reinstalled that small verified blob after the manifest was in place. Normally use `ollama pull`; a manual registry installation requires complete manifests and blobs before starting the server.

## 11. Ollama inside the assistant sandbox could not initialize Metal - 14 October 2026

**Observed:** the model downloaded correctly but the sandbox-launched server returned Metal command-queue and buffer-allocation errors. Requesting zero GPU layers still failed during backend initialization. This is not evidence that a 4B model exceeds the Mac's physical RAM.

**Resolution:** obtained filesystem permission to install the already verified files into the existing native Ollama app's model store. Used the normally running app on port 11434. The structured Qwen smoke request and the full local test suite then passed. The private `.env` points to that app; there is no cloud fallback.

## 12. Resumed work while Docker was stopped - 14 October 2026

**Observed:** after resumption, the database tests failed because Docker was no longer running. Starting Docker through this session failed with a macOS executable/launch error.

**Resolution:** the user started Docker Desktop. The existing project database container became healthy and the full suite passed: 87 tests, including the opt-in local LLM test. Do not delete volumes or regenerate database credentials for a stopped engine.

**Reporting precaution:** a failed database traceback can include connection details. The failed generated report was removed; the published JUnit report is from the passing run. Check generated reports for secrets before committing, not just application source files.

## 13. Context construction and environment validation - 14 October 2026

**Identified during review:** repeatedly removing one character while recounting JSON bytes could become expensive for long extracted spans. Integer Literal configuration also rejected environment strings such as `-1`.

**Resolution:** context shortening uses a binary search over prefix length. The GPU-layer setting is a bounded integer field so environment values parse correctly. Citation checks reject end offsets beyond the stored block. Provider errors are returned as fixed safe codes.

**Verification:** unit checks plus the 87-test full local run passed. CPU selection remains available, but did not solve the Metal initialization restriction above.
