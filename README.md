# NexusAI - Document Question Answering with RAG

NexusAI is a project I’m building to learn how to use local language models with documents. The idea is to upload files, ask a question, and see the source text behind the answer.

The backend uses FastAPI, PostgreSQL and FAISS. There is no frontend yet; I use FastAPI’s API docs to try the features.

## What works

- Upload PDF, DOCX, TXT and CSV files.
- Track file processing and avoid duplicate uploads.
- Search documents using Sentence Transformers embeddings and FAISS.
- Filter searches by document or category.
- Ask questions using a local Qwen model through Ollama.
- Return quoted answers with document IDs, source locations and checked text offsets.
- Rebuild the search index from the vectors saved in PostgreSQL.

The current answers are source excerpts selected by the model. The code checks that each quote exists in the source. It does not yet check whether the model selected every relevant fact or whether two documents disagree.

## Tech stack

Python 3.11, FastAPI, PostgreSQL, SQLAlchemy, Sentence Transformers, FAISS, PyTorch, Ollama and pytest.

Docker runs the database. Ollama runs directly on the Mac.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), Docker and [Ollama](https://ollama.com/download). Start Docker, then run these commands from the project folder:

```sh
uv sync --locked
uv run python scripts/configure_local.py
docker compose up -d --wait db
uv run python scripts/bootstrap_database.py
uv run alembic upgrade head
uv run python scripts/download_embedding_model.py
```

The configuration script creates a local `.env` with generated database passwords. It will not overwrite an existing file. Keep this file private.

Start Ollama, then download and register the generation model:

```sh
ollama pull qwen3:4b-instruct
uv run python scripts/configure_llm.py
```

The embedding model and LLM need an internet connection for their initial downloads. Queries use local models. Model files, uploaded documents and passwords are excluded from Git.

## Run

Start the API:

```sh
HF_HUB_OFFLINE=1 uv run uvicorn nexusai.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

In another terminal, start the worker that processes uploads:

```sh
HF_HUB_OFFLINE=1 uv run python -m nexusai.documents.worker
```

Open [localhost:8000/docs](http://localhost:8000/docs). Upload a file, wait for its job to finish, then try `/rag/query`:

```json
{"query": "How many annual leave days do employees get?", "category": "hr_policy"}
```

The response includes the selected quotes and links to their source chunks. `/documents/search` is also available if you only want search results.

## Tests

```sh
uv run ruff check .
uv run ruff format --check .
NEXUS_RUN_DB_TESTS=1 NEXUS_RUN_MODEL_TESTS=1 HF_HUB_OFFLINE=1 uv run pytest -q -m 'not llm'
NEXUS_RUN_DB_TESTS=1 NEXUS_RUN_MODEL_TESTS=1 NEXUS_RUN_LLM_TESTS=1 HF_HUB_OFFLINE=1 uv run pytest -q
```

The last command also needs Ollama and the registered Qwen model. Tests use temporary databases in the dedicated local PostgreSQL instance. Do not point them at a shared database.

Test results and the small synthetic RAG evaluation are explained in [the Phase 4 notes](docs/phase-4.md). These examples are development checks, not proof of accuracy on real company documents.

## Known limitations

- Scanned PDFs need OCR, which is not included yet.
- Uploads are limited to 5 MiB, with a maximum of 200 documents and 10,000 chunks.
- Search can confuse nearby dates. In an earlier test, August ranked above September for a September revenue question.
- Matching a quote does not prove that the answer is relevant, complete or true.
- This is a local, single-user project. It has no login system and should not be exposed publicly.

## Next steps

Improve retrieval and answer checking, detect conflicting statements, add controlled data-analysis tools, train anomaly and document-classification models, and build a Streamlit interface. These are still pending.

I keep the problems I ran into and their fixes in [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). The longer design is in [ARCHITECTURE.md](ARCHITECTURE.md).
