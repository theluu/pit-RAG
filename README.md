# Vietnam Legal RAG

An evaluation-first legal retrieval application for Vietnamese labour, social-insurance and personal-income-tax documents. It combines deterministic L0–L4/L7 retrieval, persistent audit data, reviewed ingestion and an optional citation-checked OpenAI generation layer. The safe extractive path remains available without an API key.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Open the web app at <http://localhost:5173>, API docs at <http://localhost:8000/docs>, and log in with `demo@legalrag.vn` / `demo1234`.

For local backend development:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
uvicorn apps.api.main:app --reload
```

## Implemented

- JWT authentication and role claims (`admin`, `curator`, `evaluator`, `user`)
- legal document/provision/relation/run/evaluation schema
- Vietnamese legal structure parser (chapter/article/clause/point)
- L1 dense-like TF-IDF cosine, L2 metadata/date filter, L3 BM25 + vector RRF, L4 deterministic reranker, L7 effective-date and replacement warnings
- grounded extractive answers with verified citations and abstention
- query comparison, retrieval diagnostics, feedback and evaluation metrics
- SQLAlchemy persistence for documents, provisions, users, runs, feedback and audit events
- reviewed document ingestion (`draft` by default) and role-protected evaluation API
- Argon2 password verification and database-backed identities
- optional OpenAI Responses structured output and embeddings gateway with citation validation
- React query/compare UI, source inspector and warning states
- Docker Compose services for API, web, PostgreSQL/pgvector and Redis
- asynchronous PDF ingestion for born-digital, scanned and hybrid files
- page-level Tesseract `vie` OCR fallback with deskew/CLAHE preprocessing and per-page degradation instead of job failure
- tone-mark charset gate that rejects recognition output whose Vietnamese dấu were dropped, and non-retryable classification for deterministic ingestion failures
- page-span provenance (`page_from`/`page_to`), extraction method, confidence and quality flags per điều khoản, with live job progress in the review UI
- MinIO object storage and Redis/Dramatiq ingestion worker with retries
- versioned OpenAI embedding indexes with pgvector HNSW, PostgreSQL FTS, atomic activation, rollback and retention
- lexical fallback (flagged on the run) when the embedding provider is unavailable
- unit-aware ranking for quantitative questions, and separate chat/embedding circuit breakers that open only after repeated failures

## Deliberate MVP limitations

The bundled corpus is synthetic demonstration data, not legal advice. SQLite/CI uses deterministic sparse scoring; Docker production retrieval switches to the active pgvector index. A production corpus, calibrated confidence model and enterprise SSO still require external infrastructure and reviewed data. See [architecture](docs/architecture.md) and [security](docs/security.md).

## Optional OpenAI generation

Create a new key after revoking any key that has been pasted into chat or committed anywhere. Keep it only in `.env` (which is gitignored):

```bash
OPENAI_API_KEY=your-new-key
ENABLE_OPENAI=true
```

The provider receives only the retrieved evidence needed for the current question. If the call fails, abstains, or cites an unknown provision, the API falls back to deterministic extractive generation.

## Administration API

- `POST /api/v1/admin/documents`: parse and preview a legal document; publication is explicit.
- `POST /api/v1/admin/documents/uploads`: upload a PDF; returns a job id to poll.
- `GET /api/v1/admin/ingestion-jobs/{id}`: stage, progress, attempt count and quality warnings.
- `GET /api/v1/admin/documents/{id}/preview`: extracted pages and chunks with provenance, for review.
- `POST /api/v1/admin/indexes/rebuild` and `.../indexes/{id}/activate`: build and atomically swap the production index.
- `POST /api/v1/admin/evaluations/{pipeline}`: benchmark citation precision/recall and latency.
- `GET /api/v1/runs/{id}`: retrieve a persisted run after restart.

## Commands

```bash
make test       # backend tests (pgvector suites skip without TEST_DATABASE_URL)
make test-pg    # backend tests including the pgvector integration suite
make lint       # compile/type sanity checks
make seed       # show seed corpus summary
make up         # docker compose up --build
```
