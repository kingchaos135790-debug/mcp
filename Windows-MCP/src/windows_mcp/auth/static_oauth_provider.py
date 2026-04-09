from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any, Iterable
import json
import logging
import time

from mcp.server.auth.provider import AccessToken, AuthorizationCode, RefreshToken
from typing import Iterable

from mcp.shared.auth import OAuthClientInformationFull

from fastmcp.server.auth.auth import (
    ClientRegistrationOptions,
    RevocationOptions,
)
from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider


def _normalize_scopes(scopes: Iterable[str] | None) -> list[str]:
    return [s.strip() for s in (scopes or []) if s and s.strip()]


class StaticClientOAuthProvider(InMemoryOAuthProvider):
    """
    In-memory OAuth provider with one optional pre-registered static client.

    This is useful for ChatGPT "User-Defined OAuth Client" mode where you want
    the server to accept only a known client_id/client_secret pair and keep
    auth fully server-side.
    """

    def __init__(
        self,
        *,
        base_url: str,
        pre_registered_client_id: str | None = None,
        pre_registered_client_secret: str | None = None,
        pre_registered_redirect_uris: list[str] | None = None,
        token_endpoint_auth_method: str = "client_secret_post",
        allow_dynamic_client_registration: bool = False,
        valid_scopes: list[str] | None = None,
        required_scopes: list[str] | None = None,
        service_documentation_url: str | None = None,
        revocation_options: RevocationOptions | None = None,
    ) -> None:
        valid_scopes = _normalize_scopes(valid_scopes)
        required_scopes = _normalize_scopes(required_scopes)

        client_registration_options = (
            ClientRegistrationOptions(valid_scopes=valid_scopes or None)
            if allow_dynamic_client_registration
            else None
        )

        super().__init__(
            base_url=base_url,
            service_documentation_url=service_documentation_url,
            client_registration_options=client_registration_options,
            revocation_options=revocation_options,
            required_scopes=required_scopes or None,
        )

        self._pre_registered_client_id = (pre_registered_client_id or "").strip()
        self._pre_registered_client_secret = (
            pre_registered_client_secret or ""
        ).strip()
        self._pre_registered_redirect_uris = [
            uri.strip()
            for uri in (pre_registered_redirect_uris or [])
            if uri and uri.strip()
        ]
        self._token_endpoint_auth_method = (
            token_endpoint_auth_method or "client_secret_post"
        ).strip()
        self._allow_dynamic_client_registration = allow_dynamic_client_registration
        self._valid_scopes = valid_scopes

        if self._token_endpoint_auth_method not in {
            "none",
            "client_secret_post",
            "client_secret_basic",
        }:
            raise ValueError(
                "OAUTH_TOKEN_ENDPOINT_AUTH_METHOD must be one of: "
                "none, client_secret_post, client_secret_basic"
            )

        if self._pre_registered_client_id and not self._pre_registered_redirect_uris:
            raise ValueError(
                "Static OAuth client is enabled but no redirect URIs were configured. "
                "Set OAUTH_REDIRECT_URIS."
            )

        if (
            self._pre_registered_client_id
            and self._token_endpoint_auth_method != "none"
            and not self._pre_registered_client_secret
        ):
            raise ValueError(
                "Static OAuth client requires OAUTH_CLIENT_SECRET unless "
                "OAUTH_TOKEN_ENDPOINT_AUTH_METHOD=none"
            )

    def _build_static_client(self) -> OAuthClientInformationFull:
        payload: dict[str, object] = {
            "client_id": self._pre_registered_client_id,
            "redirect_uris": self._pre_registered_redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": self._token_endpoint_auth_method,
            "client_name": "ChatGPT Windows MCP",
        }

        if self._pre_registered_client_secret:
            payload["client_secret"] = self._pre_registered_client_secret

        if self._valid_scopes:
            payload["scope"] = " ".join(self._valid_scopes)

        return OAuthClientInformationFull.model_validate(payload)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        existing = await super().get_client(client_id)
        if existing is not None:
            return existing

        if (
            self._pre_registered_client_id
            and client_id == self._pre_registered_client_id
        ):
            client = self._build_static_client()
            self.clients[client_id] = client
            return client

        return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not self._allow_dynamic_client_registration:
            raise ValueError(
                "Dynamic client registration is disabled on this server."
            )
        await super().register_client(client_info)