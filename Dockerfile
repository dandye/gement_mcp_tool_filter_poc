FROM python:3.11-slim

WORKDIR /app

# Install uv (pinned to the version that produced uv.lock)
COPY --from=ghcr.io/astral-sh/uv:0.7.15 /uv /bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
COPY README.md ./

# Install application dependencies from public PyPI in Cloud Build
RUN uv sync --no-dev --default-index https://pypi.org/simple

ENV PATH="/app/.venv/bin:$PATH"
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["uvicorn", "gement_mcp_tool_filter_poc.server:app", "--host", "0.0.0.0", "--port", "8080"]
