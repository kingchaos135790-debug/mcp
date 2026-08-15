from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from server_runtime import ServerContext
from utils.file_ranges import read_numbered_file_range
from utils.text_normalization import (
    normalize_vscode_text,
    offset_to_line_and_column,
    position_to_offset,
    resolve_anchor_edit_offsets,
)

from .common import format_tool_result


def _sha256_text(content: str) -> str:
    return hashlib.sha256(normalize_vscode_text(content).encode("utf-8")).hexdigest()


def _add_block_hash(payload: dict[str, object]) -> dict[str, object]:
    content = normalize_vscode_text(str(payload.get("content", "")))
    payload["contentSha256"] = _sha256_text(content)
    payload["expectedSha256Hint"] = "Pass contentSha256 as expected_sha256 to replace_range_or_anchor for compact guarded range edits."
    return payload


def _anchor_line_diagnostics(
    haystack: str,
    *,
    start_anchor: str,
    end_anchor: str,
    base_line: int,
    file_path: str,
    start_line: int = 1,
    end_line: int = 0,
) -> dict[str, object]:
    normalized_start_anchor = normalize_vscode_text(start_anchor)
    normalized_end_anchor = normalize_vscode_text(end_anchor)
    lines = haystack.split("\n")
    start_indexes = [index for index, line in enumerate(lines) if line == normalized_start_anchor]
    end_indexes = [index for index, line in enumerate(lines) if line == normalized_end_anchor]
    start_index = start_indexes[0] if start_indexes else None
    end_indexes_after_start = [index for index in end_indexes if start_index is not None and index > start_index]
    search_from = (start_index + 1) if start_index is not None else 0
    search_to = min(len(lines), search_from + 12)
    nearby_lines = [
        {"lineNumber": base_line + index, "text": lines[index]}
        for index in range(search_from, search_to)
    ]
    nearby_candidates: list[dict[str, object]] = []
    for index, line in enumerate(lines[search_from:], start=search_from):
        if not line:
            continue
        similarity = difflib.SequenceMatcher(None, normalized_end_anchor, line).ratio()
        if similarity >= 0.35:
            nearby_candidates.append({
                "lineNumber": base_line + index,
                "text": line,
                "similarity": round(similarity, 3),
            })
    nearby_candidates.sort(key=lambda item: float(item["similarity"]), reverse=True)
    nearby_candidates = nearby_candidates[:5]
    suggested_start_line = max(1, (base_line + start_index - 3) if start_index is not None else start_line)
    suggested_end_line = (base_line + start_index + 20) if start_index is not None else end_line
    return {
        "startAnchorFound": bool(start_indexes),
        "startAnchorLineNumbers": [base_line + index for index in start_indexes],
        "startAnchorUnique": len(start_indexes) == 1,
        "endAnchorExistsAnywhere": bool(end_indexes),
        "endAnchorLineNumbers": [base_line + index for index in end_indexes],
        "endAnchorFoundAfterStart": bool(end_indexes_after_start),
        "endAnchorLineNumbersAfterStart": [base_line + index for index in end_indexes_after_start],
        "nearbyLinesAfterStartAnchor": nearby_lines,
        "nearbyEndAnchorCandidates": nearby_candidates,
        "recommendedCorrectedEndAnchor": nearby_candidates[0]["text"] if nearby_candidates else "",
        "suggested_next_tool_call": {
            "tool": "get_file_range",
            "arguments": {
                "file_path": file_path,
                "start_line": suggested_start_line,
                "end_line": suggested_end_line,
            },
        },
    }


def _anchor_failure_payload(
    resolved: Path,
    *,
    start_anchor: str,
    end_anchor: str,
    start_line: int = 1,
    end_line: int = 0,
    repo_root: str = "",
    error: str,
) -> dict[str, object]:
    payload = read_numbered_file_range(resolved, start_line=start_line, end_line=end_line)
    haystack = normalize_vscode_text(str(payload.get("content", "")))
    base_line = int(payload.get("startLine") or 1)
    diagnostics = _anchor_line_diagnostics(
        haystack,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        base_line=base_line,
        file_path=str(resolved),
        start_line=start_line,
        end_line=end_line,
    )
    if repo_root.strip():
        suggested = diagnostics["suggested_next_tool_call"]
        if isinstance(suggested, dict):
            arguments = suggested.get("arguments")
            if isinstance(arguments, dict):
                arguments["repo_root"] = str(Path(repo_root).expanduser().resolve())
    return {
        "status": "error",
        "error": error,
        "filePath": str(resolved),
        "anchorDiagnostics": diagnostics,
        "suggested_next_tool_call": diagnostics["suggested_next_tool_call"],
    }


def _maybe_return_json_error(exc: ValueError) -> str | None:
    message = str(exc)
    try:
        json.loads(message)
    except json.JSONDecodeError:
        return None
    return message


def resolve_direct_file_path(file_path: str, repo_root: str = "") -> Path:
    raw_path = file_path.strip()
    if not raw_path:
        raise ValueError("file_path is required")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        base_path = Path(repo_root).expanduser() if repo_root.strip() else Path.cwd()
        candidate = base_path / candidate
    resolved = candidate.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"Path is not a file: {resolved}")
    return resolved


def apply_direct_file_edit(
    file_path: str,
    *,
    start_line: int,
    start_column: int,
    end_line: int,
    end_column: int,
    new_text: str,
    expected_text: str = "",
    repo_root: str = "",
) -> dict[str, object]:
    resolved = resolve_direct_file_path(file_path, repo_root=repo_root)
    content = normalize_vscode_text(resolved.read_text(encoding="utf-8", errors="replace"))
    start_offset = position_to_offset(content, start_line, start_column)
    end_offset = position_to_offset(content, end_line, end_column)
    if end_offset < start_offset:
        raise ValueError("end position must be >= start position")
    live_expected_text = content[start_offset:end_offset]
    normalized_expected_text = normalize_vscode_text(expected_text) if expected_text else ""
    if normalized_expected_text and live_expected_text != normalized_expected_text:
        raise ValueError("expected_text did not match the live text at the requested range")
    updated_content = content[:start_offset] + normalize_vscode_text(new_text) + content[end_offset:]
    resolved.write_text(updated_content, encoding="utf-8", newline="\n")
    return {
        "status": "ok",
        "filePath": str(resolved),
        "expectedText": live_expected_text,
        "applied": True,
        "range": {
            "startLine": start_line,
            "startColumn": start_column,
            "endLine": end_line,
            "endColumn": end_column,
        },
    }


def _resolve_anchor_range(
    resolved: Path,
    *,
    start_anchor: str,
    end_anchor: str,
    expected_body: str = "",
    start_line: int = 1,
    end_line: int = 0,
) -> dict[str, object]:
    if not start_anchor:
        raise ValueError("start_anchor is required")
    if not end_anchor:
        raise ValueError("end_anchor is required")
    payload = read_numbered_file_range(resolved, start_line=start_line, end_line=end_line)
    haystack = normalize_vscode_text(str(payload.get("content", "")))
    try:
        body_start_offset, body_end_offset, _matched_body = resolve_anchor_edit_offsets(
            haystack,
            start_anchor=start_anchor,
            end_anchor=end_anchor,
            expected_body=expected_body,
        )
    except ValueError as exc:
        error = str(exc)
        if "anchor" in error:
            failure = _anchor_failure_payload(
                resolved,
                start_anchor=start_anchor,
                end_anchor=end_anchor,
                start_line=start_line,
                end_line=end_line,
                error=error,
            )
            raise ValueError(format_tool_result(failure)) from exc
        raise
    window_start_line = int(payload.get("startLine") or 1)
    match_start_line, match_start_column = offset_to_line_and_column(haystack, body_start_offset, base_line=window_start_line)
    match_end_line, match_end_column = offset_to_line_and_column(haystack, body_end_offset, base_line=window_start_line)
    live_body = haystack[body_start_offset:body_end_offset]
    if expected_body and normalize_vscode_text(expected_body) != live_body:
        raise ValueError("expected_body no longer matches the live text between start_anchor and end_anchor")
    return {
        "liveBody": live_body,
        "range": {
            "startLine": match_start_line,
            "startColumn": match_start_column,
            "endLine": match_end_line,
            "endColumn": match_end_column,
        },
        "anchors": {"start": normalize_vscode_text(start_anchor), "end": normalize_vscode_text(end_anchor)},
    }


def apply_multi_anchor_file_edit(edits: list[dict[str, object]], *, repo_root: str = "") -> dict[str, object]:
    if not edits:
        raise ValueError("edits_json must include at least one edit")

    planned: list[dict[str, object]] = []
    original_by_file: dict[Path, str] = {}

    for index, item in enumerate(edits):
        if not isinstance(item, dict):
            raise ValueError("Each edits_json item must be an object")
        file_path = str(item.get("filePath") or item.get("file_path") or "")
        item_repo_root = str(item.get("repoRoot") or item.get("repo_root") or repo_root)
        resolved = resolve_direct_file_path(file_path, repo_root=item_repo_root)
        if resolved not in original_by_file:
            original_by_file[resolved] = normalize_vscode_text(resolved.read_text(encoding="utf-8", errors="replace"))
        resolved_range = _resolve_anchor_range(
            resolved,
            start_anchor=str(item.get("startAnchor") or item.get("start_anchor") or ""),
            end_anchor=str(item.get("endAnchor") or item.get("end_anchor") or ""),
            expected_body=str(item.get("expectedBody") or item.get("expected_body") or ""),
            start_line=int(item.get("startLine") or item.get("start_line") or 1),
            end_line=int(item.get("endLine") or item.get("end_line") or 0),
        )
        range_payload = resolved_range["range"]
        content = original_by_file[resolved]
        start_offset = position_to_offset(content, int(range_payload["startLine"]), int(range_payload["startColumn"]))
        end_offset = position_to_offset(content, int(range_payload["endLine"]), int(range_payload["endColumn"]))
        planned.append({
            "index": index,
            "filePath": str(resolved),
            "resolved": resolved,
            "startOffset": start_offset,
            "endOffset": end_offset,
            "replacementText": normalize_vscode_text(str(item.get("replacementText") or item.get("replacement_text") or "")),
            "matchedBody": resolved_range["liveBody"],
            "range": range_payload,
            "anchors": resolved_range["anchors"],
        })

    by_file: dict[Path, list[dict[str, object]]] = {}
    for edit in planned:
        by_file.setdefault(edit["resolved"], []).append(edit)  # type: ignore[index]

    updated_by_file: dict[Path, str] = {}
    for resolved, file_edits in by_file.items():
        ordered = sorted(file_edits, key=lambda edit: int(edit["startOffset"]))
        previous_end = -1
        for edit in ordered:
            start_offset = int(edit["startOffset"])
            end_offset = int(edit["endOffset"])
            if start_offset < previous_end:
                raise ValueError(f"Overlapping anchored edits are not supported for {resolved}")
            previous_end = end_offset
        content = original_by_file[resolved]
        pieces: list[str] = []
        cursor = 0
        for edit in ordered:
            start_offset = int(edit["startOffset"])
            end_offset = int(edit["endOffset"])
            pieces.append(content[cursor:start_offset])
            pieces.append(str(edit["replacementText"]))
            cursor = end_offset
        pieces.append(content[cursor:])
        updated_by_file[resolved] = "".join(pieces)

    for resolved, updated in updated_by_file.items():
        resolved.write_text(updated, encoding="utf-8", newline="\n")

    return {
        "status": "ok",
        "applied": True,
        "editCount": len(planned),
        "fileCount": len(updated_by_file),
        "edits": [
            {
                "index": int(edit["index"]),
                "filePath": str(edit["filePath"]),
                "matchedBody": str(edit["matchedBody"]),
                "range": edit["range"],
                "anchors": edit["anchors"],
            }
            for edit in planned
        ],
    }


def apply_replace_range_or_anchor(
    *,
    file_path: str,
    replacement_text: str,
    expected_text: str = "",
    start_anchor: str = "",
    end_anchor: str = "",
    start_line: int = 0,
    end_line: int = 0,
    start_column: int = 1,
    end_column: int = 1,
    expected_sha256: str = "",
    dry_run: bool = False,
    repo_root: str = "",
) -> dict[str, object]:
    resolved = resolve_direct_file_path(file_path, repo_root=repo_root)
    normalized_replacement = normalize_vscode_text(replacement_text)

    if expected_text:
        payload = read_numbered_file_range(resolved, start_line=start_line or 1, end_line=end_line)
        haystack = normalize_vscode_text(str(payload.get("content", "")))
        needle = normalize_vscode_text(expected_text)
        match_count = haystack.count(needle)
        if match_count == 0:
            raise ValueError("expected_text was not found in the requested file range")
        if match_count > 1:
            raise ValueError("expected_text matched more than once; narrow the line window or provide anchors")
        window_start_line = int(payload.get("startLine") or 1)
        start_offset = haystack.index(needle)
        end_offset = start_offset + len(needle)
        match_start_line, match_start_column = offset_to_line_and_column(haystack, start_offset, base_line=window_start_line)
        match_end_line, match_end_column = offset_to_line_and_column(haystack, end_offset, base_line=window_start_line)
        strategy = "expected_text"
        live_text = needle
        range_payload = {"startLine": match_start_line, "startColumn": match_start_column, "endLine": match_end_line, "endColumn": match_end_column}
    elif start_anchor and end_anchor:
        try:
            resolved_range = _resolve_anchor_range(
                resolved,
                start_anchor=start_anchor,
                end_anchor=end_anchor,
                expected_body="",
                start_line=start_line or 1,
                end_line=end_line,
            )
        except ValueError as exc:
            structured_error = _maybe_return_json_error(exc)
            if structured_error is not None:
                return json.loads(structured_error)
            raise
        range_payload = resolved_range["range"]
        live_text = str(resolved_range["liveBody"])
        strategy = "anchor"
    elif start_line and end_line:
        content = normalize_vscode_text(resolved.read_text(encoding="utf-8", errors="replace"))
        start_offset = position_to_offset(content, start_line, start_column)
        end_offset = position_to_offset(content, end_line, end_column)
        if end_offset < start_offset:
            raise ValueError("end position must be >= start position")
        live_text = content[start_offset:end_offset]
        range_payload = {"startLine": start_line, "startColumn": start_column, "endLine": end_line, "endColumn": end_column}
        strategy = "line_range"
    else:
        raise ValueError("Provide expected_text, start_anchor/end_anchor, or start_line/end_line")

    live_sha256 = _sha256_text(live_text)
    if expected_sha256 and expected_sha256.lower() != live_sha256.lower():
        return {
            "status": "error",
            "error": "expected_sha256 did not match the live selected text",
            "filePath": str(resolved),
            "expectedSha256": expected_sha256,
            "liveSha256": live_sha256,
            "range": range_payload,
            "suggested_next_tool_call": {
                "tool": "get_file_range",
                "arguments": {"file_path": str(resolved), "start_line": int(range_payload["startLine"]), "end_line": int(range_payload["endLine"])},
            },
        }

    result: dict[str, object] = {
        "status": "ok",
        "filePath": str(resolved),
        "strategy": strategy,
        "dryRun": dry_run,
        "applied": False,
        "range": range_payload,
        "matchedText": live_text,
        "matchedTextSha256": live_sha256,
        "replacementSha256": _sha256_text(normalized_replacement),
    }
    if dry_run:
        return result

    result = apply_direct_file_edit(
        str(resolved),
        start_line=int(range_payload["startLine"]),
        start_column=int(range_payload["startColumn"]),
        end_line=int(range_payload["endLine"]),
        end_column=int(range_payload["endColumn"]),
        new_text=normalized_replacement,
        expected_text=live_text,
    )
    result["strategy"] = strategy
    result["matchedTextSha256"] = live_sha256
    result["replacementSha256"] = _sha256_text(normalized_replacement)
    result["dryRun"] = False
    return result


class FileEditExtension:
    def register(self, mcp: FastMCP, context: ServerContext) -> None:
        @mcp.tool(
            name="get_file_range",
            description="Read a file on disk with numbered lines so MCP clients can inspect exact ranges and prepare safe direct-on-disk edits.",
            annotations=ToolAnnotations(title="get_file_range", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
        )
        def get_file_range(file_path: str = "", start_line: int = 1, end_line: int = 0, context_before: int = 0, context_after: int = 0, repo_root: str = "") -> str:
            resolved = resolve_direct_file_path(file_path, repo_root=repo_root)
            payload = read_numbered_file_range(resolved, start_line=start_line, end_line=end_line, context_before=context_before, context_after=context_after)
            payload["repoRoot"] = str(Path(repo_root).expanduser().resolve()) if repo_root.strip() else ""
            payload["directFileRead"] = True
            payload["anchorEditHint"] = "Use this fresh range to derive expected_text, anchors, or expected_sha256 for replace_range_or_anchor."
            _add_block_hash(payload)
            return format_tool_result(payload)

        @mcp.tool(
            name="get_multiple_file_ranges",
            description="Read multiple files on disk with numbered lines so MCP clients can inspect several exact ranges and prepare coordinated direct-on-disk edits.",
            annotations=ToolAnnotations(title="get_multiple_file_ranges", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
        )
        def get_multiple_file_ranges(files_json: str = "", repo_root: str = "") -> str:
            try:
                parsed = json.loads(files_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid files_json: {exc}") from exc
            if not isinstance(parsed, list):
                raise ValueError("files_json must decode to a list")
            results: list[dict[str, object]] = []
            for item in parsed:
                if not isinstance(item, dict):
                    raise ValueError("Each files_json item must be an object")
                file_path_value = str(item.get("filePath") or item.get("file_path") or "")
                if not file_path_value.strip():
                    raise ValueError("Each files_json item must include filePath")
                item_repo_root = str(item.get("repoRoot") or item.get("repo_root") or repo_root)
                resolved = resolve_direct_file_path(file_path_value, repo_root=item_repo_root)
                payload = read_numbered_file_range(
                    resolved,
                    start_line=int(item.get("startLine") or item.get("start_line") or 1),
                    end_line=int(item.get("endLine") or item.get("end_line") or 0),
                    context_before=int(item.get("contextBefore") or item.get("context_before") or 0),
                    context_after=int(item.get("contextAfter") or item.get("context_after") or 0),
                )
                payload["repoRoot"] = str(Path(item_repo_root).expanduser().resolve()) if item_repo_root.strip() else ""
                payload["directFileRead"] = True
                payload["anchorEditHint"] = "Use each fresh range to derive expected_text, anchors, or expected_sha256 for replace_range_or_anchor."
                _add_block_hash(payload)
                results.append(payload)
            return format_tool_result({"repoRoot": str(Path(repo_root).expanduser().resolve()) if repo_root.strip() else "", "count": len(results), "files": results, "directFileRead": True})

        @mcp.tool(
            name="replace_range_or_anchor",
            description="High-level guarded replacement tool. It can use expected_text, start/end anchors, or a line range, supports expected_sha256, and can dry-run the matched range before applying.",
            annotations=ToolAnnotations(title="replace_range_or_anchor", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
        )
        def replace_range_or_anchor(file_path: str = "", replacement_text: str = "", expected_text: str = "", start_anchor: str = "", end_anchor: str = "", start_line: int = 0, end_line: int = 0, start_column: int = 1, end_column: int = 1, expected_sha256: str = "", dry_run: bool = False, repo_root: str = "") -> str:
            return format_tool_result(apply_replace_range_or_anchor(file_path=file_path, replacement_text=replacement_text, expected_text=expected_text, start_anchor=start_anchor, end_anchor=end_anchor, start_line=start_line, end_line=end_line, start_column=start_column, end_column=end_column, expected_sha256=expected_sha256, dry_run=dry_run, repo_root=repo_root))

        @mcp.tool(
            name="multi_anchor_file_edit",
            description="Apply multiple anchored body replacements directly on disk in one validated request. Each edit uses exact start/end anchor lines and optional expectedBody/expected_body.",
            annotations=ToolAnnotations(title="multi_anchor_file_edit", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
        )
        def multi_anchor_file_edit(edits_json: str = "", repo_root: str = "", include_modified_files_with_lines: bool = False) -> str:
            try:
                parsed = json.loads(edits_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid edits_json: {exc}") from exc
            if not isinstance(parsed, list):
                raise ValueError("edits_json must decode to a list")
            result = apply_multi_anchor_file_edit(parsed, repo_root=repo_root)
            if include_modified_files_with_lines:
                modified_files = []
                for file_path in sorted({str(edit["filePath"]) for edit in result["edits"]}):
                    modified_files.append(read_numbered_file_range(Path(file_path), start_line=1, end_line=0))
                result["modifiedFiles"] = modified_files
            return format_tool_result(result)

    async def start(self, context: ServerContext) -> None:
        return None

    async def stop(self, context: ServerContext) -> None:
        return None
