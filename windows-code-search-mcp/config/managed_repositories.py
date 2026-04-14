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
    return str(Path(os.getenv("INDEX_ROOT", r"E:\mcp-index-data")).expanduser().resolve())


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

    qdrant_value = result.get("qdrant")
    qdrant = qdrant_value if isinstance(qdrant_value, dict) else {}
    upserted_points = coerce_int(qdrant.get("upsertedPoints", 0))
    deleted_points = coerce_int(qdrant.get("deletedPoints", 0))

    return (
        f"files={indexed_files} changed={changed_files} unchanged={unchanged_files} "
        f"deleted={deleted_files} qdrant_upserted={upserted_points} qdrant_deleted={deleted_points}"
    )
