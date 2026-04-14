from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from server_runtime import ServerContext
from server_vscode_bridge import VSCodeBridgeServer
from utils.file_ranges import read_numbered_file_range, resolve_workspace_file_path
from utils.search_normalization import summarize_vscode_context_items

from .common import bind_chat_session, format_tool_result, get_vscode_bridge, session_bound_tool


class VSCodeSessionExtension:
    def register(self, mcp: FastMCP, context: ServerContext) -> None:
        @mcp.tool(
            name="create_vscode_session",
            description="Create an empty VS Code bridge session so one chat or task can reserve its own session id before context or edits arrive.",
            annotations=ToolAnnotations(
                title="create_vscode_session",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        def create_vscode_session(
            session_id: str = "",
            workspace_root: str = "",
            workspace_name: str = "",
            active_file: str = "",
        ) -> str:
            session_id = bind_chat_session(session_id, required=False) or session_id
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            payload = {
                "workspaceRoot": workspace_root,
                "workspaceName": workspace_name,
                "activeFile": active_file,
            }
            return format_tool_result(
                {
                    "enabled": bridge.enabled,
                    "baseUrl": bridge.base_url,
                    "session": bridge.state.create_session(session_id=session_id, payload=payload),
                }
            )

        @mcp.tool(
            name="close_vscode_session",
            description="Close one VS Code bridge session and discard any remaining pending commands for that session.",
            annotations=ToolAnnotations(
                title="close_vscode_session",
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        @session_bound_tool
        def close_vscode_session(session_id: str = "") -> str:
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            return format_tool_result(
                {
                    "enabled": bridge.enabled,
                    "baseUrl": bridge.base_url,
                    "result": bridge.state.close_session(session_id),
                }
            )

        @mcp.tool(
            name="list_vscode_sessions",
            description="List active or recently seen VS Code bridge sessions discovered by context, diagnostics, heartbeat, or command polling.",
            annotations=ToolAnnotations(
                title="list_vscode_sessions",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        def list_vscode_sessions() -> str:
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            return format_tool_result(
                {
                    "enabled": bridge.enabled,
                    "baseUrl": bridge.base_url,
                    "sessions": bridge.state.list_sessions(),
                }
            )

        @mcp.tool(
            name="get_vscode_session",
            description="Show the latest VS Code context and diagnostics snapshot for one bridge session.",
            annotations=ToolAnnotations(
                title="get_vscode_session",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @session_bound_tool
        def get_vscode_session(session_id: str = "") -> str:
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            snapshot = bridge.state.get_session_snapshot(session_id)
            if snapshot is None:
                raise ValueError(f"VS Code session not found: {session_id}")
            return format_tool_result(snapshot)

        @mcp.tool(
            name="get_vscode_context",
            description="Return dropped snippets and file content currently stored in a VS Code context window session.",
            annotations=ToolAnnotations(
                title="get_vscode_context",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @session_bound_tool
        def get_vscode_context(session_id: str = "") -> str:
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            return format_tool_result(
                {
                    "sessionId": session_id,
                    "items": bridge.state.get_context_items(session_id),
                }
            )

        @mcp.tool(
            name="get_vscode_context_summary",
            description="Return basic VS Code context item metadata like labels, paths, and types without file contents.",
            annotations=ToolAnnotations(
                title="get_vscode_context_summary",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @session_bound_tool
        def get_vscode_context_summary(session_id: str = "") -> str:
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            return format_tool_result(
                {
                    "sessionId": session_id,
                    "items": summarize_vscode_context_items(bridge.state.get_context_items(session_id)),
                }
            )

        @mcp.tool(
            name="get_vscode_diagnostics",
            description="Return the latest IDE diagnostics pushed from VS Code for a bridge session.",
            annotations=ToolAnnotations(
                title="get_vscode_diagnostics",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @session_bound_tool
        def get_vscode_diagnostics(session_id: str = "", severity: str = "") -> str:
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            diagnostics = bridge.state.get_diagnostics(session_id)
            if severity.strip():
                normalized = severity.strip().lower()
                diagnostics = [item for item in diagnostics if str(item.get("severity", "")).lower() == normalized]
            return format_tool_result(
                {
                    "sessionId": session_id,
                    "severity": severity,
                    "diagnostics": diagnostics,
                }
            )

        @mcp.tool(
            name="get_vscode_file_range",
            description="Read a VS Code workspace file with numbered lines so MCP clients can target exact edit ranges.",
            annotations=ToolAnnotations(
                title="get_vscode_file_range",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @session_bound_tool
        def get_vscode_file_range(
            session_id: str = "",
            file_path: str = "",
            start_line: int = 1,
            end_line: int = 0,
            context_before: int = 0,
            context_after: int = 0,
        ) -> str:
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            snapshot = bridge.state.get_session_snapshot(session_id)
            if snapshot is None:
                raise ValueError(f"VS Code session not found: {session_id}")

            workspace_root = str(snapshot.get("workspaceRoot", "")) if isinstance(snapshot, dict) else ""
            resolved = resolve_workspace_file_path(workspace_root, file_path)
            payload = read_numbered_file_range(
                resolved,
                start_line=start_line,
                end_line=end_line,
                context_before=context_before,
                context_after=context_after,
            )
            payload["sessionId"] = session_id
            payload["workspaceRoot"] = workspace_root
            return format_tool_result(payload)

    async def start(self, context: ServerContext) -> None:
        return None

    async def stop(self, context: ServerContext) -> None:
        return None
