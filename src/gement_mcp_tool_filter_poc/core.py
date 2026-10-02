"""Core functionality for gement_mcp_tool_filter_poc."""

import logging

logger = logging.getLogger(__name__)


def run_pipeline(name: str = "world") -> str:
  """Execute core pipeline logic.

  Args:
    name: Name parameter to process.

  Returns:
    Formatted greeting string.
  """
  logger.info("Executing pipeline with name: %s", name)
  return f"Hello, {name}! gement_mcp_tool_filter_poc initialized successfully."
