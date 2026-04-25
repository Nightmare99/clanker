#!/bin/bash
# Run tests locally - mirrors the CI workflow

set -e

echo "=== Installing dependencies ==="
pip install -e ".[dev]" -q

echo ""
echo "=== Running tests ==="
python -m pytest tests/ -v --tb=short "$@"

echo ""
echo "=== Running linter ==="
ruff check src/

echo ""
echo "=== Running type checker ==="
mypy src/clanker --ignore-missing-imports --no-error-summary || true

echo ""
echo "=== All checks passed ==="
