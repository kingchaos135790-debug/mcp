from __future__ import annotations

import os
from pathlib import Path


def normalize_repo_root(repo_root: str) -> str:
    normalized = str(Path(repo_root).expanduser().resolve())
    if not Path(normalized).exists():
        raise FileNotFoundError(f"Repository path not found: {normalized}")
    if not Path(normalized).is_dir():
        raise NotADirectoryError(f"Repository path is not a directory: {normalized}")
    return normalized


def path_is_within(candidate: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(candidate), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False


def index_root_display() -> str:
    default_root = Path(__file__).resolve().parents[3] / "mcp-index-data"
    return str(Path(os.getenv("INDEX_ROOT", str(default_root))).expanduser().resolve())


def coerce_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def format_index_result_summary(result: dict[str, object]) -> str:
    indexed_files = coerce_int(result.get("indexedFiles", 0))
    changed_files = coerce_int(result.get("changedFiles", 0))
    unchanged_files = coerce_int(result.get("unchangedFiles", 0))
    deleted_files = coerce_int(result.get("deletedFiles", 0))

    graph_value = result.get("gitnexus")
    graph = graph_value if isinstance(graph_value, dict) else {}
    return (
        f"files={indexed_files} changed={changed_files} unchanged={unchanged_files} "
        f"deleted={deleted_files} gitnexus={graph.get('backend', 'unavailable')}"
    )
