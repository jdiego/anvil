.PHONY: install lint format type test check doctor build clean

install:
	uv sync --extra dev
	uv run pre-commit install

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

type:
	uv run mypy

test:
	uv run pytest

check: lint type test

doctor:
	uv run anvil doctor

build:
	uv build

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache dist build *.egg-info
