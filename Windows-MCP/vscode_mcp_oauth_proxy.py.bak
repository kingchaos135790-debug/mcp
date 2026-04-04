from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from enum import Enum

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import click
from fastmcp import FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.providers.proxy import ProxyClient
from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider
from windows_mcp.auth import StaticClientOAuthProvider


class Transport(Enum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"

    def __str__(self):
        return self.value


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_list(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = value.replace("\r", "\n").replace(",", "\n")
    return [item.strip() for item in normalized.split("\n") if item.strip()]


@dataclass
class Config:
    upstream_url: str
    oauth_enabled: bool = False
    oauth_base_url: str = ""
    oauth_required_scopes: list[str] = field(default_factory=list)
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_redirect_uris: list[str] = field(default_factory=list)
    oauth_token_endpoint_auth_method: str = "client_secret_post"
    oauth_valid_scopes: list[str] = field(default_factory=list)
    oauth_allow_dynamic_client_registration: bool = False


def _build_config(host: str, port: int) -> Config:
    oauth_base_url = os.getenv("OAUTH_BASE_URL", "").strip()
    if not oauth_base_url:
        oauth_base_url = f"http://{host}:{port}"

    upstream_url = os.getenv("UPSTREAM_MCP_URL", "http://127.0.0.1:3000/mcp").strip()
    if not upstream_url:
        raise ValueError("UPSTREAM_MCP_URL is required")

    return Config(
        upstream_url=upstream_url,
        oauth_enabled=_parse_bool(os.getenv("OAUTH_ENABLED"), False),
        oauth_base_url=oauth_base_url,
        oauth_required_scopes=_parse_list(os.getenv("OAUTH_REQUIRED_SCOPES")),
        oauth_client_id=os.getenv("OAUTH_CLIENT_ID", "").strip(),
        oauth_client_secret=os.getenv("OAUTH_CLIENT_SECRET", "").strip(),
        oauth_redirect_uris=_parse_list(os.getenv("OAUTH_REDIRECT_URIS")),
        oauth_token_endpoint_auth_method=os.getenv(
            "OAUTH_TOKEN_ENDPOINT_AUTH_METHOD",
            "client_secret_post",
        ).strip(),
        oauth_valid_scopes=_parse_list(os.getenv("OAUTH_VALID_SCOPES")),
        oauth_allow_dynamic_client_registration=_parse_bool(
            os.getenv("OAUTH_ALLOW_DYNAMIC_CLIENT_REGISTRATION"),
            False,
        ),
    )


def _build_auth(config: Config):
    if not config.oauth_enabled:
        return None

    if not config.oauth_base_url:
        raise ValueError("OAuth is enabled but OAUTH_BASE_URL is missing")

    if config.oauth_client_id:
        return StaticClientOAuthProvider(
            base_url=config.oauth_base_url,
            pre_registered_client_id=config.oauth_client_id,
            pre_registered_client_secret=config.oauth_client_secret or None,
            pre_registered_redirect_uris=config.oauth_redirect_uris,
            token_endpoint_auth_method=config.oauth_token_endpoint_auth_method,
            allow_dynamic_client_registration=config.oauth_allow_dynamic_client_registration,
            valid_scopes=config.oauth_valid_scopes or config.oauth_required_scopes,
            required_scopes=config.oauth_required_scopes or None,
        )

    return InMemoryOAuthProvider(
        base_url=config.oauth_base_url,
        required_scopes=config.oauth_required_scopes or None,
    )


def _create_proxy_server(config: Config) -> FastMCP:
    backend = StreamableHttpTransport(url=config.upstream_url)
    return FastMCP.as_proxy(
        ProxyClient(backend),
        name="vscode-mcp-oauth-proxy",
        auth=_build_auth(config),
    )


@click.command()
@click.option(
    "--transport",
    help="The transport layer used by the MCP server.",
    type=click.Choice([Transport.STDIO.value, Transport.SSE.value, Transport.STREAMABLE_HTTP.value]),
    default=Transport.STREAMABLE_HTTP.value,
)
@click.option(
    "--host",
    help="Host to bind the server.",
    default="localhost",
    type=str,
    show_default=True,
)
@click.option(
    "--port",
    help="Port to bind the server.",
    default=8000,
    type=int,
    show_default=True,
)
def main(transport: str, host: str, port: int):
    config = _build_config(host, port)
    server = _create_proxy_server(config)

    match transport:
        case Transport.STDIO.value:
            server.run(transport=Transport.STDIO.value, show_banner=False)
        case Transport.SSE.value | Transport.STREAMABLE_HTTP.value:
            server.run(transport=transport, host=host, port=port, show_banner=False)
        case _:
            raise ValueError(f"Invalid transport: {transport}")


if __name__ == "__main__":
    main()
