import importlib.util
import asyncio
import json
import sys
import types
import unittest
from pathlib import Path


fastmcp = types.ModuleType("fastmcp")
fastmcp.FastMCP = object
sys.modules["fastmcp"] = fastmcp

mcp = types.ModuleType("mcp")
mcp_types = types.ModuleType("mcp.types")


class ToolAnnotations:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


mcp_types.ToolAnnotations = ToolAnnotations
sys.modules["mcp"] = mcp
sys.modules["mcp.types"] = mcp_types

server_config = types.ModuleType("server_config")
server_config.parse_bool = lambda value, default=False: default if value is None else value
sys.modules["server_config"] = server_config

server_runtime = types.ModuleType("server_runtime")
server_runtime.ServerContext = object
sys.modules["server_runtime"] = server_runtime

session_context = types.ModuleType("session_context")
session_context.get_current_boot_id = lambda: "boot"
sys.modules["session_context"] = session_context

utils_search_normalization = types.ModuleType("utils.search_normalization")
utils_search_normalization.normalize_search_result = lambda value: value
sys.modules["utils.search_normalization"] = utils_search_normalization

extensions_common = types.ModuleType("extensions.common")
extensions_common.format_tool_result = lambda value: value
extensions_common.run_engine_tool = lambda *_args, **_kwargs: {}
sys.modules["extensions.common"] = extensions_common

search_path = Path(__file__).resolve().parents[1] / "extensions" / "search.py"
spec = importlib.util.spec_from_file_location("extensions.search", search_path)
assert spec is not None and spec.loader is not None
search_module = importlib.util.module_from_spec(spec)
sys.modules["extensions.search"] = search_module
spec.loader.exec_module(search_module)

_is_generated_path = search_module._is_generated_path
_identifier_candidates = search_module._identifier_candidates
_rerank_fused_hits = search_module._rerank_fused_hits
_extract_exact_matches = search_module._extract_exact_matches
_clarify_generated_path_warnings = search_module._clarify_generated_path_warnings
_compact_hybrid_search_result = search_module._compact_hybrid_search_result
_compact_server_health = search_module._compact_server_health

SearchExtension = search_module.SearchExtension


class FakeMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, **metadata):
        def decorator(func):
            self.tools[metadata["name"]] = {"func": func, "metadata": metadata}
            return func

        return decorator


class FakeAutoIndexer:
    def __init__(self) -> None:
        self.calls = []

    async def add_repository(self, repo_root: str, **kwargs):
        self.calls.append((repo_root, kwargs))
        return {"repoRoot": repo_root, "indexedNow": kwargs["index_now"], "watch": kwargs["watch"]}

    async def remove_repository(self, reference: str):
        self.calls.append(("remove", reference))
        return {"removed": True, "repoRoot": reference, "cleanupResult": {"removed": True}}


class FakeContext:
    def __init__(self) -> None:
        self.auto_indexer = FakeAutoIndexer()

    def get_auto_indexer(self):
        return self.auto_indexer


class SearchRepositoryManagementTests(unittest.TestCase):
    def test_search_extension_registers_runtime_repository_management_tools(self) -> None:
        mcp_instance = FakeMCP()
        context = FakeContext()

        SearchExtension().register(mcp_instance, context)

        self.assertIn("add_indexed_repository", mcp_instance.tools)
        add_annotations = mcp_instance.tools["add_indexed_repository"]["metadata"]["annotations"]
        self.assertFalse(add_annotations.readOnlyHint)
        self.assertFalse(add_annotations.destructiveHint)

        self.assertIn("remove_indexed_repository", mcp_instance.tools)
        remove_annotations = mcp_instance.tools["remove_indexed_repository"]["metadata"]["annotations"]
        self.assertFalse(remove_annotations.readOnlyHint)
        self.assertTrue(remove_annotations.destructiveHint)

    def test_add_indexed_repository_forwards_runtime_index_options(self) -> None:
        mcp_instance = FakeMCP()
        context = FakeContext()
        SearchExtension().register(mcp_instance, context)

        result = asyncio.run(
            mcp_instance.tools["add_indexed_repository"]["func"](
                repo_root="C:/new-repo",
                watch=False,
                auto_index_on_start=False,
                index_now=True,
                include_docs=True,
                include_generated=True,
                extra_extensions=[".md"],
                extra_include_globs=["docs/**"],
                extra_exclude_globs=["vendor/**"],
                max_file_bytes=1234,
            )
        )

        self.assertEqual(result["repoRoot"], "C:/new-repo")
        self.assertEqual(
            context.auto_indexer.calls,
            [(
                "C:/new-repo",
                {
                    "watch": False,
                    "auto_index_on_start": False,
                    "index_now": True,
                    "include_docs": True,
                    "include_generated": True,
                    "extra_extensions": [".md"],
                    "extra_include_globs": ["docs/**"],
                    "extra_exclude_globs": ["vendor/**"],
                    "max_file_bytes": 1234,
                },
            )],
        )

    def test_remove_indexed_repository_forwards_reference_to_runtime(self) -> None:
        mcp_instance = FakeMCP()
        context = FakeContext()
        SearchExtension().register(mcp_instance, context)

        result = asyncio.run(
            mcp_instance.tools["remove_indexed_repository"]["func"](
                reference="example-repo",
            )
        )

        self.assertTrue(result["removed"])
        self.assertEqual(result["repoRoot"], "example-repo")
        self.assertEqual(context.auto_indexer.calls, [("remove", "example-repo")])


class SearchRerankTests(unittest.TestCase):
    def test_generated_paths_are_detected(self) -> None:
        self.assertTrue(_is_generated_path("vscode-bridge-extension/out/bridgeClient.js"))
        self.assertTrue(_is_generated_path("dist/cli/run-core.js.map"))
        self.assertFalse(_is_generated_path("vscode-bridge-extension/src/bridgeClient.ts"))

    def test_rerank_prefers_lexical_and_feature_overlap(self) -> None:
        fused = [
            {
                "source": "semantic",
                "filePath": "server_runtime.py",
                "symbol": "ensure_config_file",
                "content": "async def ensure_config_file(self) -> None:",
                "score": 0.9,
            },
            {
                "source": "ripgrep",
                "filePath": "extensions/search.py",
                "text": 'name="hybrid_code_search"',
                "score": 0.1,
            },
        ]
        lexical = [{"filePath": "extensions/search.py", "text": 'name="hybrid_code_search"'}]

        reranked = _rerank_fused_hits("qdrant semantic search", fused, lexical, limit=5)

        self.assertEqual(reranked[0]["filePath"], "extensions/search.py")

    def test_rerank_filters_semantic_only_drift_when_no_feature_tokens_match(self) -> None:
        fused = [
            {
                "source": "semantic",
                "filePath": "server_runtime.py",
                "symbol": "ensure_config_file",
                "content": "async def ensure_config_file(self) -> None:",
                "score": 0.99,
            },
            {
                "source": "semantic",
                "filePath": "extensions/vscode_sessions.py",
                "symbol": "create_vscode_session",
                "content": "def create_vscode_session(workspace_root: str, active_file: str) -> str:",
                "score": 0.4,
            },
        ]

        reranked = _rerank_fused_hits("create vscode session workspace root active file", fused, lexical=None, limit=5)

        self.assertEqual(len(reranked), 1)
        self.assertEqual(reranked[0]["filePath"], "extensions/vscode_sessions.py")

    def test_rerank_penalizes_generated_output_when_source_exists(self) -> None:
        fused = [
            {
                "source": "semantic",
                "filePath": "vscode-bridge-extension/out/bridgeClient.js",
                "symbol": "normalizeBaseUrl",
                "content": "normalizeBaseUrl(baseUrl) { return (baseUrl?.trim() || this.baseUrl).replace(/\\/$/, ''); }",
                "score": 0.8,
            },
            {
                "source": "semantic",
                "filePath": "vscode-bridge-extension/src/bridgeClient.ts",
                "symbol": "create_vscode_session",
                "content": "function create_vscode_session(workspaceRoot: string, activeFile: string): void {}",
                "score": 0.7,
            },
        ]

        reranked = _rerank_fused_hits("create vscode session workspace root active file", fused, lexical=None, limit=5)

        self.assertEqual(reranked[0]["filePath"], "vscode-bridge-extension/src/bridgeClient.ts")


    def test_rerank_prefers_hybrid_agreement_and_fusion_score_for_equal_query_matches(self) -> None:
        fused = [
            {
                "source": "semantic",
                "filePath": "src/semantic_only.py",
                "symbol": "resolve_query",
                "content": "resolve_query handles the request",
                "score": 0.99,
            },
            {
                "source": "hybrid",
                "sources": ["semantic", "lexical"],
                "fusionScore": 0.8,
                "filePath": "src/hybrid.py",
                "symbol": "resolve_query",
                "content": "resolve_query handles the request",
                "score": 0.1,
            },
        ]
        lexical = [
            {"filePath": "src/semantic_only.py", "text": "resolve_query handles the request"},
            {"filePath": "src/hybrid.py", "text": "resolve_query handles the request"},
        ]

        reranked = _rerank_fused_hits("resolve_query", fused, lexical, limit=5)

        self.assertEqual(reranked[0]["filePath"], "src/hybrid.py")

    def test_rerank_promotes_exact_lexical_hit_when_fused_omits_it(self) -> None:
        fused = [
            {
                "source": "semantic",
                "filePath": "config/models.py",
                "symbol": "Transport",
                "content": "class Transport(str, Enum):",
                "score": 0.99,
            },
            {
                "source": "semantic",
                "filePath": "tests/test_extensions_refactor.py",
                "symbol": "get_session_snapshot",
                "content": "def get_session_snapshot(session_id: str) -> dict[str, object]:",
                "score": 0.9,
            },
        ]
        lexical = [
            {
                "source": "ripgrep",
                "filePath": "extensions/vscode_sessions.py",
                "text": "def create_vscode_session(",
                "score": 0.2,
            }
        ]

        reranked = _rerank_fused_hits("create_vscode_session", fused, lexical, limit=5)

        self.assertEqual(reranked[0]["filePath"], "extensions/vscode_sessions.py")

    def test_rerank_filters_test_and_doc_duplicates_when_source_definition_exists(self) -> None:
        fused = [
            {
                "source": "ripgrep",
                "filePath": "extensions/vscode_sessions.py",
                "text": "def create_vscode_session(",
                "score": 0.4,
            },
            {
                "source": "ripgrep",
                "filePath": "tests/test_search_rerank.py",
                "text": '"content": "def create_vscode_session(workspace_root: str, active_file: str) -> str:",',
                "score": 0.5,
            },
            {
                "source": "ripgrep",
                "filePath": "README.md",
                "text": "- `create_vscode_session`",
                "score": 0.6,
            },
        ]
        lexical = list(fused)

        reranked = _rerank_fused_hits("create_vscode_session", fused, lexical, limit=5)

        self.assertEqual([item["filePath"] for item in reranked], ["extensions/vscode_sessions.py"])

    def test_markdown_docs_are_treated_as_non_source_for_exact_identifier_queries(self) -> None:
        fused = [
            {
                "source": "ripgrep",
                "filePath": "extensions/vscode_sessions.py",
                "text": "def create_vscode_session(",
                "score": 0.4,
            },
            {
                "source": "ripgrep",
                "filePath": "README.md",
                "text": "create_vscode_session can now promote the real source definition",
                "score": 0.9,
            },
        ]
        lexical = list(fused)

        reranked = _rerank_fused_hits("create_vscode_session", fused, lexical, limit=5)

        self.assertEqual([item["filePath"] for item in reranked], ["extensions/vscode_sessions.py"])


    def test_extract_exact_matches_returns_separate_live_lexical_section(self) -> None:
        lexical = [
            {
                "backend": "ripgrep",
                "filePath": "extensions/search.py",
                "line": 413,
                "text": 'def hybrid_code_search(query: str, limit: int = 8, repo: str = "") -> str:',
            },
            {
                "backend": "ripgrep",
                "filePath": "README.md",
                "line": 1,
                "text": "unrelated",
            },
        ]

        exact = _extract_exact_matches("hybrid_code_search", lexical, limit=5)

        self.assertEqual(len(exact), 1)
        self.assertEqual(exact[0]["filePath"], "extensions/search.py")
        self.assertEqual(exact[0]["matchKind"], "exact_lexical")
        self.assertEqual(exact[0]["resultSource"], "live_lexical")

    def test_generated_path_warning_explains_semantic_vs_live_lexical_coverage(self) -> None:
        payload = {
            "status": {
                "warnings": [
                    "Query appears to target generated or build output, but generated/build paths are excluded from indexed coverage for one or more selected repositories."
                ]
            }
        }

        _clarify_generated_path_warnings(payload)

        self.assertIn("live lexical ripgrep", payload["status"]["warnings"][1])

    def test_exact_identifier_queries_drop_config_and_refactor_residue_when_definition_exists(self) -> None:
        fused = [
            {
                "source": "ripgrep",
                "filePath": "extensions/search.py",
                "text": "def hybrid_code_search(query: str, limit: int = 8, repo: str = \"\") -> str:",
                "score": 0.7,
            },
            {
                "source": "ripgrep",
                "filePath": "config/models.py",
                "text": '"hybrid_code_search",',
                "score": 0.9,
            },
            {
                "source": "ripgrep",
                "filePath": "scripts/_update_refactor_docs.py",
                "text": 'tool_name = "hybrid_code_search"',
                "score": 0.8,
            },
        ]
        lexical = list(fused)

        reranked = _rerank_fused_hits("hybrid_code_search", fused, lexical, limit=5)

        self.assertEqual([item["filePath"] for item in reranked], ["extensions/search.py"])

    def test_hybrid_tool_returns_bounded_sections_and_clipped_snippets(self) -> None:
        mcp_instance = FakeMCP()
        context = FakeContext()
        original_run_engine_tool = search_module.run_engine_tool

        long_text = "alpha " + ("x" * 2000)
        candidates = [
            {
                "source": "semantic",
                "filePath": f"src/file_{index}.py",
                "symbol": f"alpha_{index}",
                "content": long_text,
                "score": 1.0 - (index * 0.01),
            }
            for index in range(20)
        ]

        def fake_run_engine_tool(_context, tool_name, payload):
            if tool_name == "hybrid_code_search":
                self.assertEqual(payload["limit"], 32)
                return {
                    "semantic": [dict(item) for item in candidates],
                    "lexical": [
                        {
                            "filePath": item["filePath"],
                            "line": index + 1,
                            "text": long_text,
                        }
                        for index, item in enumerate(candidates)
                    ],
                    "fused": [dict(item) for item in candidates],
                    "status": {},
                }
            if tool_name == "lexical_code_search":
                return {"hits": []}
            self.fail(f"unexpected tool: {tool_name}")

        try:
            search_module.run_engine_tool = fake_run_engine_tool
            SearchExtension().register(mcp_instance, context)
            result = mcp_instance.tools["hybrid_code_search"]["func"](
                "alpha",
                limit=8,
                repo="mcp",
            )
        finally:
            search_module.run_engine_tool = original_run_engine_tool

        self.assertEqual(len(result["semantic"]), 3)
        self.assertEqual(len(result["lexical"]), 3)
        self.assertLessEqual(len(result["exact_matches"]), 8)
        self.assertEqual(len(result["fused"]), 8)
        self.assertEqual(result["resultCounts"]["semanticCandidates"], 20)
        self.assertEqual(result["resultCounts"]["lexicalCandidates"], 20)
        self.assertEqual(result["resultCounts"]["fusedCandidates"], 20)
        self.assertIn("[truncated ", result["semantic"][0]["content"])
        self.assertLess(len(result["semantic"][0]["content"]), len(long_text))
        self.assertLess(len(json.dumps(result)), 30_000)

    def test_server_health_compaction_removes_large_repository_details(self) -> None:
        result = {
            "repositories": [
                {
                    "repoId": "repo-1",
                    "repoName": "repo",
                    "repoRoot": "C:/repo",
                    "fileCount": 100,
                    "coverage": {"files": ["large"] * 100},
                }
            ],
            "autoIndexRepositories": [
                {
                    "repo_root": "C:/repo",
                    "watch": True,
                    "auto_index_on_start": True,
                    "last_result": {"files": ["large"] * 100},
                    "last_error": "",
                }
            ],
        }

        _compact_server_health(result)

        self.assertEqual(result["repositoryCount"], 1)
        self.assertEqual(result["autoIndexRepositoryCount"], 1)
        self.assertNotIn("coverage", result["repositories"][0])
        self.assertNotIn("last_result", result["autoIndexRepositories"][0])
        self.assertEqual(result["autoIndexRepositories"][0]["repo_root"], "C:/repo")


if __name__ == "__main__":
    unittest.main()

