.PHONY: install fetch audit run api dashboard test lint format docker

install:      ## dev install
	pip install -e ".[all]"
fetch:        ## download + verify Kaggle sources
	ayur fetch
audit:        ## data-quality gate only
	ayur audit
run:          ## full pipeline -> artifacts/
	ayur run
api:
	ayur serve
dashboard:
	ayur dashboard
test:
	pytest --cov=ayurnidaan --cov-report=term-missing
lint:
	ruff check src tests && ruff format --check src tests
format:
	ruff format src tests && ruff check --fix src tests
docker:
	docker compose up --build
