"""Unit tests for Gemini Enterprise Hairpin MCP connector discovery and registration."""

from unittest.mock import MagicMock
from unittest.mock import patch

from typer.testing import CliRunner

from secops_hairpin_mcp.agent import ensure_staging_bucket
from secops_hairpin_mcp.agent import list_connectors
from secops_hairpin_mcp.agent import register_hairpin_connector
from secops_hairpin_mcp.agent import resolve_connector_mcp_url
from secops_hairpin_mcp.agent import resolve_mcp_endpoint
from secops_hairpin_mcp.cli import app

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

  with patch("secops_hairpin_mcp.agent.AgentRegistry") as mock_registry_cls:
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
  with patch("secops_hairpin_mcp.agent.AgentRegistry") as mock_registry_cls:
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
          "secops_hairpin_mcp.agent.default",
          return_value=(mock_creds, "test-proj"),
      ),
      patch("secops_hairpin_mcp.agent.httpx.get", return_value=mock_resp),
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
          "secops_hairpin_mcp.agent.default",
          return_value=(mock_creds, "test-proj"),
      ),
      patch(
          "secops_hairpin_mcp.agent.httpx.post", return_value=mock_resp
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
      "secops_hairpin_mcp.agent.list_connectors",
      return_value=mock_servers,
  ):
    result = runner.invoke(app, ["list-connectors", "--project", "test-proj"])
    assert result.exit_code == 0
    assert "SecOps Hairpin MCP" in result.output
    assert "secops-1234" in result.output


def test_cli_register_connector():
  """Verifies CLI register-connector invokes register_hairpin_connector."""
  with patch(
      "secops_hairpin_mcp.agent.register_hairpin_connector",
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


def _fake_storage_module(bucket_exists: bool) -> tuple[MagicMock, MagicMock]:
  """Builds a stand-in for google.cloud.storage with a canned lookup result."""
  mock_client = MagicMock()
  mock_client.lookup_bucket.return_value = (
      MagicMock() if bucket_exists else None
  )
  mock_storage = MagicMock()
  mock_storage.Client.return_value = mock_client
  return mock_storage, mock_client


def test_ensure_staging_bucket_creates_missing_bucket():
  """Verifies the staging bucket is created when lookup finds nothing."""
  mock_storage, mock_client = _fake_storage_module(bucket_exists=False)

  with patch.dict("sys.modules", {"google.cloud.storage": mock_storage}):
    created = ensure_staging_bucket(
        "test-proj", "gs://test-proj-agent-engine-staging", "us-central1"
    )

  assert created is True
  mock_client.lookup_bucket.assert_called_once_with(
      "test-proj-agent-engine-staging"
  )
  mock_client.create_bucket.assert_called_once_with(
      "test-proj-agent-engine-staging", location="us-central1"
  )


def test_ensure_staging_bucket_keeps_existing_bucket():
  """Verifies no bucket is created when it already exists."""
  mock_storage, mock_client = _fake_storage_module(bucket_exists=True)

  with patch.dict("sys.modules", {"google.cloud.storage": mock_storage}):
    created = ensure_staging_bucket(
        "test-proj", "test-proj-agent-engine-staging", "us-central1"
    )

  assert created is False
  mock_client.create_bucket.assert_not_called()


def test_resolve_mcp_endpoint_precedence(monkeypatch):
  """Verifies flag, then HAIRPIN_MCP_URL, then connector lookup."""
  monkeypatch.setenv("HAIRPIN_MCP_URL", "https://env.example.com/mcp")
  assert resolve_mcp_endpoint("https://flag.example.com/mcp", "test-proj") == (
      "https://flag.example.com/mcp",
      "explicit --mcp-url",
  )
  assert resolve_mcp_endpoint(None, "test-proj") == (
      "https://env.example.com/mcp",
      "HAIRPIN_MCP_URL",
  )

  monkeypatch.delenv("HAIRPIN_MCP_URL")
  monkeypatch.setenv("MCP_SERVER_NAME", "secops-hairpin-mcp")
  with patch(
      "secops_hairpin_mcp.agent.resolve_connector_mcp_url",
      return_value="https://run.example.com/mcp",
  ) as mock_resolve:
    url, source = resolve_mcp_endpoint(None, "test-proj")
  assert url == "https://run.example.com/mcp"
  assert source == "Gemini Enterprise connector secops-hairpin-mcp"
  mock_resolve.assert_called_once_with(
      project_id="test-proj",
      location="global",
      mcp_server_name="secops-hairpin-mcp",
  )

  with patch(
      "secops_hairpin_mcp.agent.resolve_connector_mcp_url",
      return_value=None,
  ):
    url, source = resolve_mcp_endpoint(None, "test-proj")
  assert url is None
  assert source.endswith("(not resolved)")
