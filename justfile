set dotenv-load := true
export UV_NO_CONFIG := "1"

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
# Hairpin MCP Proxy & Gemini Enterprise Connector Operations
# ------------------------------------------------------------------------------

# Run project CLI
run *args="":
  uv run gement-mcp-tool-filter-poc {{ args }}

# Deploy the Hairpin MCP proxy as an IAM-authenticated Cloud Run service
deploy-cloud-run service_name="secops-hairpin-mcp" *args="":
  #!/usr/bin/env bash
  set -e
  PROJECT_ID="${GCP_PROJECT_ID:-your-gcp-project-id}"
  REGION="${GCP_LOCATION:-us-central1}"
  UPSTREAM_URL="${UPSTREAM_ONEMCP_URL:-https://us-chronicle.googleapis.com/mcp}"
  echo "Deploying Cloud Run Hairpin MCP proxy {{ service_name }} in $PROJECT_ID ($REGION) with --no-allow-unauthenticated..."
  gcloud run deploy "{{ service_name }}" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --source=. \
    --clear-base-image \
    --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},UPSTREAM_ONEMCP_URL=${UPSTREAM_URL}" \
    --no-allow-unauthenticated {{ args }}

# Grant required IAM roles and Cloud Run invoker bindings on target GCP project
setup-iam account="user@example.com" service_name="secops-hairpin-mcp":
  #!/usr/bin/env bash
  set -e
  PROJECT_ID="${GCP_PROJECT_ID:-your-gcp-project-id}"
  PROJECT_NUMBER="${GCP_PROJECT_NUMBER:-$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')}"
  REGION="${GCP_LOCATION:-us-central1}"
  MEMBER="user:{{ account }}"
  if [[ "{{ account }}" == *"@"*".iam.gserviceaccount.com" ]]; then
    MEMBER="serviceAccount:{{ account }}"
  fi
  echo "Granting project IAM roles in $PROJECT_ID..."
  for TARGET_MEMBER in \
    "$MEMBER" \
    "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    "serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"; do
    for ROLE in \
      "roles/discoveryengine.viewer" \
      "roles/agentregistry.viewer" \
      "roles/chronicle.viewer" \
      "roles/aiplatform.user"; do
      gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="$TARGET_MEMBER" \
        --role="$ROLE" \
        --condition=None \
        --quiet >/dev/null || true
    done
  done
  echo "Configuring Cloud Run roles/run.invoker bindings on {{ service_name }}..."
  for INVOKER in \
    "$MEMBER" \
    "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    "serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
    "serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-discoveryengine.iam.gserviceaccount.com"; do
    gcloud run services add-iam-policy-binding "{{ service_name }}" \
      --project="$PROJECT_ID" \
      --region="$REGION" \
      --member="$INVOKER" \
      --role="roles/run.invoker" \
      --quiet >/dev/null || true
  done
  gcloud run services remove-iam-policy-binding "{{ service_name }}" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --member="allUsers" \
    --role="roles/run.invoker" \
    --quiet >/dev/null 2>&1 || true
  echo "IAM configuration complete."

# Register the deployed Cloud Run Hairpin MCP proxy in Gemini Enterprise
register-connector *args="":
  uv run gement-mcp-tool-filter-poc register-connector {{ args }}

# List MCP connectors registered in Gemini Enterprise Agent Registry
list-connectors *args="":
  uv run gement-mcp-tool-filter-poc list-connectors {{ args }}

# List MCP connectors in JSON format
list-connectors-json *args="":
  uv run gement-mcp-tool-filter-poc list-connectors --json {{ args }}

# Run vanilla ADK agent locally against the Hairpin MCP connector
run-agent prompt="What tools are available to you in SecOps?" *args="":
  uv run gement-mcp-tool-filter-poc run-agent "{{ prompt }}" {{ args }}

# Deploy vanilla ADK agent using the Hairpin MCP connector to Vertex AI Agent Engine
deploy-reasoning-engine *args="":
  uv run gement-mcp-tool-filter-poc deploy-reasoning-engine {{ args }}

# Clean build artifacts, bytecode, and test caches
clean:
  find . -type f -name "*.pyc" -delete
  find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
  rm -rf .pytest_cache .pytype .mypy_cache .ruff_cache .coverage htmlcov dist build *.egg-info
