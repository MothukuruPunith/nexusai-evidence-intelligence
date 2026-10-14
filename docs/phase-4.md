# Phase 4: asking questions with local models

This phase adds `POST /rag/query` and `GET /rag/citations/{chunk_id}`. It uses the existing document search, then asks Qwen3 4B Instruct to select useful source quotations. The answer is assembled from checked quotations rather than unchecked model-written prose. Independent relevance checking and answer repair are Phase 5 work.

## How a request works

1. Validate the question and optional document/category filters. Questions are at most 500 characters, k is at most 5, and the request body is limited to 16 KiB.
2. Acquire a PostgreSQL advisory lock. A second query against the same database returns `generation_busy` instead of starting another model call.
3. Search the published FAISS generation using the existing local embedding model. Filters are applied before ranking.
4. Build a system instruction and a separate JSON message containing the question and untrusted source text. Source IDs are short labels such as `S1`; filenames and document text cannot set privileged instructions or choose tools.
5. Bound the input by conservative UTF-8 byte accounting, including the output schema. Longer context is shortened explicitly, with `context_truncated` in the response. The model runs with a 4,096-token context and up to 768 output tokens.
6. Ask local Ollama for a structured selection of at most three exact quotations. The runtime checks the model digest against the saved manifest before generation. It does not download models or call a cloud provider.
7. Reject unknown source labels and quotes that are absent from the supplied context. One invalid selection rejects the whole draft. Re-read the source chunk and validate its span against the stored extracted block.
8. Return the quotes with document and chunk IDs, hashes, source location and offsets. The citation URL returns the full source chunk so the shorter quote can be checked again.

Offsets are Python Unicode character positions in the canonical extracted block, not byte positions in the original PDF or DOCX. The document hash identifies the original uploaded bytes. The chunk hash identifies the extracted text used for the answer. The source locator identifies the page, paragraph or CSV row supported by the parser.

## Why the answers are extractive

A valid citation is not the same as a correct answer. A model could quote the wrong month perfectly. For now, the response says `EXTRACTIVE` or `ABSTAINED` and sets `support_assessment` to `NOT_ASSESSED`. It does not assign a confidence percentage or claim that all facts have been verified.

An empty retrieval set skips generation. An empty model selection or invalid quote produces an abstention. Missing models, changed model digests, invalid structured output, incomplete generation and provider failures return explicit errors. They are not disguised as successful answers.

The model is instructed to preserve qualifications and avoid calculations. These instructions are fallible. The deterministic checks validate provenance, not relevance, omissions, source truth or resistance to every prompt injection.

## Running locally

Use the setup in the README. Ollama defaults to `http://127.0.0.1:11434`. `NEXUS_OLLAMA_URL` may select another local port, but external URLs, URL credentials and redirects are rejected. The transport also ignores proxy environment variables.

`configure_llm.py` records the installed model digest, Ollama version and model details in `artifacts/llm/manifest.json`. It refuses to replace an existing manifest with a different digest. Review model changes before regenerating that manifest.

`NEXUS_LLM_GPU_LAYERS=-1` lets Ollama select GPU execution; `0` requests CPU layers. On this machine, the Ollama app started normally by the user works. An Ollama server launched inside the assistant sandbox failed to initialize Metal even with zero GPU layers. CPU selection alone did not fix that host restriction.

Generation HTTP work runs in a disposable Python process. The caller terminates it after 60 seconds. This bounds the application's wait; it does not prove that every Ollama backend stops computing immediately after client disconnection. Embedding inference has bounded input but no separate hard wall-clock deadline. Only one API process is recommended; different databases or direct Ollama clients do not share the database lock.

No request text, source text or generated drafts are written to application logs. This phase does not add persistent conversation history or an execution-trace store. The response request ID supports correlation with existing safe request logs.

## Evaluation

`datasets/evaluation/phase4.json` contains eight original synthetic development cases: ordinary questions, a month-specific CSV question, an unknown fact, an ambiguous question, two conflicting policies, a source containing hostile instructions, and a calculation that should be deferred.

Start the API and worker, then run:

```sh
uv run python scripts/evaluate_rag.py --output docs/phase-4-baseline.json
```

The script uploads its own named synthetic files and restricts each query to the intended document IDs. It records actual responses, citation resolution checks, expected-span retrieval ranks, Recall@5 for annotated cases and a simple case rubric. Missing retrieval slots are not invented. Unanswerable cases have no retrieval-recall denominator.

The rubric uses expected status, required text and prohibited text. It is not a semantic judge or a general answer-accuracy metric. A conflict case checks whether both quoted values are retained; it does not establish contradiction detection or authority resolution. Cases are visible development examples, not a sealed benchmark, and were not used to train model weights. The report includes the dataset hash and model digest.

Results and test evidence are recorded in `PHASE-4-VALIDATION.md` after execution. Local LLM tests are opt-in. GitHub CI runs database, embedding and deterministic RAG tests; it does not claim to run the local Qwen model.

## Code to read

- `rag/schemas.py`: request, model-draft and answer contracts.
- `rag/generator.py`: context construction, manifest check and generation deadline.
- `rag/ollama_process.py`: bounded local HTTP transport.
- `rag/service.py`: retrieval, concurrency limit, source-span checks and answer assembly.
- `rag/api.py`: the two routes.
- `tests/test_rag.py`: invalid-output, context, deadline and request checks.
- `tests/test_rag_integration.py`: database/model integration and an opt-in real LLM test.

The main alternative is unrestricted prose generation followed by a separate semantic verifier. That can produce more natural answers but needs labeled verification data and measured error rates. Another option is to show search excerpts without an LLM; the LLM here selects smaller passages in response to a question. Its added usefulness must be measured rather than assumed.

Interview explanation: “I first retrieve candidate chunks with embeddings. The local LLM selects exact quotes in a structured response. My code checks the quotes against the stored source text and returns immutable source identifiers. This verifies citation provenance, but I keep answer relevance and contradiction checking as separate tasks.”

## API references used

The local adapter follows Ollama's [chat endpoint](https://docs.ollama.com/api/chat) and [structured output](https://docs.ollama.com/capabilities/structured-outputs) documentation. Model details come from the installed artifact and the [official Qwen3 4B Instruct listing](https://ollama.com/library/qwen3:4b-instruct).
