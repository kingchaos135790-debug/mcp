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
from extensions.file_edits import FileEditExtension
from extensions.search import SearchExtension
from server_runtime import ServerContext


class ServerExtension(Protocol):
    def register(self, mcp: FastMCP, context: ServerContext) -> None: ...

    async def start(self, context: ServerContext) -> None: ...

    async def stop(self, context: ServerContext) -> None: ...


__all__ = [
    "ServerExtension",
    "SearchExtension",
    "FileEditExtension",
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
