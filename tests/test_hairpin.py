"""Unit tests for the Hairpin MCP proxy and agent factory."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from gement_mcp_tool_filter_poc.agent import create_agent
from gement_mcp_tool_filter_poc.hairpin import STRIPPED_INPUT_SCHEMA
from gement_mcp_tool_filter_poc.hairpin import build_mcp_auth_headers
from gement_mcp_tool_filter_poc.hairpin import hairpin_app
from gement_mcp_tool_filter_poc.hairpin import proxy
from gement_mcp_tool_filter_poc.hairpin import sanitize_tools_list_response
from gement_mcp_tool_filter_poc.hairpin import strip_tool_schemas
from gement_mcp_tool_filter_poc.server import app as server_app


def test_strip_tool_schemas_removes_both_input_and_output():
  raw_tool = {
      "name": "get_case",
      "description": "Retrieves a single case by its resource name.",
      "annotations": {"readOnlyHint": True},
      "inputSchema": {
          "type": "object",
          "properties": {"caseId": {"type": "string"}},
          "required": ["caseId"],
      },
      "outputSchema": {
          "type": "object",
          "properties": {"name": {"type": "string"}},
      },
  }

  stripped = strip_tool_schemas(raw_tool, strip_input=True, strip_output=True)
  assert stripped["name"] == "get_case"
  assert (
      stripped["description"] == "Retrieves a single case by its resource name."
  )
  assert stripped["annotations"] == {"readOnlyHint": True}
  assert "outputSchema" not in stripped
  assert stripped["inputSchema"] == STRIPPED_INPUT_SCHEMA


def test_sanitize_tools_list_response():
  rpc = {
      "jsonrpc": "2.0",
      "id": 42,
      "result": {
          "tools": [
              {
                  "name": "create_feed",
                  "description": "Creates a feed.",
                  "inputSchema": {"type": "object", "properties": {"a": {}}},
                  "outputSchema": {"type": "object", "properties": {"b": {}}},
              }
          ]
      },
  }
  sanitized = sanitize_tools_list_response(rpc)
  tool = sanitized["result"]["tools"][0]
  assert "outputSchema" not in tool
  assert tool["inputSchema"] == STRIPPED_INPUT_SCHEMA


@pytest.mark.asyncio
async def test_create_agent_with_hairpin_url():
  agent = create_agent(mcp_url="https://example.com/mcp")
  assert agent.name == "secops_hairpin_agent"
  assert server_app is hairpin_app


def test_hairpin_http_endpoints():
  sample_raw_tools = [
      {
          "name": "get_case",
          "description": "Gets a case.",
          "annotations": {"readOnlyHint": True},
          "inputSchema": {
              "type": "object",
              "properties": {"caseId": {"type": "string"}},
          },
          "outputSchema": {
              "type": "object",
              "properties": {"case": {"type": "object"}},
          },
      }
  ]

  with patch.object(
      proxy,
      "fetch_raw_tools",
      new=AsyncMock(return_value=sample_raw_tools),
  ):
    client = TestClient(hairpin_app)

    r_root = client.get("/")
    assert r_root.status_code == 200
    assert r_root.json()["status"] == "ok"

    r_health = client.get("/healthz")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    r_stats = client.get("/stats")
    assert r_stats.status_code == 200
    stats_data = r_stats.json()
    assert stats_data["tool_count"] == 1
    assert (
        stats_data["input_and_output_schema_stripped_bytes"]
        < stats_data["raw_tools_list_bytes"]
    )

    r_mcp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert r_mcp.status_code == 200
    mcp_tool = r_mcp.json()["result"]["tools"][0]
    assert "outputSchema" not in mcp_tool
    assert mcp_tool["inputSchema"] == STRIPPED_INPUT_SCHEMA


def test_build_mcp_auth_headers_and_forwarded_oauth():
  mock_creds = MagicMock()
  mock_creds.token = "fake-token"  # noqa: S105
  mock_creds.id_token = None

  with (
      patch(
          "gement_mcp_tool_filter_poc.hairpin.google.auth.default",
          return_value=(mock_creds, "your-gcp-project-id"),
      ),
      patch(
          "gement_mcp_tool_filter_poc.hairpin.id_token.fetch_id_token",
          return_value="eyJ-fake-oidc-token",
      ),
  ):
    google_headers = build_mcp_auth_headers(
        "https://us-chronicle.googleapis.com/mcp",
        project_id="your-gcp-project-id",
    )
    assert google_headers["Authorization"] == "Bearer fake-token"
    assert google_headers["X-Goog-User-Project"] == "your-gcp-project-id"
    assert "X-Forwarded-Authorization" not in google_headers

    run_headers = build_mcp_auth_headers(
        "https://secops-hairpin-mcp-123456789012.us-central1.run.app/mcp",
        project_id="your-gcp-project-id",
    )
    assert run_headers["Authorization"] == "Bearer eyJ-fake-oidc-token"
    assert run_headers["X-Forwarded-Authorization"] == "Bearer fake-token"
    assert run_headers["X-Goog-User-Project"] == "your-gcp-project-id"

  resolved = proxy._resolve_oauth_bearer(  # pylint: disable=protected-access
      incoming_auth="Bearer eyJ-fake-oidc-token",
      incoming_forwarded_auth="Bearer forwarded-oauth-access-token",
  )
  assert resolved == "Bearer forwarded-oauth-access-token"
