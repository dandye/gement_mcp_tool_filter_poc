"""Hairpin MCP proxy server that strips inputSchema and outputSchema from OneMCP.

Forwards MCP JSON-RPC 2.0 requests to the upstream Google SecOps OneMCP server
(https://us-chronicle.googleapis.com/mcp) and strips bloated inputSchema and
outputSchema definitions from tools/list responses so clients only receive tool
names, descriptions, annotations, and a minimal open object inputSchema stub.
"""

import copy
import json
import logging
import os
import time
import urllib.parse
from typing import Any

import google.auth
import google.auth.transport.requests
import httpx
from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import Header
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from google.oauth2 import id_token

logger = logging.getLogger(__name__)

DEFAULT_UPSTREAM_ONEMCP_URL = "https://us-chronicle.googleapis.com/mcp"
DEFAULT_PROJECT_ID = "your-gcp-project-id"
DEFAULT_CACHE_TTL_SECONDS = 300.0

# Minimal open object schema required by mcp.types.Tool Pydantic validation
# while allowing Gemini to pass arbitrary arguments inferred from descriptions.
STRIPPED_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
}


def build_mcp_auth_headers(
    target_url: str,
    project_id: str | None = None,
) -> dict[str, str]:
  """Builds HTTP authentication headers for an MCP endpoint.

  For Google API endpoints (*.googleapis.com), attaches an OAuth 2.0 access
  token in Authorization. For Cloud Run (*.run.app) or custom HTTPS endpoints
  deployed with --no-allow-unauthenticated, attaches a Google-signed OIDC ID
  token in Authorization (for Cloud Run IAM roles/run.invoker verification) and
  forwards the caller's OAuth 2.0 access token in X-Forwarded-Authorization.

  Args:
    target_url: Target MCP HTTP endpoint URL.
    project_id: Optional GCP project ID for X-Goog-User-Project.

  Returns:
    Dictionary of authentication headers.
  """
  headers: dict[str, str] = {}
  if project_id:
    headers["X-Goog-User-Project"] = project_id

  try:
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    req = google.auth.transport.requests.Request()
    creds.refresh(req)
  except Exception as e:
    logger.debug(
        "Could not refresh default credentials for %s: %s", target_url, e
    )
    return headers

  parsed = urllib.parse.urlparse(target_url)
  hostname = (parsed.hostname or "").lower()
  is_google_api = hostname == "googleapis.com" or hostname.endswith(
      ".googleapis.com"
  )

  raw_access_token = getattr(creds, "token", None)
  access_token = raw_access_token if isinstance(raw_access_token, str) else None

  if is_google_api:
    if access_token:
      headers["Authorization"] = f"Bearer {access_token}"
  else:
    # Check user ADC id_token first (populated by gcloud auth login --update-adc)
    # before falling back to metadata server / SA fetch_id_token.
    raw_id_token = getattr(creds, "id_token", None)
    oidc_token = raw_id_token if isinstance(raw_id_token, str) else None
    if not oidc_token:
      audience = (
          f"{parsed.scheme}://{parsed.netloc}"
          if parsed.scheme and parsed.netloc
          else target_url
      )
      try:
        fetched = id_token.fetch_id_token(req, audience)
        if isinstance(fetched, str):
          oidc_token = fetched
      except Exception as e:
        logger.debug("Could not fetch OIDC ID token for %s: %s", audience, e)
    if oidc_token:
      headers["Authorization"] = f"Bearer {oidc_token}"
      if access_token:
        headers["X-Forwarded-Authorization"] = f"Bearer {access_token}"
    elif access_token:
      headers["Authorization"] = f"Bearer {access_token}"

  return headers


def strip_tool_schemas(
    tool: dict[str, Any],
    *,
    strip_input: bool = True,
    strip_output: bool = True,
) -> dict[str, Any]:
  """Strips inputSchema and outputSchema from a single MCP tool definition.

  Args:
    tool: Raw MCP tool dictionary from upstream tools/list.
    strip_input: Whether to replace inputSchema with STRIPPED_INPUT_SCHEMA.
    strip_output: Whether to remove outputSchema completely.

  Returns:
    Sanitized copy of the MCP tool dictionary.
  """
  sanitized = copy.copy(tool)
  if strip_output:
    sanitized.pop("outputSchema", None)
  if strip_input:
    sanitized["inputSchema"] = dict(STRIPPED_INPUT_SCHEMA)
  return sanitized


def sanitize_tools_list_response(
    rpc_response: dict[str, Any],
    *,
    strip_input: bool = True,
    strip_output: bool = True,
) -> dict[str, Any]:
  """Sanitizes a JSON-RPC tools/list response by stripping tool schemas.

  Args:
    rpc_response: Raw JSON-RPC 2.0 response dictionary from upstream OneMCP.
    strip_input: Whether to replace inputSchema with STRIPPED_INPUT_SCHEMA.
    strip_output: Whether to remove outputSchema completely.

  Returns:
    Sanitized JSON-RPC 2.0 response dictionary.
  """
  sanitized_resp = copy.copy(rpc_response)
  result = sanitized_resp.get("result")
  if isinstance(result, dict) and isinstance(result.get("tools"), list):
    new_result = copy.copy(result)
    new_result["tools"] = [
        strip_tool_schemas(
            t,
            strip_input=strip_input,
            strip_output=strip_output,
        )
        if isinstance(t, dict)
        else t
        for t in result["tools"]
    ]
    sanitized_resp["result"] = new_result
  return sanitized_resp


class HairpinMcpProxy:
  """Proxy forwarding MCP JSON-RPC calls to OneMCP and stripping schemas."""

  def __init__(
      self,
      upstream_url: str | None = None,
      default_project_id: str | None = None,
      cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
      timeout_seconds: float = 60.0,
  ) -> None:
    self.upstream_url = upstream_url or os.environ.get(
        "UPSTREAM_ONEMCP_URL", DEFAULT_UPSTREAM_ONEMCP_URL
    )
    self.default_project_id = default_project_id or os.environ.get(
        "GCP_PROJECT_ID", DEFAULT_PROJECT_ID
    )
    self.cache_ttl_seconds = cache_ttl_seconds
    self.timeout_seconds = timeout_seconds
    self._cached_raw_tools: list[dict[str, Any]] | None = None
    self._cache_timestamp: float = 0.0

  def _resolve_oauth_bearer(
      self,
      incoming_auth: str | None,
      incoming_forwarded_auth: str | None = None,
  ) -> str:
    """Resolves an OAuth 2.0 Bearer header for upstream OneMCP requests.

    Checks X-Forwarded-Authorization first (used when Authorization carries a
    Cloud Run OIDC ID token), then Authorization for a non-JWT OAuth 2.0 access
    token, and falls back to Application Default Credentials.

    Args:
      incoming_auth: Optional Authorization header from the inbound request.
      incoming_forwarded_auth: Optional X-Forwarded-Authorization header.

    Returns:
      Authorization header value formatted as 'Bearer <token>'.
    """
    if incoming_forwarded_auth:
      forwarded = incoming_forwarded_auth.removeprefix("Bearer ").strip()
      if forwarded:
        return f"Bearer {forwarded}"

    if incoming_auth:
      token = incoming_auth.removeprefix("Bearer ").strip()
      if token and not token.startswith("eyJ"):
        return f"Bearer {token}"

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    return f"Bearer {creds.token}"

  def _build_upstream_headers(
      self,
      incoming_auth: str | None = None,
      incoming_forwarded_auth: str | None = None,
      incoming_user_project: str | None = None,
      incoming_session_id: str | None = None,
  ) -> dict[str, str]:
    """Constructs HTTP headers for calling the upstream OneMCP endpoint."""
    headers = {
        "Authorization": self._resolve_oauth_bearer(
            incoming_auth, incoming_forwarded_auth
        ),
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "x-goog-user-project": incoming_user_project or self.default_project_id,
    }
    if incoming_session_id:
      headers["Mcp-Session-Id"] = incoming_session_id
    return headers

  async def forward_jsonrpc(
      self,
      payload: dict[str, Any],
      *,
      incoming_auth: str | None = None,
      incoming_forwarded_auth: str | None = None,
      incoming_user_project: str | None = None,
      incoming_session_id: str | None = None,
      strip_input: bool = True,
      strip_output: bool = True,
  ) -> dict[str, Any] | None:
    """Forwards a single JSON-RPC 2.0 message to upstream OneMCP.

    Args:
      payload: JSON-RPC 2.0 request object.
      incoming_auth: Optional inbound Authorization header.
      incoming_forwarded_auth: Optional inbound X-Forwarded-Authorization.
      incoming_user_project: Optional inbound x-goog-user-project header.
      incoming_session_id: Optional inbound Mcp-Session-Id header.
      strip_input: Whether to strip inputSchema on tools/list.
      strip_output: Whether to strip outputSchema on tools/list.

    Returns:
      JSON-RPC 2.0 response dictionary, or None for notifications.
    """
    method = payload.get("method", "")
    rpc_id = payload.get("id")

    if method.startswith("notifications/"):
      return None

    if method == "ping":
      return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

    if method == "tools/list":
      raw_tools = await self.fetch_raw_tools(
          incoming_auth=incoming_auth,
          incoming_forwarded_auth=incoming_forwarded_auth,
          incoming_user_project=incoming_user_project,
          incoming_session_id=incoming_session_id,
      )
      raw_rpc = {
          "jsonrpc": "2.0",
          "id": rpc_id,
          "result": {"tools": raw_tools},
      }
      return sanitize_tools_list_response(
          raw_rpc,
          strip_input=strip_input,
          strip_output=strip_output,
      )

    headers = self._build_upstream_headers(
        incoming_auth=incoming_auth,
        incoming_forwarded_auth=incoming_forwarded_auth,
        incoming_user_project=incoming_user_project,
        incoming_session_id=incoming_session_id,
    )
    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
      resp = await client.post(
          self.upstream_url,
          headers=headers,
          json=payload,
      )
      if resp.status_code == 204 or not resp.content:
        return None
      try:
        resp_json = resp.json()
        if isinstance(resp_json, dict) and "jsonrpc" in resp_json:
          return resp_json
      except ValueError:
        pass
      resp.raise_for_status()
      return resp.json()

  async def fetch_raw_tools(
      self,
      *,
      incoming_auth: str | None = None,
      incoming_forwarded_auth: str | None = None,
      incoming_user_project: str | None = None,
      incoming_session_id: str | None = None,
      force_refresh: bool = False,
  ) -> list[dict[str, Any]]:
    """Fetches raw tool definitions from upstream OneMCP with TTL caching."""
    now = time.monotonic()
    if (
        not force_refresh
        and self._cached_raw_tools is not None
        and (now - self._cache_timestamp) < self.cache_ttl_seconds
    ):
      return self._cached_raw_tools

    headers = self._build_upstream_headers(
        incoming_auth=incoming_auth,
        incoming_forwarded_auth=incoming_forwarded_auth,
        incoming_user_project=incoming_user_project,
        incoming_session_id=incoming_session_id,
    )
    rpc_req = {
        "jsonrpc": "2.0",
        "id": "hairpin-tools-list",
        "method": "tools/list",
        "params": {},
    }
    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
      resp = await client.post(
          self.upstream_url,
          headers=headers,
          json=rpc_req,
      )
      resp.raise_for_status()
      data = resp.json()

    tools = data.get("result", {}).get("tools", [])
    if isinstance(tools, list) and tools:
      self._cached_raw_tools = tools
      self._cache_timestamp = now
    return tools


proxy = HairpinMcpProxy()
router = APIRouter()


def _wire_bytes(payload: dict[str, Any]) -> int:
  """Returns the byte length of payload serialized as the /mcp endpoint sends it.

  Uses the same compact UTF-8 JSON encoding as fastapi.responses.JSONResponse
  so that /stats figures match the bytes observed on the wire.

  Args:
    payload: JSON-RPC 2.0 response dictionary.

  Returns:
    Encoded payload length in bytes.
  """
  return len(
      json.dumps(
          payload,
          ensure_ascii=False,
          allow_nan=False,
          indent=None,
          separators=(",", ":"),
      ).encode("utf-8")
  )


@router.get("/stats")
async def stats(
    authorization: str | None = Header(default=None),
    x_forwarded_authorization: str | None = Header(default=None),
    x_goog_user_project: str | None = Header(default=None),
) -> dict[str, Any]:
  """Returns payload size comparison between raw OneMCP and hairpin proxy."""
  raw_tools = await proxy.fetch_raw_tools(
      incoming_auth=authorization,
      incoming_forwarded_auth=x_forwarded_authorization,
      incoming_user_project=x_goog_user_project,
  )
  raw_rpc = {"jsonrpc": "2.0", "id": 1, "result": {"tools": raw_tools}}
  output_stripped_rpc = sanitize_tools_list_response(
      raw_rpc, strip_input=False, strip_output=True
  )
  both_stripped_rpc = sanitize_tools_list_response(
      raw_rpc, strip_input=True, strip_output=True
  )

  raw_bytes = _wire_bytes(raw_rpc)
  output_stripped_bytes = _wire_bytes(output_stripped_rpc)
  both_stripped_bytes = _wire_bytes(both_stripped_rpc)

  return {
      "tool_count": len(raw_tools),
      "raw_tools_list_bytes": raw_bytes,
      "output_schema_stripped_bytes": output_stripped_bytes,
      "input_and_output_schema_stripped_bytes": both_stripped_bytes,
      "reduction_bytes": raw_bytes - both_stripped_bytes,
      "reduction_percent": (
          round((1.0 - both_stripped_bytes / raw_bytes) * 100.0, 2)
          if raw_bytes
          else 0.0
      ),
  }


async def _dispatch_jsonrpc_http(
    request: Request,
    *,
    authorization: str | None,
    x_forwarded_authorization: str | None,
    x_goog_user_project: str | None,
    mcp_session_id: str | None,
    strip_input: bool,
    strip_output: bool,
) -> Response:
  """Internal helper to parse and forward single or batch JSON-RPC payloads."""
  try:
    payload = await request.json()
  except Exception as e:
    raise HTTPException(
        status_code=400, detail=f"Invalid JSON-RPC payload: {e}"
    ) from e

  try:
    if isinstance(payload, list):
      responses: list[dict[str, Any]] = []
      for item in payload:
        if isinstance(item, dict):
          res = await proxy.forward_jsonrpc(
              item,
              incoming_auth=authorization,
              incoming_forwarded_auth=x_forwarded_authorization,
              incoming_user_project=x_goog_user_project,
              incoming_session_id=mcp_session_id,
              strip_input=strip_input,
              strip_output=strip_output,
          )
          if res is not None:
            responses.append(res)
      if not responses:
        return Response(status_code=202)
      return JSONResponse(content=responses)

    if not isinstance(payload, dict):
      raise HTTPException(
          status_code=400, detail="JSON-RPC payload must be an object or array"
      )

    res = await proxy.forward_jsonrpc(
        payload,
        incoming_auth=authorization,
        incoming_forwarded_auth=x_forwarded_authorization,
        incoming_user_project=x_goog_user_project,
        incoming_session_id=mcp_session_id,
        strip_input=strip_input,
        strip_output=strip_output,
    )
    if res is None:
      return Response(status_code=202)
    return JSONResponse(content=res)
  except httpx.HTTPStatusError as e:
    logger.error(
        "Upstream OneMCP HTTP error %s: %s",
        e.response.status_code,
        e.response.text,
    )
    raise HTTPException(
        status_code=e.response.status_code,
        detail=e.response.text,
    ) from e
  except Exception as e:
    logger.error("Hairpin proxy execution error: %s", e)
    raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/mcp")
async def handle_mcp_jsonrpc(
    request: Request,
    authorization: str | None = Header(default=None),
    x_forwarded_authorization: str | None = Header(default=None),
    x_goog_user_project: str | None = Header(default=None),
    mcp_session_id: str | None = Header(default=None),
    strip_input: bool = Query(
        default=True,
        description="Strip inputSchema to minimal open object stub",
    ),
    strip_output: bool = Query(
        default=True,
        description="Strip outputSchema from tools/list response",
    ),
) -> Response:
  """Handles Hairpin MCP JSON-RPC 2.0 requests (strips input and outputSchema)."""
  return await _dispatch_jsonrpc_http(
      request,
      authorization=authorization,
      x_forwarded_authorization=x_forwarded_authorization,
      x_goog_user_project=x_goog_user_project,
      mcp_session_id=mcp_session_id,
      strip_input=strip_input,
      strip_output=strip_output,
  )


hairpin_app = FastAPI(
    title="SecOps OneMCP Hairpin Proxy",
    description=(
        "Hairpin MCP Server backed by Google SecOps OneMCP that strips"
        " inputSchema and outputSchema from tools/list responses."
    ),
    version="0.1.0",
)
hairpin_app.include_router(router)


@hairpin_app.get("/")
@hairpin_app.get("/health")
async def health() -> dict[str, str]:
  """Health check and root status endpoint.

  Served at /health rather than /healthz because Cloud Run reserves /healthz
  and answers it at the Google Frontend without reaching the container.
  """
  return {
      "status": "ok",
      "service": "secops-hairpin-mcp",
      "upstream_url": proxy.upstream_url,
      "default_project_id": proxy.default_project_id,
  }


@hairpin_app.post("/")
async def handle_root_mcp_jsonrpc(
    request: Request,
    authorization: str | None = Header(default=None),
    x_forwarded_authorization: str | None = Header(default=None),
    x_goog_user_project: str | None = Header(default=None),
    mcp_session_id: str | None = Header(default=None),
    strip_input: bool = Query(default=True),
    strip_output: bool = Query(default=True),
) -> Response:
  """Root POST alias for Hairpin MCP JSON-RPC 2.0 requests."""
  return await _dispatch_jsonrpc_http(
      request,
      authorization=authorization,
      x_forwarded_authorization=x_forwarded_authorization,
      x_goog_user_project=x_goog_user_project,
      mcp_session_id=mcp_session_id,
      strip_input=strip_input,
      strip_output=strip_output,
  )
