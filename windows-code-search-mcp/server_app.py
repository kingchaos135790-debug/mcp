from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import logging
import os

import bootstrap  # noqa: F401

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from windows_mcp.analytics import PostHogAnalytics
from windows_mcp.desktop.service import Desktop
from windows_mcp.watchdog.service import WatchDog

from server_config import Config, build_auth
from server_extensions import ServerExtension
from server_runtime import RepositoryAutoIndexer, SearchEngineBridge, ServerContext


logger = logging.getLogger(__name__)


class ServerApp:
    def __init__(self, config: Config, extensions: list[ServerExtension]) -> None:
        self.config = config
        self.context = ServerContext(config=config, engine=SearchEngineBridge(config))
        self.extensions = extensions

    def build(self) -> FastMCP:
        mcp = FastMCP(
            name="windows-code-search-mcp",
            lifespan=self.lifespan,
            auth=build_auth(self.config),
        )
        for extension in self.extensions:
            extension.register(mcp, self.context)
        self._register_discovery_routes(mcp)
        return mcp

    def _oauth_metadata(self) -> dict[str, object]:
        base_url = self.config.oauth_base_url.rstrip("/")
        token_auth_method = self.config.oauth_token_endpoint_auth_method or "client_secret_post"
        scopes = self.config.oauth_valid_scopes or self.config.oauth_required_scopes
        metadata: dict[str, object] = {
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/authorize",
            "token_endpoint": f"{base_url}/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [token_auth_method],
        }
        if scopes:
            metadata["scopes_supported"] = scopes
        if self.config.oauth_allow_dynamic_client_registration:
            metadata["registration_endpoint"] = f"{base_url}/register"
        return metadata

    def _register_discovery_routes(self, mcp: FastMCP) -> None:
        if not self.config.oauth_enabled:
            return

        metadata = self._oauth_metadata()

        @mcp.custom_route("/.well-known/openid-configuration", methods=["GET"], include_in_schema=False)
        async def openid_configuration(_: Request) -> Response:
            return JSONResponse(metadata)

        @mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"], include_in_schema=False)
        async def oauth_authorization_server(_: Request) -> Response:
            return JSONResponse(metadata)

    @asynccontextmanager
    async def lifespan(self, app: FastMCP):
        await self._start_core_services()
        try:
            for extension in self.extensions:
                await extension.start(self.context)
            yield
        finally:
            for extension in reversed(self.extensions):
                await extension.stop(self.context)
            await self._stop_core_services()

    async def _start_core_services(self) -> None:
        if os.getenv("ANONYMIZED_TELEMETRY", "true").lower() != "false":
            self.context.analytics = PostHogAnalytics()

        self.context.desktop = Desktop()
        self.context.watchdog = WatchDog()
        self.context.watchdog.set_focus_callback(self.context.desktop.tree.on_focus_change)
        self.context.auto_indexer = RepositoryAutoIndexer(self.config, self.context.engine)

        self.context.watchdog.start()
        await asyncio.sleep(1)
        await self.context.auto_indexer.start()
        await self.context.auto_indexer.log_launch_status()

    async def _stop_core_services(self) -> None:
        if self.context.auto_indexer is not None:
            await self.context.auto_indexer.stop()
            self.context.auto_indexer = None
        if self.context.watchdog is not None:
            self.context.watchdog.stop()
            self.context.watchdog = None
        if self.context.analytics is not None:
            await self.context.analytics.close()
            self.context.analytics = None
        self.context.desktop = None
