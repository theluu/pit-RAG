# Vietnam Legal RAG

An evaluation-first legal retrieval application for Vietnamese labour, social-insurance and personal-income-tax documents. The MVP implements deterministic, inspectable L0–L4 pipelines plus effective-date filtering (L7); it runs without an external LLM key and can later be connected to a model provider.

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
- React query/compare UI, source inspector and warning states
- Docker Compose services for API, web, PostgreSQL/pgvector and Redis

## Deliberate MVP limitations

The bundled corpus is synthetic demonstration data, not legal advice. Dense retrieval uses a deterministic sparse embedding so the project works offline. Production deployments should import reviewed primary-source documents, configure a multilingual embedding/reranker and LLM adapter, scan uploads, and replace the development JWT secret. See [architecture](docs/architecture.md) and [security](docs/security.md).

## Commands

```bash
make test       # backend tests
make lint       # compile/type sanity checks
make seed       # show seed corpus summary
make up         # docker compose up --build
```
