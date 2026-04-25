from __future__ import annotations

from dataclasses import asdict
import os
import re

import fastmcp
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from server_config import parse_bool
from server_runtime import ServerContext
from session_context import get_current_boot_id
from utils.search_normalization import normalize_search_result

from .common import format_tool_result, run_engine_tool


_GENERATED_PATH_PARTS = {
    "dist",
    "build",
    "out",
    "coverage",
    ".next",
    ".nuxt",
    "vendor",
    "generated",
    "gen",
    "bin",
    "obj",
    "target",
    "__pycache__",
    "node_modules",
}
_NON_SOURCE_PATH_PARTS = {
    "test",
    "tests",
    "testing",
    "doc",
    "docs",
    "example",
    "examples",
    "sample",
    "samples",
    "fixture",
    "fixtures",
    "__tests__",
    "__snapshots__",
}
_GENERIC_QUERY_TOKENS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "code",
    "create",
    "exact",
    "file",
    "files",
    "for",
    "from",
    "get",
    "in",
    "into",
    "match",
    "now",
    "of",
    "on",
    "or",
    "run",
    "search",
    "set",
    "text",
    "that",
    "the",
    "this",
    "to",
    "tool",
    "tools",
    "use",
    "using",
    "with",
}
_IMPLEMENTATION_HINT_TOKENS = {
    "function",
    "functions",
    "implementation",
    "implementations",
    "implement",
    "implemented",
    "method",
    "methods",
    "definition",
    "definitions",
    "define",
    "defined",
    "source",
    "real",
    "actual",
    "exact",
}
_SOURCE_DEFINITION_PATTERNS = (
    "def {symbol}(",
    "async def {symbol}(",
    "function {symbol}(",
    "async function {symbol}(",
    "const {symbol} =",
    "let {symbol} =",
    "var {symbol} =",
    "class {symbol}",
)


def _normalize_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _basename(value: str) -> str:
    normalized = _normalize_path(value)
    return normalized.rsplit("/", 1)[-1] if normalized else ""


def _query_tokens(query: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", query.lower()) if len(token) >= 2}


def _feature_tokens(query: str) -> set[str]:
    tokens = {token for token in _query_tokens(query) if len(token) >= 3 and token not in _GENERIC_QUERY_TOKENS}
    return tokens or _query_tokens(query)


def _identifier_candidates(query: str) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []

    def add(value: str) -> None:
        normalized = value.strip().lower()
        if len(normalized) < 3 or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    for match in re.finditer(r"""[`"']([A-Za-z_][A-Za-z0-9_]*)[`"']""", query):
        add(match.group(1))

    for match in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\b", query):
        token = match.group(0)
        if "_" in token or re.search(r"[a-z][A-Z]", token):
            add(token)

    feature_tokens = [token for token in _feature_tokens(query) if token not in _IMPLEMENTATION_HINT_TOKENS]
    if 2 <= len(feature_tokens) <= 6:
        add("_".join(feature_tokens))

    return candidates


def _definition_patterns(symbol: str) -> tuple[str, ...]:
    if not symbol:
        return ()
    return tuple(pattern.format(symbol=symbol) for pattern in _SOURCE_DEFINITION_PATTERNS)


def _is_definition_like(snippet: str, symbol: str) -> int:
    if not snippet or not symbol:
        return 0
    lowered = snippet.lower()
    return 1 if any(pattern in lowered for pattern in _definition_patterns(symbol)) else 0


def _supplement_lexical_hits(context: ServerContext, query: str, repo: str, limit: int, lexical: list[object] | None) -> list[object]:
    combined: list[object] = list(lexical or [])
    seen_paths: set[tuple[str, int]] = set()
    for item in combined:
        if isinstance(item, dict):
            seen_paths.add((_normalize_path(item.get("filePath") or item.get("path") or item.get("file")), int(item.get("line") or 0)))

    probes: list[str] = []
    raw_query = query.strip()
    if raw_query:
        probes.append(raw_query)
    probes.extend(_identifier_candidates(query))

    for probe in probes:
        result = normalize_search_result(
            run_engine_tool(context, "lexical_code_search", {"query": probe, "limit": limit, "repo": repo, "case_mode": "smart"})
        )
        if not isinstance(result, dict):
            continue
        hits = result.get("hits")
        if not isinstance(hits, list):
            continue
        for item in hits:
            if not isinstance(item, dict):
                continue
            key = (_normalize_path(item.get("filePath") or item.get("path") or item.get("file")), int(item.get("line") or 0))
            if key in seen_paths:
                continue
            seen_paths.add(key)
            combined.append(item)
    return combined


def _extract_identifier_tokens(text: str) -> set[str]:
    if not text:
        return set()
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    normalized = re.sub(r"[^a-zA-Z0-9]+", " ", expanded).lower()
    return {token for token in normalized.split() if len(token) >= 2}


def _token_overlap(text: str, tokens: set[str]) -> int:
    if not text or not tokens:
        return 0
    text_tokens = _extract_identifier_tokens(text)
    return sum(1 for token in tokens if token in text_tokens)


def _is_generated_path(file_path: str) -> bool:
    normalized = _normalize_path(file_path)
    if not normalized:
        return False
    parts = [part for part in normalized.split("/") if part]
    if any(part in _GENERATED_PATH_PARTS for part in parts):
        return True
    basename = parts[-1] if parts else normalized
    if basename.endswith((".map", ".min.js", ".min.css", ".pyc")):
        return True
    return False


def _path_preference(file_path: str) -> int:
    normalized = _normalize_path(file_path)
    if not normalized:
        return 0
    if _is_generated_path(normalized):
        return 0
    parts = [part for part in normalized.split("/") if part]
    if any(part in _NON_SOURCE_PATH_PARTS for part in parts):
        return 1
    basename = parts[-1] if parts else normalized
    if basename in {"readme.md", "changelog.md", "license", "license.md"}:
        return 1
    if basename.endswith((".md", ".rst", ".txt", ".adoc")):
        return 1
    return 2


def _rerank_fused_hits(query: str, fused: list[object], lexical: list[object] | None, limit: int) -> list[object]:
    lexical_paths: set[str] = set()
    lexical_basenames: set[str] = set()
    lexical_items: list[dict[str, object]] = []
    if isinstance(lexical, list):
        for item in lexical:
            if not isinstance(item, dict):
                continue
            lexical_path = _normalize_path(item.get("filePath") or item.get("path") or item.get("file"))
            if lexical_path:
                lexical_paths.add(lexical_path)
                lexical_basenames.add(_basename(lexical_path))
            lexical_items.append(item)

    feature_tokens = _feature_tokens(query)
    identifier_candidates = _identifier_candidates(query)
    exact_query = query.strip().lower()

    def metrics(item: object) -> tuple[int, int, int, int, int, int, int, int, int, int, float]:
        if not isinstance(item, dict):
            return (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, float("-inf"))
        file_path = _normalize_path(item.get("filePath") or item.get("path") or item.get("file"))
        basename = _basename(file_path)
        symbol = str(item.get("symbol") or "").strip().lower()
        snippet = str(item.get("snippet") or item.get("text") or item.get("content") or "").strip().lower()
        path_preference = _path_preference(file_path)
        lexical_match = 1 if file_path and (file_path in lexical_paths or basename in lexical_basenames) else 0
        exact_phrase = 1 if exact_query and exact_query in "\n".join(part for part in (file_path, symbol, snippet) if part) else 0
        identifier_exact = 1 if symbol and symbol in identifier_candidates else 0
        definition_like = 1 if any(_is_definition_like(snippet, candidate) for candidate in identifier_candidates) else 0
        path_overlap = _token_overlap(file_path, feature_tokens)
        symbol_overlap = _token_overlap(symbol, feature_tokens)
        snippet_overlap = _token_overlap(snippet, feature_tokens)
        score = float(item.get("score") or 0.0)
        return (
            identifier_exact,
            lexical_match,
            definition_like,
            symbol_overlap,
            path_overlap,
            snippet_overlap,
            exact_phrase,
            path_preference,
            len(symbol),
            len(snippet),
            score,
        )

    def should_keep(item_metrics: tuple[int, int, int, int, int, int, int, int, int, int, float]) -> bool:
        identifier_exact = item_metrics[0]
        lexical_match = item_metrics[1]
        definition_like = item_metrics[2]
        overlap_total = sum(item_metrics[3:6])
        exact_phrase = item_metrics[6]
        path_preference = item_metrics[7]
        return bool(
            identifier_exact
            or definition_like
            or lexical_match
            or exact_phrase
            or overlap_total >= 2
            or (path_preference >= 2 and overlap_total >= 1)
        )

    reranked: list[object] = []
    seen_paths: set[str] = set()
    for item in fused:
        item_metrics = metrics(item)
        if should_keep(item_metrics):
            reranked.append(item)
            if isinstance(item, dict):
                file_path = _normalize_path(item.get("filePath") or item.get("path") or item.get("file"))
                if file_path:
                    seen_paths.add(file_path)

    for item in lexical_items:
        file_path = _normalize_path(item.get("filePath") or item.get("path") or item.get("file"))
        if not file_path or file_path in seen_paths:
            continue
        item_metrics = metrics(item)
        overlap_total = sum(item_metrics[3:6])
        if item_metrics[0] or item_metrics[2] or item_metrics[6] or overlap_total >= 1:
            reranked.append(item)
            seen_paths.add(file_path)

    if reranked and exact_query and exact_query in identifier_candidates:
        has_source_definition = False
        for item in reranked:
            item_metrics = metrics(item)
            path_preference = item_metrics[7]
            if path_preference >= 2 and (item_metrics[0] or item_metrics[2] or item_metrics[6]):
                has_source_definition = True
                break
        if has_source_definition:
            filtered: list[object] = []
            for item in reranked:
                item_metrics = metrics(item)
                path_preference = item_metrics[7]
                overlap_total = sum(item_metrics[3:6])
                strong_source_match = bool(
                    item_metrics[0]
                    or item_metrics[2]
                    or (item_metrics[1] and overlap_total >= 1)
                )
                if path_preference >= 2 and strong_source_match:
                    filtered.append(item)
            reranked = filtered

    if not reranked:
        reranked = list(fused)

    return sorted(reranked, key=metrics, reverse=True)[:limit]



class SearchExtension:
    def register(self, mcp: FastMCP, context: ServerContext) -> None:
        @mcp.tool(
            name="semantic_code_search",
            description="Search indexed code semantically from Qdrant.",
            annotations=ToolAnnotations(
                title="semantic_code_search",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        def semantic_code_search(query: str, limit: int = 8, repo: str = "") -> str:
            return format_tool_result(
                normalize_search_result(run_engine_tool(context, "semantic_code_search", {"query": query, "limit": limit, "repo": repo}))
            )

        @mcp.tool(
            name="lexical_code_search",
            description="Search indexed code lexically through ripgrep or the local fallback index. Supports case_mode: smart, ignore, or sensitive.",
            annotations=ToolAnnotations(
                title="lexical_code_search",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        def lexical_code_search(query: str, limit: int = 8, repo: str = "", case_mode: str = "smart") -> str:
            return format_tool_result(
                normalize_search_result(
                    run_engine_tool(context, "lexical_code_search", {"query": query, "limit": limit, "repo": repo, "case_mode": case_mode})
                )
            )

        @mcp.tool(
            name="hybrid_code_search",
            description="Combine Qdrant semantic search with ripgrep or local lexical search.",
            annotations=ToolAnnotations(
                title="hybrid_code_search",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        def hybrid_code_search(query: str, limit: int = 8, repo: str = "") -> str:
            candidate_limit = min(max(limit * 4, 20), 50)
            result = normalize_search_result(
                run_engine_tool(context, "hybrid_code_search", {"query": query, "limit": candidate_limit, "repo": repo})
            )
            if isinstance(result, dict):
                fused = result.get("fused")
                lexical = result.get("lexical")
                lexical_hits = _supplement_lexical_hits(
                    context,
                    query,
                    repo,
                    candidate_limit,
                    lexical if isinstance(lexical, list) else None,
                )
                result["lexical"] = lexical_hits
                if isinstance(fused, list) and fused:
                    result["fused"] = _rerank_fused_hits(query, fused, lexical_hits, limit)
            return format_tool_result(result)

        @mcp.tool(
            name="server_health",
            description="Show search-engine configuration, dependency readiness, and auto-index status.",
            annotations=ToolAnnotations(
                title="server_health",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        async def server_health() -> str:
            result = run_engine_tool(context, "server_health", {})
            if isinstance(result, dict):
                result["autoIndexConfigPath"] = context.config.managed_repositories_path
                result["autoIndexRepositories"] = [asdict(item) for item in await context.get_auto_indexer().load_repositories()]
                result["bootId"] = get_current_boot_id()
                result["pid"] = os.getpid()
                result["streamableHttpPath"] = str(getattr(fastmcp.settings, "streamable_http_path", ""))
                result["statelessHttp"] = bool(getattr(fastmcp.settings, "stateless_http", False))
                result["watchdogEnabled"] = parse_bool(os.getenv("WINDOWS_MCP_WATCHDOG_ENABLED"), False)
            return format_tool_result(result)

        @mcp.tool(
            name="list_indexed_repositories",
            description="List indexed codebases available for repo-scoped search.",
            annotations=ToolAnnotations(
                title="list_indexed_repositories",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        def list_indexed_repositories() -> str:
            return format_tool_result(run_engine_tool(context, "list_indexed_repositories", {}))

        @mcp.tool(
            name="index_repository",
            description=(
                "Index a source repository now. Supports mode=incremental|force|verify, "
                "hashMode=metadata-first|hash-changed-candidates|hash-all-candidates, "
                "and coverage options such as includeDocs, includeGenerated, extraExtensions, "
                "extraIncludeGlobs, extraExcludeGlobs, and maxFileBytes."
            ),
            annotations=ToolAnnotations(
                title="index_repository",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def index_repository(
            repo_root: str = "",
            mode: str = "incremental",
            hashMode: str = "metadata-first",
            includeDocs: bool = False,
            includeGenerated: bool = False,
            extraExtensions: list[str] | None = None,
            extraIncludeGlobs: list[str] | None = None,
            extraExcludeGlobs: list[str] | None = None,
            maxFileBytes: int = 0,
        ) -> str:
            payload: dict[str, object] = {
                "repoRoot": repo_root or os.getenv("REPO_ROOT", "."),
                "mode": mode,
                "hashMode": hashMode,
                "includeDocs": includeDocs,
                "includeGenerated": includeGenerated,
            }
            if extraExtensions:
                payload["extraExtensions"] = extraExtensions
            if extraIncludeGlobs:
                payload["extraIncludeGlobs"] = extraIncludeGlobs
            if extraExcludeGlobs:
                payload["extraExcludeGlobs"] = extraExcludeGlobs
            if maxFileBytes > 0:
                payload["maxFileBytes"] = maxFileBytes

            result = await context.get_auto_indexer().run_index(
                str(payload["repoRoot"]),
                reason="manual",
                options=payload,
            )
            return format_tool_result(result)

        @mcp.tool(
            name="diagnose_index_repository",
            description="Diagnose repository index freshness and coverage without updating Qdrant or local lexical artifacts.",
            annotations=ToolAnnotations(
                title="diagnose_index_repository",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        async def diagnose_index_repository(
            repo_root: str = "",
            hashMode: str = "hash-all-candidates",
            includeDocs: bool = False,
            includeGenerated: bool = False,
            extraExtensions: list[str] | None = None,
            extraIncludeGlobs: list[str] | None = None,
            extraExcludeGlobs: list[str] | None = None,
            maxFileBytes: int = 0,
        ) -> str:
            payload: dict[str, object] = {
                "repoRoot": repo_root or os.getenv("REPO_ROOT", "."),
                "mode": "verify",
                "hashMode": hashMode,
                "includeDocs": includeDocs,
                "includeGenerated": includeGenerated,
            }
            if extraExtensions:
                payload["extraExtensions"] = extraExtensions
            if extraIncludeGlobs:
                payload["extraIncludeGlobs"] = extraIncludeGlobs
            if extraExcludeGlobs:
                payload["extraExcludeGlobs"] = extraExcludeGlobs
            if maxFileBytes > 0:
                payload["maxFileBytes"] = maxFileBytes

            result = await context.get_auto_indexer().run_index(
                str(payload["repoRoot"]),
                reason="diagnose",
                options=payload,
                record_result=False,
            )
            return format_tool_result(result)

        @mcp.tool(
            name="remove_indexed_repository",
            description="Remove indexed artifacts and Qdrant vectors for a repository.",
            annotations=ToolAnnotations(
                title="remove_indexed_repository",
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        def remove_indexed_repository(repo_root: str) -> str:
            return format_tool_result(run_engine_tool(context, "remove_indexed_repository", {"repoRoot": repo_root}))

        @mcp.tool(
            name="list_auto_index_repositories",
            description="List repositories managed for startup auto-indexing and file-watch reindexing.",
            annotations=ToolAnnotations(
                title="list_auto_index_repositories",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        async def list_auto_index_repositories() -> str:
            repositories = [asdict(item) for item in await context.get_auto_indexer().load_repositories()]
            return format_tool_result(repositories)

        @mcp.tool(
            name="add_auto_index_repository",
            description="Add a repository to managed auto-indexing. Optionally index it now and watch for future file changes.",
            annotations=ToolAnnotations(
                title="add_auto_index_repository",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def add_auto_index_repository(
            repo_root: str,
            watch: bool = True,
            auto_index_on_start: bool = True,
            index_now: bool = True,
        ) -> str:
            result = await context.get_auto_indexer().add_repository(
                repo_root,
                watch=watch,
                auto_index_on_start=auto_index_on_start,
                index_now=index_now,
            )
            return format_tool_result(result)

        @mcp.tool(
            name="remove_auto_index_repository",
            description="Remove a repository from managed startup auto-indexing and file watching.",
            annotations=ToolAnnotations(
                title="remove_auto_index_repository",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def remove_auto_index_repository(repo: str) -> str:
            result = await context.get_auto_indexer().remove_repository(repo)
            return format_tool_result(result)

    async def start(self, context: ServerContext) -> None:
        return None

    async def stop(self, context: ServerContext) -> None:
        return None

