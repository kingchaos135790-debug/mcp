from __future__ import annotations

import bootstrap  # noqa: F401
from typing import Protocol

from fastmcp import FastMCP

from extensions.common import (
    bind_chat_session,
    format_tool_result,
    get_vscode_bridge,
    is_vscode_edit_drift_error,
    require_vscode_command_success,
    resolve_vscode_workspace_root,
    run_engine_tool,
    session_bound_tool,
)
from extensions.desktop import WindowsDesktopExtension
from extensions.search import SearchExtension
from extensions.vscode_edits import VSCodeEditExtension
from extensions.vscode_sessions import VSCodeSessionExtension
from server_runtime import ServerContext
from server_vscode_bridge import VSCodeBridgeServer


class ServerExtension(Protocol):
    def register(self, mcp: FastMCP, context: ServerContext) -> None: ...

    async def start(self, context: ServerContext) -> None: ...

    async def stop(self, context: ServerContext) -> None: ...


class VSCodeBridgeExtension:
    def __init__(self) -> None:
        self._session_extension = VSCodeSessionExtension()
        self._edit_extension = VSCodeEditExtension()

    def register(self, mcp: FastMCP, context: ServerContext) -> None:
        self._session_extension.register(mcp, context)
        self._edit_extension.register(mcp, context)

    async def start(self, context: ServerContext) -> None:
        bridge = VSCodeBridgeServer(context.config)
        if bridge.enabled:
            bridge.start()
        context.vscode_bridge = bridge

    async def stop(self, context: ServerContext) -> None:
        bridge = context.vscode_bridge
        if isinstance(bridge, VSCodeBridgeServer):
            bridge.stop()
        context.vscode_bridge = None


__all__ = [
    "ServerExtension",
    "SearchExtension",
    "VSCodeBridgeExtension",
    "WindowsDesktopExtension",
    "bind_chat_session",
    "format_tool_result",
    "get_vscode_bridge",
    "is_vscode_edit_drift_error",
    "require_vscode_command_success",
    "resolve_vscode_workspace_root",
    "run_engine_tool",
    "session_bound_tool",
]
