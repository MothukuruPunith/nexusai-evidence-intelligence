# Phase 4 validation - 14 October 2026

## Local execution

The full suite passed **87 tests, zero failures and zero skips**, with the database, embedding and LLM flags enabled. Pytest reported 13.38 seconds. See [JUnit report](phase-4-tests.xml). Lint and format checks passed.

Hardware: MacBook Air M4, 16 GB unified memory. Python 3.11; PostgreSQL in the existing Docker Compose service. Embeddings use local MiniLM on CPU. Qwen uses the normally running native Ollama app; no GPU speed or memory benchmark is claimed.

Generation model: `qwen3:4b-instruct`, Q4_K_M, digest `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`; Ollama 0.35.0. Context 4096, maximum output 768 tokens, temperature 0, seed 42. Identical seeds are not a guarantee of byte-identical answers across runtimes/hardware.

The full run includes the previous 65 tests plus 22 RAG tests/cases. It covers invalid references and quotes, missing/changed models, invalid JSON, context limits, request limits, generation deadline error translation, local-only provider configuration, advisory-lock contention, corrupted source spans and citation resolution. One real LLM test makes two calls: a known policy answer and an unknown-fact abstention. Most malformed-output tests use controlled doubles, not adversarial model trials.

The first attempt after resuming failed because Docker was stopped. The user restarted Docker; the passing report above is the rerun. The failed report was removed because database tracebacks can contain connection details. The troubleshooting log records the failure rather than treating it as a pass.

## Separate live API evaluation

Started Uvicorn and the ingestion worker as separate processes, then ran `scripts/evaluate_rag.py` against the real API. The script uploaded five synthetic files and ran eight fixed development cases. [Raw results](phase-4-baseline.json) include every answer, source identifier, raw latency, dataset hash and model digest.

| Case | Rubric result |
|---|---|
| Annual leave allowance | Passed |
| Support hours | Passed |
| September revenue | Passed |
| Unknown fact | Abstained as expected |
| Ambiguous allowance question | Abstained as expected |
| Two policies stating different allowances | Returned both quoted values |
| Embedded instruction in office-hours source | Returned the requested office-hours quote |
| Percentage-change calculation | Abstained as expected |

All eight simple rubrics passed in this run. All six emitted citations resolved to matching stored source text, document hashes and chunk hashes. These are small visible development checks, not held-out accuracy or hallucination-rate measurements. In particular, the conflict case does not demonstrate an implemented contradiction detector, and one injection case does not establish general prompt-injection resistance.

The September evidence remained at retrieval rank 2, as in the earlier dense-search limitation. The LLM selected the correct retrieved row for this example; retrieval ranking itself was not fixed.

## Remote validation

The GitHub workflow runs the non-LLM suite with a real PostgreSQL instance and the downloaded embedding model. Qwen is tested locally; the CI command explicitly deselects the `llm` marker. The [GitHub Actions run for commit ab1e2f9](https://github.com/MothukuruPunith/nexusai-evidence-intelligence/actions/runs/38602829490) completed successfully on Ubuntu. This validates the non-LLM suite; the local Qwen test remains separately recorded above.

## Limits

Answers are extractive quotations. Semantic support, completeness, source authority, contradictions and computed facts are not independently verified. No public deployment, load test, memory benchmark, trained ML/DL result or representative-domain evaluation was performed. A provider timeout bounds the application's wait but does not certify immediate server-side cancellation. This is the Phase 4 baseline for later retrieval and verification work.
