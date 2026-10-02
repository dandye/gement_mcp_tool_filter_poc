# AGENTS.md

This file provides guidance to AI coding assistants (Gemini, Claude, Cursor, Codex, etc.) working in this repository.

## Google Python Style Guide Standards

This repository strictly complies with the **Google Python Style Guide**:
- **Indentation (§3.4)**: Use **2 spaces** per indentation level. Never use tabs.
- **Line Length (§3.2)**: Maximum **80 characters** per line.
- **Formatter**: Use **Pyink** (`google/pyink`) with `--pyink-indentation 2`.
- **Docstrings (§3.8)**: Follow Google docstring conventions (`Args:`, `Returns:`, `Raises:`). Test functions are exempt (§3.8.2.1).
- **Logging (§3.10.1)**: **Never use f-strings in logging calls.** Always use `%s` placeholders (e.g. `logger.info("Value is %s", val)`).
- **Imports (§3.13)**: Single-line module imports without parentheses (`from foo import bar`).
- **Type Analysis**: Analyzed using Google **Pytype** static analyzer.

## Code Style and Communication

**CRITICAL: Never use emojis. Anywhere. Ever.**
- No emojis in code comments
- No emojis in commit messages
- No emojis in pull request descriptions
- No emojis in code review comments
- No emojis in documentation
- Emojis are unprofessional and must not be used in any context

## Shell and Environment Variables

- In code and shell examples, define environment variables first (e.g. `PROJECT_ID="..."`) and then reference them as `$PROJECT_ID`.

## Git Worktree and Path Conventions

- This repository adheres to the Git worktree conventions under `<project_name>__worktrees/` or `<project_name>/`.
- Linked worktrees exist as sibling directories (e.g., `<branch_name>`).
- Always resolve internal paths relative to `Path(__file__).resolve().parents[...]` to maintain portability across sibling worktrees.

## Project Structure

```text
.
├── .env.example          # Environment variable template
├── .gitignore            # Git ignore configuration
├── .github/
│   └── workflows/
│       └── ci.yml        # CI automation (GitHub Actions with setup-uv)
├── AGENTS.md             # AI coding instructions and repo guidelines
├── justfile              # Task runner (uv sync, test, lint, format, typecheck, run)
├── pyproject.toml        # PEP 621 + Hatchling + PEP 735 dependency groups + Pyink config
├── uv.lock               # Deterministic dependency lockfile
├── docs/                 # Technical documentation & architecture notes
│   ├── .gitkeep
│   ├── architecture.md
│   └── setup.md
├── scripts/              # Helper & deployment automation scripts
│   ├── .gitkeep
│   └── setup_env.sh
├── src/
│   └── gement_mcp_tool_filter_poc/
│       ├── __init__.py
│       ├── __main__.py   # Module execution entrypoint (python -m gement_mcp_tool_filter_poc)
│       ├── cli.py        # Typer + Rich unified CLI (2-space indent, 80 cols)
│       ├── core.py       # Core package implementation
│       └── py.typed      # PEP 561 marker
└── tests/
    ├── conftest.py       # Pytest fixtures and mock setup
    └── test_basic.py     # Basic test suite
```

## Common Commands

| Task | Command | Description |
| :--- | :--- | :--- |
| **Setup** | `just setup` | Create `.env` from template and sync environment with `uv` |
| **Sync** | `just sync` | Synchronize virtual environment and lockfile with `uv sync` |
| **Run Tests** | `just test` | Run pytest suite via `uv run pytest` |
| **Coverage** | `just test-cov` | Run tests with terminal and HTML coverage report |
| **Format** | `just format` | In-place format with Pyink (2 spaces, 80 columns) |
| **Format Check** | `just format-check` | Verify formatting without modifying files |
| **Lint** | `just lint` | Run Ruff checks + Pyink format verification |
| **Typecheck** | `just typecheck` | Run Google Pytype static type analysis |
| **CLI Info** | `just run info` | Print environment status via CLI |
| **Clean** | `just clean` | Remove cache files, coverage reports, and build artifacts |
