"""Tenant-defined HTTP tools ("bring your own tool").

A custom tool is a REST endpoint the tenant registers with a JSON schema for its
input. The Ops Copilot can call it like any built-in tool (it is not exposed over MCP).

Safety
------
* SSRF guard: only http(s); the hostname is resolved and every address must be
  public (no loopback / private / link-local / multicast / reserved), unless the
  operator sets CUSTOM_TOOLS_ALLOW_PRIVATE_NETWORK=true. Redirects are refused.
* Secrets: the auth header value is stored Fernet-encrypted and never returned.
* Bounded: per-tool timeout, 256 KB response cap, input validated against the schema.
* Side-effecting tools (`side_effect=True`) never run directly from the model;
  they go through the policy engine and, by default, human approval.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import IntegrationError, NotFound, TransientIntegrationError, ValidationFailed
from app.core.security import decrypt_secret
from app.db.models import CustomTool
from app.integrations.base import ConnectionTestResult, VerificationResult
from app.tools.registry import ToolSpec

MAX_RESPONSE_BYTES = 256 * 1024
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
_PATH_PARAM = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

# Test hooks (httpx.MockTransport / fake resolver) - never set in production code paths.
_transport_override: httpx.BaseTransport | None = None
_resolver_override: Callable[[str], list[str]] | None = None


def custom_tool_key(name: str) -> str:
    return f"custom.{name}"


def spec_for(tool: CustomTool) -> ToolSpec:
    return ToolSpec(
        key=custom_tool_key(tool.name),
        name=tool.name,
        description=tool.description,
        provider="custom",
        method="invoke",
        side_effect=tool.side_effect,
        idempotent=tool.method.upper() in {"GET", "PUT", "DELETE"},
        required_permission="tools:custom",
        risk_level=tool.risk_level,
        external_ref_field=None,
    )


def load_tool(db: Session, tenant_id: str | uuid.UUID, name: str) -> CustomTool:
    tool = db.execute(select(CustomTool).where(CustomTool.tenant_id == uuid.UUID(str(tenant_id)), CustomTool.name == name)).scalar_one_or_none()
    if tool is None:
        raise NotFound(f"Custom tool '{name}' not found")
    return tool


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_JSON_TYPES: dict[str, tuple[type, ...]] = {"string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,), "object": (dict,), "array": (list,)}


def validate_input(schema: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Minimal JSON-schema validation (required, types, enum, additionalProperties)."""
    if not isinstance(data, dict):
        raise ValidationFailed("Tool input must be a JSON object")
    props: dict[str, Any] = schema.get("properties", {}) or {}
    errors: list[str] = []
    for req in schema.get("required", []) or []:
        if req not in data or data[req] in (None, ""):
            errors.append(f"'{req}' is required")
    for key, value in data.items():
        spec = props.get(key)
        if spec is None:
            if schema.get("additionalProperties") is False:
                errors.append(f"unexpected field '{key}'")
            continue
        expected = spec.get("type")
        if expected and value is not None:
            types = expected if isinstance(expected, list) else [expected]
            ok = any(isinstance(value, _JSON_TYPES.get(t, (object,))) and not (t in {"integer", "number"} and isinstance(value, bool)) for t in types if t != "null")
            if not ok:
                errors.append(f"'{key}' must be {expected}")
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"'{key}' must be one of {spec['enum']}")
    if errors:
        raise ValidationFailed("Invalid tool input: " + "; ".join(errors), details={"errors": errors})
    return data


def validate_definition(name: str, method: str, url_template: str, input_schema: dict[str, Any]) -> None:
    if not NAME_RE.match(name):
        raise ValidationFailed("Tool name must be 2-48 chars: lowercase letters, digits and underscores, starting with a letter")
    if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValidationFailed("method must be GET, POST, PUT, PATCH or DELETE")
    parts = urlsplit(url_template.replace("{", "x").replace("}", "x"))
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise ValidationFailed("url_template must be an absolute http(s) URL")
    if "{" in (urlsplit(url_template).netloc or ""):
        raise ValidationFailed("The host part of url_template cannot contain {placeholders}")
    if input_schema and input_schema.get("type", "object") != "object":
        raise ValidationFailed("input_schema must describe an object")
    for p in _PATH_PARAM.findall(url_template):
        if p not in (input_schema.get("properties") or {}):
            raise ValidationFailed(f"URL placeholder '{{{p}}}' must be declared in input_schema.properties")


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------


def _resolve(host: str) -> list[str]:
    if _resolver_override is not None:
        return _resolver_override(host)
    try:
        return list({info[4][0] for info in socket.getaddrinfo(host, None)})
    except socket.gaierror as exc:
        raise IntegrationError(f"Cannot resolve host '{host}'") from exc


def assert_public_destination(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise ValidationFailed("Only absolute http(s) URLs are allowed")
    if get_settings().custom_tools_allow_private_network:
        return
    if parts.scheme != "https":
        raise ValidationFailed("Custom tools must use https (set CUSTOM_TOOLS_ALLOW_PRIVATE_NETWORK=true for local http testing)")
    for addr in _resolve(parts.hostname):
        ip = ipaddress.ip_address(addr.split("%")[0])
        # Judge the embedded IPv4 of ::ffff:a.b.c.d / 6to4 addresses (older Pythons don't unwrap them in is_global).
        if isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.sixtofour):
            ip = ip.ipv4_mapped or ip.sixtofour
        if not ip.is_global or ip.is_multicast:
            raise ValidationFailed(f"Destination {parts.hostname} resolves to a non-public address ({ip}); blocked to prevent SSRF")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def build_request(tool: CustomTool, data: dict[str, Any]) -> tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]:
    remaining = dict(data)

    def sub(m: re.Match[str]) -> str:
        return quote(str(remaining.pop(m.group(1), "")), safe="")

    url = _PATH_PARAM.sub(sub, tool.url_template)
    method = tool.method.upper()
    params = {k: v for k, v in remaining.items() if v is not None} if method in {"GET", "DELETE"} else None
    body = remaining if method in {"POST", "PUT", "PATCH"} else None
    return method, url, params, body


def execute(tool: CustomTool, data: dict[str, Any], *, idempotency_key: str | None = None) -> dict[str, Any]:
    if not tool.enabled:
        raise ValidationFailed(f"Custom tool '{tool.name}' is disabled")
    validate_input(tool.input_schema or {}, data)
    method, url, params, body = build_request(tool, data)
    assert_public_destination(url)
    headers = {"User-Agent": "OpsPilot-CustomTool/1.0", "Accept": "application/json, text/plain;q=0.8"}
    for k, v in (tool.headers or {}).items():
        if isinstance(k, str) and isinstance(v, str | int | float):
            headers[k] = str(v)
    if tool.auth_header_name and tool.auth_secret_encrypted:
        headers[tool.auth_header_name] = decrypt_secret(tool.auth_secret_encrypted)
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    client_kwargs: dict[str, Any] = {"timeout": float(tool.timeout_seconds or 15), "follow_redirects": False}
    if _transport_override is not None:
        client_kwargs["transport"] = _transport_override
    try:
        with httpx.Client(**client_kwargs) as client:
            resp = client.request(method, url, params=params, json=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise TransientIntegrationError(f"Custom tool '{tool.name}' timed out") from exc
    except httpx.TransportError as exc:
        raise TransientIntegrationError(f"Custom tool '{tool.name}' could not connect: {type(exc).__name__}") from exc
    raw = resp.content[:MAX_RESPONSE_BYTES]
    truncated = len(resp.content) > MAX_RESPONSE_BYTES
    ctype = resp.headers.get("content-type", "")
    payload: Any
    if "json" in ctype:
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw.decode("utf-8", "replace")
    else:
        payload = raw.decode("utf-8", "replace")
    if 300 <= resp.status_code < 400:
        raise IntegrationError(f"Custom tool '{tool.name}' returned a redirect ({resp.status_code}); redirects are not followed")
    if resp.status_code >= 500 or resp.status_code == 429:
        raise TransientIntegrationError(f"Custom tool '{tool.name}' returned HTTP {resp.status_code}", details={"body": str(payload)[:500]})
    if resp.status_code >= 400:
        raise IntegrationError(f"Custom tool '{tool.name}' returned HTTP {resp.status_code}", details={"body": str(payload)[:500]})
    return {"status_code": resp.status_code, "data": payload, "truncated": truncated, "tool": tool.name, "method": method, "url": url.split("?")[0]}


class CustomToolAdapter:
    """Adapter so custom tools flow through ActionService exactly like built-in tools."""

    provider = "custom"
    mode = "live"
    capabilities = ["http"]
    display_name = "Custom HTTP tools"

    def __init__(self, db: Session, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    def invoke(self, tool: str, input: dict[str, Any] | None = None, idempotency_key: str | None = None, **_: Any) -> dict[str, Any]:  # noqa: A002
        row = load_tool(self.db, self.tenant_id, tool)
        result = execute(row, input or {}, idempotency_key=idempotency_key)
        row.last_called_at = datetime.now(UTC)
        row.call_count = (row.call_count or 0) + 1
        self.db.flush()
        return result

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, mode="live", provider="custom", message="custom tools are tested individually")

    def verify_action(self, method: str, request: dict[str, Any], external_ref: str | None) -> VerificationResult | None:
        return None  # generic HTTP endpoints cannot be verified; unknown outcomes stay unknown (never blindly retried)
