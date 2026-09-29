from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import math
import os

import anyio

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from server_config import build_auth
from server_public import PublicServerMixin
from .health import monitor_node
from .node_connection import NodeConnection
from .registry import DeviceRegistry
from .search import search_devices
from .tunnel_manager import LocalEndpointManager, TunnelManager, resolve_ssh


def positive_setting(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


class GatewayApp(PublicServerMixin):
    def __init__(self, config, *, registry=None, connection_factory=NodeConnection, tunnel_factory=TunnelManager):
        self.config = config
        self.registry = registry if registry is not None else DeviceRegistry.load(config.devices_path)
        self.health_interval = positive_setting("MCP_HEALTH_INTERVAL_SECONDS", 15)
        self.search_timeout = positive_setting("MCP_DISTRIBUTED_SEARCH_TIMEOUT_SECONDS", 60)
        health_timeout = positive_setting("MCP_HEALTH_TIMEOUT_SECONDS", 5)
        call_timeout = positive_setting("MCP_NODE_CALL_TIMEOUT_SECONDS", 600)
        self.connections = {
            d.device_id: connection_factory(d, health_timeout=health_timeout, call_timeout=call_timeout)
            for d in self.registry.enabled
        }
        ssh_devices = tuple(d for d in self.registry.enabled if d.transport == "ssh")
        executable = resolve_ssh() if ssh_devices else ""
        self.tunnels = {
            d.device_id: (tunnel_factory(d, executable) if d.transport == "ssh" else LocalEndpointManager(d))
            for d in self.registry.enabled
        }
        self._monitors = []

    def build(self) -> FastMCP:
        from mcp_message_session import McpMessageSessionMiddleware

        mcp = FastMCP(name="windows-code-search-gateway", lifespan=self.lifespan, auth=build_auth(self.config))
        mcp.add_middleware(McpMessageSessionMiddleware())
        for device_id, connection in self.connections.items():
            # Mount immediately, even when offline. The provider serves verified
            # schema snapshots and later discovery needs no gateway restart.
            node = FastMCP(name=f"node-{device_id}", providers=[connection])
            mcp.mount(node, namespace=device_id)
        self._register_discovery_routes(mcp)
        readonly = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)

        @mcp.tool(annotations=readonly)
        def list_devices() -> list[dict]:
            """List configured devices and cached status, including disabled or unreachable devices."""
            return [self.device_status(d.device_id) for d in self.registry.devices]

        @mcp.tool(annotations=readonly)
        async def device_health(device_id: str) -> dict:
            """Refresh one device's identity, tool schemas and health without affecting other devices."""
            self.device_status(device_id)  # Validate before looking up a connection.
            if device_id in self.connections:
                await self.connections[device_id].refresh()
            return self.device_status(device_id)

        @mcp.tool(annotations=readonly)
        async def distributed_code_search(query: str, device_ids: list[str] | None = None,
                                          repo: dict[str, str] | None = None, limit: int = 8) -> dict:
            """Search enabled nodes concurrently. repo is {deviceId, repoId}; results retain origin and node scores. Offline nodes produce partial results."""
            return await search_devices(self.connections, query, device_ids, repo, limit, self.search_timeout)

        return mcp

    def device_status(self, device_id: str) -> dict:
        device = next((d for d in self.registry.devices if d.device_id == device_id), None)
        if device is None:
            raise ValueError(f"Unknown device: {device_id}")
        if not device.enabled:
            return {"device_id": device_id, "name": device.name, "transport": device.transport,
                    "enabled": False, "state": "disabled"}
        tunnel = self.tunnels[device_id]
        return {"device_id": device_id, "name": device.name, "transport": device.transport, "enabled": True,
                **asdict(self.connections[device_id].status), "tunnel_error": tunnel.last_error}

    @asynccontextmanager
    async def lifespan(self, _):
        try:
            for tunnel in self.tunnels.values():
                tunnel.start()
            await asyncio.gather(*(c.refresh() for c in self.connections.values()))
            self._monitors = [asyncio.create_task(monitor_node(c, self.health_interval))
                              for c in self.connections.values()]
            yield
        finally:
            # The MCP transport may cancel its enclosing AnyIO scope before
            # exiting the lifespan. Shield cleanup so SSH children cannot leak.
            with anyio.CancelScope(shield=True):
                for task in self._monitors:
                    task.cancel()
                await asyncio.gather(*self._monitors, return_exceptions=True)
                self._monitors.clear()
                await asyncio.gather(*(t.stop() for t in self.tunnels.values()), return_exceptions=True)
