from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio  # noqa: F401 - compatibility for watchdog tests and callers
import logging

import anyio

import bootstrap  # noqa: F401

from fastmcp import FastMCP

from server_config import Config, build_auth
from server_extensions import ServerExtension
from local_node_runtime import LocalNodeRuntime, _watchdog_enabled  # noqa: F401
from server_public import PublicServerMixin


logger = logging.getLogger(__name__)


class ServerApp(PublicServerMixin):
    def __init__(self, config: Config, extensions: list[ServerExtension]) -> None:
        self.config = config
        self.runtime = LocalNodeRuntime(config)
        self.context = self.runtime.context
        self.extensions = extensions

    def build(self) -> FastMCP:
        mcp = FastMCP(
            name="windows-code-search-mcp",
            lifespan=self.lifespan,
            auth=build_auth(self.config),
        )
        # Bind tool/resource/prompt execution from FastMCP's logical session rather
        # than from ContextVars inherited by the long-lived server task at initialize.
        from mcp_message_session import McpMessageSessionMiddleware

        mcp.add_middleware(McpMessageSessionMiddleware())
        for extension in self.extensions:
            extension.register(mcp, self.context)
        if getattr(self.config, "role", "standalone") == "node":
            from distributed.health import register_node_health
            register_node_health(mcp, self.context)
        self._register_discovery_routes(mcp)
        return mcp

    @asynccontextmanager
    async def lifespan(self, app: FastMCP):
        started = []
        try:
            await self._start_core_services()
            for extension in self.extensions:
                started.append(extension)
                await extension.start(self.context)
            yield
        finally:
            with anyio.CancelScope(shield=True):
                for extension in reversed(started):
                    try:
                        await extension.stop(self.context)
                    except Exception:
                        logger.exception("Extension cleanup failed: %s", type(extension).__name__)
                await self._stop_core_services()

    async def _start_core_services(self) -> None:
        await self.runtime.start()

    async def _stop_core_services(self) -> None:
        await self.runtime.stop()
