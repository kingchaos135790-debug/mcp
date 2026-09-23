from __future__ import annotations

_SEARCH_RESPONSE_RAW_SECTION_LIMIT = 3
_SEARCH_RESPONSE_TEXT_LIMIT = 800


def _clip_search_text(value: object, max_chars: int = _SEARCH_RESPONSE_TEXT_LIMIT) -> object:
    if not isinstance(value, str) or len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + f"\n... [truncated {len(value) - max_chars} chars]"


def _compact_search_hit(item: object) -> object:
    if not isinstance(item, dict):
        return item

    compact = dict(item)
    for key in ("content", "text", "snippet"):
        if key in compact:
            compact[key] = _clip_search_text(compact[key])

    if compact.get("snippet") == compact.get("text"):
        compact.pop("snippet", None)
    if compact.get("snippet") == compact.get("content"):
        compact.pop("snippet", None)
    return compact


def _compact_search_hits(items: object, limit: int) -> list[object]:
    if not isinstance(items, list):
        return []
    return [_compact_search_hit(item) for item in items[:max(0, limit)]]


def compact_hybrid_search_result(
    result: dict[str, object],
    *,
    limit: int,
    semantic_candidates: int,
    lexical_candidates: int,
    fused_candidates: int,
) -> None:
    raw_section_limit = min(max(1, limit), _SEARCH_RESPONSE_RAW_SECTION_LIMIT)
    result["semantic"] = _compact_search_hits(result.get("semantic"), raw_section_limit)
    result["lexical"] = _compact_search_hits(result.get("lexical"), raw_section_limit)
    result["exact_matches"] = _compact_search_hits(result.get("exact_matches"), limit)
    result["fused"] = _compact_search_hits(result.get("fused"), limit)
    result["resultCounts"] = {
        "semanticCandidates": semantic_candidates,
        "lexicalCandidates": lexical_candidates,
        "fusedCandidates": fused_candidates,
        "returnedSemantic": len(result["semantic"]),
        "returnedLexical": len(result["lexical"]),
        "returnedExactMatches": len(result["exact_matches"]),
        "returnedFused": len(result["fused"]),
    }


def _compact_repository_health(repository: object) -> object:
    if not isinstance(repository, dict):
        return repository

    keys = (
        "repoId",
        "repoName",
        "repoRoot",
        "indexedAt",
        "fileCount",
        "status",
        "watch",
        "autoIndexOnStart",
        "repo_root",
        "auto_index_on_start",
        "last_indexed_at",
        "last_index_reason",
        "last_error",
    )
    return {key: repository.get(key) for key in keys if key in repository}


def compact_server_health(result: dict[str, object]) -> None:
    repositories = result.get("repositories")
    if isinstance(repositories, list):
        result["repositories"] = [_compact_repository_health(item) for item in repositories]
        result["repositoryCount"] = len(repositories)

    auto_index_repositories = result.get("autoIndexRepositories")
    if isinstance(auto_index_repositories, list):
        result["autoIndexRepositories"] = [
            _compact_repository_health(item) for item in auto_index_repositories
        ]
        result["autoIndexRepositoryCount"] = len(auto_index_repositories)
