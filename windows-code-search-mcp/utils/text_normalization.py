from __future__ import annotations

from pathlib import Path

from utils.file_ranges import resolve_workspace_file_path


def normalize_vscode_text(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


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
    normalized_lines = normalized_content.split("\n")

    start_anchor_line_indexes = [index for index, line in enumerate(normalized_lines) if line == normalized_start_anchor]
    if not start_anchor_line_indexes:
        raise ValueError("start_anchor exact line was not found in the requested file range")
    if len(start_anchor_line_indexes) > 1:
        raise ValueError("start_anchor exact line matched more than once; narrow the line window or provide a more specific anchor")

    start_line_index = start_anchor_line_indexes[0]
    start_anchor_offset = sum(len(line) + 1 for line in normalized_lines[:start_line_index])
    body_start_offset = start_anchor_offset + len(normalized_start_anchor)
    if body_start_offset < len(normalized_content) and normalized_content[body_start_offset:body_start_offset + 1] == "\n":
        body_start_offset += 1

    end_anchor_line_indexes = [
        index for index, line in enumerate(normalized_lines[start_line_index + 1 :], start=start_line_index + 1) if line == normalized_end_anchor
    ]
    if not end_anchor_line_indexes:
        raise ValueError("end_anchor exact line was not found after start_anchor in the requested file range")
    if len(end_anchor_line_indexes) > 1:
        raise ValueError("end_anchor exact line matched more than once after start_anchor; narrow the line window or provide a more specific anchor")

    end_line_index = end_anchor_line_indexes[0]
    end_anchor_offset = sum(len(line) + 1 for line in normalized_lines[:end_line_index])
    matched_body = normalized_content[body_start_offset:end_anchor_offset]
    normalized_expected_body = normalize_vscode_text(expected_body) if expected_body else ""
    if normalized_expected_body and matched_body != normalized_expected_body:
        raise ValueError("expected_body did not match the text between start_anchor and end_anchor")
    return body_start_offset, end_anchor_offset, matched_body
