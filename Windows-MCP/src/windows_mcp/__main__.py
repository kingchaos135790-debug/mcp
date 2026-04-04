from windows_mcp.analytics import PostHogAnalytics
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.providers.proxy import ProxyClient
from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider
from windows_mcp.desktop.service import Desktop, Size
from windows_mcp.watchdog.service import WatchDog
from contextlib import asynccontextmanager
from windows_mcp.auth import AuthClient, StaticClientOAuthProvider
from fastmcp import FastMCP
from windows_mcp.tools import register_all
from dataclasses import dataclass, field
from textwrap import dedent
from enum import Enum
import logging
import asyncio
import click
import os


logger = logging.getLogger(__name__)

desktop: Desktop | None = None
watchdog: WatchDog | None = None
analytics: PostHogAnalytics | None = None
screen_size: Size | None = None

instructions = dedent("""
Windows MCP server provides tools to interact directly with the Windows desktop,
thus enabling to operate the desktop on the user's behalf.
""")


@asynccontextmanager
async def lifespan(app: FastMCP):
    """Runs initialization code before the server starts and cleanup code after it shuts down."""
    global desktop, watchdog, analytics, screen_size

    if os.getenv("ANONYMIZED_TELEMETRY", "true").lower() != "false":
        analytics = PostHogAnalytics()
    desktop = Desktop()
    watchdog = WatchDog()
    screen_size = desktop.get_screen_size()
    watchdog.set_focus_callback(desktop.tree.on_focus_change)

    try:
        watchdog.start()
        await asyncio.sleep(1)
        yield
    finally:
        if watchdog:
            watchdog.stop()
        if analytics:
            await analytics.close()


@dataclass
class Config:
    mode: str
    sandbox_id: str = field(default="")
    api_key: str = field(default="")
    oauth_enabled: bool = field(default=False)
    oauth_base_url: str = field(default="")
    oauth_required_scopes: list[str] = field(default_factory=list)

    oauth_client_id: str = field(default="")
    oauth_client_secret: str = field(default="")
    oauth_redirect_uris: list[str] = field(default_factory=list)
    oauth_token_endpoint_auth_method: str = field(default="client_secret_post")
    oauth_valid_scopes: list[str] = field(default_factory=list)
    oauth_allow_dynamic_client_registration: bool = field(default=False)


class Transport(Enum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"

    def __str__(self):
        return self.value


class Mode(Enum):
    LOCAL = "local"
    REMOTE = "remote"

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


def _build_config(host: str, port: int) -> Config:
    oauth_base_url = os.getenv("OAUTH_BASE_URL", "").strip()
    if not oauth_base_url:
        oauth_base_url = f"http://{host}:{port}"

    return Config(
        mode=os.getenv("MODE", Mode.LOCAL.value).lower(),
        sandbox_id=os.getenv("SANDBOX_ID", ""),
        api_key=os.getenv("API_KEY", ""),
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

    logger.info(
        "Starting with built-in OAuth protection enabled at base URL %s",
        config.oauth_base_url,
    )

    # Static pre-registered client mode
    if config.oauth_client_id:
        logger.info(
            "Using static OAuth client registration for client_id=%s",
            config.oauth_client_id,
        )
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

    # Pure in-memory DCR mode
    return InMemoryOAuthProvider(
        base_url=config.oauth_base_url,
        required_scopes=config.oauth_required_scopes or None,
    )


def _create_local_server(config: Config) -> FastMCP:
    mcp = FastMCP(
        name="windows-mcp",
        instructions=instructions,
        lifespan=lifespan,
        auth=_build_auth(config),
    )
    register_all(mcp, get_desktop=lambda: desktop, get_analytics=lambda: analytics)
    return mcp


def _create_remote_proxy_server(config: Config) -> FastMCP:
    if not config.sandbox_id:
        raise ValueError("SANDBOX_ID is required for MODE: remote")
    if not config.api_key:
        raise ValueError("API_KEY is required for MODE: remote")

    client = AuthClient(api_key=config.api_key, sandbox_id=config.sandbox_id)
    client.authenticate()
    backend = StreamableHttpTransport(url=client.proxy_url, headers=client.proxy_headers)
    return FastMCP.as_proxy(
        ProxyClient(backend),
        name="windows-mcp",
        auth=_build_auth(config),
    )


# Backward-compatible re-exports for existing tests
from windows_mcp.tools.snapshot import state_tool, screenshot_tool  # noqa: E402, F401


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
    default="localhost",
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
def main(transport, host, port):
    config = _build_config(host, port)

    if config.mode == Mode.LOCAL.value:
        server = _create_local_server(config)
    elif config.mode == Mode.REMOTE.value:
        server = _create_remote_proxy_server(config)
    else:
        raise ValueError(f"Invalid mode: {config.mode}")

    match transport:
        case Transport.STDIO.value:
            server.run(transport=Transport.STDIO.value, show_banner=False)
        case Transport.SSE.value | Transport.STREAMABLE_HTTP.value:
            server.run(transport=transport, host=host, port=port, show_banner=False)
        case _:
            raise ValueError(f"Invalid transport: {transport}")


if __name__ == "__main__":
    main()