from __future__ import annotations

import json

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from server_runtime import ServerContext
from server_vscode_bridge import VSCodeBridgeServer
from utils.file_ranges import read_numbered_file_range, resolve_workspace_file_path
from utils.text_normalization import (
    extract_live_range_text,
    normalize_vscode_text,
    offset_to_line_and_column,
    resolve_anchor_edit_offsets,
)

from .common import (
    format_tool_result,
    get_vscode_bridge,
    is_vscode_edit_drift_error,
    require_vscode_command_success,
    resolve_vscode_workspace_root,
    session_bound_tool,
)


class VSCodeEditExtension:
    def register(self, mcp: FastMCP, context: ServerContext) -> None:
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
                resolved, live_expected_text = extract_live_range_text(
                    workspace_root,
                    file_path,
                    start_line,
                    start_column,
                    end_line,
                    end_column,
                )
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
                    result.setdefault(
                        "refreshReason",
                        "Retried after re-reading the exact live range from disk and normalizing line endings.",
                    )
                    result.setdefault(
                        "initialExpectedTextMatchedAfterNormalization",
                        normalize_vscode_text(expected_text) == normalize_vscode_text(live_expected_text),
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
                            resolved, live_expected_text = extract_live_range_text(
                                workspace_root,
                                str(file_path_value),
                                start_line_value,
                                start_column_value,
                                end_line_value,
                                end_column_value,
                            )
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
                    result.setdefault(
                        "refreshReason",
                        "Retried after re-reading live expectedText for ranged edits and normalizing line endings.",
                    )
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
            _, live_expected_text = extract_live_range_text(
                workspace_root,
                str(resolved),
                match_start_line,
                match_start_column,
                match_end_line,
                match_end_column,
            )
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
            name="anchored_vscode_edit",
            description="Find a unique region between start and end anchors in a VS Code workspace file, validate optional expected body text, and apply a validated edit to just that anchored body.",
            annotations=ToolAnnotations(
                title="anchored_vscode_edit",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        @session_bound_tool
        async def anchored_vscode_edit(
            session_id: str = "",
            file_path: str = "",
            start_anchor: str = "",
            end_anchor: str = "",
            replacement_text: str = "",
            expected_body: str = "",
            start_line: int = 1,
            end_line: int = 0,
            timeout_seconds: int = 30,
        ) -> str:
            if not start_anchor:
                raise ValueError("start_anchor is required")
            if not end_anchor:
                raise ValueError("end_anchor is required")
            bridge = get_vscode_bridge(context)
            assert isinstance(bridge, VSCodeBridgeServer)
            workspace_root = resolve_vscode_workspace_root(bridge, session_id)
            resolved = resolve_workspace_file_path(workspace_root, file_path)
            payload = read_numbered_file_range(resolved, start_line=start_line, end_line=end_line)
            haystack = normalize_vscode_text(str(payload.get("content", "")))
            body_start_offset, body_end_offset, _matched_body = resolve_anchor_edit_offsets(
                haystack,
                start_anchor=start_anchor,
                end_anchor=end_anchor,
                expected_body=expected_body,
            )
            window_start_line = int(payload.get("startLine") or 1)
            match_start_line, match_start_column = offset_to_line_and_column(haystack, body_start_offset, base_line=window_start_line)
            match_end_line, match_end_column = offset_to_line_and_column(haystack, body_end_offset, base_line=window_start_line)
            _, live_expected_text = extract_live_range_text(
                workspace_root,
                str(resolved),
                match_start_line,
                match_start_column,
                match_end_line,
                match_end_column,
            )
            if expected_body and normalize_vscode_text(live_expected_text) != normalize_vscode_text(expected_body):
                raise ValueError("expected_body no longer matches the live text between start_anchor and end_anchor")
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
                result.setdefault("anchorBasedEdit", True)
                result.setdefault("matchedBody", live_expected_text)
                result.setdefault("filePath", str(resolved))
                result.setdefault("anchors", {"start": normalize_vscode_text(start_anchor), "end": normalize_vscode_text(end_anchor)})
                result.setdefault(
                    "range",
                    {
                        "startLine": match_start_line,
                        "startColumn": match_start_column,
                        "endLine": match_end_line,
                        "endColumn": match_end_column,
                    },
                )
            return format_tool_result(require_vscode_command_success("anchored_vscode_edit", result))

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
        return None

    async def stop(self, context: ServerContext) -> None:
        return None
