from __future__ import annotations

from dataclasses import asdict
from functools import wraps
import inspect
import json
import os
from pathlib import Path
from typing import Any, Callable, ParamSpec, Protocol, TypeVar, cast

import bootstrap  # noqa: F401

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from windows_mcp.tools import register_all

from server_config import path_is_within
from server_runtime import ServerContext
from server_vscode_bridge import VSCodeBridgeServer
from session_context import bind_current_request_session, get_current_chat_session_id


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


def normalize_vscode_text(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


def is_vscode_edit_drift_error(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    status = str(result.get("status", "ok")).strip().lower()
    if not status or status == "ok":
        return False
    normalized_error = normalize_vscode_text(str(result.get("error", ""))).lower()
    return (
        "expected text mismatch before applying edit" in normalized_error
        or "expected text mismatch before workspace edit" in normalized_error
        or "could not reliably locate edit target after drift" in normalized_error
        or ("edit target" in normalized_error and "drift" in normalized_error)
    )


def resolve_vscode_workspace_root(bridge: VSCodeBridgeServer, session_id: str) -> str:
    snapshot = bridge.state.get_session_snapshot(session_id)
    if snapshot is None:
        raise ValueError(f"VS Code session not found: {session_id}")
    return str(snapshot.get("workspaceRoot", "")) if isinstance(snapshot, dict) else ""


def position_to_offset(content: str, line_number: int, column_number: int) -> int:
    if line_number < 1:
        raise ValueError("line_number must be >= 1")
    if column_number < 1:
        raise ValueError("column_number must be >= 1")
    normalized = normalize_vscode_text(content)
    if normalized == "":
        if line_number == 1 and column_number == 1:
            return 0
        raise ValueError("position is outside the available text")

    lines = normalized.splitlines(keepends=True)
    if line_number > len(lines):
        if line_number == len(lines) + 1 and column_number == 1 and normalized.endswith("\n"):
            return len(normalized)
        raise ValueError("line_number is outside the available text")

    offset = sum(len(line) for line in lines[: line_number - 1])
    line = lines[line_number - 1]
    line_text = line[:-1] if line.endswith("\n") else line
    max_column = len(line_text) + 1
    if column_number > max_column:
        raise ValueError("column_number is outside the available text")
    return offset + (column_number - 1)


def offset_to_line_and_column(content: str, offset: int, base_line: int = 1) -> tuple[int, int]:
    normalized = normalize_vscode_text(content)
    if offset < 0 or offset > len(normalized):
        raise ValueError("offset is outside the available text")
    prefix = normalized[:offset]
    line = base_line + prefix.count("\n")
    last_newline = prefix.rfind("\n")
    column = (len(prefix) + 1) if last_newline < 0 else (len(prefix) - last_newline)
    return line, column


def extract_live_range_text(workspace_root: str, file_path: str, start_line: int, start_column: int, end_line: int, end_column: int) -> tuple[Path, str]:
    resolved = resolve_workspace_file_path(workspace_root, file_path)
    content = normalize_vscode_text(resolved.read_text(encoding="utf-8", errors="replace"))
    start_offset = position_to_offset(content, start_line, start_column)
    end_offset = position_to_offset(content, end_line, end_column)
    if end_offset < start_offset:
        raise ValueError("end position must be >= start position")
    return resolved, content[start_offset:end_offset]


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
        guidance = (
            "Re-read with get_vscode_file_range, retry with fresh expected_text, and confirm the VS Code session is active and polling."
        )
        normalized_error = error.lower()
        if (
            "expected text mismatch before applying edit" in normalized_error
            or "expected text mismatch before workspace edit" in normalized_error
            or "could not reliably locate edit target after drift" in normalized_error
            or ("edit target" in normalized_error and "drift" in normalized_error)
        ):
            guidance = (
                "Re-read the exact range with get_vscode_file_range, retry with fresh expected_text, and consider a narrower edit, a smaller anchored change, or safe_vscode_edit."
            )
        elif "resource not found" in normalized_error:
            guidance = (
                "Refresh the available tool paths, prefer the canonical /Windows MCP/... path, and retry after confirming the VS Code session is still active."
            )
        elif "outside the vs code workspace root" in normalized_error:
            guidance = (
                "Use FileSystem or PowerShell for files outside the active workspace, or switch to a VS Code session rooted at the target repo before retrying."
            )
        raise RuntimeError(f"{action} failed: {error}. {guidance}")
    return result


def get_vscode_bridge(context: ServerContext) -> VSCodeBridgeServer:
    return cast(VSCodeBridgeServer, context.get_vscode_bridge())


P = ParamSpec("P")
R = TypeVar("R")


def bind_chat_session(session_id: str | None, *, required: bool = True) -> str:
    requested_session_id = (session_id or "").strip()
    if requested_session_id:
        bound_session_id = bind_current_request_session(requested_session_id)
        if bound_session_id:
            return bound_session_id

    current_session_id = get_current_chat_session_id()
    if current_session_id:
        return current_session_id

    if required:
        raise ValueError("session_id is required unless the current request is already bound to a chat session")
    return ""


def session_bound_tool(func: Callable[P, R]) -> Callable[P, R]:
    signature = inspect.signature(func)

    if inspect.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs):
            bound = signature.bind_partial(*args, **kwargs)
            bound.arguments["session_id"] = bind_chat_session(cast(str | None, bound.arguments.get("session_id", "")))
            return await cast(Any, func)(*bound.args, **bound.kwargs)

        return cast(Callable[P, R], async_wrapper)

    @wraps(func)
    def sync_wrapper(*args: P.args, **kwargs: P.kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        bound.arguments["session_id"] = bind_chat_session(cast(str | None, bound.arguments.get("session_id", "")))
        return func(*bound.args, **bound.kwargs)

    return cast(Callable[P, R], sync_wrapper)


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
        @session_bound_tool
        async def request_vscode_edit(
            session_id: str = "",
            file_path: str = "",
            start_line: int = 0,
            start_column: int = 0,
            end_line: int = 0,
            end_column: int = 0,
            new_text: str = "",
            expected_text: str = "",
            timeout_seconds: int = 30,
        ) -> str:
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            normalized_new_text = normalize_vscode_text(new_text)
            normalized_expected_text = normalize_vscode_text(expected_text) if expected_text else ""
            result = await bridge.request_edit(
                session_id=session_id,
                file_path=file_path,
                start_line=start_line,
                start_column=start_column,
                end_line=end_line,
                end_column=end_column,
                new_text=normalized_new_text,
                expected_text=normalized_expected_text,
                timeout_seconds=timeout_seconds,
            )
            if is_vscode_edit_drift_error(result) and normalized_expected_text:
                workspace_root = resolve_vscode_workspace_root(bridge, session_id)
                resolved, live_expected_text = extract_live_range_text(workspace_root, file_path, start_line, start_column, end_line, end_column)
                result = await bridge.request_edit(
                    session_id=session_id,
                    file_path=str(resolved),
                    start_line=start_line,
                    start_column=start_column,
                    end_line=end_line,
                    end_column=end_column,
                    new_text=normalized_new_text,
                    expected_text=live_expected_text,
                    timeout_seconds=timeout_seconds,
                )
                if isinstance(result, dict):
                    result.setdefault("retriedWithFreshExpectedText", True)
                    result.setdefault("refreshedExpectedText", live_expected_text)
                    result.setdefault("refreshReason", "Retried after re-reading the exact live range from disk and normalizing line endings.")
                    result.setdefault("initialExpectedTextMatchedAfterNormalization", normalize_vscode_text(expected_text) == normalize_vscode_text(live_expected_text))
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
        @session_bound_tool
        async def request_vscode_workspace_edit(
            session_id: str = "",
            edits_json: str = "",
            label: str = "MCP workspace edit",
            timeout_seconds: int = 30,
        ) -> str:
            try:
                parsed = json.loads(edits_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid edits_json: {exc}") from exc
            if not isinstance(parsed, list):
                raise ValueError("edits_json must decode to a list")
            normalized_parsed: list[dict[str, object]] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                normalized_item = dict(item)
                if isinstance(normalized_item.get("newText"), str):
                    normalized_item["newText"] = normalize_vscode_text(str(normalized_item["newText"]))
                elif isinstance(normalized_item.get("new_text"), str):
                    normalized_item["new_text"] = normalize_vscode_text(str(normalized_item["new_text"]))
                if isinstance(normalized_item.get("expectedText"), str):
                    normalized_item["expectedText"] = normalize_vscode_text(str(normalized_item["expectedText"]))
                elif isinstance(normalized_item.get("expected_text"), str):
                    normalized_item["expected_text"] = normalize_vscode_text(str(normalized_item["expected_text"]))
                normalized_parsed.append(normalized_item)
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            result = await bridge.request_workspace_edit(
                session_id=session_id,
                label=label,
                edits=normalized_parsed,
                timeout_seconds=timeout_seconds,
            )
            if is_vscode_edit_drift_error(result):
                workspace_root = resolve_vscode_workspace_root(bridge, session_id)
                refreshed_edits: list[dict[str, object]] = []
                refreshed_count = 0
                for item in normalized_parsed:
                    refreshed_item = dict(item)
                    file_path_value = refreshed_item.get("filePath") or refreshed_item.get("file_path")
                    range_payload = refreshed_item.get("range")
                    if not isinstance(range_payload, dict):
                        range_payload = {
                            "startLine": refreshed_item.get("startLine") or refreshed_item.get("start_line"),
                            "startColumn": refreshed_item.get("startColumn") or refreshed_item.get("start_column"),
                            "endLine": refreshed_item.get("endLine") or refreshed_item.get("end_line"),
                            "endColumn": refreshed_item.get("endColumn") or refreshed_item.get("end_column"),
                        }
                    expected_value = refreshed_item.get("expectedText")
                    expected_key = "expectedText"
                    if not isinstance(expected_value, str):
                        expected_value = refreshed_item.get("expected_text")
                        expected_key = "expected_text"
                    if isinstance(file_path_value, str) and file_path_value.strip() and isinstance(expected_value, str) and expected_value:
                        try:
                            start_line_value = int(range_payload.get("startLine") or 1)
                            start_column_value = int(range_payload.get("startColumn") or 1)
                            end_line_value = int(range_payload.get("endLine") or start_line_value)
                            end_column_value = int(range_payload.get("endColumn") or start_column_value)
                            resolved, live_expected_text = extract_live_range_text(workspace_root, str(file_path_value), start_line_value, start_column_value, end_line_value, end_column_value)
                            refreshed_item["filePath"] = str(resolved)
                            refreshed_item[expected_key] = live_expected_text
                            refreshed_count += 1
                        except Exception:
                            refreshed_item[expected_key] = normalize_vscode_text(expected_value)
                    elif isinstance(expected_value, str):
                        refreshed_item[expected_key] = normalize_vscode_text(expected_value)
                    refreshed_edits.append(refreshed_item)
                result = await bridge.request_workspace_edit(
                    session_id=session_id,
                    label=label,
                    edits=refreshed_edits,
                    timeout_seconds=timeout_seconds,
                )
                if isinstance(result, dict):
                    result.setdefault("retriedWithFreshExpectedText", refreshed_count > 0)
                    result.setdefault("refreshedEditCount", refreshed_count)
                    result.setdefault("refreshReason", "Retried after re-reading live expectedText for ranged edits and normalizing line endings.")
            return format_tool_result(require_vscode_command_success("request_vscode_workspace_edit", result))

        @mcp.tool(
            name="safe_vscode_edit",
            description="Find one exact text match in a VS Code workspace file, convert it into precise line and column coordinates, and apply a validated edit.",
            annotations=ToolAnnotations(
                title="safe_vscode_edit",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        @session_bound_tool
        async def safe_vscode_edit(
            session_id: str = "",
            file_path: str = "",
            search_text: str = "",
            replacement_text: str = "",
            start_line: int = 1,
            end_line: int = 0,
            timeout_seconds: int = 30,
        ) -> str:
            if not search_text:
                raise ValueError("search_text is required")
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            workspace_root = resolve_vscode_workspace_root(bridge, session_id)
            resolved = resolve_workspace_file_path(workspace_root, file_path)
            payload = read_numbered_file_range(resolved, start_line=start_line, end_line=end_line)
            haystack = normalize_vscode_text(str(payload.get("content", "")))
            needle = normalize_vscode_text(search_text)
            match_count = haystack.count(needle)
            if match_count == 0:
                raise ValueError("search_text was not found in the requested file range")
            if match_count > 1:
                raise ValueError("search_text matched more than once; narrow the line window or provide a more specific anchor")
            window_start_line = int(payload.get("startLine") or 1)
            start_offset = haystack.index(needle)
            end_offset = start_offset + len(needle)
            match_start_line, match_start_column = offset_to_line_and_column(haystack, start_offset, base_line=window_start_line)
            match_end_line, match_end_column = offset_to_line_and_column(haystack, end_offset, base_line=window_start_line)
            _, live_expected_text = extract_live_range_text(workspace_root, str(resolved), match_start_line, match_start_column, match_end_line, match_end_column)
            result = await bridge.request_edit(
                session_id=session_id,
                file_path=str(resolved),
                start_line=match_start_line,
                start_column=match_start_column,
                end_line=match_end_line,
                end_column=match_end_column,
                new_text=normalize_vscode_text(replacement_text),
                expected_text=live_expected_text,
                timeout_seconds=timeout_seconds,
            )
            if isinstance(result, dict):
                result.setdefault("safeEdit", True)
                result.setdefault("matchedText", live_expected_text)
                result.setdefault("filePath", str(resolved))
                result.setdefault(
                    "range",
                    {
                        "startLine": match_start_line,
                        "startColumn": match_start_column,
                        "endLine": match_end_line,
                        "endColumn": match_end_column,
                    },
                )
            return format_tool_result(require_vscode_command_success("safe_vscode_edit", result))

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
        @session_bound_tool
        async def open_vscode_file(
            session_id: str = "",
            file_path: str = "",
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
