from __future__ import annotations

from importlib import import_module

from fastmcp import FastMCP

from server_runtime import ServerContext


class WindowsDesktopExtension:
    def register(self, mcp: FastMCP, context: ServerContext) -> None:
        for module_name in ("windows_mcp.tools.shell", "windows_mcp.tools.filesystem"):
            module = import_module(module_name)
            module.register(mcp, get_desktop=lambda: context.desktop, get_analytics=lambda: context.analytics)

    async def start(self, context: ServerContext) -> None:
        return None

    async def stop(self, context: ServerContext) -> None:
        return None
