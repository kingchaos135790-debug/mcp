from __future__ import annotations

from fastmcp import FastMCP
from windows_mcp.tools import register_all

from server_runtime import ServerContext


class WindowsDesktopExtension:
    def register(self, mcp: FastMCP, context: ServerContext) -> None:
        register_all(mcp, get_desktop=lambda: context.desktop, get_analytics=lambda: context.analytics)

    async def start(self, context: ServerContext) -> None:
        return None

    async def stop(self, context: ServerContext) -> None:
        return None
