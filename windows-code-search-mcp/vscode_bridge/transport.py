from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from threading import Thread
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
import json
import logging

from .models import SESSION_TTL_SECONDS, _parse_iso

if TYPE_CHECKING:
    from .server import VSCodeBridgeServer


logger = logging.getLogger(__name__)


def build_bridge_handler(bridge: "VSCodeBridgeServer") -> type[BaseHTTPRequestHandler]:
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

            if parsed.path == "/session-health":
                with bridge.state._lock:
                    bridge.state._prune_stale_sessions_locked()
                    sessions = list(bridge.state._sessions.values())
                health = []
                for session in sessions:
                    last_poll = _parse_iso(session.last_command_poll_at) if session.last_command_poll_at else None
                    last_heartbeat = _parse_iso(session.last_heartbeat_at) if session.last_heartbeat_at else None
                    last_seen = _parse_iso(session.last_seen_at) if session.last_seen_at else None
                    now = datetime.now(UTC)
                    poll_age = (now - last_poll).total_seconds() if last_poll else None
                    heartbeat_age = (now - last_heartbeat).total_seconds() if last_heartbeat else None
                    seen_age = (now - last_seen).total_seconds() if last_seen else None
                    is_polling = poll_age is not None and poll_age < 30
                    is_alive = seen_age is not None and seen_age < SESSION_TTL_SECONDS
                    health.append({
                        "sessionId": session.session_id,
                        "isPolling": is_polling,
                        "isAlive": is_alive,
                        "pollAgeSeconds": round(poll_age, 1) if poll_age is not None else None,
                        "heartbeatAgeSeconds": round(heartbeat_age, 1) if heartbeat_age is not None else None,
                        "seenAgeSeconds": round(seen_age, 1) if seen_age is not None else None,
                        "pendingCommandCount": sum(1 for c in session.pending_commands.values() if c.result is None),
                        "workspaceRoot": session.workspace_root,
                    })
                self._send_json(HTTPStatus.OK, {"sessions": health})
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
