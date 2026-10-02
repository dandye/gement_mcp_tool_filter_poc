set dotenv-load := true

# Default environment file
env_file := ".env"

# Default recipe: list available commands
default:
  @just --list

# ------------------------------------------------------------------------------
# Setup & Environment Management
# ------------------------------------------------------------------------------

# Setup local environment (.env from template and sync uv dependencies)
setup:
  #!/usr/bin/env bash
  set -e
  if [ ! -f "{{ env_file }}" ]; then
    echo "Creating {{ env_file }} from template..."
    cp .env.example "{{ env_file }}"
    echo "Created {{ env_file }} - please update values as needed."
  fi
  just sync

# Synchronize virtual environment and lock dependencies via uv
sync:
  uv sync --all-groups

# ------------------------------------------------------------------------------
# Quality & Testing (Google Python Style Guide)
# ------------------------------------------------------------------------------

# Run unit tests with pytest
test *args="":
  uv run pytest {{ args }}

# Run tests with coverage report
test-cov:
  uv run pytest --cov=src --cov-report=term-missing --cov-report=html

# Check formatting with Pyink (Google Style: 2-space, 80-col)
format-check:
  uv run pyink --check --diff .

# Format code in-place with Pyink and apply Ruff fixes
format:
  uv run ruff check --fix .
  uv run pyink .

# Lint code against Google Python Style Guide
lint:
  uv run ruff check .
  uv run pyink --check .

# Static type analysis with Google Pytype
typecheck:
  uv run pytype src

# ------------------------------------------------------------------------------
# Execution & CLI Helpers
# ------------------------------------------------------------------------------

# Run project CLI
run *args="":
  uv run gement-mcp-tool-filter-poc {{ args }}

# Clean build artifacts, bytecode, and test caches
clean:
  find . -type f -name "*.pyc" -delete
  find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
  rm -rf .pytest_cache .pytype .mypy_cache .ruff_cache .coverage htmlcov dist build *.egg-info
