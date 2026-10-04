"""CLI for deploying and using the Gemini Enterprise Hairpin MCP proxy."""

from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console

# Resolve repo root (src/gement_mcp_tool_filter_poc/cli.py -> parents[2])
REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")

console = Console()

app = typer.Typer(
    name="gement-mcp-tool-filter-poc",
    help="CLI for the Gemini Enterprise Hairpin MCP Proxy and ADK Agent",
    add_completion=True,
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.callback()
def main_callback() -> None:
  """Gemini Enterprise Hairpin MCP CLI operations."""


@app.command("list-connectors")
def list_connectors_cmd(
    project: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="GCP project ID (defaults to GOOGLE_CLOUD_PROJECT or ADC)",
        ),
    ] = None,
    location: Annotated[
        str | None,
        typer.Option(
            "--location",
            "-l",
            help="Agent Registry location (defaults to global)",
        ),
    ] = None,
    query: Annotated[
        str | None,
        typer.Option(
            "--query",
            "-q",
            help="Optional search query (e.g. 'chronicle', 'secops')",
        ),
    ] = None,
    filter_str: Annotated[
        str | None,
        typer.Option(
            "--filter",
            "-f",
            help="Optional filter expression for listing connectors",
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output raw JSON response",
        ),
    ] = False,
) -> None:
  """List MCP connectors registered in Gemini Enterprise Agent Registry."""
  import json

  from rich.table import Table

  from gement_mcp_tool_filter_poc.agent import list_connectors

  try:
    connectors = list_connectors(
        project_id=project,
        location=location,
        query=query,
        filter_str=filter_str,
    )
  except Exception as e:
    console.print(f"[bold red]Failed to list connectors:[/bold red] {e}")
    raise typer.Exit(code=1) from e

  if as_json:
    console.print_json(json.dumps(connectors, indent=2))
    return

  if not connectors:
    console.print("[yellow]No MCP connectors found.[/yellow]")
    return

  table = Table(
      title="Gemini Enterprise MCP Connectors",
      show_header=True,
      header_style="bold magenta",
      show_lines=True,
  )
  table.add_column("Display Name", style="cyan", no_wrap=True)
  table.add_column("Server Resource ID", style="green")
  table.add_column("Tools", style="yellow", justify="right")
  table.add_column("Interface URL", style="white")

  for conn in connectors:
    display_name = conn.get("displayName", "N/A")
    name = conn.get("name", "")
    server_id = name.split("/")[-1] if "/" in name else name
    tools = conn.get("tools", [])
    tools_count = f"{len(tools)} tools" if tools else "N/A"
    interfaces = conn.get("interfaces", [])
    interface_url = interfaces[0].get("url", "N/A") if interfaces else "N/A"

    table.add_row(display_name, server_id, tools_count, interface_url)

  console.print(table)


@app.command("register-connector")
def register_connector_cmd(
    hairpin_url: Annotated[
        str | None,
        typer.Option(
            "--hairpin-url",
            "-u",
            help="Cloud Run Hairpin MCP URL (defaults to HAIRPIN_MCP_URL)",
        ),
    ] = None,
    collection_id: Annotated[
        str,
        typer.Option(
            "--collection-id",
            "-c",
            help="Discovery Engine collection ID to create",
        ),
    ] = "secops-hairpin-mcp",
    display_name: Annotated[
        str,
        typer.Option(
            "--display-name",
            "-d",
            help="Display name for the Gemini Enterprise connector",
        ),
    ] = "SecOps Hairpin MCP (Schema Stripped)",
    project: Annotated[
        str | None,
        typer.Option("--project", "-p", help="GCP project ID"),
    ] = None,
    project_number: Annotated[
        str | None,
        typer.Option("--project-number", "-n", help="GCP project number"),
    ] = None,
    location: Annotated[
        str,
        typer.Option("--location", "-l", help="Discovery Engine location"),
    ] = "global",
) -> None:
  """Register the Cloud Run Hairpin MCP proxy as a Gemini Enterprise connector."""
  import json
  import os

  from gement_mcp_tool_filter_poc.agent import DEFAULT_PROJECT_ID
  from gement_mcp_tool_filter_poc.agent import register_hairpin_connector

  resolved_project = (
      project
      or os.environ.get("GCP_PROJECT_ID")
      or os.environ.get("GOOGLE_CLOUD_PROJECT")
      or DEFAULT_PROJECT_ID
  )
  resolved_number = project_number or os.environ.get("GCP_PROJECT_NUMBER")
  resolved_url = hairpin_url or os.environ.get("HAIRPIN_MCP_URL")
  if not resolved_url:
    console.print(
        "[bold red]Error:[/bold red] Provide --hairpin-url or set"
        " HAIRPIN_MCP_URL in .env"
    )
    raise typer.Exit(code=1)

  console.print(
      "[bold cyan]Registering Hairpin MCP connector in Gemini Enterprise..."
      "[/bold cyan]\n"
      f"  Project: {resolved_project}\n"
      f"  Collection ID: {collection_id}\n"
      f"  Hairpin MCP URL: {resolved_url}"
  )
  try:
    result = register_hairpin_connector(
        project_id=resolved_project,
        hairpin_mcp_url=resolved_url,
        collection_id=collection_id,
        display_name=display_name,
        project_number=resolved_number,
        location=location,
    )
    console.print_json(json.dumps(result, indent=2))
  except Exception as e:
    console.print(f"[bold red]Registration failed:[/bold red] {e}")
    raise typer.Exit(code=1) from e


@app.command("run-agent")
def run_agent_cmd(
    prompt: Annotated[
        str,
        typer.Argument(help="Prompt query for the agent"),
    ] = "What tools are available to you in SecOps?",
    project: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="GCP project ID (defaults to GOOGLE_CLOUD_PROJECT or ADC)",
        ),
    ] = None,
    location: Annotated[
        str | None,
        typer.Option(
            "--location",
            "-l",
            help="Agent Registry location (defaults to global)",
        ),
    ] = None,
    server: Annotated[
        str | None,
        typer.Option(
            "--server",
            "-s",
            help="Gemini Enterprise MCP server ID or collection ID",
        ),
    ] = None,
    mcp_url: Annotated[
        str | None,
        typer.Option(
            "--mcp-url",
            "-u",
            help="Optional direct Hairpin MCP URL override",
        ),
    ] = None,
) -> None:
  """Execute the vanilla ADK agent locally against the Hairpin MCP connector."""
  import asyncio
  import uuid

  from google.adk.runners import InMemoryRunner
  from google.genai import types

  from gement_mcp_tool_filter_poc.agent import create_agent

  console.print(
      "[bold cyan]Initializing ADK agent with Hairpin MCP connector..."
      "[/bold cyan]"
  )

  agent = create_agent(
      mcp_url=mcp_url,
      project_id=project,
      location=location,
      mcp_server_name=server,
  )

  runner = InMemoryRunner(agent=agent)
  user_id = "test-user"
  session_id = f"session-{uuid.uuid4().hex[:8]}"

  async def execute() -> None:
    await runner.session_service.create_session(
        user_id=user_id,
        session_id=session_id,
        app_name=runner.app_name,
    )
    console.print(f"[bold green]Prompt:[/bold green] {prompt}\n")
    console.print("[bold magenta]Agent Response:[/bold magenta]")
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(parts=[types.Part.from_text(text=prompt)]),
    ):
      if event.content and event.content.parts:
        for part in event.content.parts:
          if part.text:
            console.print(part.text, end="")
    console.print()

  try:
    asyncio.run(execute())
  except Exception as e:
    console.print(f"\n[bold red]Execution failed:[/bold red] {e}")
    raise typer.Exit(code=1) from e


@app.command("deploy-reasoning-engine")
def deploy_reasoning_engine_cmd(
    display_name: Annotated[
        str,
        typer.Option(
            "--display-name",
            "-d",
            help="Vertex AI Reasoning Engine display name",
        ),
    ] = "secops-hairpin-mcp-vanilla-agent",
    project: Annotated[
        str | None,
        typer.Option("--project", "-p", help="GCP project ID"),
    ] = None,
    location: Annotated[
        str | None,
        typer.Option("--location", "-l", help="Vertex AI region"),
    ] = None,
    staging_bucket: Annotated[
        str | None,
        typer.Option("--staging-bucket", "-b", help="GCS staging bucket"),
    ] = None,
    server: Annotated[
        str | None,
        typer.Option(
            "--server",
            "-s",
            help="Registered Gemini Enterprise MCP connector ID",
        ),
    ] = None,
) -> None:
  """Deploy a vanilla ADK agent using the Hairpin MCP connector to Agent Engine."""
  import os

  os.environ["GRPC_DNS_RESOLVER"] = "native"

  import vertexai
  from google.auth import default
  from vertexai.preview import reasoning_engines

  from gement_mcp_tool_filter_poc.agent import DEFAULT_PROJECT_ID

  if not project:
    _, default_project = default()
    project = os.environ.get(
        "GOOGLE_CLOUD_PROJECT", default_project or DEFAULT_PROJECT_ID
    )

  resolved_server = (
      server
      or os.environ.get("MCP_SERVER_NAME")
      or "agentregistry-00000000-0000-0000-0000-000000000002"
  )
  region = location or os.environ.get("GCP_LOCATION") or "us-central1"
  bucket = (
      staging_bucket
      or os.environ.get("GCP_STAGING_BUCKET")
      or f"gs://{project}-agent-engine-staging"
  )

  console.print(
      "[bold cyan]Deploying Vanilla Hairpin MCP Agent to Vertex AI Agent"
      " Engine...[/bold cyan]\n"
      f"  Project: {project}\n"
      f"  Region: {region}\n"
      f"  Bucket: {bucket}\n"
      f"  Connector: {resolved_server}\n"
      f"  Display Name: {display_name}"
  )

  vertexai.init(project=project, location=region, staging_bucket=bucket)

  class HairpinVanillaReasoningEngineAgent:
    """Vanilla ADK Agent in Vertex AI Agent Engine using Hairpin MCP connector."""

    def __init__(self, project_id: str, mcp_server_name: str):
      self.project_id = project_id
      self.mcp_server_name = mcp_server_name

    def query(self, prompt: str) -> str:
      import asyncio
      import concurrent.futures
      import os
      import urllib.parse
      import uuid

      import google.auth
      import google.auth.transport.requests
      import httpx
      from google.adk.agents import Agent
      from google.adk.models import Gemini
      from google.adk.runners import InMemoryRunner
      from google.adk.tools.mcp_tool.mcp_session_manager import (
          StreamableHTTPConnectionParams,
      )
      from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
      from google.genai import types
      from google.oauth2 import id_token

      os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

      creds, _ = google.auth.default(
          scopes=["https://www.googleapis.com/auth/cloud-platform"]
      )
      req = google.auth.transport.requests.Request()
      creds.refresh(req)
      auth_headers = {
          "Authorization": f"Bearer {creds.token}",
          "X-Goog-User-Project": self.project_id,
      }

      collection_id = self.mcp_server_name.split("/")[-1]
      if collection_id.startswith("agentregistry-"):
        ar_url = (
            f"https://agentregistry.googleapis.com/v1alpha/projects/"
            f"{self.project_id}/locations/global/mcpServers/{collection_id}"
        )
        ar_resp = httpx.get(ar_url, headers=auth_headers, timeout=15.0)
        if ar_resp.status_code == 200:
          srv = ar_resp.json()
          uri = (
              srv.get("attributes", {})
              .get("agentregistry.googleapis.com/system/RuntimeReference", {})
              .get("uri", "")
          )
          if "/collections/" in uri:
            collection_id = uri.split("/collections/")[1].split("/")[0]

      dc_url = (
          f"https://discoveryengine.googleapis.com/v1alpha/projects/"
          f"{self.project_id}/locations/global/collections/"
          f"{collection_id}/dataConnector"
      )
      resp = httpx.get(dc_url, headers=auth_headers, timeout=15.0)
      resp.raise_for_status()
      dc = resp.json()
      mcp_url = dc.get("actionConfig", {}).get("actionParams", {}).get(
          "instance_uri"
      ) or dc.get("params", {}).get("instance_uri")

      def _build_mcp_headers(target_url: str) -> dict[str, str]:
        c, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        r = google.auth.transport.requests.Request()
        c.refresh(r)
        parsed = urllib.parse.urlparse(target_url)
        audience = (
            f"{parsed.scheme}://{parsed.netloc}"
            if parsed.scheme and parsed.netloc
            else target_url
        )
        oidc_tok = getattr(c, "id_token", None)
        if not isinstance(oidc_tok, str) or not oidc_tok:
          oidc_tok = id_token.fetch_id_token(r, audience)
        hdrs = {
            "Authorization": f"Bearer {oidc_tok}",
            "X-Goog-User-Project": self.project_id,
        }
        if getattr(c, "token", None):
          hdrs["X-Forwarded-Authorization"] = f"Bearer {c.token}"
        return hdrs

      async def _exec() -> str:
        agent = Agent(
            name="vanilla_hairpin_mcp_agent",
            description=(
                "You are a Security Operations AI Assistant connected to the"
                " Gemini Enterprise Hairpin MCP connector."
            ),
            model=Gemini(
                model="gemini-2.5-flash",
                retry_options=types.HttpRetryOptions(attempts=3),
            ),
            tools=[
                McpToolset(
                    connection_params=StreamableHTTPConnectionParams(
                        url=mcp_url,
                        headers=_build_mcp_headers(mcp_url),
                        timeout=30.0,
                    ),
                    header_provider=lambda _ctx: _build_mcp_headers(mcp_url),
                )
            ],
        )
        runner = InMemoryRunner(agent=agent)
        user_id = "user"
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        await runner.session_service.create_session(
            user_id=user_id, session_id=session_id, app_name=runner.app_name
        )
        response_parts = []
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=types.Content(
                parts=[types.Part.from_text(text=prompt)]
            ),
        ):
          if event.content and event.content.parts:
            for part in event.content.parts:
              if part.text:
                response_parts.append(part.text)
        return "".join(response_parts)

      with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _exec()).result()

  try:
    remote_agent = reasoning_engines.ReasoningEngine.create(
        HairpinVanillaReasoningEngineAgent(
            project_id=project, mcp_server_name=resolved_server
        ),
        requirements=[
            "google-adk[mcp]>=2.0.0",
            "google-genai>=0.1.1",
            "pydantic>=2.0.0",
            "google-auth>=2.0.0",
            "google-cloud-aiplatform>=1.50.0",
            "httpx>=0.27.0",
        ],
        display_name=display_name,
        description=(
            "Vanilla ADK Agent in Agent Engine connected to the Gemini"
            " Enterprise Hairpin MCP connector (secops-hairpin-mcp) with"
            " stripped inputSchema and outputSchema."
        ),
    )
    console.print(
        f"[bold green]Successfully deployed Reasoning Engine:[/bold green] "
        f"{remote_agent.resource_name}"
    )
  except Exception as e:
    console.print(f"[bold red]Deployment failed:[/bold red] {e}")
    raise typer.Exit(code=1) from e


if __name__ == "__main__":
  app()
