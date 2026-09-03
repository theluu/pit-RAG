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
