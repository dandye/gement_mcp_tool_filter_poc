# Gemini Enterprise Hairpin MCP Proxy for Google SecOps

When you connect an Agent Development Kit (ADK) agent or Gemini Enterprise connector directly to the Google Security Operations OneMCP server at `https://us-chronicle.googleapis.com/mcp`, the `tools/list` response returns 71 tools totaling 4.13 MB of JSON (`3.74 MB` of `outputSchema` and `243 KB` of `inputSchema`).

When ADK converts those MCP tool definitions into Gemini function declarations, it passes both `inputSchema` and `outputSchema` to Vertex AI. Vertex AI rejects the request with `400 INVALID_ARGUMENT` because the combined schemas exceed the model's schema state limit.

This repository provides a **Hairpin MCP Proxy** on Cloud Run that unblocks using Gemini Enterprise MCP connectors with Google SecOps OneMCP:
1. **Strips bloated schemas server-side**: Forwards JSON-RPC 2.0 requests to `https://us-chronicle.googleapis.com/mcp`, removes `outputSchema` from `tools/list`, and replaces `inputSchema` with an open object stub (`{"type": "object", "additionalProperties": true}`).
2. **Reduces `tools/list` payload by 96.52%**: Shrinks the `tools/list` payload from `4,125,239 bytes` (`4.13 MB`) to `143,464 bytes` (`143.5 KB`) while preserving all 71 tool names, descriptions, and annotations.
3. **Registers as a Gemini Enterprise connector**: Registers in Discovery Engine as a `custom_mcp` (`BYO_MCP`) connector and syncs automatically to the Gemini Enterprise Agent Registry catalog.
4. **Enforces Cloud Run IAM (`--no-allow-unauthenticated`)**: Requires `roles/run.invoker` with an OIDC ID token in `Authorization` while forwarding the caller's OAuth 2.0 access token to OneMCP via `X-Forwarded-Authorization`.

```mermaid
flowchart LR
    Agent["ADK Agent / Vertex AI Agent Engine"] -->|1. Resolve connector URL| GE["Gemini Enterprise\n(Agent Registry & Discovery Engine)"]
    Agent -->|2. JSON-RPC 2.0 + OIDC & OAuth| Proxy["Cloud Run Hairpin MCP Proxy\nPOST /mcp (--no-allow-unauthenticated)"]
    Proxy -->|3. Forward JSON-RPC 2.0| OneMCP["Google SecOps OneMCP\nhttps://us-chronicle.googleapis.com/mcp"]
    OneMCP -->|4.13 MB tools/list| Proxy
    Proxy -->|143.5 KB stripped tools/list| Agent
```

---

## Prerequisites

Local tools: [`gcloud`](https://cloud.google.com/sdk/docs/install), [`uv`](https://docs.astral.sh/uv/), [`just`](https://just.systems/), [`direnv`](https://direnv.net/), `curl`, and `jq` (verification commands). `uv` installs Python 3.11 on demand.

Google Cloud project state:

- A Google SecOps (Chronicle) instance linked to the project, and Gemini Enterprise available in the project. Confirm with your Google account team that the project can register custom (`BYO_MCP`) connectors and call the SecOps OneMCP endpoint.
- APIs enabled:

```bash
PROJECT_ID="your-gcp-project-id"
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  discoveryengine.googleapis.com agentregistry.googleapis.com \
  aiplatform.googleapis.com chronicle.googleapis.com storage.googleapis.com \
  --project="$PROJECT_ID"
```

- An operator account that can deploy Cloud Run services, grant project IAM bindings (`just setup-iam` edits the project policy), create Cloud Storage buckets, and create Discovery Engine collections and Vertex AI reasoning engines. `roles/owner` on a sandbox project satisfies all of these.

---

## Quickstart: Repeat the Hairpin MCP setup

### 1. Initialize local environment

```bash
just setup
direnv allow .
```

`.envrc` activates `./.venv` and isolates gcloud configuration and Application Default Credentials to `./.gcloud` (gitignored). Edit `.env` and set `GCP_PROJECT_ID`; `CHRONICLE_CUSTOMER_ID` is only substituted into example prompts and verification commands, and `GCP_PROJECT_NUMBER`, `CLOUDSDK_CORE_ACCOUNT`, and `GCP_STAGING_BUCKET` are optional. Then authenticate once from inside the repository directory so the credentials land in the isolated configuration:

```bash
ACCOUNT="user@example.com"
gcloud auth login "$ACCOUNT" --update-adc
```

In non-interactive shells (CI, scripts, coding agents) the direnv hook does not run; prefix commands with `direnv exec .` to load the same environment.

### 2. Deploy the Hairpin MCP proxy to Cloud Run

Deploy the FastAPI proxy (`src/secops_hairpin_mcp/hairpin.py`) to Cloud Run with `--no-allow-unauthenticated`:

```bash
SERVICE_NAME="secops-hairpin-mcp"
just deploy-cloud-run "$SERVICE_NAME"
```

### 3. Configure IAM and Cloud Run invoker bindings

`just setup-iam` grants `roles/discoveryengine.viewer`, `roles/agentregistry.viewer`, `roles/chronicle.viewer`, `roles/aiplatform.user`, `roles/mcp.toolUser`, and `roles/serviceusage.serviceUsageConsumer` on the project to your account, the default compute service account (the Cloud Run runtime identity), and the Vertex AI Agent Engine service agent. It then grants `roles/run.invoker` on the service to those identities and the Discovery Engine service agent, and removes any `allUsers` invoker binding:

```bash
ACCOUNT="user@example.com"
SERVICE_NAME="secops-hairpin-mcp"
just setup-iam "$ACCOUNT" "$SERVICE_NAME"
```

The flow was validated in a project where some of these bindings already existed. If a later step fails with `PERMISSION_DENIED`, the error names the missing permission; add the corresponding role for the identity shown in the error and rerun the step.

Retrieve the deployed Cloud Run URL and set `HAIRPIN_MCP_URL` in `.env`:

```bash
PROJECT_ID="your-gcp-project-id"
REGION="us-central1"
SERVICE_NAME="secops-hairpin-mcp"
SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')"
HAIRPIN_MCP_URL="${SERVICE_URL}/mcp"
echo "HAIRPIN_MCP_URL=$HAIRPIN_MCP_URL"
```

### 4. Register the Hairpin MCP connector in Gemini Enterprise

Register the Cloud Run `/mcp` endpoint as a `custom_mcp` (`BYO_MCP`) connector in Discovery Engine (`collections:setUpDataConnector`). The `--hairpin-url` flag is only needed when `HAIRPIN_MCP_URL` is not yet set in `.env`:

```bash
just register-connector --hairpin-url "$HAIRPIN_MCP_URL"
```

Verify that the connector is synced into Gemini Enterprise Agent Registry (the entry appears as `Custom MCP Server - secops-hairpin-mcp`, usually within a minute):

```bash
just list-connectors
```

### 5. Run the ADK agent locally or deploy to Vertex AI Agent Engine

Run a test prompt locally against the registered Gemini Enterprise Hairpin MCP connector:

```bash
just run-agent "What SecOps tools do you have access to?"
```

Deploy the unmodified ADK agent to Vertex AI Agent Engine (Reasoning Engine):

```bash
DISPLAY_NAME="secops-hairpin-mcp-vanilla-agent"
just deploy-reasoning-engine --display-name "$DISPLAY_NAME"
```

Agent Engine uploads the packaged agent to a Cloud Storage staging bucket (`GCP_STAGING_BUCKET` in `.env`, default `gs://<GCP_PROJECT_ID>-agent-engine-staging`). The command creates the bucket in the deployment region if it does not exist yet. Copy the printed resource name into `REASONING_ENGINE_ID` in `.env`; the verification commands in [`docs/deployment.md`](./docs/deployment.md) and `just teardown` read it from there.

### 6. Teardown

Delete the reasoning engine named by `REASONING_ENGINE_ID`, the Discovery Engine collection (which removes the Agent Registry entry), and the Cloud Run service:

```bash
SERVICE_NAME="secops-hairpin-mcp"
COLLECTION_ID="secops-hairpin-mcp"
just teardown "$SERVICE_NAME" "$COLLECTION_ID"
```

The recipe leaves the staging bucket, the container images in Artifact Registry, and the Cloud Build source uploads in place and prints the commands that remove them.

---

## Security notes

- The service is deployed with `--no-allow-unauthenticated`. Only identities with `roles/run.invoker` on the service can reach it; Cloud Run verifies the OIDC ID token in `Authorization` before the container sees the request.
- The proxy calls OneMCP with the OAuth 2.0 access token from `X-Forwarded-Authorization` when present (the ADK agent and Agent Engine send it), so SecOps enforces the end user's Chronicle permissions. When no token is forwarded, the proxy falls back to the Cloud Run runtime service account's credentials. Any invoker that omits the header therefore acts with that service account's Chronicle role (`roles/chronicle.viewer` as granted by `just setup-iam`); keep the invoker list short.
- `tools/list` responses are cached in the container for 300 seconds and shared across callers; `tools/call` requests are never cached.
- Stripping can be disabled per request for comparison with `POST /mcp?strip_input=false&strip_output=false`. `POST /` is an alias for `POST /mcp`.

---

## Documentation

- [Customer guide: Deploying a Hairpin MCP proxy for Gemini Enterprise (`docs/hairpin_mcp_deployment_guide.md`)](./docs/hairpin_mcp_deployment_guide.md)
- [Deployment inventory, IAM bindings, and verification runbook (`docs/deployment.md`)](./docs/deployment.md)

---

## Repository structure

```text
.
├── .env.example          # Environment variable template
├── Dockerfile            # Cloud Run container definition for the Hairpin MCP proxy
├── AGENTS.md             # Repository coding standards (Google Python Style Guide)
├── justfile              # Task runner recipes
├── pyproject.toml        # Project dependencies and Pyink/Ruff/Pytype config
├── docs/
│   ├── deployment.md                   # Deployment inventory and verification runbook
│   └── hairpin_mcp_deployment_guide.md # Standalone step-by-step customer guide
├── src/
│   └── secops_hairpin_mcp/
│       ├── agent.py      # Gemini Enterprise connector resolution & ADK agent factory
│       ├── cli.py        # Typer + Rich CLI
│       ├── hairpin.py    # Cloud Run Hairpin MCP proxy server
│       └── server.py     # ASGI entrypoint for Cloud Run (uvicorn)
└── tests/
    ├── test_connectors.py # Unit tests for connector discovery and registration
    └── test_hairpin.py    # Unit tests for schema stripping and proxy endpoints
```

---

## Just recipes reference

| Recipe | Description |
| :--- | :--- |
| `just setup` | Create `.env` from template and sync `uv` dependencies |
| `just sync` | Synchronize virtual environment with lockfile |
| `just deploy-cloud-run [service_name]` | Deploy the Hairpin MCP proxy to Cloud Run (`--no-allow-unauthenticated`) |
| `just setup-iam [account] [service_name]` | Configure GCP project IAM roles and Cloud Run `roles/run.invoker` bindings |
| `just register-connector` | Register the Cloud Run Hairpin MCP proxy in Gemini Enterprise Discovery Engine |
| `just list-connectors` | List Gemini Enterprise MCP connectors in table view |
| `just list-connectors-json` | List MCP connectors in JSON format |
| `just run-agent [prompt]` | Run the vanilla ADK agent locally against the Hairpin MCP connector |
| `just deploy-reasoning-engine` | Deploy the vanilla ADK agent to Vertex AI Agent Engine |
| `just teardown [service_name] [collection_id]` | Delete the reasoning engine (`REASONING_ENGINE_ID`), connector collection, and Cloud Run service |
| `just test` | Run pytest unit test suite |
| `just format` | Format code in-place with Pyink (2 spaces, 80 columns) |
| `just lint` | Run Ruff checks and Pyink format verification |
| `just typecheck` | Run Google Pytype static type analysis |
| `just clean` | Remove caches, coverage reports, and build artifacts |
