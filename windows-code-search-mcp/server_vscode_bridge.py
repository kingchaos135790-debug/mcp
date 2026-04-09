from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any
from urllib.parse import urlparse
import asyncio
import json
import logging
import uuid

from server_config import Config


logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 300


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    if not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_path(value: str) -> str:
    if not value.strip():
        return value
    try:
        return str(Path(value).expanduser().resolve())
    except Exception:
        return value


@dataclass
class VSCodeCommand:
    command_id: str
    session_id: str
    command_type: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=_now_iso)
    delivered_at: str = ""
    status: str = "queued"
    result: dict[str, Any] | None = None
    completion_event: Event = field(default_factory=Event, repr=False)

    def to_wire(self) -> dict[str, Any]:
        return {
            "commandId": self.command_id,
            "type": self.command_type,
            "payload": self.payload,
            "createdAt": self.created_at,
        }


@dataclass
class VSCodeSession:
    session_id: str
    created_at: str = field(default_factory=_now_iso)
    workspace_root: str = ""
    workspace_name: str = ""
    active_file: str = ""
    context_items: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    last_context_update_at: str = ""
    last_diagnostics_update_at: str = ""
    last_heartbeat_at: str = ""
    last_command_poll_at: str = ""
    last_seen_at: str = field(default_factory=_now_iso)
    pending_commands: dict[str, VSCodeCommand] = field(default_factory=dict, repr=False)

    def to_summary(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "createdAt": self.created_at,
            "workspaceRoot": self.workspace_root,
            "workspaceName": self.workspace_name,
            "activeFile": self.active_file,
            "contextItemCount": len(self.context_items),
            "diagnosticCount": len(self.diagnostics),
            "pendingCommandCount": sum(1 for command in self.pending_commands.values() if command.result is None),
            "lastContextUpdateAt": self.last_context_update_at,
            "lastDiagnosticsUpdateAt": self.last_diagnostics_update_at,
            "lastHeartbeatAt": self.last_heartbeat_at,
            "lastCommandPollAt": self.last_command_poll_at,
            "lastSeenAt": self.last_seen_at,
        }

    def to_snapshot(self) -> dict[str, Any]:
        payload = self.to_summary()
        payload["contextItems"] = self.context_items
        payload["diagnostics"] = self.diagnostics
        return payload


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

    def wait_for_command(self, command: VSCodeCommand, timeout_seconds: float) -> dict[str, Any]:
        completed = command.completion_event.wait(timeout_seconds)
        if completed and command.result is not None:
            return dict(command.result)

        with self._lock:
            self._prune_stale_sessions_locked()
            session = self._sessions.get(command.session_id)
            if session is None:
                message = (
                    f"Timed out waiting for VS Code bridge command {command.command_id} for session {command.session_id}. "
                    "The session is no longer registered; the bridge or extension may have restarted."
                )
                logger.warning(message)
                raise TimeoutError(message)

            if command.result is not None:
                return dict(command.result)

            last_seen_at = session.last_seen_at or "never"
            last_command_poll_at = session.last_command_poll_at or "never"
            delivered_at = command.delivered_at or "not delivered"
            poll_after_enqueue = bool(session.last_command_poll_at and session.last_command_poll_at >= command.created_at)

            if not poll_after_enqueue:
                reason = (
                    "The session exists but no command poll was observed after the command was queued; "
                    "the VS Code extension may not be polling /commands or may be using the wrong token."
                )
            elif not command.delivered_at:
                reason = "The session polled /commands after the command was queued, but the command was not claimed."
            else:
                reason = "The extension claimed the command, but no result was posted back to the bridge."

            message = (
                f"Timed out waiting for VS Code bridge command {command.command_id} for session {command.session_id}. "
                f"{reason} lastSeenAt={last_seen_at} lastCommandPollAt={last_command_poll_at} deliveredAt={delivered_at}"
            )
            logger.warning(message)
            raise TimeoutError(message)


class VSCodeBridgeServer:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.state = VSCodeBridgeState(token=config.vscode_bridge_token)
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None
        self._server_lock = Lock()

    @property
    def enabled(self) -> bool:
        return self.config.vscode_bridge_enabled

    @property
    def base_url(self) -> str:
        return f"http://{self.config.vscode_bridge_host}:{self.config.vscode_bridge_port}"

    def preview_base_url(self, host: str, port: int) -> str:
        return f"http://{host}:{port}"

    def _create_server(self, host: str, port: int, handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
        return ThreadingHTTPServer((host, port), handler)

    def start(self) -> None:
        if not self.enabled:
            return

        with self._server_lock:
            if self._server is not None:
                return

            handler = self._build_handler()
            self._server = self._create_server(self.config.vscode_bridge_host, self.config.vscode_bridge_port, handler)
            self._thread = Thread(target=self._server.serve_forever, name="vscode-bridge-server", daemon=True)
            self._thread.start()
            logger.info("VS Code bridge listening at %s", self.base_url)

    def stop(self) -> None:
        with self._server_lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None

        if server is None:
            return

        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5)

    def restart(self, host: str | None = None, port: int | None = None, token: str | None = None) -> str:
        next_host = (host or self.config.vscode_bridge_host).strip() or "127.0.0.1"
        next_port = int(port if port is not None else self.config.vscode_bridge_port)
        next_token = self.config.vscode_bridge_token if token is None else token.strip()

        previous_host = self.config.vscode_bridge_host
        previous_port = self.config.vscode_bridge_port
        previous_token = self.config.vscode_bridge_token

        if self._server is not None and (next_host, next_port) != (previous_host, previous_port):
            probe = self._create_server(next_host, next_port, self._build_handler())
            probe.server_close()

        self.stop()
        self.config.vscode_bridge_host = next_host
        self.config.vscode_bridge_port = next_port
        self.config.vscode_bridge_token = next_token
        self.state.token = next_token

        try:
            self.start()
        except Exception:
            self.config.vscode_bridge_host = previous_host
            self.config.vscode_bridge_port = previous_port
            self.config.vscode_bridge_token = previous_token
            self.state.token = previous_token
            self.start()
            raise

        return self.base_url

    async def request_edit(
        self,
        session_id: str,
        file_path: str,
        start_line: int,
        start_column: int,
        end_line: int,
        end_column: int,
        new_text: str,
        expected_text: str = "",
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        command = self.state.enqueue_command(
            session_id,
            "apply_edit",
            {
                "filePath": _normalize_path(file_path),
                "range": {
                    "startLine": start_line,
                    "startColumn": start_column,
                    "endLine": end_line,
                    "endColumn": end_column,
                },
                "newText": new_text,
                "expectedText": expected_text,
            },
        )
        return await asyncio.to_thread(self.state.wait_for_command, command, timeout_seconds)

    async def request_workspace_edit(
        self,
        session_id: str,
        label: str,
        edits: list[dict[str, Any]],
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        normalized_edits: list[dict[str, Any]] = []
        for item in edits:
            if not isinstance(item, dict):
                continue
            file_path = item.get("filePath") or item.get("file_path")
            range_payload = item.get("range")
            if not isinstance(range_payload, dict):
                range_payload = {
                    "startLine": item.get("startLine") or item.get("start_line"),
                    "startColumn": item.get("startColumn") or item.get("start_column"),
                    "endLine": item.get("endLine") or item.get("end_line"),
                    "endColumn": item.get("endColumn") or item.get("end_column"),
                }
            normalized_item = dict(item)
            if file_path:
                normalized_item["filePath"] = _normalize_path(str(file_path))
            normalized_item["range"] = {
                "startLine": int(range_payload.get("startLine") or 1),
                "startColumn": int(range_payload.get("startColumn") or 1),
                "endLine": int(range_payload.get("endLine") or 1),
                "endColumn": int(range_payload.get("endColumn") or 1),
            }
            if "newText" not in normalized_item and "new_text" in normalized_item:
                normalized_item["newText"] = normalized_item.get("new_text")
            if "expectedText" not in normalized_item and "expected_text" in normalized_item:
                normalized_item["expectedText"] = normalized_item.get("expected_text")
            normalized_edits.append(normalized_item)

        command = self.state.enqueue_command(
            session_id,
            "apply_workspace_edit",
            {
                "label": label,
                "edits": normalized_edits,
            },
        )
        return await asyncio.to_thread(self.state.wait_for_command, command, timeout_seconds)

    async def request_open_file(
        self,
        session_id: str,
        file_path: str,
        line: int = 1,
        column: int = 1,
        preserve_focus: bool = False,
        timeout_seconds: float = 15,
    ) -> dict[str, Any]:
        command = self.state.enqueue_command(
            session_id,
            "open_file",
            {
                "filePath": _normalize_path(file_path),
                "line": line,
                "column": column,
                "preserveFocus": preserve_focus,
            },
        )
        return await asyncio.to_thread(self.state.wait_for_command, command, timeout_seconds)

    def _build_handler(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "VSCodeBridge/0.1"

            def _send_json(self, status: int, payload: dict[str, Any] | list[Any]) -> None:
                body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json_body(self) -> dict[str, Any]:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
                try:
                    parsed = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON body: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise ValueError("JSON body must be an object")
                return parsed

            def _require_token(self) -> bool:
                if not bridge.state.token:
                    return True
                provided = self.headers.get("X-Bridge-Token", "").strip()
                if provided == bridge.state.token:
                    return True
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
                return False

            def do_GET(self) -> None:
                if not self._require_token():
                    return

                parsed = urlparse(self.path)
                parts = [part for part in parsed.path.split("/") if part]

                if parsed.path == "/health":
                    self._send_json(HTTPStatus.OK, {"ok": True, "baseUrl": bridge.base_url})
                    return

                if parts == ["sessions"]:
                    self._send_json(HTTPStatus.OK, {"sessions": bridge.state.list_sessions()})
                    return

                if len(parts) >= 2 and parts[0] == "sessions":
                    session_id = parts[1]
                    if len(parts) == 2:
                        snapshot = bridge.state.get_session_snapshot(session_id)
                        if snapshot is None:
                            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown session: {session_id}"})
                            return
                        self._send_json(HTTPStatus.OK, snapshot)
                        return
                    if len(parts) == 3 and parts[2] == "context":
                        self._send_json(HTTPStatus.OK, {"sessionId": session_id, "items": bridge.state.get_context_items(session_id)})
                        return
                    if len(parts) == 3 and parts[2] == "diagnostics":
                        self._send_json(
                            HTTPStatus.OK,
                            {"sessionId": session_id, "diagnostics": bridge.state.get_diagnostics(session_id)},
                        )
                        return
                    if len(parts) == 3 and parts[2] == "commands":
                        self._send_json(HTTPStatus.OK, {"sessionId": session_id, "commands": bridge.state.claim_commands(session_id)})
                        return

                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Route not found"})

            def do_POST(self) -> None:
                if not self._require_token():
                    return

                parsed = urlparse(self.path)
                parts = [part for part in parsed.path.split("/") if part]

                try:
                    body = self._read_json_body()
                    if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "context":
                        result = bridge.state.update_context(parts[1], body)
                        self._send_json(HTTPStatus.OK, result)
                        return
                    if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "heartbeat":
                        result = bridge.state.heartbeat_session(parts[1], body)
                        self._send_json(HTTPStatus.OK, result)
                        return
                    if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "diagnostics":
                        result = bridge.state.update_diagnostics(parts[1], body)
                        self._send_json(HTTPStatus.OK, result)
                        return
                    if len(parts) == 5 and parts[0] == "sessions" and parts[2] == "commands" and parts[4] == "result":
                        result = bridge.state.complete_command(parts[1], parts[3], body)
                        self._send_json(HTTPStatus.OK, result)
                        return
                    if parts == ["admin", "restart"]:
                        next_host = str(body.get("host", bridge.config.vscode_bridge_host)).strip() or "127.0.0.1"
                        next_port = int(body.get("port", bridge.config.vscode_bridge_port))
                        if next_port < 1 or next_port > 65535:
                            raise ValueError("Port must be between 1 and 65535")
                        next_token = body.get("token")
                        next_url = bridge.preview_base_url(next_host, next_port)

                        def restart_bridge() -> None:
                            try:
                                bridge.restart(host=next_host, port=next_port, token=next_token if isinstance(next_token, str) else None)
                            except Exception:
                                logger.exception("VS Code bridge restart failed")

                        Thread(target=restart_bridge, name="vscode-bridge-restart", daemon=True).start()
                        self._send_json(
                            HTTPStatus.ACCEPTED,
                            {
                                "status": "restarting",
                                "previousBaseUrl": bridge.base_url,
                                "nextBaseUrl": next_url,
                            },
                        )
                        return
                except KeyError as exc:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                    return
                except ValueError as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                except Exception as exc:
                    logger.exception("VS Code bridge request failed")
                    self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                    return

                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Route not found"})

            def log_message(self, format: str, *args: Any) -> None:
                logger.debug("VS Code bridge: " + format, *args)

        return Handler

