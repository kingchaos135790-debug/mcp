import importlib.util
import sys
import types
import unittest
from pathlib import Path


fastmcp = types.ModuleType("fastmcp")
fastmcp.FastMCP = object
sys.modules["fastmcp"] = fastmcp

mcp = types.ModuleType("mcp")
mcp_types = types.ModuleType("mcp.types")
mcp_types.ToolAnnotations = object
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


if __name__ == "__main__":
    unittest.main()

