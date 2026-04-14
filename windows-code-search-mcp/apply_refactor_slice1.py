from __future__ import annotations

from pathlib import Path

ROOT = Path(r"E:\Program Files\mcp\windows-code-search-mcp")
UTILS = ROOT / "utils"
UTILS.mkdir(exist_ok=True)
(UTILS / "__init__.py").write_text("", encoding="utf-8")

(UTILS / "search_normalization.py").write_text(
    '''from __future__ import annotations


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
''',
    encoding="utf-8",
)

(UTILS / "file_ranges.py").write_text(
    '''from __future__ import annotations

from pathlib import Path

from server_config import path_is_within


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
        "content": "\\n".join(line["text"] for line in selected_lines),
        "lines": selected_lines,
    }
''',
    encoding="utf-8",
)

(UTILS / "text_normalization.py").write_text(
    '''from __future__ import annotations

from pathlib import Path

from utils.file_ranges import resolve_workspace_file_path


def normalize_vscode_text(content: str) -> str:
    return content.replace("\\r\\n", "\\n").replace("\\r", "\\n")


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
        if line_number == len(lines) + 1 and column_number == 1 and normalized.endswith("\\n"):
            return len(normalized)
        raise ValueError("line_number is outside the available text")

    offset = sum(len(line) for line in lines[: line_number - 1])
    line = lines[line_number - 1]
    line_text = line[:-1] if line.endswith("\\n") else line
    max_column = len(line_text) + 1
    if column_number > max_column:
        raise ValueError("column_number is outside the available text")
    return offset + (column_number - 1)


def offset_to_line_and_column(content: str, offset: int, base_line: int = 1) -> tuple[int, int]:
    normalized = normalize_vscode_text(content)
    if offset < 0 or offset > len(normalized):
        raise ValueError("offset is outside the available text")
    prefix = normalized[:offset]
    line = base_line + prefix.count("\\n")
    last_newline = prefix.rfind("\\n")
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


def find_unique_substring(content: str, needle: str, *, label: str) -> int:
    if not needle:
        raise ValueError(f"{label} is required")
    normalized_content = normalize_vscode_text(content)
    normalized_needle = normalize_vscode_text(needle)
    first_index = normalized_content.find(normalized_needle)
    if first_index < 0:
        raise ValueError(f"{label} was not found in the requested file range")
    second_index = normalized_content.find(normalized_needle, first_index + 1)
    if second_index >= 0:
        raise ValueError(f"{label} matched more than once; narrow the line window or provide a more specific anchor")
    return first_index


def resolve_anchor_edit_offsets(content: str, start_anchor: str, end_anchor: str, expected_body: str = "") -> tuple[int, int, str]:
    normalized_content = normalize_vscode_text(content)
    normalized_start_anchor = normalize_vscode_text(start_anchor)
    normalized_end_anchor = normalize_vscode_text(end_anchor)
    start_anchor_offset = find_unique_substring(normalized_content, normalized_start_anchor, label="start_anchor")
    body_start_offset = start_anchor_offset + len(normalized_start_anchor)
    end_anchor_offset = normalized_content.find(normalized_end_anchor, body_start_offset)
    if end_anchor_offset < 0:
        raise ValueError("end_anchor was not found after start_anchor in the requested file range")
    if normalized_content.find(normalized_end_anchor, end_anchor_offset + 1) >= 0:
        raise ValueError("end_anchor matched more than once after start_anchor; narrow the line window or provide a more specific anchor")
    matched_body = normalized_content[body_start_offset:end_anchor_offset]
    normalized_expected_body = normalize_vscode_text(expected_body) if expected_body else ""
    if normalized_expected_body and matched_body != normalized_expected_body:
        raise ValueError("expected_body did not match the text between start_anchor and end_anchor")
    return body_start_offset, end_anchor_offset, matched_body
''',
    encoding="utf-8",
)

server_extensions_path = ROOT / "server_extensions.py"
content = server_extensions_path.read_text(encoding="utf-8")
start_marker = "def count_text_lines(content: str) -> int:"
end_marker = "def run_engine_tool(context: ServerContext, tool_name: str, payload: dict[str, object]) -> object:"
start = content.index(start_marker)
end = content.index(end_marker)
new_block = '''from utils.file_ranges import read_numbered_file_range, resolve_workspace_file_path
from utils.search_normalization import normalize_search_result, summarize_vscode_context_items
from utils.text_normalization import (
    extract_live_range_text,
    find_unique_substring,
    normalize_vscode_text,
    offset_to_line_and_column,
    position_to_offset,
    resolve_anchor_edit_offsets,
)


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


'''
content = content[:start] + new_block + content[end:]
content = content.replace('from pathlib import Path\n', '')
content = content.replace('from server_config import path_is_within\n', '')
server_extensions_path.write_text(content, encoding="utf-8")

print("apply_refactor_slice1.py completed")
