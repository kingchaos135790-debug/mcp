from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
from typing import Any, Protocol, cast

import bootstrap  # noqa: F401

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from windows_mcp.tools import register_all

from server_config import path_is_within
from server_runtime import ServerContext
from server_vscode_bridge import VSCodeBridgeServer


def format_tool_result(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True)


def count_text_lines(content: str) -> int:
    if not content:
        return 0
    return len(content.splitlines()) or 1


def summarize_vscode_context_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    summarized: list[dict[str, object]] = []
    for item in items:
        summary = {key: value for key, value in item.items() if key != "content"}
        content = item.get("content")
        if isinstance(content, str):
            summary["contentLength"] = len(content)
            summary["hasContent"] = bool(content)
            line_count = count_text_lines(content)
            summary["lineCount"] = line_count
            if "startLine" not in summary and item.get("kind") in {"file", "snippet"} and line_count > 0:
                summary["startLine"] = 1
                summary["endLine"] = line_count
        else:
            summary["contentLength"] = 0
            summary["hasContent"] = False
            summary["lineCount"] = 0
        summarized.append(summary)
    return summarized


def coerce_line_number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        coerced = int(value)
        return coerced if coerced > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        coerced = int(value.strip())
        return coerced if coerced > 0 else None
    return None


def normalize_search_hit(hit: object) -> object:
    if not isinstance(hit, dict):
        return hit

    normalized = dict(hit)
    file_path = hit.get("filePath") or hit.get("path") or hit.get("file")
    if isinstance(file_path, str) and file_path.strip():
        normalized["filePath"] = file_path

    snippet = hit.get("snippet") or hit.get("text")
    if isinstance(snippet, str) and snippet:
        normalized["snippet"] = snippet

    start_line = coerce_line_number(hit.get("startLine"))
    end_line = coerce_line_number(hit.get("endLine"))
    line = coerce_line_number(hit.get("line"))
    if start_line is not None or end_line is not None or line is not None:
        normalized["location"] = {
            "line": line,
            "startLine": start_line,
            "endLine": end_line,
        }
    return normalized


def normalize_search_result(result: object) -> object:
    if isinstance(result, list):
        return [normalize_search_hit(item) for item in result]
    if not isinstance(result, dict):
        return result

    normalized = dict(result)
    for key in ("hits", "semantic", "lexical", "fused"):
        value = normalized.get(key)
        if isinstance(value, list):
            normalized[key] = [normalize_search_hit(item) for item in value]
    return normalized


def resolve_workspace_file_path(workspace_root: str, file_path: str) -> Path:
    raw_path = file_path.strip()
    if not raw_path:
        raise ValueError("file_path is required")

    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        if not workspace_root:
            raise ValueError("Relative file_path requires a VS Code session with a workspaceRoot")
        candidate = Path(workspace_root) / candidate

    resolved = candidate.resolve()
    if workspace_root and not path_is_within(str(resolved), workspace_root):
        raise ValueError(f"File path is outside the VS Code workspace root: {resolved}")
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"Path is not a file: {resolved}")
    return resolved


def read_numbered_file_range(
    file_path: Path,
    start_line: int = 1,
    end_line: int = 0,
    context_before: int = 0,
    context_after: int = 0,
) -> dict[str, object]:
    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if end_line < 0:
        raise ValueError("end_line must be >= 0")
    if context_before < 0 or context_after < 0:
        raise ValueError("context_before and context_after must be >= 0")

    content = file_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    total_lines = len(lines)

    if total_lines == 0:
        return {
            "filePath": str(file_path),
            "lineCount": 0,
            "requestedStartLine": start_line,
            "requestedEndLine": end_line,
            "startLine": 0,
            "endLine": 0,
            "content": "",
            "lines": [],
        }

    effective_end_line = total_lines if end_line == 0 else end_line
    if effective_end_line < start_line:
        raise ValueError("end_line must be >= start_line")

    window_start = max(1, start_line - context_before)
    window_end = min(total_lines, effective_end_line + context_after)
    selected_lines = [
        {"lineNumber": line_number, "text": lines[line_number - 1]}
        for line_number in range(window_start, window_end + 1)
    ]

    return {
        "filePath": str(file_path),
        "lineCount": total_lines,
        "requestedStartLine": start_line,
        "requestedEndLine": effective_end_line,
        "startLine": window_start,
        "endLine": window_end,
        "content": "\n".join(line["text"] for line in selected_lines),
        "lines": selected_lines,
    }


def run_engine_tool(context: ServerContext, tool_name: str, payload: dict[str, object]) -> object:
    try:
        return context.engine.run_tool(tool_name, payload)
    except Exception as exc:
        raise RuntimeError(f"{tool_name} failed: {exc}") from exc


def require_vscode_command_success(action: str, result: object) -> dict[str, object]:
    if not isinstance(result, dict):
        raise RuntimeError(f"{action} returned an invalid VS Code bridge response")

    status = str(result.get("status", "ok")).strip().lower()
    if status and status != "ok":
        error = str(result.get("error", "")).strip() or f"{action} failed"
        raise RuntimeError(
            f"{action} failed: {error}. Re-read with get_vscode_file_range, retry with fresh expected_text, "
            "and confirm the VS Code session is active and polling."
        )
    return result


def get_vscode_bridge(context: ServerContext) -> VSCodeBridgeServer:
    return cast(VSCodeBridgeServer, context.get_vscode_bridge())


class ServerExtension(Protocol):
    def register(self, mcp: FastMCP, context: ServerContext) -> None: ...

    async def start(self, context: ServerContext) -> None: ...

    async def stop(self, context: ServerContext) -> None: ...


class SearchExtension:
    def register(self, mcp: FastMCP, context: ServerContext) -> None:
        @mcp.tool(
            name="semantic_code_search",
            description="Search indexed code semantically from Qdrant.",
            annotations=ToolAnnotations(
                title="semantic_code_search",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        def semantic_code_search(query: str, limit: int = 8, repo: str = "") -> str:
            return format_tool_result(
                normalize_search_result(run_engine_tool(context, "semantic_code_search", {"query": query, "limit": limit, "repo": repo}))
            )

        @mcp.tool(
            name="lexical_code_search",
            description="Search indexed code lexically through ripgrep or the local fallback index. Supports case_mode: smart, ignore, or sensitive.",
            annotations=ToolAnnotations(
                title="lexical_code_search",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        def lexical_code_search(query: str, limit: int = 8, repo: str = "", case_mode: str = "smart") -> str:
            return format_tool_result(
                normalize_search_result(
                    run_engine_tool(context, "lexical_code_search", {"query": query, "limit": limit, "repo": repo, "case_mode": case_mode})
                )
            )

        @mcp.tool(
            name="hybrid_code_search",
            description="Combine Qdrant semantic search with ripgrep or local lexical search.",
            annotations=ToolAnnotations(
                title="hybrid_code_search",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        def hybrid_code_search(query: str, limit: int = 8, repo: str = "") -> str:
            return format_tool_result(
                normalize_search_result(run_engine_tool(context, "hybrid_code_search", {"query": query, "limit": limit, "repo": repo}))
            )

        @mcp.tool(
            name="server_health",
            description="Show search-engine configuration, dependency readiness, and auto-index status.",
            annotations=ToolAnnotations(
                title="server_health",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        async def server_health() -> str:
            result = run_engine_tool(context, "server_health", {})
            if isinstance(result, dict):
                result["autoIndexConfigPath"] = context.config.managed_repositories_path
                result["autoIndexRepositories"] = [asdict(item) for item in await context.get_auto_indexer().load_repositories()]
            return format_tool_result(result)

        @mcp.tool(
            name="list_indexed_repositories",
            description="List indexed codebases available for repo-scoped search.",
            annotations=ToolAnnotations(
                title="list_indexed_repositories",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        def list_indexed_repositories() -> str:
            return format_tool_result(run_engine_tool(context, "list_indexed_repositories", {}))

        @mcp.tool(
            name="index_repository",
            description="Index a source repository now. Re-running is incremental and updates only changed or deleted files.",
            annotations=ToolAnnotations(
                title="index_repository",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def index_repository(repo_root: str = "") -> str:
            result = await context.get_auto_indexer().run_index(repo_root or os.getenv("REPO_ROOT", "."), reason="manual")
            return format_tool_result(result)

        @mcp.tool(
            name="remove_indexed_repository",
            description="Remove indexed artifacts and Qdrant vectors for a repository.",
            annotations=ToolAnnotations(
                title="remove_indexed_repository",
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        def remove_indexed_repository(repo_root: str) -> str:
            return format_tool_result(run_engine_tool(context, "remove_indexed_repository", {"repoRoot": repo_root}))

        @mcp.tool(
            name="list_auto_index_repositories",
            description="List repositories managed for startup auto-indexing and file-watch reindexing.",
            annotations=ToolAnnotations(
                title="list_auto_index_repositories",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        async def list_auto_index_repositories() -> str:
            repositories = [asdict(item) for item in await context.get_auto_indexer().load_repositories()]
            return format_tool_result(repositories)

        @mcp.tool(
            name="add_auto_index_repository",
            description="Add a repository to managed auto-indexing. Optionally index it now and watch for future file changes.",
            annotations=ToolAnnotations(
                title="add_auto_index_repository",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def add_auto_index_repository(
            repo_root: str,
            watch: bool = True,
            auto_index_on_start: bool = True,
            index_now: bool = True,
        ) -> str:
            result = await context.get_auto_indexer().add_repository(
                repo_root,
                watch=watch,
                auto_index_on_start=auto_index_on_start,
                index_now=index_now,
            )
            return format_tool_result(result)

        @mcp.tool(
            name="remove_auto_index_repository",
            description="Remove a repository from managed startup auto-indexing and file watching.",
            annotations=ToolAnnotations(
                title="remove_auto_index_repository",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def remove_auto_index_repository(repo: str) -> str:
            result = await context.get_auto_indexer().remove_repository(repo)
            return format_tool_result(result)

    async def start(self, context: ServerContext) -> None:
        return None

    async def stop(self, context: ServerContext) -> None:
        return None


class WindowsDesktopExtension:
    def register(self, mcp: FastMCP, context: ServerContext) -> None:
        register_all(mcp, get_desktop=lambda: context.desktop, get_analytics=lambda: context.analytics)

    async def start(self, context: ServerContext) -> None:
        return None

    async def stop(self, context: ServerContext) -> None:
        return None


class VSCodeBridgeExtension:
    def register(self, mcp: FastMCP, context: ServerContext) -> None:
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
        def get_vscode_session(session_id: str) -> str:
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
        def get_vscode_context(session_id: str) -> str:
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
        def get_vscode_context_summary(session_id: str) -> str:
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
        def get_vscode_diagnostics(session_id: str, severity: str = "") -> str:
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
        def get_vscode_file_range(
            session_id: str,
            file_path: str,
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

        @mcp.tool(
            name="request_vscode_edit",
            description="Ask the VS Code extension to apply one text edit to a file using exact line and column ranges.",
            annotations=ToolAnnotations(
                title="request_vscode_edit",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def request_vscode_edit(
            session_id: str,
            file_path: str,
            start_line: int,
            start_column: int,
            end_line: int,
            end_column: int,
            new_text: str,
            expected_text: str = "",
            timeout_seconds: int = 30,
        ) -> str:
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            result = await bridge.request_edit(
                session_id=session_id,
                file_path=file_path,
                start_line=start_line,
                start_column=start_column,
                end_line=end_line,
                end_column=end_column,
                new_text=new_text,
                expected_text=expected_text,
                timeout_seconds=timeout_seconds,
            )
            return format_tool_result(require_vscode_command_success("request_vscode_edit", result))

        @mcp.tool(
            name="request_vscode_workspace_edit",
            description="Ask the VS Code extension to apply multiple edits through one workspace edit request.",
            annotations=ToolAnnotations(
                title="request_vscode_workspace_edit",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def request_vscode_workspace_edit(
            session_id: str,
            edits_json: str,
            label: str = "MCP workspace edit",
            timeout_seconds: int = 30,
        ) -> str:
            try:
                parsed = json.loads(edits_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid edits_json: {exc}") from exc
            if not isinstance(parsed, list):
                raise ValueError("edits_json must decode to a list")
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            result = await bridge.request_workspace_edit(
                session_id=session_id,
                label=label,
                edits=[item for item in parsed if isinstance(item, dict)],
                timeout_seconds=timeout_seconds,
            )
            return format_tool_result(require_vscode_command_success("request_vscode_workspace_edit", result))

        @mcp.tool(
            name="open_vscode_file",
            description="Ask the VS Code extension to reveal a file at a specific line and column.",
            annotations=ToolAnnotations(
                title="open_vscode_file",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def open_vscode_file(
            session_id: str,
            file_path: str,
            line: int = 1,
            column: int = 1,
            preserve_focus: bool = False,
            timeout_seconds: int = 15,
        ) -> str:
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            result = await bridge.request_open_file(
                session_id=session_id,
                file_path=file_path,
                line=line,
                column=column,
                preserve_focus=preserve_focus,
                timeout_seconds=timeout_seconds,
            )
            return format_tool_result(require_vscode_command_success("open_vscode_file", result))

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


