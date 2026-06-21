.PHONY: up down lint typecheck test dbt-run dbt-test

up:
	docker-compose up -d

down:
	docker-compose down

lint:
	ruff check .
	ruff format --check .

typecheck:
	mypy extractors/ loaders/postgres/ transformers/ --ignore-missing-imports

test:
	pytest tests/

dbt-run:
	python -m loaders.postgres.load_silver
	cd dbt && dbt run

dbt-test:
	cd dbt && dbt test