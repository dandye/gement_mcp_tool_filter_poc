"""Basic test suite for gement_mcp_tool_filter_poc."""

from gement_mcp_tool_filter_poc.core import run_pipeline


def test_run_pipeline() -> None:
  result = run_pipeline("developer")
  assert "developer" in result
  assert "gement_mcp_tool_filter_poc initialized successfully." in result
