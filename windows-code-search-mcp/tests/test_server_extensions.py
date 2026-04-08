import sys
import types
import unittest


bootstrap = types.ModuleType("bootstrap")
sys.modules["bootstrap"] = bootstrap

fastmcp = types.ModuleType("fastmcp")
fastmcp.FastMCP = object
sys.modules["fastmcp"] = fastmcp

mcp = types.ModuleType("mcp")
mcp_types = types.ModuleType("mcp.types")
mcp_types.ToolAnnotations = object
sys.modules["mcp"] = mcp
sys.modules["mcp.types"] = mcp_types

windows_mcp = types.ModuleType("windows_mcp")
windows_mcp_tools = types.ModuleType("windows_mcp.tools")
windows_mcp_tools.register_all = lambda *args, **kwargs: None
sys.modules["windows_mcp"] = windows_mcp
sys.modules["windows_mcp.tools"] = windows_mcp_tools

server_config = types.ModuleType("server_config")
server_config.path_is_within = lambda candidate, root: True
sys.modules["server_config"] = server_config

server_runtime = types.ModuleType("server_runtime")
server_runtime.ServerContext = object
sys.modules["server_runtime"] = server_runtime

server_vscode_bridge = types.ModuleType("server_vscode_bridge")
server_vscode_bridge.VSCodeBridgeServer = object
sys.modules["server_vscode_bridge"] = server_vscode_bridge

from server_extensions import require_vscode_command_success, run_engine_tool

sys.modules.pop("server_config", None)
sys.modules.pop("server_runtime", None)
sys.modules.pop("server_vscode_bridge", None)


class ServerExtensionsTests(unittest.TestCase):
    def test_run_engine_tool_wraps_tool_name(self) -> None:
        engine = types.SimpleNamespace(run_tool=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
        context = types.SimpleNamespace(engine=engine)

        with self.assertRaisesRegex(RuntimeError, "hybrid_code_search failed: boom"):
            run_engine_tool(context, "hybrid_code_search", {"query": "needle"})

    def test_require_vscode_command_success_returns_ok_result(self) -> None:
        result = {"status": "ok", "payload": {"applied": True}}

        self.assertEqual(require_vscode_command_success("request_vscode_edit", result), result)

    def test_require_vscode_command_success_raises_with_recovery_hint(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "narrower edit"):
            require_vscode_command_success(
                "request_vscode_edit",
                {"status": "error", "error": "Expected text mismatch before applying edit."},
            )

    def test_require_vscode_command_success_raises_with_drift_recovery_hint(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "narrower edit"):
            require_vscode_command_success(
                "request_vscode_edit",
                {"status": "error", "error": "Could not reliably locate edit target after drift."},
            )

    def test_require_vscode_command_success_raises_with_resource_path_hint(self) -> None:
        with self.assertRaisesRegex(RuntimeError, r"/Windows MCP/"):
            require_vscode_command_success(
                "request_vscode_edit",
                {"status": "error", "error": "Resource not found"},
            )

    def test_require_vscode_command_success_raises_with_workspace_root_hint(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "outside the active workspace"):
            require_vscode_command_success(
                "get_vscode_file_range",
                {"status": "error", "error": "File path is outside the VS Code workspace root"},
            )


if __name__ == "__main__":
    unittest.main()
