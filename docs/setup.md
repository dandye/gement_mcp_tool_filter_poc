# Setup & Installation - gement_mcp_tool_filter_poc

## Prerequisites
- Python >= 3.11
- `just` (command runner: `cargo install just` or system package manager)
- `uv` (modern Python manager: `curl -LsSf https://astral.sh/uv/install.sh | sh`)

## Local Development
1. Run `just setup` to initialize `.env` and sync dependencies into `.venv`.
2. Run `just test` to verify the test suite.
3. Run `just lint` to verify formatting and lint rules (Pyink & Ruff).
4. Run `just typecheck` to run Google Pytype static type analysis.
