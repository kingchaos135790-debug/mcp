from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import logging
import os

import bootstrap  # noqa: F401

from fastmcp import FastMCP
from windows_mcp.analytics import PostHogAnalytics
from windows_mcp.desktop.service import Desktop
from windows_mcp.watchdog.service import WatchDog

from server_config import Config, build_auth
from server_extensions import ServerExtension
from server_runtime import RepositoryAutoIndexer, SearchEngineBridge, ServerContext


logger = logging.getLogger(__name__)


class ServerApp:
    def __init__(self, config: Config, extensions: list[ServerExtension]) -> None:
        self.config = config
        self.context = ServerContext(config=config, engine=SearchEngineBridge(config))
        self.extensions = extensions

    def build(self) -> FastMCP:
        mcp = FastMCP(
            name="windows-code-search-mcp",
            lifespan=self.lifespan,
            auth=build_auth(self.config),
        )
        for extension in self.extensions:
            extension.register(mcp, self.context)
        return mcp

    @asynccontextmanager
    async def lifespan(self, app: FastMCP):
        await self._start_core_services()
        try:
            for extension in self.extensions:
                await extension.start(self.context)
            yield
        finally:
            for extension in reversed(self.extensions):
                await extension.stop(self.context)
            await self._stop_core_services()

    async def _start_core_services(self) -> None:
        if os.getenv("ANONYMIZED_TELEMETRY", "true").lower() != "false":
            self.context.analytics = PostHogAnalytics()

        self.context.desktop = Desktop()
        self.context.watchdog = WatchDog()
        self.context.watchdog.set_focus_callback(self.context.desktop.tree.on_focus_change)
        self.context.auto_indexer = RepositoryAutoIndexer(self.config, self.context.engine)

        self.context.watchdog.start()
        await asyncio.sleep(1)
        await self.context.auto_indexer.start()
        await self.context.auto_indexer.log_launch_status()

    async def _stop_core_services(self) -> None:
        if self.context.auto_indexer is not None:
            await self.context.auto_indexer.stop()
            self.context.auto_indexer = None
        if self.context.watchdog is not None:
            self.context.watchdog.stop()
            self.context.watchdog = None
        if self.context.analytics is not None:
            await self.context.analytics.close()
            self.context.analytics = None
        self.context.desktop = None
