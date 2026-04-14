from __future__ import annotations

import atexit
import click
import logging
import os
import re
import sys
import uuid
from pathlib import Path

import fastmcp

import bootstrap  # noqa: F401

from server_app import ServerApp
from server_config import SEARCH_TOOL_NAMES, Transport, VSCODE_TOOL_NAMES, build_config, parse_bool
from server_extensions import SearchExtension, VSCodeBridgeExtension, WindowsDesktopExtension
from session_context import get_current_boot_id, get_current_chat_session_id, normalize_chat_session_id, set_current_boot_id

LOGGER = logging.getLogger(__name__)
_BOOT_LOG_NAME = re.compile(r"^(?P<stem>.+)-(?P<boot>[0-9a-f]{12})(?:--session-(?P<session>[A-Za-z0-9._-]+))?(?P<suffix>\.[^.]+)?$")


def _coerce_history_limit() -> int:
    raw = os.getenv("MCP_RUNTIME_HISTORY_LIMIT", "1").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _build_runtime_log_path(log_dir_text: str, runtime_log_text: str, boot_id: str) -> Path | None:
    if runtime_log_text:
        configured = Path(runtime_log_text).expanduser()
        suffix = configured.suffix or ".log"
        return configured.with_name(f"{configured.stem}-{boot_id}{suffix}")
    if log_dir_text:
        log_dir = Path(log_dir_text).expanduser()
        return log_dir / f"windows-code-search-mcp-runtime-{boot_id}.log"
    return None


def _log_identity(log_path: Path) -> tuple[str, str, str]:
    match = _BOOT_LOG_NAME.match(log_path.name)
    if match:
        return match.group("stem"), match.group("boot"), match.group("suffix") or ""
    suffix = log_path.suffix or ".log"
    return log_path.stem, get_current_boot_id() or "boot", suffix


def _prune_runtime_log_history(current_log_path: Path, history_limit: int) -> None:
    if history_limit < 1:
        return
    stem, _, suffix = _log_identity(current_log_path)
    groups: dict[str, list[Path]] = {}
    pattern = re.compile(rf"^{re.escape(stem)}-(?P<boot>[0-9a-f]{{12}})(?:--session-[A-Za-z0-9._-]+)?{re.escape(suffix)}$")
    for candidate in current_log_path.parent.glob(f"{stem}-*{suffix}"):
        match = pattern.match(candidate.name)
        if not match:
            continue
        groups.setdefault(match.group("boot"), []).append(candidate)
    if len(groups) <= history_limit:
        return
    ordered_boots = sorted(
        groups,
        key=lambda boot: max(path.stat().st_mtime for path in groups[boot]),
        reverse=True,
    )
    keep = set(ordered_boots[:history_limit])
    for boot_id, paths in groups.items():
        if boot_id in keep:
            continue
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                LOGGER.warning("Failed to prune runtime log file %s", path, exc_info=True)


class SessionContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.boot_id = get_current_boot_id() or "-"
        record.chat_session_id = get_current_chat_session_id() or "-"
        return True


class SessionRoutingFileHandler(logging.Handler):
    def __init__(self, general_log_path: Path, history_limit: int) -> None:
        super().__init__()
        self._general_log_path = general_log_path.resolve()
        self._general_log_path.parent.mkdir(parents=True, exist_ok=True)
        _prune_runtime_log_history(self._general_log_path, history_limit)
        self._stem, self._boot_id, self._suffix = _log_identity(self._general_log_path)
        self._general_handler = logging.FileHandler(self._general_log_path, encoding="utf-8")
        self._session_handlers: dict[str, logging.FileHandler] = {}

    def setFormatter(self, formatter: logging.Formatter | None) -> None:  # noqa: N802
        super().setFormatter(formatter)
        self._general_handler.setFormatter(formatter)
        for handler in self._session_handlers.values():
            handler.setFormatter(formatter)

    def _session_log_path(self, session_id: str) -> Path:
        normalized = normalize_chat_session_id(session_id)
        return self._general_log_path.with_name(f"{self._stem}-{self._boot_id}--session-{normalized}{self._suffix}")

    def _get_session_handler(self, session_id: str) -> logging.FileHandler | None:
        normalized = normalize_chat_session_id(session_id)
        if not normalized:
            return None
        handler = self._session_handlers.get(normalized)
        if handler is None:
            handler = logging.FileHandler(self._session_log_path(normalized), encoding="utf-8")
            if self.formatter is not None:
                handler.setFormatter(self.formatter)
            self._session_handlers[normalized] = handler
        return handler

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._general_handler.emit(record)
            session_id = normalize_chat_session_id(str(getattr(record, "chat_session_id", "")))
            if session_id:
                session_handler = self._get_session_handler(session_id)
                if session_handler is not None:
                    session_handler.emit(record)
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        self._general_handler.flush()
        for handler in self._session_handlers.values():
            handler.flush()

    def close(self) -> None:
        try:
            self._general_handler.close()
            for handler in self._session_handlers.values():
                handler.close()
        finally:
            self._session_handlers.clear()
            super().close()


def create_server_app(host: str, port: int) -> ServerApp:
    config = build_config(host, port)
    if config.mode not in {"", "local"}:
        raise ValueError("Only MODE=local is supported by windows-code-search-mcp")
    return ServerApp(config, [SearchExtension(), VSCodeBridgeExtension(), WindowsDesktopExtension()])


def configure_http_runtime(transport: str, host: str, port: int) -> None:
    if transport != Transport.STREAMABLE_HTTP.value:
        return

    fastmcp.settings.set_setting("host", host)
    fastmcp.settings.set_setting("port", port)
    fastmcp.settings.set_setting("streamable_http_path", "/mcp")
    fastmcp.settings.set_setting("stateless_http", parse_bool(os.getenv("FASTMCP_STATELESS_HTTP"), False))


def configure_process_diagnostics() -> tuple[str, str | None]:
    boot_id = uuid.uuid4().hex[:12]
    set_current_boot_id(boot_id)
    log_dir_text = os.getenv("MCP_LOG_DIR", "").strip()
    runtime_log_text = os.getenv("MCP_RUNTIME_LOG", "").strip()
    root_logger = logging.getLogger()
    configured_level = str(os.getenv("FASTMCP_LOG_LEVEL", "INFO")).upper()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] boot=%(boot_id)s chat_session=%(chat_session_id)s %(name)s: %(message)s")

    has_console_handler = any(
        isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
        for handler in root_logger.handlers
    )
    if not has_console_handler:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    if not any(isinstance(existing, SessionContextFilter) for existing in root_logger.filters):
        root_logger.addFilter(SessionContextFilter())
    for handler in root_logger.handlers:
        if not any(isinstance(existing, SessionContextFilter) for existing in handler.filters):
            handler.addFilter(SessionContextFilter())

    log_path = _build_runtime_log_path(log_dir_text, runtime_log_text, boot_id)
    if log_path is not None:
        file_path_text = str(log_path.resolve())
        has_file_handler = any(
            isinstance(handler, SessionRoutingFileHandler) and str(handler._general_log_path) == file_path_text
            for handler in root_logger.handlers
        )
        if not has_file_handler:
            file_handler = SessionRoutingFileHandler(log_path, _coerce_history_limit())
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

    if root_logger.level in (logging.NOTSET, 0):
        root_logger.setLevel(getattr(logging, configured_level, logging.INFO))

    LOGGER.info("server startup boot_id=%s pid=%s", boot_id, os.getpid())

    def _log_shutdown() -> None:
        LOGGER.info("server shutdown boot_id=%s pid=%s", boot_id, os.getpid())

    def _log_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        LOGGER.error(
            "unhandled exception boot_id=%s pid=%s",
            boot_id,
            os.getpid(),
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    atexit.register(_log_shutdown)
    sys.excepthook = _log_unhandled_exception
    return boot_id, str(log_path) if log_path else None


@click.command()
@click.option(
    "--transport",
    help="The transport layer used by the MCP server.",
    type=click.Choice([Transport.STDIO.value, Transport.SSE.value, Transport.STREAMABLE_HTTP.value]),
    default="stdio",
)
@click.option(
    "--host",
    help="Host to bind the SSE/Streamable HTTP server.",
    default="127.0.0.1",
    type=str,
    show_default=True,
)
@click.option(
    "--port",
    help="Port to bind the SSE/Streamable HTTP server.",
    default=8000,
    type=int,
    show_default=True,
)
def main(transport: str, host: str, port: int) -> None:
    configure_http_runtime(transport, host, port)
    boot_id, runtime_log_path = configure_process_diagnostics()
    app = create_server_app(host, port)
    server = app.build()
    print(f"[INFO] Process ID : {os.getpid()}")
    print(f"[INFO] Boot ID : {boot_id}")
    if runtime_log_path:
        print(f"[INFO] Runtime log : {runtime_log_path}")
    print(f"[INFO] FastMCP log level : {fastmcp.settings.log_level}")
    if transport == Transport.STREAMABLE_HTTP.value:
        print(f"[INFO] Streamable HTTP path : {fastmcp.settings.streamable_http_path}")
        print(f"[INFO] Streamable HTTP stateless : {fastmcp.settings.stateless_http}")
    print("[INFO] Search tools : " + ", ".join(SEARCH_TOOL_NAMES))
    print("[INFO] VS Code tools : " + ", ".join(VSCODE_TOOL_NAMES))
    print(f"[INFO] Auto-index config : {app.config.managed_repositories_path}")
    if app.config.vscode_bridge_enabled:
        print(f"[INFO] VS Code bridge : http://{app.config.vscode_bridge_host}:{app.config.vscode_bridge_port}")

    match transport:
        case Transport.STDIO.value:
            server.run(transport=Transport.STDIO.value, show_banner=False)
        case Transport.SSE.value | Transport.STREAMABLE_HTTP.value:
            server.run(transport=transport, host=host, port=port, show_banner=False)
        case _:
            raise ValueError(f"Invalid transport: {transport}")


if __name__ == "__main__":
    main()
