from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from typing import Any
import asyncio
import logging

from server_config import Config

from .models import _normalize_path
from .state import VSCodeBridgeState
from .transport import build_bridge_handler


logger = logging.getLogger(__name__)


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

    def _build_handler(self):
        return build_bridge_handler(self)

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
