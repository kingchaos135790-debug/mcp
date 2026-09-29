from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import ssl

import httpx
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.providers import Provider
from fastmcp.server.providers.proxy import ProxyClient, ProxyTool

from . import PROTOCOL_VERSION
from .models import DeviceConfig, DeviceStatus

_TLS_CONTEXT = ssl.create_default_context()


def result_json(result):
    if getattr(result, "is_error", False) or getattr(result, "isError", False):
        raise ValueError("Node returned an MCP tool error")
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if structured is not None:
        # FastMCP wraps scalar return values in {result: ...}.
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
    # FastMCP 3.0 forwards incoming HTTP headers by default. Do not leak gateway
    # OAuth credentials, cookies or its transport-session ID into private nodes.
    headers = kwargs.pop("headers", {})
    safe = {k: v for k, v in headers.items() if k.lower() == "x-openai-session"}
    kwargs.pop("auth", None)
    kwargs.pop("follow_redirects", None)
    return httpx.AsyncClient(headers=safe, trust_env=False, follow_redirects=False, verify=_TLS_CONTEXT, **kwargs)


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
            identity = result_json(result)
            if not isinstance(identity, dict) or identity.get("device_id") != self.expected_device:
                raise ValueError(f"Node identity mismatch for {self.expected_device}")
            if identity.get("protocol_version") != PROTOCOL_VERSION or identity.get("role") != "node":
                raise ValueError("Incompatible node role or distribution protocol")
            self.identity = identity
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
                    return await super().run(arguments, context)
        except Exception as exc:
            # Never retry: a lost response may follow a successful mutation.
            raise ToolError(
                f"Device {connection.device.device_id}: {exc or type(exc).__name__}. "
                "The call was not retried; if it could change state, verify its outcome before retrying."
            ) from exc


class NodeConnection(Provider):
    """FastMCP proxy tools with independently refreshed, in-memory schemas.

    Nodes currently expose tools only. Resources/prompts are intentionally not
    advertised until the node contract contains them.
    """

    def __init__(self, device: DeviceConfig, *, health_timeout: float = 5,
                 call_timeout: float = 600, client_factory=None) -> None:
        super().__init__()
        self.device = device
        self.health_timeout = health_timeout
        self.call_timeout = call_timeout
        self.status = DeviceStatus()
        self._tools: dict[str, ProxyTool] = {}
        self._client_factory = client_factory
        self._refresh_lock = asyncio.Lock()
        self.slots = asyncio.Semaphore(8)

    def client(self, *, timeout: float | None = None):
        if self._client_factory is not None:
            return self._client_factory()
        from session_context import get_current_chat_session_id

        session = get_current_chat_session_id()
        transport = StreamableHttpTransport(
            self.device.url,
            headers={"x-openai-session": session} if session else {},
            httpx_client_factory=private_http_client,
        )
        return VerifiedNodeClient(
            transport, expected_device=self.device.device_id,
            health_timeout=self.health_timeout, init_timeout=self.health_timeout,
            timeout=timeout or self.call_timeout,
        )

    async def refresh(self) -> None:
        if self._refresh_lock.locked():
            return  # Another bounded refresh is already updating this snapshot.
        async with self._refresh_lock:
            try:
                async with asyncio.timeout(self.health_timeout):
                    async with self.client(timeout=self.health_timeout) as client:
                        schemas = await client.list_tools()
                        identity = client.identity
                tools = {}
                for schema in schemas:
                    if not self.device.permits(schema.name):
                        continue
                    public_name = f"{self.device.device_id}_{schema.name}"
                    if public_name in {"list_devices", "device_health", "distributed_code_search"}:
                        raise ValueError(f"Namespaced tool conflicts with gateway management: {public_name}")
                    if len(public_name) > 64:
                        raise ValueError(f"Namespaced tool exceeds 64 characters: {schema.name}")
                    tool = BoundedProxyTool.from_mcp_tool(self.client, schema)
                    tool._connection = self
                    tools[schema.name] = tool
                self._tools = tools
                self.status.identity = identity
                self.status.advertised_tools = sorted(tools)
                self.status.state = "online"
                self.status.last_success = datetime.now(UTC).isoformat()
                self.status.last_error = None
            except Exception as exc:
                self.status.state = "offline"
                self.status.last_error = str(exc) or type(exc).__name__
                # Keep the last verified schemas: existing clients can still call
                # the same names when the node recovers. Calls reverify identity.

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
