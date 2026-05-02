import asyncio
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


bootstrap = types.ModuleType("bootstrap")
sys.modules["bootstrap"] = bootstrap


class FastMCP:
    pass


fastmcp = types.ModuleType("fastmcp")
fastmcp.FastMCP = FastMCP
sys.modules["fastmcp"] = fastmcp

mcp = types.ModuleType("mcp")
mcp_types = types.ModuleType("mcp.types")


class ToolAnnotations:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


mcp_types.ToolAnnotations = ToolAnnotations
sys.modules["mcp"] = mcp
sys.modules["mcp.types"] = mcp_types

windows_mcp = types.ModuleType("windows_mcp")
windows_mcp_tools = types.ModuleType("windows_mcp.tools")
windows_mcp_tools.register_all = lambda *args, **kwargs: None
sys.modules["windows_mcp"] = windows_mcp
sys.modules["windows_mcp.tools"] = windows_mcp_tools

server_config = types.ModuleType("server_config")
server_config.path_is_within = lambda candidate, root: True
server_config.parse_bool = lambda value, default=False: default if value is None else str(value).strip().lower() in {"1", "true", "yes", "on"}
sys.modules["server_config"] = server_config

server_runtime = types.ModuleType("server_runtime")
server_runtime.ServerContext = object
sys.modules["server_runtime"] = server_runtime

server_vscode_bridge = types.ModuleType("server_vscode_bridge")
server_vscode_bridge.VSCodeBridgeServer = object
sys.modules["server_vscode_bridge"] = server_vscode_bridge

import extensions.common as common
import extensions.file_edits as file_edits
from extensions.file_edits import FileEditExtension
import server_extensions

sys.modules.pop("server_config", None)
sys.modules.pop("server_runtime", None)
sys.modules.pop("server_vscode_bridge", None)


class FakeMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, **metadata):
        def decorator(func):
            self.tools[metadata["name"]] = {"func": func, "metadata": metadata}
            return func

        return decorator


class FakeBridgeState:
    def __init__(self, workspace_root: str = "C:/repo") -> None:
        self.workspace_root = workspace_root

    def get_session_snapshot(self, session_id: str):
        return {"sessionId": session_id, "workspaceRoot": self.workspace_root}

    def list_sessions(self):
        return []

    def get_context_items(self, session_id: str):
        return []

    def get_diagnostics(self, session_id: str):
        return []

    def create_session(self, session_id: str = "", payload=None):
        return {"sessionId": session_id, "payload": payload or {}}

    def close_session(self, session_id: str):
        return {"closed": session_id}


class FakeBridge:
    def __init__(self) -> None:
        self.enabled = True
        self.base_url = "http://127.0.0.1:8876"
        self.state = FakeBridgeState()
        self.workspace_edit_calls = []
        self.edit_calls = []
        self.edit_results = []
        self.workspace_edit_results = []

    async def request_edit(
        self,
        *,
        session_id: str,
        file_path: str,
        start_line: int,
        start_column: int,
        end_line: int,
        end_column: int,
        new_text: str,
        expected_text: str,
        timeout_seconds: int,
    ):
        self.edit_calls.append(
            {
                "session_id": session_id,
                "file_path": file_path,
                "start_line": start_line,
                "start_column": start_column,
                "end_line": end_line,
                "end_column": end_column,
                "new_text": new_text,
                "expected_text": expected_text,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.edit_results:
            return self.edit_results.pop(0)
        return {"status": "ok", "payload": {"applied": True}}

    async def request_workspace_edit(self, *, session_id: str, label: str, edits, timeout_seconds: int):
        self.workspace_edit_calls.append(
            {
                "session_id": session_id,
                "label": label,
                "edits": edits,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.workspace_edit_results:
            return self.workspace_edit_results.pop(0)
        return {"status": "ok", "payload": {"applied": True}}


class FakeContext:
    def __init__(self, bridge: FakeBridge | None = None) -> None:
        self._bridge = bridge or FakeBridge()

    def get_vscode_bridge(self):
        return self._bridge


class CommonHelperTests(unittest.TestCase):
    def test_is_vscode_edit_drift_error_detects_known_messages(self) -> None:
        self.assertTrue(common.is_vscode_edit_drift_error({"status": "error", "error": "Expected text mismatch before applying edit."}))
        self.assertTrue(common.is_vscode_edit_drift_error({"status": "error", "error": "Could not reliably locate edit target after drift."}))
        self.assertFalse(common.is_vscode_edit_drift_error({"status": "ok", "error": "Expected text mismatch before applying edit."}))
        self.assertFalse(common.is_vscode_edit_drift_error("not-a-dict"))

    def test_bind_chat_session_prefers_explicit_bound_session(self) -> None:
        with patch.object(common, "bind_current_request_session", return_value="bound-session") as bind_mock:
            with patch.object(common, "get_current_chat_session_id", return_value=""):
                self.assertEqual(common.bind_chat_session("requested-session"), "bound-session")
        bind_mock.assert_called_once_with("requested-session")

    def test_bind_chat_session_falls_back_to_current_session(self) -> None:
        with patch.object(common, "bind_current_request_session", return_value=""):
            with patch.object(common, "get_current_chat_session_id", return_value="chat-session"):
                self.assertEqual(common.bind_chat_session(""), "chat-session")

    def test_bind_chat_session_raises_when_required_and_unbound(self) -> None:
        with patch.object(common, "bind_current_request_session", return_value=""):
            with patch.object(common, "get_current_chat_session_id", return_value=""):
                with self.assertRaisesRegex(ValueError, "session_id is required"):
                    common.bind_chat_session("")

    def test_session_bound_tool_injects_bound_session_for_sync_function(self) -> None:
        @common.session_bound_tool
        def sample_tool(session_id: str = "") -> str:
            return session_id

        with patch.object(common, "bind_chat_session", return_value="sync-session") as bind_mock:
            self.assertEqual(sample_tool(""), "sync-session")
        bind_mock.assert_called_once_with("")

    def test_session_bound_tool_injects_bound_session_for_async_function(self) -> None:
        @common.session_bound_tool
        async def sample_tool(session_id: str = "") -> str:
            return session_id

        with patch.object(common, "bind_chat_session", return_value="async-session") as bind_mock:
            self.assertEqual(asyncio.run(sample_tool("")), "async-session")
        bind_mock.assert_called_once_with("")


class ExtensionBoundaryTests(unittest.TestCase):
    def test_server_extensions_re_exports_common_helpers(self) -> None:
        self.assertIs(server_extensions.bind_chat_session, common.bind_chat_session)
        self.assertIs(server_extensions.require_vscode_command_success, common.require_vscode_command_success)
        self.assertIs(server_extensions.run_engine_tool, common.run_engine_tool)
        self.assertIs(server_extensions.session_bound_tool, common.session_bound_tool)

    def test_file_edit_extension_registers_direct_edit_tool_set(self) -> None:
        mcp = FakeMCP()
        context = FakeContext()

        FileEditExtension().register(mcp, context)

        self.assertEqual(
            set(mcp.tools),
            {
                "get_file_range",
                "get_multiple_file_ranges",
                "request_file_edit",
                "safe_file_edit",
                "anchored_file_edit",
                "multi_anchor_file_edit",
            },
        )
        self.assertTrue(mcp.tools["get_file_range"]["metadata"]["annotations"].readOnlyHint)
        self.assertTrue(mcp.tools["get_multiple_file_ranges"]["metadata"]["annotations"].readOnlyHint)
        self.assertFalse(mcp.tools["safe_file_edit"]["metadata"]["annotations"].readOnlyHint)
        self.assertFalse(mcp.tools["anchored_file_edit"]["metadata"]["annotations"].readOnlyHint)
        self.assertFalse(mcp.tools["multi_anchor_file_edit"]["metadata"]["annotations"].readOnlyHint)


class FileEditExtensionTests(unittest.TestCase):
    def test_resolve_anchor_edit_offsets_requires_exact_anchor_lines(self) -> None:
        with self.assertRaisesRegex(ValueError, "start_anchor exact line was not found"):
            file_edits.resolve_anchor_edit_offsets(
                "prefix start\nlive\nend suffix\n",
                start_anchor="start",
                end_anchor="end",
            )

    def test_anchored_file_edit_can_include_modified_file_with_numbered_lines(self) -> None:
        mcp = FakeMCP()
        context = FakeContext()
        FileEditExtension().register(mcp, context)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "app.py"
            target.write_text("start\nlive\nend\n", encoding="utf-8", newline="\n")
            result = mcp.tools["anchored_file_edit"]["func"](
                file_path=str(target),
                start_anchor="start",
                end_anchor="end",
                replacement_text="updated\n",
                expected_body="live\n",
                include_modified_file_with_lines=True,
            )

            payload = json.loads(result)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(payload["anchorBasedEdit"])
            self.assertEqual(payload["modifiedFile"]["content"], "start\nupdated\nend")
            self.assertEqual(payload["modifiedFile"]["lines"][1]["lineNumber"], 2)
            self.assertEqual(payload["modifiedFile"]["lines"][1]["text"], "updated")
            self.assertEqual(target.read_text(encoding="utf-8"), "start\nupdated\nend\n")

    def test_get_file_range_reads_numbered_lines_without_vscode(self) -> None:
        mcp = FakeMCP()
        context = FakeContext()
        FileEditExtension().register(mcp, context)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "app.py"
            target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8", newline="\n")
            result = mcp.tools["get_file_range"]["func"](
                file_path=str(target),
                start_line=2,
                end_line=2,
                context_before=1,
            )
            payload = json.loads(result)
            self.assertTrue(payload["directFileRead"])
            self.assertEqual(payload["startLine"], 1)
            self.assertEqual(payload["endLine"], 2)
            self.assertEqual(payload["content"], "alpha\nbeta")
            self.assertEqual(payload["lines"][1]["text"], "beta")
            self.assertIn("anchored_file_edit", payload["anchorEditHint"])

    def test_get_multiple_file_ranges_reads_multiple_files_without_vscode(self) -> None:
        mcp = FakeMCP()
        context = FakeContext()
        FileEditExtension().register(mcp, context)

        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "app.py"
            second = Path(tmpdir) / "lib.py"
            first.write_text("alpha\nbeta\n", encoding="utf-8", newline="\n")
            second.write_text("one\ntwo\nthree\n", encoding="utf-8", newline="\n")
            files_json = json.dumps(
                [
                    {"filePath": str(first), "startLine": 1, "endLine": 2},
                    {"filePath": str(second), "startLine": 2, "endLine": 3, "contextBefore": 1},
                ]
            )
            result = mcp.tools["get_multiple_file_ranges"]["func"](files_json=files_json)
            payload = json.loads(result)
            self.assertTrue(payload["directFileRead"])
            self.assertEqual(payload["count"], 2)
            self.assertEqual(payload["files"][0]["content"], "alpha\nbeta")
            self.assertEqual(payload["files"][1]["content"], "one\ntwo\nthree")
            self.assertEqual(payload["files"][1]["startLine"], 1)
            self.assertEqual(payload["files"][1]["endLine"], 3)

    def test_request_file_edit_applies_validated_direct_disk_edit(self) -> None:
        mcp = FakeMCP()
        context = FakeContext()
        FileEditExtension().register(mcp, context)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "app.py"
            target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8", newline="\n")
            result = mcp.tools["request_file_edit"]["func"](
                file_path=str(target),
                start_line=2,
                start_column=1,
                end_line=2,
                end_column=5,
                new_text="delta",
                expected_text="beta",
            )
            payload = json.loads(result)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(target.read_text(encoding="utf-8"), "alpha\ndelta\ngamma\n")

    def test_safe_file_edit_applies_single_unique_match(self) -> None:
        mcp = FakeMCP()
        context = FakeContext()
        FileEditExtension().register(mcp, context)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "app.py"
            target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8", newline="\n")
            result = mcp.tools["safe_file_edit"]["func"](
                file_path=str(target),
                search_text="beta",
                replacement_text="delta",
            )
            payload = json.loads(result)
            self.assertTrue(payload["safeEdit"])
            self.assertEqual(target.read_text(encoding="utf-8"), "alpha\ndelta\ngamma\n")

    def test_anchored_file_edit_replaces_body_without_vscode(self) -> None:
        mcp = FakeMCP()
        context = FakeContext()
        FileEditExtension().register(mcp, context)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "app.py"
            target.write_text("before\n<start>\nlive\n<end>\nafter\n", encoding="utf-8", newline="\n")
            result = mcp.tools["anchored_file_edit"]["func"](
                file_path=str(target),
                start_anchor="<start>",
                end_anchor="<end>",
                replacement_text="updated\n",
                expected_body="live\n",
                include_modified_file_with_lines=True,
            )
            payload = json.loads(result)
            self.assertTrue(payload["anchorBasedEdit"])
            self.assertEqual(payload["modifiedFile"]["content"], "before\n<start>\nupdated\n<end>\nafter")
            self.assertEqual(payload["modifiedFile"]["lines"][2]["lineNumber"], 3)
            self.assertEqual(payload["modifiedFile"]["lines"][2]["text"], "updated")
            self.assertEqual(target.read_text(encoding="utf-8"), "before\n<start>\nupdated\n<end>\nafter\n")


    def test_multi_anchor_file_edit_replaces_multiple_bodies_in_one_request(self) -> None:
        mcp = FakeMCP()
        context = FakeContext()
        FileEditExtension().register(mcp, context)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "app.py"
            target.write_text(
                "one\n<a>\nfirst\n</a>\nmid\n<b>\nsecond\n</b>\ntail\n",
                encoding="utf-8",
                newline="\n",
            )
            edits_json = json.dumps(
                [
                    {"filePath": str(target), "startAnchor": "<a>", "endAnchor": "</a>", "replacementText": "FIRST\n", "expectedBody": "first\n"},
                    {"filePath": str(target), "startAnchor": "<b>", "endAnchor": "</b>", "replacementText": "SECOND\n", "expectedBody": "second\n"},
                ]
            )
            result = mcp.tools["multi_anchor_file_edit"]["func"](
                edits_json=edits_json,
                include_modified_files_with_lines=True,
            )
            payload = json.loads(result)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["editCount"], 2)
            self.assertEqual(payload["fileCount"], 1)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "one\n<a>\nFIRST\n</a>\nmid\n<b>\nSECOND\n</b>\ntail\n",
            )
            self.assertEqual(payload["modifiedFiles"][0]["lines"][2]["text"], "FIRST")
            self.assertEqual(payload["modifiedFiles"][0]["lines"][6]["text"], "SECOND")


if __name__ == "__main__":
    unittest.main()
