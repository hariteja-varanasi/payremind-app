.PHONY: install check test run
install:
	pip install -e ".[dev]"
check:
	ruff check . && ruff format --check . && mypy src && bandit -q -r src && pip-audit --skip-editable
test:
	pytest
run:
	uvicorn --factory payremind.api.app:create_app --reload
