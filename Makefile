.PHONY: help build build-go build-py test lint fmt clean

PYTHON := python3
GO := go

help:
	@echo "AlgoTrader build targets"
	@echo "  build       Build both Python wheel and Go binary"
	@echo "  build-go    Build the Go orchestrator/execution binary"
	@echo "  build-py    Build the Python wheel"
	@echo "  test        Run Python unit tests"
	@echo "  lint        Run ruff and mypy on Python code"
	@echo "  fmt         Auto-format Python code with ruff"
	@echo "  clean       Remove build artifacts"

build: build-go build-py

build-go:
	@echo "Building Go binary..."
	$(GO) build -o bin/algotrade ./cmd/algotrade

build-py:
	@echo "Building Python wheel..."
	$(PYTHON) -m pip install build
	$(PYTHON) -m build

test:
	$(PYTHON) -m pytest

lint:
	ruff check algotrader/ tests/
	mypy algotrader/ tests/

fmt:
	ruff format algotrader/ tests/

clean:
	rm -rf bin/ dist/ build/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
