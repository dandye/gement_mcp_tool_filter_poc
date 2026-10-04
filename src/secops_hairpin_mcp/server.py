"""Cloud Run FastAPI entrypoint for the SecOps OneMCP Hairpin Proxy."""

from secops_hairpin_mcp.hairpin import hairpin_app as app

__all__ = ["app"]
