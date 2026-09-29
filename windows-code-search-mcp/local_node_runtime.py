from __future__ import annotations

import asyncio
import logging
import os

from windows_mcp.analytics import PostHogAnalytics
from windows_mcp.desktop.service import Desktop
from windows_mcp.watchdog.service import WatchDog
from server_config import parse_bool
from server_runtime import RepositoryAutoIndexer, SearchEngineBridge, ServerContext

logger = logging.getLogger(__name__)


def _watchdog_enabled() -> bool:
    return parse_bool(os.getenv("WINDOWS_MCP_WATCHDOG_ENABLED"), False)


class LocalNodeRuntime:
    def __init__(self, config):
        self.config = config
        self.context = ServerContext(config=config, engine=SearchEngineBridge(config))

    async def start(self) -> None:
        if os.getenv("ANONYMIZED_TELEMETRY", "true").lower() != "false":
            self.context.analytics = PostHogAnalytics()

        self.context.desktop = Desktop()
        self.context.auto_indexer = RepositoryAutoIndexer(self.config, self.context.engine)

        if _watchdog_enabled():
            logger.info("Windows UIA watchdog enabled for integrated MCP server")
            self.context.watchdog = WatchDog()
            self.context.watchdog.set_focus_callback(self.context.desktop.tree.on_focus_change)
            self.context.watchdog.start()
            await asyncio.sleep(1)
        else:
            logger.info("Windows UIA watchdog disabled for integrated MCP server")

        await self.context.auto_indexer.start()
        await self.context.auto_indexer.log_launch_status()

    async def stop(self) -> None:
        errors = []
        if self.context.auto_indexer is not None:
            try:
                await self.context.auto_indexer.stop()
            except Exception as exc:
                errors.append(exc)
            finally:
                self.context.auto_indexer = None
        if self.context.watchdog is not None:
            try:
                self.context.watchdog.stop()
            except Exception as exc:
                errors.append(exc)
            finally:
                self.context.watchdog = None
        if self.context.analytics is not None:
            try:
                await self.context.analytics.close()
            except Exception as exc:
                errors.append(exc)
            finally:
                self.context.analytics = None
        self.context.desktop = None
        if errors:
            raise ExceptionGroup("Local runtime cleanup failed", errors)
