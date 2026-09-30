from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import os
import ssl

import httpx
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.providers import Provider
from fastmcp.server.providers.proxy import ProxyClient, ProxyTool
from fastmcp.tools.tool import ToolResult
from mcp.types import Tool

from . import PROTOCOL_VERSION
from .models import DeviceConfig, DeviceStatus
from .schema_cache import NodeSchemaCache

_TLS_CONTEXT = ssl.create_default_context()


def result_json(result):
    if getattr(result, "is_error", False) or getattr(result, "isError", False):
        raise ValueError("Node returned an MCP tool error")
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if structured is not None:
        value = structured.get("result") if isinstance(structured, dict) and set(structured) == {"result"} else structured
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value
    text = "".join(item.text for item in result.content if getattr(item, "type", "") == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def private_http_client(**kwargs) -> httpx.AsyncClient:
    # Do not leak gateway OAuth credentials, cookies or transport-session IDs.
    headers = kwargs.pop("headers", {})
    safe = {k: v for k, v in headers.items() if k.lower() == "x-openai-session"}
    kwargs.pop("auth", None)
    kwargs.pop("follow_redirects", None)
    return httpx.AsyncClient(headers=safe, trust_env=False, follow_redirects=False, verify=_TLS_CONTEXT, **kwargs)


def validate_identity(identity, expected_device: str) -> dict:
    if not isinstance(identity, dict) or identity.get("device_id") != expected_device:
        raise ValueError(f"Node identity mismatch for {expected_device}")
    if identity.get("protocol_version") != PROTOCOL_VERSION or identity.get("role") != "node":
        raise ValueError("Incompatible node role or distribution protocol")
    return identity


class VerifiedNodeClient(ProxyClient):
    def __init__(self, *args, expected_device: str, health_timeout: float, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_device = expected_device
        self.health_timeout = health_timeout
        self.identity: dict = {}

    async def __aenter__(self):
        await super().__aenter__()
        try:
            result = await self.call_tool("node_health", {}, timeout=self.health_timeout)
            self.identity = validate_identity(result_json(result), self.expected_device)
            return self
        except BaseException as exc:
            await super().__aexit__(type(exc), exc, exc.__traceback__)
            raise


class BoundedProxyTool(ProxyTool):
    async def run(self, arguments, context=None):
        connection = self._connection
        try:
            async with asyncio.timeout(connection.call_timeout):
                async with connection.slots:
                    result = await super().run(arguments, context)
                    return connection.clamp_tool_result(result)
        except Exception as exc:
            raise ToolError(
                f"Device {connection.device.device_id}: {exc or type(exc).__name__}. "
                "The call was not retried; if it could change state, verify its outcome before retrying."
            ) from exc


class NodeConnection(Provider):
    """Proxy provider with persistent last-verified tool schemas."""

    def __init__(
        self,
        device: DeviceConfig,
        *,
        health_timeout: float = 5,
        call_timeout: float = 600,
        client_factory=None,
        schema_cache: NodeSchemaCache | None = None,
    ) -> None:
        super().__init__()
        self.device = device
        self.health_timeout = health_timeout
        self.call_timeout = call_timeout
        try:
            self.max_result_chars = max(4_000, int(os.getenv("MCP_GATEWAY_MAX_RESULT_CHARS", "24000")))
        except ValueError:
            self.max_result_chars = 24_000
        self.status = DeviceStatus()
        self._tools: dict[str, ProxyTool] = {}
        self._schemas: list[Tool] = []
        self._tool_contract = ""
        self._client_factory = client_factory
        self._schema_cache = schema_cache
        self._refresh_lock = asyncio.Lock()
        self.slots = asyncio.Semaphore(8)
        self._restore_cached_schema()

    @staticmethod
    def _clip_text(value: str, budget: int) -> str:
        if len(value) <= budget:
            return value
        suffix = f"\n... [MCP result truncated: {len(value) - budget} characters omitted]"
        keep = max(0, budget - len(suffix))
        return value[:keep] + suffix

    @classmethod
    def _compact_structured(cls, value, budget: int):
        if budget < 64:
            budget = 64
        if isinstance(value, str):
            return cls._clip_text(value, budget)
        if isinstance(value, list):
            if not value:
                return []
            limit = min(len(value), 32)
            per_item = max(64, budget // limit)
            return [cls._compact_structured(item, per_item) for item in value[:limit]]
        if isinstance(value, dict):
            if not value:
                return {}
            per_item = max(64, budget // len(value))
            return {key: cls._compact_structured(item, per_item) for key, item in value.items()}
        return value

    def clamp_tool_result(self, result: ToolResult) -> ToolResult:
        max_chars = self.max_result_chars
        structured = result.structured_content
        structured_size = 0
        if structured is not None:
            serialized = json.dumps(structured, ensure_ascii=False, default=str)
            if len(serialized) > max_chars // 2:
                structured = self._compact_structured(structured, max_chars // 2)
                serialized = json.dumps(structured, ensure_ascii=False, default=str)
            structured_size = len(serialized)

        text_budget = max(1_000, max_chars - min(structured_size, max_chars - 1_000))
        content = []
        used = 0
        for block in result.content:
            if getattr(block, "type", "") != "text":
                content.append(block)
                continue
            text = getattr(block, "text", "") or ""
            remaining = max(0, text_budget - used)
            if len(text) <= remaining:
                content.append(block)
                used += len(text)
                continue
            content.append(block.model_copy(update={"text": self._clip_text(text, remaining)}))
            used = text_budget
            break

        return ToolResult(content=content, structured_content=structured, meta=result.meta)

    @property
    def health_url(self) -> str:
        base = self.device.url.removesuffix("/mcp")
        return f"{base}/__node_health"

    def _headers(self) -> dict[str, str]:
        from session_context import get_current_chat_session_id

        session = get_current_chat_session_id()
        return {"x-openai-session": session} if session else {}

    def _restore_cached_schema(self) -> None:
        if self._schema_cache is None:
            return
        cached = self._schema_cache.load(self.device.device_id)
        if cached is None:
            return
        identity, schemas, contract = cached
        self._install_schemas(schemas)
        self._tool_contract = contract
        self.status.identity = identity
        self.status.advertised_tools = sorted(self._tools)

    def _install_schemas(self, schemas: list[Tool]) -> None:
        tools: dict[str, ProxyTool] = {}
        kept: list[Tool] = []
        for schema in schemas:
            if not self.device.permits(schema.name):
                continue
            tool = BoundedProxyTool.from_mcp_tool(self.client, schema)
            tool._connection = self
            tools[schema.name] = tool
            kept.append(schema)
        self._tools = tools
        self._schemas = kept

    def _transport(self) -> StreamableHttpTransport:
        return StreamableHttpTransport(
            self.device.url,
            headers=self._headers(),
            httpx_client_factory=private_http_client,
        )

    def client(self, *, timeout: float | None = None):
        if self._client_factory is not None:
            return self._client_factory()
        return VerifiedNodeClient(
            self._transport(),
            expected_device=self.device.device_id,
            health_timeout=self.health_timeout,
            init_timeout=self.health_timeout,
            timeout=timeout or self.call_timeout,
        )

    async def _fetch_health(self) -> dict:
        async with private_http_client(headers=self._headers(), timeout=self.health_timeout) as client:
            response = await client.get(self.health_url)
            response.raise_for_status()
            return validate_identity(response.json(), self.device.device_id)

    async def _fetch_schemas(self) -> tuple[dict, list[Tool]]:
        async with self.client(timeout=self.health_timeout) as client:
            schemas = list(await client.list_tools())
            return client.identity, schemas

    async def _sync(self, *, force_schema: bool) -> None:
        if self._refresh_lock.locked():
            return
        async with self._refresh_lock:
            try:
                async with asyncio.timeout(self.health_timeout):
                    identity = await self._fetch_health()
                    contract = str(identity.get("tool_contract") or "")
                    schema_changed = bool(contract and contract != self._tool_contract)
                    schemas: list[Tool] | None = None
                    if force_schema or not self._schemas or schema_changed:
                        verified_identity, schemas = await self._fetch_schemas()
                        identity = verified_identity
                        contract = str(identity.get("tool_contract") or contract)
                if schemas is not None:
                    self._install_schemas(schemas)
                    self._tool_contract = contract
                self.status.identity = identity
                self.status.advertised_tools = sorted(self._tools)
                self.status.state = "online"
                self.status.last_success = datetime.now(UTC).isoformat()
                self.status.last_error = None
                if self._schema_cache is not None and self._schemas:
                    self._schema_cache.save(
                        self.device.device_id,
                        identity,
                        self._schemas,
                        self._tool_contract or contract,
                    )
            except Exception as exc:
                self.status.state = "offline"
                self.status.last_error = str(exc) or type(exc).__name__
                # Keep verified schemas so the gateway tool surface stays stable.

    async def check_health(self) -> None:
        """Check identity/readiness and fetch schemas only when the contract changed."""
        await self._sync(force_schema=False)

    async def refresh(self) -> None:
        """Explicitly re-fetch and persist tool schemas after verifying identity."""
        await self._sync(force_schema=True)

    async def stop(self) -> None:
        return None

    async def _list_tools(self):
        return list(self._tools.values())

    async def _get_tool(self, name, version=None):
        return self._tools.get(name)

    async def get_tasks(self):
        return []

    async def call(self, name: str, arguments: dict):
        if not self.device.permits(name):
            raise ValueError(f"Tool {name} is not allowed on {self.device.device_id}")
        async with asyncio.timeout(self.call_timeout):
            async with self.slots:
                async with self.client() as client:
                    return result_json(await client.call_tool(name, arguments))
