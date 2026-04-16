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
import extensions.vscode_edits as vscode_edits
from extensions.vscode_edits import VSCodeEditExtension
from extensions.vscode_sessions import VSCodeSessionExtension
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

    def test_vscode_session_and_edit_extensions_register_distinct_tool_sets(self) -> None:
        mcp = FakeMCP()
        context = FakeContext()

        VSCodeSessionExtension().register(mcp, context)
        session_tools = set(mcp.tools)
        VSCodeEditExtension().register(mcp, context)
        all_tools = set(mcp.tools)
        edit_only_tools = all_tools - session_tools

        self.assertEqual(
            session_tools,
            {
                "create_vscode_session",
                "close_vscode_session",
                "list_vscode_sessions",
                "get_vscode_session",
                "get_vscode_context",
                "get_vscode_context_summary",
                "get_vscode_diagnostics",
                "get_vscode_file_range",
            },
        )
        self.assertEqual(
            edit_only_tools,
            {
                "request_vscode_edit",
                "request_vscode_workspace_edit",
                "safe_vscode_edit",
                "anchored_vscode_edit",
                "get_file_range",
                "get_multiple_file_ranges",
                "request_file_edit",
                "safe_file_edit",
                "anchored_file_edit",
                "open_vscode_file",
            },
        )
        self.assertTrue(mcp.tools["get_vscode_file_range"]["metadata"]["annotations"].readOnlyHint)
        self.assertTrue(mcp.tools["get_file_range"]["metadata"]["annotations"].readOnlyHint)
        self.assertTrue(mcp.tools["get_multiple_file_ranges"]["metadata"]["annotations"].readOnlyHint)
        self.assertFalse(mcp.tools["safe_vscode_edit"]["metadata"]["annotations"].readOnlyHint)
        self.assertFalse(mcp.tools["anchored_file_edit"]["metadata"]["annotations"].readOnlyHint)


class VSCodeEditExtensionTests(unittest.TestCase):
    def test_request_vscode_workspace_edit_normalizes_line_endings_before_bridge_call(self) -> None:
        bridge = FakeBridge()
        mcp = FakeMCP()
        context = FakeContext(bridge)
        VSCodeEditExtension().register(mcp, context)

        edits_json = json.dumps(
            [
                {
                    "filePath": "app.py",
                    "newText": "line1\r\nline2\r\n",
                    "expectedText": "before\r\nafter\r\n",
                }
            ]
        )

        result = asyncio.run(
            mcp.tools["request_vscode_workspace_edit"]["func"](
                session_id="session-1",
                edits_json=edits_json,
                label="Normalize",
            )
        )

        payload = json.loads(result)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(len(bridge.workspace_edit_calls), 1)
        sent_edit = bridge.workspace_edit_calls[0]["edits"][0]
        self.assertEqual(sent_edit["newText"], "line1\nline2\n")
        self.assertEqual(sent_edit["expectedText"], "before\nafter\n")

    def test_request_vscode_edit_retries_with_fresh_expected_text_after_drift(self) -> None:
        bridge = FakeBridge()
        bridge.edit_results = [
            {"status": "error", "error": "Expected text mismatch before applying edit."},
            {"status": "ok", "payload": {"applied": True}},
        ]
        mcp = FakeMCP()
        context = FakeContext(bridge)
        VSCodeEditExtension().register(mcp, context)

        with patch.object(vscode_edits, "extract_live_range_text", return_value=("C:/repo/app.py", "live\ntext")) as extract_mock:
            result = asyncio.run(
                mcp.tools["request_vscode_edit"]["func"](
                    session_id="session-1",
                    file_path="app.py",
                    start_line=1,
                    start_column=1,
                    end_line=1,
                    end_column=5,
                    new_text="next\r\ntext",
                    expected_text="old\r\ntext",
                )
            )

        payload = json.loads(result)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(len(bridge.edit_calls), 2)
        self.assertEqual(bridge.edit_calls[0]["new_text"], "next\ntext")
        self.assertEqual(bridge.edit_calls[0]["expected_text"], "old\ntext")
        self.assertEqual(bridge.edit_calls[1]["file_path"], "C:/repo/app.py")
        self.assertEqual(bridge.edit_calls[1]["expected_text"], "live\ntext")
        extract_mock.assert_called_once()

    def test_request_vscode_workspace_edit_retries_with_refreshed_expected_text_after_drift(self) -> None:
        bridge = FakeBridge()
        bridge.workspace_edit_results = [
            {"status": "error", "error": "Could not reliably locate edit target after drift."},
            {"status": "ok", "payload": {"applied": True}},
        ]
        mcp = FakeMCP()
        context = FakeContext(bridge)
        VSCodeEditExtension().register(mcp, context)

        edits_json = json.dumps(
            [
                {
                    "filePath": "app.py",
                    "range": {"startLine": 2, "startColumn": 1, "endLine": 2, "endColumn": 4},
                    "newText": "new\r\nvalue",
                    "expectedText": "old\r\nvalue",
                }
            ]
        )

        with patch.object(vscode_edits, "extract_live_range_text", return_value=("C:/repo/app.py", "live\nvalue")) as extract_mock:
            result = asyncio.run(
                mcp.tools["request_vscode_workspace_edit"]["func"](
                    session_id="session-1",
                    edits_json=edits_json,
                    label="Refresh",
                )
            )

        payload = json.loads(result)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(len(bridge.workspace_edit_calls), 2)
        first_edit = bridge.workspace_edit_calls[0]["edits"][0]
        second_edit = bridge.workspace_edit_calls[1]["edits"][0]
        self.assertEqual(first_edit["newText"], "new\nvalue")
        self.assertEqual(first_edit["expectedText"], "old\nvalue")
        self.assertEqual(second_edit["filePath"], "C:/repo/app.py")
        self.assertEqual(second_edit["expectedText"], "live\nvalue")
        extract_mock.assert_called_once()

    def test_safe_vscode_edit_applies_single_unique_match(self) -> None:
        bridge = FakeBridge()
        mcp = FakeMCP()
        context = FakeContext(bridge)
        VSCodeEditExtension().register(mcp, context)

        with patch.object(vscode_edits, "resolve_workspace_file_path", return_value="C:/repo/app.py"):
            with patch.object(vscode_edits, "read_numbered_file_range", return_value={"content": "alpha\nbeta\ngamma\n", "startLine": 1}):
                with patch.object(vscode_edits, "extract_live_range_text", return_value=("C:/repo/app.py", "beta")):
                    result = asyncio.run(
                        mcp.tools["safe_vscode_edit"]["func"](
                            session_id="session-1",
                            file_path="app.py",
                            search_text="beta",
                            replacement_text="delta",
                        )
                    )

        payload = json.loads(result)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(len(bridge.edit_calls), 1)
        self.assertEqual(bridge.edit_calls[0]["file_path"], "C:/repo/app.py")
        self.assertEqual(bridge.edit_calls[0]["expected_text"], "beta")
        self.assertEqual(bridge.edit_calls[0]["new_text"], "delta")

    def test_safe_vscode_edit_rejects_multiple_matches(self) -> None:
        bridge = FakeBridge()
        mcp = FakeMCP()
        context = FakeContext(bridge)
        VSCodeEditExtension().register(mcp, context)

        with patch.object(vscode_edits, "resolve_workspace_file_path", return_value="C:/repo/app.py"):
            with patch.object(vscode_edits, "read_numbered_file_range", return_value={"content": "beta\nalpha\nbeta\n", "startLine": 1}):
                with self.assertRaisesRegex(ValueError, "matched more than once"):
                    asyncio.run(
                        mcp.tools["safe_vscode_edit"]["func"](
                            session_id="session-1",
                            file_path="app.py",
                            search_text="beta",
                            replacement_text="delta",
                        )
                    )

        self.assertEqual(bridge.edit_calls, [])

    def test_anchored_vscode_edit_rejects_expected_body_mismatch(self) -> None:
        bridge = FakeBridge()
        mcp = FakeMCP()
        context = FakeContext(bridge)
        VSCodeEditExtension().register(mcp, context)

        with patch.object(vscode_edits, "resolve_workspace_file_path", return_value="C:/repo/app.py"):
            with patch.object(vscode_edits, "read_numbered_file_range", return_value={"content": "start\nlive\nend\n", "startLine": 1}):
                with patch.object(vscode_edits, "resolve_anchor_edit_offsets", return_value=(6, 10, "live")):
                    with patch.object(vscode_edits, "extract_live_range_text", return_value=("C:/repo/app.py", "live")):
                        with self.assertRaisesRegex(ValueError, "expected_body no longer matches"):
                            asyncio.run(
                                mcp.tools["anchored_vscode_edit"]["func"](
                                    session_id="session-1",
                                    file_path="app.py",
                                    start_anchor="start",
                                    end_anchor="end",
                                    replacement_text="updated",
                                    expected_body="stale",
                                )
                            )

        self.assertEqual(bridge.edit_calls, [])

    def test_get_file_range_reads_numbered_lines_without_vscode(self) -> None:
        mcp = FakeMCP()
        context = FakeContext()
        VSCodeEditExtension().register(mcp, context)

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
        VSCodeEditExtension().register(mcp, context)

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
        VSCodeEditExtension().register(mcp, context)

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
        VSCodeEditExtension().register(mcp, context)

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
        VSCodeEditExtension().register(mcp, context)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "app.py"
            target.write_text("before\n<start>\nlive\n<end>\nafter\n", encoding="utf-8", newline="\n")
            result = mcp.tools["anchored_file_edit"]["func"](
                file_path=str(target),
                start_anchor="<start>\n",
                end_anchor="\n<end>",
                replacement_text="updated",
                expected_body="live",
            )
            payload = json.loads(result)
            self.assertTrue(payload["anchorBasedEdit"])
            self.assertEqual(target.read_text(encoding="utf-8"), "before\n<start>\nupdated\n<end>\nafter\n")


if __name__ == "__main__":
    unittest.main()
