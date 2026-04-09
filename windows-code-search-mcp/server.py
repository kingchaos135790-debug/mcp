from __future__ import annotations

import atexit
import click
import logging
import os
import sys
import uuid
from pathlib import Path

import fastmcp

import bootstrap  # noqa: F401

from server_app import ServerApp
from server_config import SEARCH_TOOL_NAMES, Transport, VSCODE_TOOL_NAMES, build_config
from server_extensions import SearchExtension, VSCodeBridgeExtension, WindowsDesktopExtension

LOGGER = logging.getLogger(__name__)


def create_server_app(host: str, port: int) -> ServerApp:
    config = build_config(host, port)
    if config.mode not in {'', 'local'}:
        raise ValueError('Only MODE=local is supported by windows-code-search-mcp')
    return ServerApp(config, [SearchExtension(), VSCodeBridgeExtension(), WindowsDesktopExtension()])


def configure_http_runtime(transport: str, host: str, port: int) -> None:
    if transport != Transport.STREAMABLE_HTTP.value:
        return

    fastmcp.settings.set_setting('host', host)
    fastmcp.settings.set_setting('port', port)
    fastmcp.settings.set_setting('streamable_http_path', '/mcp')
    fastmcp.settings.set_setting('stateless_http', True)


def configure_process_diagnostics() -> tuple[str, str | None]:
    boot_id = uuid.uuid4().hex[:12]
    log_dir_text = os.getenv('MCP_LOG_DIR', '').strip()
    if not log_dir_text:
        return boot_id, None

    log_dir = Path(log_dir_text).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / 'windows-code-search-mcp-runtime.log'
    root_logger = logging.getLogger()
    file_path_text = str(log_path.resolve())
    has_file_handler = any(
        isinstance(handler, logging.FileHandler) and getattr(handler, 'baseFilename', '') == file_path_text
        for handler in root_logger.handlers
    )
    if not has_file_handler:
        handler = logging.FileHandler(log_path, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
        root_logger.addHandler(handler)
    configured_level = str(os.getenv('FASTMCP_LOG_LEVEL', 'INFO')).upper()
    if root_logger.level in (logging.NOTSET, 0):
        root_logger.setLevel(getattr(logging, configured_level, logging.INFO))

    LOGGER.info('server startup boot_id=%s pid=%s', boot_id, os.getpid())

    def _log_shutdown() -> None:
        LOGGER.info('server shutdown boot_id=%s pid=%s', boot_id, os.getpid())

    def _log_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        LOGGER.error(
            'unhandled exception boot_id=%s pid=%s',
            boot_id,
            os.getpid(),
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    atexit.register(_log_shutdown)
    sys.excepthook = _log_unhandled_exception
    return boot_id, str(log_path)


@click.command()
@click.option(
    '--transport',
    help='The transport layer used by the MCP server.',
    type=click.Choice([Transport.STDIO.value, Transport.SSE.value, Transport.STREAMABLE_HTTP.value]),
    default='stdio',
)
@click.option(
    '--host',
    help='Host to bind the SSE/Streamable HTTP server.',
    default='127.0.0.1',
    type=str,
    show_default=True,
)
@click.option(
    '--port',
    help='Port to bind the SSE/Streamable HTTP server.',
    default=8000,
    type=int,
    show_default=True,
)
def main(transport: str, host: str, port: int) -> None:
    configure_http_runtime(transport, host, port)
    boot_id, runtime_log_path = configure_process_diagnostics()
    app = create_server_app(host, port)
    server = app.build()
    print(f'[INFO] Process ID : {os.getpid()}')
    print(f'[INFO] Boot ID : {boot_id}')
    if runtime_log_path:
        print(f'[INFO] Runtime log : {runtime_log_path}')
    print(f'[INFO] FastMCP log level : {fastmcp.settings.log_level}')
    if transport == Transport.STREAMABLE_HTTP.value:
        print(f'[INFO] Streamable HTTP path : {fastmcp.settings.streamable_http_path}')
        print(f'[INFO] Streamable HTTP stateless : {fastmcp.settings.stateless_http}')
    print('[INFO] Search tools : ' + ', '.join(SEARCH_TOOL_NAMES))
    print('[INFO] VS Code tools : ' + ', '.join(VSCODE_TOOL_NAMES))
    print(f'[INFO] Auto-index config : {app.config.managed_repositories_path}')
    if app.config.vscode_bridge_enabled:
        print(f'[INFO] VS Code bridge : http://{app.config.vscode_bridge_host}:{app.config.vscode_bridge_port}')

    match transport:
        case Transport.STDIO.value:
            server.run(transport=Transport.STDIO.value, show_banner=False)
        case Transport.SSE.value | Transport.STREAMABLE_HTTP.value:
            server.run(transport=transport, host=host, port=port, show_banner=False)
        case _:
            raise ValueError(f'Invalid transport: {transport}')


if __name__ == '__main__':
    main()
