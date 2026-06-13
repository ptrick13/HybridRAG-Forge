.PHONY: up down lint test dbt-run dbt-test

up:
	docker-compose up -d

down:
	docker-compose down

lint:
	ruff check .

format:
	ruff format .

test:
	pytest tests/

dbt-run:
	cd dbt && dbt run

dbt-test:
	cd dbt && dbt test
