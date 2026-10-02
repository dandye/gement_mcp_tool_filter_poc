# gement_mcp_tool_filter_poc

PoC for disabling MCP connector tools in Gemini Enterprise via ADK

Adheres to the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) (2-space indentation, 80-column line limit, Pyink formatter, Pytype static analyzer).

## Quickstart

```bash
# Setup environment and sync dependencies
just setup

# Run test suite
just test

# Check formatting and lint
just lint

# Run CLI info command
just run info
# or
uv run gement-mcp-tool-filter-poc info
```

## Directory Structure

- `src/` - Application source code and Typer CLI.
- `tests/` - Automated pytest suite.
- `docs/` - Technical documentation and architectural decisions.
- `scripts/` - Shell automation and helper scripts.
- `.github/workflows/` - Continuous integration pipelines.
