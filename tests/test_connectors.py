"""Unit tests for Gemini Enterprise Hairpin MCP connector discovery and registration."""

from unittest.mock import MagicMock
from unittest.mock import patch

from typer.testing import CliRunner

from gement_mcp_tool_filter_poc.agent import list_connectors
from gement_mcp_tool_filter_poc.agent import register_hairpin_connector
from gement_mcp_tool_filter_poc.agent import resolve_connector_mcp_url
from gement_mcp_tool_filter_poc.cli import app

runner = CliRunner()


def test_list_connectors_search_success():
  """Verifies list_connectors extracts servers from search_mcp_servers."""
  mock_servers = [
      {
          "displayName": "SecOps Hairpin MCP (Schema Stripped)",
          "mcpServerId": "agentregistry-0000-422e",
          "description": "Hairpin MCP connector",
          "name": "projects/test-proj/locations/global/mcpServers/agentregistry-0000-422e",
      }
  ]

  with patch(
      "gement_mcp_tool_filter_poc.agent.AgentRegistry"
  ) as mock_registry_cls:
    mock_registry_instance = MagicMock()
    mock_registry_instance.search_mcp_servers.return_value = {
        "mcpServers": mock_servers
    }
    mock_registry_cls.return_value = mock_registry_instance

    result = list_connectors(
        project_id="test-proj", location="global", query="secops"
    )
    assert result == mock_servers
    mock_registry_instance.search_mcp_servers.assert_called_once_with(
        search_string="secops", filter_str=None
    )


def test_list_connectors_empty():
  """Verifies list_connectors handles empty response gracefully."""
  with patch(
      "gement_mcp_tool_filter_poc.agent.AgentRegistry"
  ) as mock_registry_cls:
    mock_registry_instance = MagicMock()
    mock_registry_instance.search_mcp_servers.return_value = {}
    mock_registry_instance.list_mcp_servers.return_value = {}
    mock_registry_cls.return_value = mock_registry_instance

    result = list_connectors(project_id="test-proj")
    assert result == []


def test_resolve_connector_mcp_url():
  """Verifies resolve_connector_mcp_url reads instance_uri from Discovery Engine."""
  mock_creds = MagicMock()
  mock_creds.token = "fake-token"  # noqa: S105
  mock_resp = MagicMock()
  mock_resp.status_code = 200
  mock_resp.json.return_value = {
      "actionConfig": {
          "actionParams": {
              "instance_uri": "https://secops-hairpin-mcp-123.us-central1.run.app/mcp"
          }
      }
  }

  with (
      patch(
          "gement_mcp_tool_filter_poc.agent.default",
          return_value=(mock_creds, "test-proj"),
      ),
      patch(
          "gement_mcp_tool_filter_poc.agent.httpx.get", return_value=mock_resp
      ),
  ):
    url = resolve_connector_mcp_url(
        project_id="test-proj",
        location="global",
        mcp_server_name="secops-hairpin-mcp",
    )
    assert url == "https://secops-hairpin-mcp-123.us-central1.run.app/mcp"


def test_register_hairpin_connector():
  """Verifies register_hairpin_connector calls Discovery Engine setUpDataConnector."""
  mock_creds = MagicMock()
  mock_creds.token = "fake-token"  # noqa: S105
  mock_resp = MagicMock()
  mock_resp.status_code = 200
  mock_resp.json.return_value = {
      "name": "projects/123456/locations/global/operations/setup-connector-1"
  }

  with (
      patch(
          "gement_mcp_tool_filter_poc.agent.default",
          return_value=(mock_creds, "test-proj"),
      ),
      patch(
          "gement_mcp_tool_filter_poc.agent.httpx.post", return_value=mock_resp
      ) as mock_post,
  ):
    op = register_hairpin_connector(
        project_id="test-proj",
        project_number="123456",
        hairpin_mcp_url="https://secops-hairpin-mcp-123.us-central1.run.app/mcp",
        collection_id="secops-hairpin-mcp",
    )
    assert "operations/setup-connector-1" in op["name"]
    mock_post.assert_called_once()


def test_cli_list_connectors_table():
  """Verifies CLI list-connectors outputs formatted table."""
  mock_servers = [
      {
          "displayName": "SecOps Hairpin MCP",
          "mcpServerId": "secops-1234",
          "description": "SecOps Tools",
          "name": "projects/test-proj/locations/global/mcpServers/secops-1234",
      }
  ]

  with patch(
      "gement_mcp_tool_filter_poc.agent.list_connectors",
      return_value=mock_servers,
  ):
    result = runner.invoke(app, ["list-connectors", "--project", "test-proj"])
    assert result.exit_code == 0
    assert "SecOps Hairpin MCP" in result.output
    assert "secops-1234" in result.output


def test_cli_register_connector():
  """Verifies CLI register-connector invokes register_hairpin_connector."""
  with patch(
      "gement_mcp_tool_filter_poc.agent.register_hairpin_connector",
      return_value={"name": "operations/123", "done": False},
  ):
    result = runner.invoke(
        app,
        [
            "register-connector",
            "--project",
            "test-proj",
            "--hairpin-url",
            "https://secops-hairpin-mcp-123.us-central1.run.app/mcp",
        ],
    )
    assert result.exit_code == 0
    assert '"name": "operations/123"' in result.output
