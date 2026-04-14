from __future__ import annotations

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
        "content": "\n".join(line["text"] for line in selected_lines),
        "lines": selected_lines,
    }
