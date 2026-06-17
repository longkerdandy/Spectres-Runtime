.PHONY: help venv install install-dev update test lint format typecheck check clean

PYTHON := python3.13
VENV := .venv
BIN := $(VENV)/bin

help:
	@echo "Available commands:"
	@echo "  make venv        Create a Python 3.13 virtual environment"
	@echo "  make install     Install the package in editable mode"
	@echo "  make install-dev Install the package with dev dependencies"
	@echo "  make update      Update dev tools to their latest compatible versions"
	@echo "  make test        Run the test suite"
	@echo "  make lint        Run linting checks"
	@echo "  make format      Format code"
	@echo "  make format-check Check formatting without modifying files"
	@echo "  make typecheck   Run static type checking"
	@echo "  make check       Run lint, format-check, typecheck, and tests"
	@echo "  make clean       Remove build artifacts and virtual environment"

venv:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip setuptools wheel

install: venv
	$(BIN)/pip install -e .

install-dev: venv
	$(BIN)/pip install -e ".[dev]"

update:
	$(BIN)/pip install --upgrade -e ".[dev]"

test:
	$(BIN)/pytest

lint:
	$(BIN)/ruff check src tests

format:
	$(BIN)/ruff format src tests

format-check:
	$(BIN)/ruff format --check src tests

typecheck:
	$(BIN)/mypy src tests

check: lint format-check typecheck test

clean:
	rm -rf $(VENV) build dist .pytest_cache .mypy_cache .ruff_cache src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
