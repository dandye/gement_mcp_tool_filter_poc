"""Unified CLI for gement_mcp_tool_filter_poc.

Entrypoint for CLI commands, service operations, and development workflows.
"""

from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console

# Resolve repo root (src/gement_mcp_tool_filter_poc/cli.py -> parents[2])
REPO_ROOT = Path(__file__).resolve().parents[2]

# Load environment variables
load_dotenv(REPO_ROOT / ".env")

console = Console()

app = typer.Typer(
    name="gement-mcp-tool-filter-poc",
    help="Unified management CLI for gement_mcp_tool_filter_poc",
    add_completion=True,
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.callback()
def main_callback() -> None:
  """gement_mcp_tool_filter_poc CLI Operations."""
  pass


@app.command("info")
def info() -> None:
  """Display project configuration and environment status."""
  console.print("[bold blue]gement_mcp_tool_filter_poc[/bold blue] Environment Status")
  console.print(f"Repository Root: [cyan]{REPO_ROOT}[/cyan]")


@app.command("run-demo")
def run_demo(
    name: Annotated[
        str, typer.Option("--name", "-n", help="Target entity name")
    ] = "world",
) -> None:
  """Run basic demo pipeline.

  Args:
    name: Target entity name to process.
  """
  from gement_mcp_tool_filter_poc.core import run_pipeline

  result = run_pipeline(name)
  console.print(f"[green]Pipeline Output:[/green] {result}")


if __name__ == "__main__":
  app()
