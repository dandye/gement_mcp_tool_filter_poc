"""Cloud Run FastAPI entrypoint for the SecOps OneMCP Hairpin Proxy."""

from gement_mcp_tool_filter_poc.hairpin import hairpin_app as app

__all__ = ["app"]
