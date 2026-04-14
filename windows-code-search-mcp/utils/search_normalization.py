from __future__ import annotations


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
