from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import sys
import types
import unittest
from unittest.mock import Mock


server_config = types.ModuleType("server_config")


@dataclass
class Config:
    vscode_bridge_enabled: bool = True
    vscode_bridge_host: str = "127.0.0.1"
    vscode_bridge_port: int = 8876
    vscode_bridge_token: str = ""


server_config.Config = Config
sys.modules["server_config"] = server_config

from server_vscode_bridge import VSCodeBridgeState


class VSCodeBridgeStateTests(unittest.TestCase):
    def test_heartbeat_registers_session(self) -> None:
        state = VSCodeBridgeState()

        summary = state.heartbeat_session("session-1", {"workspaceRoot": "/repo", "activeFile": "/repo/app.py"})

        self.assertEqual(summary["sessionId"], "session-1")
        self.assertTrue(summary["workspaceRoot"].lower().endswith("repo"))
        self.assertTrue(summary["lastHeartbeatAt"])
        self.assertEqual(len(state.list_sessions()), 1)

    def test_claim_commands_registers_polling_session(self) -> None:
        state = VSCodeBridgeState()

        claimed = state.claim_commands("session-1")
        snapshot = state.get_session_snapshot("session-1")

        self.assertEqual(claimed, [])
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertTrue(snapshot["lastCommandPollAt"])

    def test_enqueue_command_requires_existing_session(self) -> None:
        state = VSCodeBridgeState()

        with self.assertRaisesRegex(KeyError, "Unknown session: missing"):
            state.enqueue_command("missing", "apply_edit", {})

    def test_wait_for_command_timeout_reports_missing_poll(self) -> None:
        state = VSCodeBridgeState()
        state.heartbeat_session("session-1", {})
        command = state.enqueue_command("session-1", "apply_edit", {})

        with self.assertRaisesRegex(TimeoutError, "no command poll was observed"):
            state.wait_for_command(command, 0.01)

    def test_wait_for_command_fails_fast_when_no_poll_is_observed(self) -> None:
        state = VSCodeBridgeState()
        state.heartbeat_session("session-1", {})
        command = state.enqueue_command("session-1", "apply_edit", {})
        command.completion_event = Mock()
        command.completion_event.wait.return_value = False

        with self.assertRaisesRegex(TimeoutError, "within 5.00s"):
            state.wait_for_command(command, 30)

        command.completion_event.wait.assert_called_once_with(5.0)

    def test_wait_for_command_timeout_reports_missing_result_after_claim(self) -> None:
        state = VSCodeBridgeState()
        state.heartbeat_session("session-1", {})
        command = state.enqueue_command("session-1", "apply_edit", {})
        state.claim_commands("session-1")

        with self.assertRaisesRegex(TimeoutError, "claimed the command"):
            state.wait_for_command(command, 0.01)

    def test_stale_sessions_are_pruned(self) -> None:
        state = VSCodeBridgeState()
        state.heartbeat_session("session-1", {})
        session = state._sessions["session-1"]
        session.last_seen_at = (datetime.now(UTC) - timedelta(seconds=301)).isoformat().replace("+00:00", "Z")

        self.assertEqual(state.list_sessions(), [])


if __name__ == "__main__":
    unittest.main()
