from __future__ import annotations

from functools import wraps
import inspect
import json
from typing import Any, Callable, ParamSpec, TypeVar, cast

from server_runtime import ServerContext
from server_vscode_bridge import VSCodeBridgeServer
from session_context import bind_current_request_session, get_current_chat_session_id
from utils.text_normalization import normalize_vscode_text


P = ParamSpec("P")
R = TypeVar("R")


def format_tool_result(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True)


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


__all__ = [
    "bind_chat_session",
    "format_tool_result",
    "get_vscode_bridge",
    "is_vscode_edit_drift_error",
    "require_vscode_command_success",
    "resolve_vscode_workspace_root",
    "run_engine_tool",
    "session_bound_tool",
]
