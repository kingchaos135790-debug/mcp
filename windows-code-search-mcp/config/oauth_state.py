from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import RLock

from mcp.server.auth.provider import AccessToken, AuthorizationCode, RefreshToken
from mcp.shared.auth import OAuthClientInformationFull

from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider
from windows_mcp.auth import StaticClientOAuthProvider
from session_context import (
    get_current_boot_id,
    get_current_chat_session_id,
    normalize_chat_session_id,
    register_token_session_binder,
    set_current_access_token,
    set_current_chat_session_id,
)

from .models import Config

LOGGER = logging.getLogger(__name__)


class _PersistentOAuthStateMixin:
    def _init_persistence(self, storage_path: str | Path, max_tokens: int = 0) -> None:
        self._storage_path = Path(storage_path).expanduser().resolve()
        self._state_lock = RLock()
        self._run_count = 0
        self._last_boot_id = ""
        self._max_persisted_tokens = max(
            0,
            int(max_tokens or os.getenv("OAUTH_STATE_MAX_TOKENS", "0") or 0),
        )
        self._access_token_session_map: dict[str, str] = {}
        self._refresh_token_session_map: dict[str, str] = {}
        self._auth_code_session_map: dict[str, str] = {}
        self._auth_code_resource_map: dict[str, str] = {}
        self._load_state()
        current_boot_id = get_current_boot_id()
        if current_boot_id and current_boot_id != self._last_boot_id:
            self._run_count += 1
            self._last_boot_id = current_boot_id
        register_token_session_binder(self.bind_access_token_to_chat_session)
        self._persist_state()

    def _serialize_models(self, values: dict[str, object]) -> dict[str, object]:
        return {
            key: value.model_dump(mode="json")
            for key, value in values.items()
        }

    def _deserialize_models(self, values: dict[str, object], model_cls):
        return {
            key: model_cls.model_validate(value)
            for key, value in values.items()
        }

    def _drop_token_pair(self, access_token: str, *, reason: str = "pruned") -> bool:
        access_token_value = str(access_token or "").strip()
        if not access_token_value:
            return False
        had_session = self._access_token_session_map.pop(access_token_value, None)
        removed = self.access_tokens.pop(access_token_value, None) is not None
        linked_refresh = self._access_to_refresh_map.pop(access_token_value, "")
        if linked_refresh:
            self.refresh_tokens.pop(linked_refresh, None)
            self._refresh_token_session_map.pop(linked_refresh, None)
            self._refresh_to_access_map.pop(linked_refresh, None)
            removed = True
        if removed:
            LOGGER.info(
                "OAuth binding dropped: access_token=...%s session=%s refresh=%s reason=%s",
                access_token_value[-8:] if len(access_token_value) >= 8 else access_token_value,
                had_session or "(none)",
                bool(linked_refresh),
                reason,
            )
        return removed

    def _enforce_max_token_count(self) -> None:
        if self._max_persisted_tokens <= 0:
            return
        overflow = len(self.access_tokens) - self._max_persisted_tokens
        if overflow > 0:
            LOGGER.info(
                "OAuth token pruning: %d access tokens exceed cap of %d, pruning %d (prefer unbound tokens)",
                len(self.access_tokens),
                self._max_persisted_tokens,
                overflow,
            )
        while len(self.access_tokens) > self._max_persisted_tokens:
            access_tokens = list(self.access_tokens)
            if not access_tokens:
                break
            candidate_access_token = next(
                (
                    token
                    for token in access_tokens
                    if not self.resolve_chat_session_for_access_token(token)
                ),
                access_tokens[0],
            )
            if not candidate_access_token:
                break
            if not self._drop_token_pair(candidate_access_token, reason="max_token_count"):
                break
        self._prune_session_maps()

    def _persist_state(self) -> None:
        self._enforce_max_token_count()
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._storage_path.with_suffix(self._storage_path.suffix + ".tmp")
        payload = {
            "version": 2,
            "run_count": int(self._run_count),
            "last_boot_id": self._last_boot_id,
            "clients": self._serialize_models(self.clients),
            "auth_codes": self._serialize_models(self.auth_codes),
            "access_tokens": self._serialize_models(self.access_tokens),
            "refresh_tokens": self._serialize_models(self.refresh_tokens),
            "access_to_refresh_map": dict(self._access_to_refresh_map),
            "refresh_to_access_map": dict(self._refresh_to_access_map),
            "access_token_session_map": dict(self._access_token_session_map),
            "refresh_token_session_map": dict(self._refresh_token_session_map),
            "auth_code_session_map": dict(self._auth_code_session_map),
            "auth_code_resource_map": dict(self._auth_code_resource_map),
        }
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._storage_path)

    def _load_state(self) -> None:
        self._run_count = 0
        self._last_boot_id = ""
        self._access_token_session_map = {}
        self._refresh_token_session_map = {}
        self._auth_code_session_map = {}
        if not self._storage_path.exists():
            return
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            self.clients = self._deserialize_models(payload.get("clients", {}), OAuthClientInformationFull)
            self.auth_codes = self._deserialize_models(payload.get("auth_codes", {}), AuthorizationCode)
            self.access_tokens = self._deserialize_models(payload.get("access_tokens", {}), AccessToken)
            self.refresh_tokens = self._deserialize_models(payload.get("refresh_tokens", {}), RefreshToken)
            self._access_to_refresh_map = {
                str(k): str(v)
                for k, v in payload.get("access_to_refresh_map", {}).items()
            }
            self._refresh_to_access_map = {
                str(k): str(v)
                for k, v in payload.get("refresh_to_access_map", {}).items()
            }
            self._access_token_session_map = {
                str(k): normalize_chat_session_id(str(v))
                for k, v in payload.get("access_token_session_map", {}).items()
                if normalize_chat_session_id(str(v))
            }
            self._refresh_token_session_map = {
                str(k): normalize_chat_session_id(str(v))
                for k, v in payload.get("refresh_token_session_map", {}).items()
                if normalize_chat_session_id(str(v))
            }
            self._auth_code_session_map = {
                str(k): normalize_chat_session_id(str(v))
                for k, v in payload.get("auth_code_session_map", {}).items()
                if normalize_chat_session_id(str(v))
            }
            self._run_count = int(payload.get("run_count", 0) or 0)
            self._last_boot_id = str(payload.get("last_boot_id", "") or "").strip()
            self._auth_code_resource_map = {
                str(k): str(v)
                for k, v in payload.get("auth_code_resource_map", {}).items()
                if v
            }
        except Exception as exc:
            LOGGER.warning("Failed to load OAuth state from %s: %s", self._storage_path, exc)

    def _prune_session_maps(self) -> None:
        pruned_access = {
            token: session_id
            for token, session_id in self._access_token_session_map.items()
            if token not in self.access_tokens or not session_id
        }
        pruned_refresh = {
            token: session_id
            for token, session_id in self._refresh_token_session_map.items()
            if token not in self.refresh_tokens or not session_id
        }
        pruned_auth_codes = {
            code: session_id
            for code, session_id in self._auth_code_session_map.items()
            if code not in self.auth_codes or not session_id
        }
        pruned_resources = {
            code: resource
            for code, resource in self._auth_code_resource_map.items()
            if code not in self.auth_codes or not resource
        }
        for token, session_id in pruned_access.items():
            LOGGER.info(
                "OAuth binding pruned: access_token=...%s session=%s reason=token_evicted_or_session_empty",
                token[-8:] if len(token) >= 8 else token,
                session_id or "(none)",
            )
        for token, session_id in pruned_refresh.items():
            LOGGER.info(
                "OAuth binding pruned: refresh_token=...%s session=%s reason=token_evicted_or_session_empty",
                token[-8:] if len(token) >= 8 else token,
                session_id or "(none)",
            )
        for code, resource in pruned_resources.items():
            LOGGER.debug(
                "OAuth resource binding pruned: auth_code=...%s resource=%s reason=code_consumed_or_missing",
                code[-8:] if len(code) >= 8 else code,
                resource,
            )
        self._access_token_session_map = {
            token: session_id
            for token, session_id in self._access_token_session_map.items()
            if token in self.access_tokens and session_id
        }
        self._refresh_token_session_map = {
            token: session_id
            for token, session_id in self._refresh_token_session_map.items()
            if token in self.refresh_tokens and session_id
        }
        self._auth_code_session_map = {
            code: session_id
            for code, session_id in self._auth_code_session_map.items()
            if code in self.auth_codes and session_id
        }
        self._auth_code_resource_map = {
            code: resource
            for code, resource in self._auth_code_resource_map.items()
            if code in self.auth_codes and resource
        }

    def _record_token_session_ownership(
        self,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
        session_id: str | None = None,
    ) -> str:
        normalized_session_id = normalize_chat_session_id(session_id)
        if not normalized_session_id:
            return ""

        access_token_value = str(access_token or "").strip()
        refresh_token_value = str(refresh_token or "").strip()
        changed = False

        if access_token_value:
            old_session = self._access_token_session_map.get(access_token_value)
            if old_session != normalized_session_id:
                self._access_token_session_map[access_token_value] = normalized_session_id
                LOGGER.info(
                    "OAuth binding created: access_token=...%s -> session=%s (was=%s)",
                    access_token_value[-8:] if len(access_token_value) >= 8 else access_token_value,
                    normalized_session_id,
                    old_session or "(none)",
                )
                changed = True
            linked_refresh = self._access_to_refresh_map.get(access_token_value)
            if linked_refresh and self._refresh_token_session_map.get(linked_refresh) != normalized_session_id:
                self._refresh_token_session_map[linked_refresh] = normalized_session_id
                changed = True

        if refresh_token_value:
            old_session = self._refresh_token_session_map.get(refresh_token_value)
            if old_session != normalized_session_id:
                self._refresh_token_session_map[refresh_token_value] = normalized_session_id
                LOGGER.info(
                    "OAuth binding created: refresh_token=...%s -> session=%s (was=%s)",
                    refresh_token_value[-8:] if len(refresh_token_value) >= 8 else refresh_token_value,
                    normalized_session_id,
                    old_session or "(none)",
                )
                changed = True
            linked_access = self._refresh_to_access_map.get(refresh_token_value)
            if linked_access and self._access_token_session_map.get(linked_access) != normalized_session_id:
                self._access_token_session_map[linked_access] = normalized_session_id
                changed = True

        if changed:
            self._persist_state()
        return normalized_session_id

    def _record_auth_code_session_ownership(self, authorization_code: str | None, session_id: str | None) -> str:
        normalized_session_id = normalize_chat_session_id(session_id)
        authorization_code_value = str(authorization_code or "").strip()
        if not normalized_session_id or not authorization_code_value:
            return ""

        if self._auth_code_session_map.get(authorization_code_value) != normalized_session_id:
            self._auth_code_session_map[authorization_code_value] = normalized_session_id
            self._persist_state()
        return normalized_session_id

    def bind_access_token_to_chat_session(self, access_token: str, session_id: str) -> None:
        self._record_token_session_ownership(
            access_token=str(access_token),
            refresh_token=self._access_to_refresh_map.get(str(access_token), ""),
            session_id=session_id,
        )

    def resolve_chat_session_for_access_token(self, access_token: str | None) -> str:
        access_token_value = str(access_token or "").strip()
        if not access_token_value:
            return ""
        direct = normalize_chat_session_id(self._access_token_session_map.get(access_token_value, ""))
        if direct:
            return direct
        refresh_token = self._access_to_refresh_map.get(access_token_value, "")
        if not refresh_token:
            return ""
        rebound_session_id = normalize_chat_session_id(self._refresh_token_session_map.get(refresh_token, ""))
        if rebound_session_id:
            self._access_token_session_map[access_token_value] = rebound_session_id
            LOGGER.info(
                "OAuth binding recovered: access_token=...%s -> session=%s (from refresh_token)",
                access_token_value[-8:] if len(access_token_value) >= 8 else access_token_value,
                rebound_session_id,
            )
            self._persist_state()
        return rebound_session_id

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await super().register_client(client_info)
        self._persist_state()

    async def authorize(self, client: OAuthClientInformationFull, params):
        existing_codes = set(self.auth_codes)
        resource = str(getattr(params, "resource", None) or "").strip()
        redirect_uri = await super().authorize(client, params)
        session_id = get_current_chat_session_id()
        for authorization_code in self.auth_codes:
            if authorization_code not in existing_codes:
                LOGGER.info(
                    "OAuth authorize: new auth_code issued, resource=%s session=%s",
                    resource or "(none)",
                    session_id or "(none)",
                )
                if session_id:
                    self._record_auth_code_session_ownership(authorization_code, session_id)
                if resource:
                    self._auth_code_resource_map[authorization_code] = resource
        self._persist_state()
        return redirect_uri

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str):
        had_code = authorization_code in self.auth_codes
        result = await super().load_authorization_code(client, authorization_code)
        if had_code and authorization_code not in self.auth_codes:
            self._auth_code_session_map.pop(str(authorization_code), None)
            self._persist_state()
        return result

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code):
        code_str = getattr(authorization_code, "code", None) or str(authorization_code or "")
        code_str = str(code_str).strip()
        resource = self._auth_code_resource_map.pop(code_str, "")
        token = await super().exchange_authorization_code(client, authorization_code)
        access_token_str = str(getattr(token, "access_token", "") or "")
        if resource and access_token_str:
            self._stamp_resource_on_access_token(access_token_str, resource)
            LOGGER.info(
                "OAuth resource stamped on code exchange: access_token=...%s resource=%s",
                access_token_str[-8:] if len(access_token_str) >= 8 else access_token_str,
                resource,
            )
        session_id = (
            get_current_chat_session_id()
            or normalize_chat_session_id(self._auth_code_session_map.pop(code_str, ""))
        )
        LOGGER.info(
            "OAuth code exchange: access_token=...%s session=%s",
            access_token_str[-8:] if len(access_token_str) >= 8 else access_token_str,
            session_id or "(none)",
        )
        self._record_token_session_ownership(
            access_token=access_token_str,
            refresh_token=getattr(token, "refresh_token", ""),
            session_id=session_id,
        )
        self._persist_state()
        return token

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str):
        had_token = refresh_token in self.refresh_tokens
        result = await super().load_refresh_token(client, refresh_token)
        if had_token and refresh_token not in self.refresh_tokens:
            self._persist_state()
        return result

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token, scopes: list[str]):
        refresh_token_str = getattr(refresh_token, "token", None) or str(refresh_token or "")
        refresh_token_str = str(refresh_token_str).strip()
        linked_access = self._refresh_to_access_map.get(refresh_token_str, "")
        resource = ""
        if linked_access:
            old_token_obj = self.access_tokens.get(linked_access)
            resource = str(getattr(old_token_obj, "resource", None) or "").strip()
        token = await super().exchange_refresh_token(client, refresh_token, scopes)
        access_token_str = str(getattr(token, "access_token", "") or "")
        if resource and access_token_str:
            self._stamp_resource_on_access_token(access_token_str, resource)
            LOGGER.info(
                "OAuth resource propagated on refresh: access_token=...%s resource=%s",
                access_token_str[-8:] if len(access_token_str) >= 8 else access_token_str,
                resource,
            )
        session_id = (
            get_current_chat_session_id()
            or normalize_chat_session_id(self._refresh_token_session_map.get(refresh_token_str, ""))
        )
        LOGGER.info(
            "OAuth refresh exchange: access_token=...%s session=%s",
            access_token_str[-8:] if len(access_token_str) >= 8 else access_token_str,
            session_id or "(none)",
        )
        self._record_token_session_ownership(
            access_token=access_token_str,
            refresh_token=getattr(token, "refresh_token", "") or refresh_token_str,
            session_id=session_id,
        )
        self._persist_state()
        return token

    def _stamp_resource_on_access_token(self, access_token_str: str, resource: str) -> None:
        token_obj = self.access_tokens.get(access_token_str)
        if token_obj is None or not resource:
            return
        try:
            token_obj.resource = resource  # type: ignore[assignment]
        except Exception:
            try:
                self.access_tokens[access_token_str] = token_obj.model_copy(update={"resource": resource})
            except Exception:
                LOGGER.warning("Could not stamp resource on access token %s", access_token_str[-8:])

    async def load_access_token(self, token: str):  # type: ignore[override]
        had_token = token in self.access_tokens
        request_session_id = get_current_chat_session_id()
        result = await super().load_access_token(token)
        set_current_access_token(token)
        session_id = self.resolve_chat_session_for_access_token(token)
        if not session_id and request_session_id:
            linked_refresh = self._access_to_refresh_map.get(str(token), "")
            session_id = self._record_token_session_ownership(
                access_token=str(token),
                refresh_token=linked_refresh,
                session_id=request_session_id,
            )
            if session_id:
                LOGGER.info(
                    "Recovered missing OAuth session binding for access token during request continuation"
                )
        if session_id:
            set_current_chat_session_id(session_id)
        if had_token and token not in self.access_tokens:
            LOGGER.info(
                "OAuth binding loss: access_token=...%s evicted during load_access_token",
                token[-8:] if len(token) >= 8 else token,
            )
            self._prune_session_maps()
            self._persist_state()
        return result

    async def revoke_token(self, token) -> None:
        token_value = str(token)
        had_access_session = self._access_token_session_map.get(token_value)
        had_refresh_session = self._refresh_token_session_map.get(token_value)
        await super().revoke_token(token)
        self._access_token_session_map.pop(token_value, None)
        self._refresh_token_session_map.pop(token_value, None)
        linked_refresh = self._access_to_refresh_map.get(token_value)
        if linked_refresh:
            self._refresh_token_session_map.pop(linked_refresh, None)
        linked_access = self._refresh_to_access_map.get(token_value)
        if linked_access:
            self._access_token_session_map.pop(linked_access, None)
        LOGGER.info(
            "OAuth token revoked: token=...%s access_session=%s refresh_session=%s",
            token_value[-8:] if len(token_value) >= 8 else token_value,
            had_access_session or "(none)",
            had_refresh_session or "(none)",
        )
        self._prune_session_maps()
        self._persist_state()


class PersistentInMemoryOAuthProvider(_PersistentOAuthStateMixin, InMemoryOAuthProvider):
    def __init__(self, *, storage_path: str | Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._init_persistence(storage_path)


class PersistentStaticClientOAuthProvider(_PersistentOAuthStateMixin, StaticClientOAuthProvider):
    def __init__(self, *, storage_path: str | Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._init_persistence(storage_path)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        had_client = client_id in self.clients
        client = await super().get_client(client_id)
        if client is not None and not had_client and client_id in self.clients:
            self._persist_state()
        return client


def build_auth(config: Config):
    if not config.oauth_enabled:
        return None

    if not config.oauth_base_url:
        raise ValueError("OAuth is enabled but OAUTH_BASE_URL is missing")

    if config.oauth_client_id:
        return PersistentStaticClientOAuthProvider(
            storage_path=config.oauth_state_path,
            base_url=config.oauth_base_url,
            pre_registered_client_id=config.oauth_client_id,
            pre_registered_client_secret=config.oauth_client_secret or None,
            pre_registered_redirect_uris=config.oauth_redirect_uris,
            token_endpoint_auth_method=config.oauth_token_endpoint_auth_method,
            allow_dynamic_client_registration=config.oauth_allow_dynamic_client_registration,
            valid_scopes=config.oauth_valid_scopes or config.oauth_required_scopes,
            required_scopes=config.oauth_required_scopes or None,
        )

    return PersistentInMemoryOAuthProvider(
        storage_path=config.oauth_state_path,
        base_url=config.oauth_base_url,
        required_scopes=config.oauth_required_scopes or None,
    )
