set dotenv-load := true
# Pass recipe arguments through as "$@" so values with spaces survive.
set positional-arguments := true
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
test *args:
  uv run pytest "$@"

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
run *args:
  uv run gement-mcp-tool-filter-poc "$@"

# Deploy the Hairpin MCP proxy as an IAM-authenticated Cloud Run service
deploy-cloud-run service_name="secops-hairpin-mcp" *args:
  #!/usr/bin/env bash
  set -e
  PROJECT_ID="${GCP_PROJECT_ID:-your-gcp-project-id}"
  REGION="${GCP_LOCATION:-us-central1}"
  UPSTREAM_URL="${UPSTREAM_ONEMCP_URL:-https://us-chronicle.googleapis.com/mcp}"
  echo "Deploying Cloud Run Hairpin MCP proxy {{ service_name }} in $PROJECT_ID ($REGION) with --no-allow-unauthenticated..."
  # "$1" is service_name; any further arguments are passed through to gcloud.
  gcloud run deploy "{{ service_name }}" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --source=. \
    --clear-base-image \
    --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},UPSTREAM_ONEMCP_URL=${UPSTREAM_URL}" \
    --no-allow-unauthenticated "${@:2}"

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
  WARNINGS=0
  echo "Granting project IAM roles in $PROJECT_ID (project number $PROJECT_NUMBER)..."
  for TARGET_MEMBER in \
    "$MEMBER" \
    "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    "serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"; do
    for ROLE in \
      "roles/discoveryengine.viewer" \
      "roles/agentregistry.viewer" \
      "roles/chronicle.viewer" \
      "roles/aiplatform.user" \
      "roles/mcp.toolUser" \
      "roles/serviceusage.serviceUsageConsumer"; do
      if ! gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="$TARGET_MEMBER" \
        --role="$ROLE" \
        --condition=None \
        --quiet >/dev/null; then
        echo "WARNING: could not grant $ROLE to $TARGET_MEMBER"
        WARNINGS=$((WARNINGS + 1))
      fi
    done
  done
  echo "Configuring Cloud Run roles/run.invoker bindings on {{ service_name }}..."
  for INVOKER in \
    "$MEMBER" \
    "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    "serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
    "serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-discoveryengine.iam.gserviceaccount.com"; do
    if ! gcloud run services add-iam-policy-binding "{{ service_name }}" \
      --project="$PROJECT_ID" \
      --region="$REGION" \
      --member="$INVOKER" \
      --role="roles/run.invoker" \
      --quiet >/dev/null; then
      echo "WARNING: could not grant roles/run.invoker on {{ service_name }} to $INVOKER"
      WARNINGS=$((WARNINGS + 1))
    fi
  done
  # Removing allUsers fails harmlessly when the binding does not exist.
  gcloud run services remove-iam-policy-binding "{{ service_name }}" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --member="allUsers" \
    --role="roles/run.invoker" \
    --quiet >/dev/null 2>&1 || true
  if [ "$WARNINGS" -gt 0 ]; then
    echo "IAM configuration finished with $WARNINGS warning(s); review the output above."
  else
    echo "IAM configuration complete."
  fi

# Register the deployed Cloud Run Hairpin MCP proxy in Gemini Enterprise
register-connector *args:
  uv run gement-mcp-tool-filter-poc register-connector "$@"

# List MCP connectors registered in Gemini Enterprise Agent Registry
list-connectors *args:
  uv run gement-mcp-tool-filter-poc list-connectors "$@"

# List MCP connectors in JSON format
list-connectors-json *args:
  uv run gement-mcp-tool-filter-poc list-connectors --json "$@"

# Run vanilla ADK agent locally against the Hairpin MCP connector
run-agent prompt="What tools are available to you in SecOps?" *args:
  uv run gement-mcp-tool-filter-poc run-agent "$@"

# Deploy vanilla ADK agent using the Hairpin MCP connector to Vertex AI Agent Engine
deploy-reasoning-engine *args:
  uv run gement-mcp-tool-filter-poc deploy-reasoning-engine "$@"

# Delete the Cloud Run service, the Gemini Enterprise connector, and the
# reasoning engine named by REASONING_ENGINE_ID; print what remains
teardown service_name="secops-hairpin-mcp" collection_id="secops-hairpin-mcp":
  #!/usr/bin/env bash
  set -e
  PROJECT_ID="${GCP_PROJECT_ID:-your-gcp-project-id}"
  REGION="${GCP_LOCATION:-us-central1}"
  ACCESS_TOKEN="$(gcloud auth print-access-token)"
  if [ -n "${REASONING_ENGINE_ID:-}" ]; then
    ENGINE_NAME="${REASONING_ENGINE_ID}"
    case "$ENGINE_NAME" in
      projects/*) ;;
      *) ENGINE_NAME="projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${ENGINE_NAME}" ;;
    esac
    echo "Deleting reasoning engine ${ENGINE_NAME}..."
    curl -sS -X DELETE \
      -H "Authorization: Bearer ${ACCESS_TOKEN}" \
      -w "HTTP %{http_code}\n" \
      "https://${REGION}-aiplatform.googleapis.com/v1beta1/${ENGINE_NAME}?force=true"
  else
    echo "REASONING_ENGINE_ID is not set; skipping reasoning engine deletion."
  fi
  echo "Deleting Gemini Enterprise connector collection {{ collection_id }}..."
  curl -sS -X DELETE \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "X-Goog-User-Project: ${PROJECT_ID}" \
    -w "HTTP %{http_code}\n" \
    "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_ID}/locations/global/collections/{{ collection_id }}"
  echo "Deleting Cloud Run service {{ service_name }}..."
  gcloud run services delete "{{ service_name }}" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --quiet || echo "WARNING: could not delete Cloud Run service {{ service_name }}"
  echo
  echo "Not deleted (remove manually when no longer needed):"
  echo "  Staging bucket:   gcloud storage rm -r \"${GCP_STAGING_BUCKET:-gs://${PROJECT_ID}-agent-engine-staging}\""
  echo "  Container images: gcloud artifacts docker images delete \"${REGION}-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy/{{ service_name }}\" --delete-tags --quiet"
  echo "  Build sources:    gcloud storage rm -r \"gs://run-sources-${PROJECT_ID}-${REGION}/services/{{ service_name }}\""
  echo "Connector deletion runs as a long-running operation and can take a few minutes to finish."

# Clean build artifacts, bytecode, and test caches
clean:
  find . -type f -name "*.pyc" -delete
  find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
  rm -rf .pytest_cache .pytype .mypy_cache .ruff_cache .coverage htmlcov dist build *.egg-info
