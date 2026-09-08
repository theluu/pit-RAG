.PHONY: up down test lint seed
up:
	docker compose up --build
down:
	docker compose down
test:
	pytest -q
lint:
	python -m compileall -q apps packages tests
	ruff check .
seed:
	python -m apps.api.seed

.PHONY: test-pg
# The production retrieval path is pgvector SQL that SQLite cannot run.
test-pg:
	docker run -d --rm --name pitrag-pg -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \
	  -e POSTGRES_DB=test -p 55432:5432 pgvector/pgvector:pg16
	until docker exec pitrag-pg pg_isready -U test >/dev/null 2>&1; do sleep 1; done
	TEST_DATABASE_URL=postgresql+psycopg://test:test@localhost:55432/test pytest -q; \
	  status=$$?; docker stop pitrag-pg >/dev/null; exit $$status
