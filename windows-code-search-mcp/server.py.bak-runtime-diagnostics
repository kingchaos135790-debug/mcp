from __future__ import annotations

import click
import os

import fastmcp

import bootstrap  # noqa: F401

from server_app import ServerApp
from server_config import SEARCH_TOOL_NAMES, Transport, VSCODE_TOOL_NAMES, build_config
from server_extensions import SearchExtension, VSCodeBridgeExtension, WindowsDesktopExtension


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
    fastmcp.settings.set_setting("stateless_http", True)


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
    app = create_server_app(host, port)
    server = app.build()
    print(f"[INFO] Process ID : {os.getpid()}")
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
