from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from fastmcp import FastMCP


class PublicServerMixin:
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

