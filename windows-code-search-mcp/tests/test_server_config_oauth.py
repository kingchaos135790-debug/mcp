from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import asyncio
import sys
import tempfile
import types
import unittest


bootstrap = types.ModuleType("bootstrap")
sys.modules["bootstrap"] = bootstrap


class _ModelBase:
    def model_dump(self, mode: str = "json"):
        return dict(self.__dict__)

    @classmethod
    def model_validate(cls, value):
        if isinstance(value, cls):
            return value
        return cls(**value)


class AccessToken(_ModelBase):
    def __init__(self, token: str, client_id: str = "windows", scopes: list[str] | None = None, expires_at=None, resource=None):
        self.token = token
        self.client_id = client_id
        self.scopes = list(scopes or ["mcp:access"])
        self.expires_at = expires_at
        self.resource = resource
        self.access_token = token


class RefreshToken(_ModelBase):
    def __init__(self, token: str, client_id: str = "windows", scopes: list[str] | None = None, expires_at=None):
        self.token = token
        self.client_id = client_id
        self.scopes = list(scopes or ["mcp:access", "offline_access"])
        self.expires_at = expires_at
        self.refresh_token = token


class AuthorizationCode(_ModelBase):
    def __init__(self, code: str, client_id: str = "windows"):
        self.code = code
        self.client_id = client_id


class OAuthClientInformationFull(_ModelBase):
    def __init__(self, client_id: str, **kwargs):
        self.client_id = client_id
        for key, value in kwargs.items():
            setattr(self, key, value)


provider_module = types.ModuleType("mcp.server.auth.provider")
provider_module.AccessToken = AccessToken
provider_module.AuthorizationCode = AuthorizationCode
provider_module.RefreshToken = RefreshToken
sys.modules["mcp.server.auth.provider"] = provider_module

shared_auth_module = types.ModuleType("mcp.shared.auth")
shared_auth_module.OAuthClientInformationFull = OAuthClientInformationFull
sys.modules["mcp.shared.auth"] = shared_auth_module


class InMemoryOAuthProvider:
    def __init__(self, **kwargs):
        self.clients = {}
        self.auth_codes = {}
        self.access_tokens = {}
        self.refresh_tokens = {}
        self._access_to_refresh_map = {}
        self._refresh_to_access_map = {}
        self._next_code = 0
        self._next_access = 0
        self._next_refresh = 0

    async def register_client(self, client_info):
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client, params):
        self._next_code += 1
        code = f"code-{self._next_code}"
        self.auth_codes[code] = AuthorizationCode(code=code, client_id=client.client_id)
        return getattr(params, "redirect_uri", "https://example.test/callback")

    async def load_authorization_code(self, client, authorization_code):
        return self.auth_codes.get(authorization_code)

    async def exchange_authorization_code(self, client, authorization_code):
        self.auth_codes.pop(authorization_code, None)
        self._next_access += 1
        self._next_refresh += 1
        access_value = f"access-{self._next_access}"
        refresh_value = f"refresh-{self._next_refresh}"
        access_token = AccessToken(token=access_value, client_id=client.client_id)
        refresh_token = RefreshToken(token=refresh_value, client_id=client.client_id)
        self.access_tokens[access_value] = access_token
        self.refresh_tokens[refresh_value] = refresh_token
        self._access_to_refresh_map[access_value] = refresh_value
        self._refresh_to_access_map[refresh_value] = access_value
        return SimpleNamespace(access_token=access_value, refresh_token=refresh_value)

    async def load_refresh_token(self, client, refresh_token):
        return self.refresh_tokens.get(refresh_token)

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        self._next_access += 1
        access_value = f"access-{self._next_access}"
        access_token = AccessToken(token=access_value, client_id=client.client_id, scopes=scopes)
        self.access_tokens[access_value] = access_token
        self._access_to_refresh_map[access_value] = refresh_token
        self._refresh_to_access_map[refresh_token] = access_value
        return SimpleNamespace(access_token=access_value, refresh_token=refresh_token)

    async def load_access_token(self, token):
        return self.access_tokens.get(token)

    async def revoke_token(self, token):
        token_value = str(token)
        self.access_tokens.pop(token_value, None)
        self.refresh_tokens.pop(token_value, None)


in_memory_module = types.ModuleType("fastmcp.server.auth.providers.in_memory")
in_memory_module.InMemoryOAuthProvider = InMemoryOAuthProvider
sys.modules["fastmcp.server.auth.providers.in_memory"] = in_memory_module


class StaticClientOAuthProvider(InMemoryOAuthProvider):
    async def get_client(self, client_id: str):
        return self.clients.get(client_id)


windows_auth_module = types.ModuleType("windows_mcp.auth")
windows_auth_module.StaticClientOAuthProvider = StaticClientOAuthProvider
sys.modules["windows_mcp.auth"] = windows_auth_module


import session_context
import server_config


class PersistentOAuthProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.storage_path = Path(self.tempdir.name) / "oauth-state.json"
        session_context.set_current_chat_session_id("")
        session_context.set_current_access_token("")
        self.provider = server_config.PersistentInMemoryOAuthProvider(storage_path=self.storage_path)
        self.client = OAuthClientInformationFull(client_id="windows")
        asyncio.run(self.provider.register_client(self.client))

    def test_exchange_authorization_code_uses_saved_auth_code_session_when_context_is_missing(self) -> None:
        session_context.set_current_chat_session_id("chat-mid-reauth")
        asyncio.run(self.provider.authorize(self.client, SimpleNamespace()))

        auth_code = next(iter(self.provider.auth_codes))
        self.assertEqual(self.provider._auth_code_session_map[auth_code], "chat-mid-reauth")

        session_context.set_current_chat_session_id("")
        token = asyncio.run(self.provider.exchange_authorization_code(self.client, auth_code))

        self.assertEqual(
            self.provider.resolve_chat_session_for_access_token(token.access_token),
            "chat-mid-reauth",
        )
        self.assertNotIn(auth_code, self.provider._auth_code_session_map)

    def test_load_access_token_rebinds_missing_session_maps_from_current_request_context(self) -> None:
        session_context.set_current_chat_session_id("chat-continue")
        asyncio.run(self.provider.authorize(self.client, SimpleNamespace()))
        auth_code = next(iter(self.provider.auth_codes))
        token = asyncio.run(self.provider.exchange_authorization_code(self.client, auth_code))

        refresh_token = self.provider._access_to_refresh_map[token.access_token]
        self.provider._access_token_session_map.clear()
        self.provider._refresh_token_session_map.clear()
        self.provider._persist_state()

        session_context.set_current_chat_session_id("chat-continue")
        asyncio.run(self.provider.load_access_token(token.access_token))

        self.assertEqual(
            self.provider._access_token_session_map[token.access_token],
            "chat-continue",
        )
        self.assertEqual(
            self.provider._refresh_token_session_map[refresh_token],
            "chat-continue",
        )


if __name__ == "__main__":
    unittest.main()
