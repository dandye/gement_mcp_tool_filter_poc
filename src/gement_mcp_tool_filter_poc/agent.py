"""Gemini Enterprise connector helpers and ADK agent factory for Hairpin MCP."""

import logging
import os
from typing import Any

import google.auth.transport.requests
import httpx
from google.adk.agents import Agent
from google.adk.integrations.agent_registry import AgentRegistry
from google.adk.models import Gemini
from google.adk.tools.base_toolset import BaseToolset
from google.auth import default
from google.genai import types

from gement_mcp_tool_filter_poc.hairpin import build_mcp_auth_headers

logger = logging.getLogger(__name__)

DEFAULT_LOCATION = "global"
DEFAULT_MCP_SERVER_NAME = "secops-hairpin-mcp"
DEFAULT_PROJECT_ID = "your-gcp-project-id"


def resolve_connector_mcp_url(
    project_id: str,
    location: str = DEFAULT_LOCATION,
    mcp_server_name: str = DEFAULT_MCP_SERVER_NAME,
) -> str | None:
  """Resolves the live MCP instance_uri for a registered Gemini Enterprise connector.

  Queries Agent Registry and Discovery Engine dataConnector metadata to extract
  the underlying BYO_MCP instance_uri when connecting to a custom_mcp connector.

  Args:
    project_id: GCP project ID or number.
    location: Connector location (for example, 'global').
    mcp_server_name: Agent Registry server ID or Discovery Engine collection ID.

  Returns:
    Resolved HTTP MCP endpoint URL, or None if not found.
  """
  collection_id = mcp_server_name.split("/")[-1]
  try:
    if collection_id.startswith("agentregistry-"):
      registry = AgentRegistry(project_id=project_id, location=location)
      full_name = (
          mcp_server_name
          if mcp_server_name.startswith("projects/")
          else (
              f"projects/{project_id}/locations/{location}/"
              f"mcpServers/{collection_id}"
          )
      )
      server = registry.get_mcp_server(full_name)
      if isinstance(server, dict):
        attrs = server.get("attributes", {})
        runtime_ref = attrs.get(
            "agentregistry.googleapis.com/system/RuntimeReference", {}
        )
        uri = runtime_ref.get("uri", "")
        if "/collections/" in uri:
          collection_id = uri.split("/collections/")[1].split("/")[0]

    creds, _ = default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    dc_url = (
        f"https://discoveryengine.googleapis.com/v1alpha/projects/{project_id}/"
        f"locations/{location}/collections/{collection_id}/dataConnector"
    )
    resp = httpx.get(
        dc_url,
        headers={
            "Authorization": f"Bearer {creds.token}",
            "X-Goog-User-Project": project_id,
        },
        timeout=15.0,
    )
    if resp.status_code == 200:
      dc = resp.json()
      instance_uri = dc.get("actionConfig", {}).get("actionParams", {}).get(
          "instance_uri"
      ) or dc.get("params", {}).get("instance_uri")
      if isinstance(instance_uri, str) and instance_uri.startswith("http"):
        return instance_uri
  except Exception as e:
    logger.debug(
        "Could not resolve instance_uri for %s: %s", mcp_server_name, e
    )
  return None


def register_hairpin_connector(
    project_id: str,
    hairpin_mcp_url: str,
    collection_id: str = DEFAULT_MCP_SERVER_NAME,
    display_name: str = "SecOps Hairpin MCP (Schema Stripped)",
    project_number: str | None = None,
    location: str = DEFAULT_LOCATION,
) -> dict[str, Any]:
  """Registers a Hairpin MCP proxy URL as a Gemini Enterprise connector.

  Calls Discovery Engine setUpDataConnector with dataSource='custom_mcp' and
  mcp_server_source='BYO_MCP'. Discovery Engine automatically syncs the
  resulting connector into the Gemini Enterprise Agent Registry catalog.

  Args:
    project_id: GCP project ID for X-Goog-User-Project billing/quota.
    hairpin_mcp_url: Cloud Run Hairpin MCP endpoint URL (ending in /mcp).
    collection_id: Discovery Engine collection ID to create.
    display_name: Human-readable display name for the connector.
    project_number: Optional GCP project number (defaults to project_id).
    location: Discovery Engine location (defaults to 'global').

  Returns:
    Long-running operation dictionary returned by Discovery Engine.
  """
  creds, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
  creds.refresh(google.auth.transport.requests.Request())
  target_project = project_number or project_id
  url = (
      "https://discoveryengine.googleapis.com/v1alpha/projects/"
      f"{target_project}/locations/{location}:setUpDataConnector"
  )
  payload = {
      "collectionId": collection_id,
      "collectionDisplayName": display_name,
      "dataConnector": {
          "dataSource": "custom_mcp",
          "params": {
              "oauth_access_token": "unused",
          },
          "actionConfig": {
              "actionParams": {
                  "auth_type": "NO_AUTH",
                  "instance_uri": hairpin_mcp_url,
                  "mcp_server_source": "BYO_MCP",
              }
          },
          "connectorModes": ["FEDERATED", "ACTIONS"],
      },
  }
  resp = httpx.post(
      url,
      headers={
          "Authorization": f"Bearer {creds.token}",
          "Content-Type": "application/json",
          "X-Goog-User-Project": project_id,
      },
      json=payload,
      timeout=30.0,
  )
  resp.raise_for_status()
  return resp.json()


def create_agent(
    name: str = "secops_hairpin_agent",
    mcp_url: str | None = None,
    project_id: str | None = None,
    location: str | None = None,
    mcp_server_name: str | None = None,
) -> Agent:
  """Constructs a standard ADK agent connected to the Hairpin MCP connector.

  Requires zero client-side tool filtering or schema pruning wrappers because
  the Hairpin MCP proxy strips bloated inputSchema and outputSchema payloads
  server-side on tools/list.

  Args:
    name: Name of the agent.
    mcp_url: Optional direct Streamable HTTP MCP URL (for example, the Cloud Run
      Hairpin MCP endpoint). When omitted, resolves the MCP URL from the
      registered Gemini Enterprise connector in Agent Registry or Discovery
      Engine.
    project_id: GCP project ID.
    location: Agent Registry location.
    mcp_server_name: Agent Registry MCP server resource name, ID, or Discovery
      Engine collection ID (defaults to 'secops-hairpin-mcp').

  Returns:
    Configured ADK Agent instance.
  """
  from google.adk.tools.mcp_tool.mcp_session_manager import (
      StreamableHTTPConnectionParams,
  )
  from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

  os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
  os.environ["GOOGLE_API_USE_CLIENT_CERTIFICATE"] = "false"
  os.environ["GOOGLE_API_USE_MTLS_ENDPOINT"] = "never"
  os.environ["CLOUDSDK_CONTEXT_AWARE_USE_CLIENT_CERTIFICATE"] = "false"

  if not project_id:
    _, default_project = default()
    project_id = os.environ.get(
        "GOOGLE_CLOUD_PROJECT", default_project or DEFAULT_PROJECT_ID
    )
  resolved_location = location or DEFAULT_LOCATION
  resolved_server = mcp_server_name or os.environ.get(
      "MCP_SERVER_NAME", DEFAULT_MCP_SERVER_NAME
  )

  resolved_url = (
      mcp_url
      or os.environ.get("HAIRPIN_MCP_URL")
      or resolve_connector_mcp_url(
          project_id=project_id,
          location=resolved_location,
          mcp_server_name=resolved_server,
      )
  )

  if resolved_url:
    toolset: BaseToolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=resolved_url,
            headers=build_mcp_auth_headers(resolved_url, project_id),
            timeout=30.0,
        ),
        header_provider=lambda _ctx: build_mcp_auth_headers(
            resolved_url, project_id
        ),
    )
  else:
    if resolved_server.startswith("projects/"):
      server_resource_name = resolved_server
    else:
      server_resource_name = (
          f"projects/{project_id}/locations/{resolved_location}/"
          f"mcpServers/{resolved_server}"
      )
    registry = AgentRegistry(project_id=project_id, location=resolved_location)
    toolset = registry.get_mcp_toolset(server_resource_name)

  return Agent(
      name=name,
      description=(
          "You are a helpful Security Operations AI Assistant connected"
          " to the Gemini Enterprise Hairpin MCP connector."
      ),
      model=Gemini(
          model="gemini-2.5-flash",
          retry_options=types.HttpRetryOptions(attempts=3),
      ),
      tools=[toolset],
  )


create_vanilla_mcp_agent = create_agent


def list_connectors(
    project_id: str | None = None,
    location: str | None = None,
    query: str | None = None,
    filter_str: str | None = None,
) -> list[dict[str, Any]]:
  """Lists MCP server connectors in Gemini Enterprise Agent Registry.

  Args:
    project_id: GCP project ID. Defaults to environment or ADC.
    location: Registry location. Defaults to 'global'.
    query: Optional search keyword/query (e.g. 'chronicle', 'secops').
    filter_str: Optional filter expression.

  Returns:
    List of dictionary objects describing registered MCP servers.
  """
  if not project_id:
    _, default_project = default()
    project_id = os.environ.get(
        "GOOGLE_CLOUD_PROJECT", default_project or DEFAULT_PROJECT_ID
    )

  resolved_location = location or DEFAULT_LOCATION

  os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
  os.environ["GOOGLE_API_USE_CLIENT_CERTIFICATE"] = "false"
  os.environ["GOOGLE_API_USE_MTLS_ENDPOINT"] = "never"
  os.environ["CLOUDSDK_CONTEXT_AWARE_USE_CLIENT_CERTIFICATE"] = "false"
  registry = AgentRegistry(project_id=project_id, location=resolved_location)

  search_response = registry.search_mcp_servers(
      search_string=query, filter_str=filter_str
  )
  servers: list[dict[str, Any]] = []
  if isinstance(search_response, dict):
    mcp_list = search_response.get("mcpServers", [])
    if isinstance(mcp_list, list):
      servers = list(mcp_list)

  if not servers and not query:
    list_response = registry.list_mcp_servers(filter_str=filter_str)
    if isinstance(list_response, dict):
      mcp_list = list_response.get(
          "mcpServers", list_response.get("servers", [])
      )
      if isinstance(mcp_list, list):
        servers = list(mcp_list)

  if not servers and resolved_location == "global":
    try:
      us_registry = AgentRegistry(project_id=project_id, location="us")
      us_response = us_registry.search_mcp_servers(
          search_string=query, filter_str=filter_str
      )
      if isinstance(us_response, dict):
        mcp_list = us_response.get("mcpServers", [])
        if isinstance(mcp_list, list):
          servers = list(mcp_list)
    except Exception as e:
      logger.debug("Failed checking fallback location 'us': %s", e)

  return servers
