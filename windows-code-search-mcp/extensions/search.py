from __future__ import annotations

from dataclasses import asdict
import os

import fastmcp
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from server_config import parse_bool
from server_runtime import ServerContext
from session_context import get_current_boot_id
from utils.search_normalization import normalize_search_result

from .common import format_tool_result, run_engine_tool


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
            return format_tool_result(
                normalize_search_result(run_engine_tool(context, "hybrid_code_search", {"query": query, "limit": limit, "repo": repo}))
            )

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
            description="Index a source repository now. Re-running is incremental and updates only changed or deleted files.",
            annotations=ToolAnnotations(
                title="index_repository",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def index_repository(repo_root: str = "") -> str:
            result = await context.get_auto_indexer().run_index(repo_root or os.getenv("REPO_ROOT", "."), reason="manual")
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
