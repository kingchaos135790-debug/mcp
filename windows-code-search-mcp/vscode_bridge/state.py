from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Any
import logging
import uuid

from .models import SESSION_TTL_SECONDS, VSCodeCommand, VSCodeSession, _normalize_path, _now_iso, _parse_iso


logger = logging.getLogger(__name__)


class VSCodeBridgeState:
    def __init__(self, token: str = "") -> None:
        self.token = token.strip()
        self._lock = Lock()
        self._command_counter = 0
        self._sessions: dict[str, VSCodeSession] = {}

    def _next_command_id(self) -> str:
        self._command_counter += 1
        return f"cmd-{self._command_counter}"

    def _get_or_create_session(self, session_id: str) -> VSCodeSession:
        session = self._sessions.get(session_id)
        if session is None:
            session = VSCodeSession(session_id=session_id)
            self._sessions[session_id] = session
        return session

    def _touch_session(self, session: VSCodeSession, *, heartbeat: bool = False, command_poll: bool = False) -> str:
        timestamp = _now_iso()
        session.last_seen_at = timestamp
        if heartbeat:
            session.last_heartbeat_at = timestamp
        if command_poll:
            session.last_command_poll_at = timestamp
        return timestamp

    def _prune_stale_sessions_locked(self) -> None:
        now = datetime.now(UTC)
        stale_session_ids = []
        for session_id, session in self._sessions.items():
            last_seen = _parse_iso(session.last_seen_at)
            if last_seen is None:
                continue
            age_seconds = (now - last_seen).total_seconds()
            if age_seconds <= SESSION_TTL_SECONDS:
                continue
            stale_session_ids.append(session_id)

        for session_id in stale_session_ids:
            logger.info("Pruning stale VS Code bridge session %s", session_id)
            self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            self._prune_stale_sessions_locked()
            return [session.to_summary() for session in self._sessions.values()]

    def get_session_snapshot(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._prune_stale_sessions_locked()
            session = self._sessions.get(session_id)
            if session is None:
                return None
            return session.to_snapshot()

    def create_session(self, session_id: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        session_payload = payload if isinstance(payload, dict) else {}
        requested_session_id = str(session_id or session_payload.get("sessionId") or "").strip()
        normalized_session_id = requested_session_id or f"mcp-{uuid.uuid4().hex[:10]}"

        with self._lock:
            self._prune_stale_sessions_locked()
            if normalized_session_id in self._sessions:
                raise ValueError(f"VS Code session already exists: {normalized_session_id}")
            session = VSCodeSession(session_id=normalized_session_id)
            session.workspace_root = _normalize_path(str(session_payload.get("workspaceRoot", "")))
            session.workspace_name = str(session_payload.get("workspaceName", ""))
            session.active_file = _normalize_path(str(session_payload.get("activeFile", "")))
            self._touch_session(session)
            self._sessions[normalized_session_id] = session
            return session.to_snapshot()

    def close_session(self, session_id: str) -> dict[str, Any]:
        normalized_session_id = session_id.strip()
        if not normalized_session_id:
            raise ValueError("session_id is required")

        with self._lock:
            self._prune_stale_sessions_locked()
            session = self._sessions.pop(normalized_session_id, None)
            if session is None:
                raise KeyError(f"Unknown session: {normalized_session_id}")
            pending_command_count = sum(1 for command in session.pending_commands.values() if command.result is None)
            return {
                "sessionId": normalized_session_id,
                "closed": True,
                "pendingCommandCount": pending_command_count,
                "workspaceRoot": session.workspace_root,
                "workspaceName": session.workspace_name,
                "activeFile": session.active_file,
                "closedAt": _now_iso(),
            }

    def get_context_items(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._prune_stale_sessions_locked()
            session = self._sessions.get(session_id)
            return list(session.context_items) if session is not None else []

    def get_diagnostics(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._prune_stale_sessions_locked()
            session = self._sessions.get(session_id)
            return list(session.diagnostics) if session is not None else []

    def heartbeat_session(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._prune_stale_sessions_locked()
            session = self._get_or_create_session(session_id)
            session.workspace_root = _normalize_path(str(payload.get("workspaceRoot", session.workspace_root or "")))
            session.workspace_name = str(payload.get("workspaceName", session.workspace_name or ""))
            session.active_file = _normalize_path(str(payload.get("activeFile", session.active_file or "")))
            self._touch_session(session, heartbeat=True)
            return session.to_summary()

    def update_context(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise ValueError("items must be a list")

        with self._lock:
            self._prune_stale_sessions_locked()
            session = self._get_or_create_session(session_id)
            session.workspace_root = _normalize_path(str(payload.get("workspaceRoot", session.workspace_root or "")))
            session.workspace_name = str(payload.get("workspaceName", session.workspace_name or ""))
            session.active_file = _normalize_path(str(payload.get("activeFile", session.active_file or "")))
            session.context_items = [item for item in items if isinstance(item, dict)]
            session.last_context_update_at = _now_iso()
            self._touch_session(session)
            return session.to_summary()

    def update_diagnostics(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        diagnostics = payload.get("diagnostics", [])
        if not isinstance(diagnostics, list):
            raise ValueError("diagnostics must be a list")

        with self._lock:
            self._prune_stale_sessions_locked()
            session = self._get_or_create_session(session_id)
            session.workspace_root = _normalize_path(str(payload.get("workspaceRoot", session.workspace_root or "")))
            session.workspace_name = str(payload.get("workspaceName", session.workspace_name or ""))
            session.active_file = _normalize_path(str(payload.get("activeFile", session.active_file or "")))
            session.diagnostics = [item for item in diagnostics if isinstance(item, dict)]
            session.last_diagnostics_update_at = _now_iso()
            self._touch_session(session)
            return session.to_summary()

    def enqueue_command(self, session_id: str, command_type: str, payload: dict[str, Any]) -> VSCodeCommand:
        with self._lock:
            self._prune_stale_sessions_locked()
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"Unknown session: {session_id}")
            command = VSCodeCommand(
                command_id=self._next_command_id(),
                session_id=session_id,
                command_type=command_type,
                payload=payload,
            )
            session.pending_commands[command.command_id] = command
            logger.info(
                "Enqueued VS Code bridge command %s type=%s session=%s",
                command.command_id,
                command.command_type,
                command.session_id,
            )
            return command

    def claim_commands(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._prune_stale_sessions_locked()
            session = self._get_or_create_session(session_id)

            claimed: list[dict[str, Any]] = []
            now = self._touch_session(session, command_poll=True)
            for command in session.pending_commands.values():
                if command.result is not None:
                    continue
                command.status = "dispatched"
                command.delivered_at = now
                claimed.append(command.to_wire())
            logger.debug("Claimed %s VS Code bridge commands for session %s", len(claimed), session_id)
            return claimed

    def complete_command(self, session_id: str, command_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._prune_stale_sessions_locked()
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"Unknown session: {session_id}")
            command = session.pending_commands.get(command_id)
            if command is None:
                raise KeyError(f"Unknown command: {command_id}")
            command.result = {
                "commandId": command.command_id,
                "type": command.command_type,
                "status": str(payload.get("status", "ok")),
                "payload": payload.get("payload", {}),
                "error": str(payload.get("error", "")),
                "completedAt": _now_iso(),
            }
            command.status = "completed"
            self._touch_session(session)
            command.completion_event.set()
            logger.info(
                "Completed VS Code bridge command %s type=%s session=%s status=%s",
                command.command_id,
                command.command_type,
                session_id,
                command.result["status"],
            )
            return dict(command.result)

    def _find_active_polling_session(self, *, exclude_session_id: str = "") -> VSCodeSession | None:
        """Find a session that has recently polled for commands (within the last 30 seconds)."""
        now = datetime.now(UTC)
        best: VSCodeSession | None = None
        best_poll_time: datetime | None = None
        for session_id, session in self._sessions.items():
            if session_id == exclude_session_id:
                continue
            poll_at = _parse_iso(session.last_command_poll_at)
            if poll_at is None:
                continue
            age = (now - poll_at).total_seconds()
            if age > 30:
                continue
            if best_poll_time is None or poll_at > best_poll_time:
                best = session
                best_poll_time = poll_at
        return best

    def _try_recover_command_to_active_session(self, command: VSCodeCommand) -> VSCodeSession | None:
        """Attempt to migrate a pending command to another session that is actively polling."""
        if command.result is not None:
            return None
        active_session = self._find_active_polling_session(exclude_session_id=command.session_id)
        if active_session is None:
            return None
        old_session = self._sessions.get(command.session_id)
        if old_session is not None:
            old_session.pending_commands.pop(command.command_id, None)
        command.session_id = active_session.session_id
        command.status = "queued"
        command.delivered_at = ""
        active_session.pending_commands[command.command_id] = command
        logger.info(
            "Recovered VS Code bridge command %s by migrating to active session %s (was %s)",
            command.command_id,
            active_session.session_id,
            old_session.session_id if old_session else "(gone)",
        )
        return active_session

    def _build_wait_for_command_timeout_message(
        self,
        command: VSCodeCommand,
        session: VSCodeSession | None,
        *,
        poll_observation_window_seconds: float | None = None,
    ) -> str:
        if session is None:
            return (
                f"Timed out waiting for VS Code bridge command {command.command_id} for session {command.session_id}. "
                "The session is no longer registered; the bridge or extension may have restarted."
            )

        last_seen_at = session.last_seen_at or "never"
        last_command_poll_at = session.last_command_poll_at or "never"
        delivered_at = command.delivered_at or "not delivered"
        poll_after_enqueue = bool(session.last_command_poll_at and session.last_command_poll_at >= command.created_at)

        if not poll_after_enqueue:
            if poll_observation_window_seconds is not None:
                reason = (
                    f"The session exists but no command poll was observed within {poll_observation_window_seconds:.2f}s "
                    "after the command was queued; the VS Code extension may not be polling /commands or may be "
                    "using the wrong token."
                )
            else:
                reason = (
                    "The session exists but no command poll was observed after the command was queued; "
                    "the VS Code extension may not be polling /commands or may be using the wrong token."
                )
        elif not command.delivered_at:
            reason = "The session polled /commands after the command was queued, but the command was not claimed."
        else:
            reason = "The extension claimed the command, but no result was posted back to the bridge."

        return (
            f"Timed out waiting for VS Code bridge command {command.command_id} for session {command.session_id}. "
            f"{reason} lastSeenAt={last_seen_at} lastCommandPollAt={last_command_poll_at} deliveredAt={delivered_at}"
        )

    def wait_for_command(self, command: VSCodeCommand, timeout_seconds: float) -> dict[str, Any]:
        poll_observation_window_seconds = min(max(timeout_seconds, 0.0), 5.0)

        if poll_observation_window_seconds > 0:
            completed = command.completion_event.wait(poll_observation_window_seconds)
            if completed and command.result is not None:
                return dict(command.result)

            with self._lock:
                self._prune_stale_sessions_locked()
                session = self._sessions.get(command.session_id)
                if command.result is not None:
                    return dict(command.result)
                poll_after_enqueue = bool(
                    session is not None
                    and session.last_command_poll_at
                    and session.last_command_poll_at >= command.created_at
                )
                if not poll_after_enqueue:
                    # Attempt automatic session recovery before failing
                    recovered_session = self._try_recover_command_to_active_session(command)
                    if recovered_session is not None:
                        logger.info(
                            "Session recovery: command %s migrated to session %s, retrying wait",
                            command.command_id,
                            recovered_session.session_id,
                        )
                    else:
                        message = self._build_wait_for_command_timeout_message(
                            command,
                            session,
                            poll_observation_window_seconds=poll_observation_window_seconds,
                        )
                        logger.warning(message)
                        raise TimeoutError(message)

        remaining_timeout_seconds = max(0.0, timeout_seconds - poll_observation_window_seconds)
        if remaining_timeout_seconds > 0:
            completed = command.completion_event.wait(remaining_timeout_seconds)
            if completed and command.result is not None:
                return dict(command.result)

        with self._lock:
            self._prune_stale_sessions_locked()
            session = self._sessions.get(command.session_id)
            if command.result is not None:
                return dict(command.result)
            message = self._build_wait_for_command_timeout_message(command, session)
            logger.warning(message)
            raise TimeoutError(message)
