from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import os
import json
import logging
from threading import RLock

from mcp.server.auth.provider import AccessToken, AuthorizationCode, RefreshToken
from mcp.shared.auth import OAuthClientInformationFull


import bootstrap  # noqa: F401

from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider
from windows_mcp.auth import StaticClientOAuthProvider

LOGGER = logging.getLogger(__name__)


class _PersistentOAuthStateMixin:
    def _init_persistence(self, storage_path: str | Path) -> None:
        self._storage_path = Path(storage_path).expanduser().resolve()
        self._state_lock = RLock()
        self._load_state()

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

    def _persist_state(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._storage_path.with_suffix(self._storage_path.suffix + ".tmp")
        payload = {
            "version": 1,
            "clients": self._serialize_models(self.clients),
            "auth_codes": self._serialize_models(self.auth_codes),
            "access_tokens": self._serialize_models(self.access_tokens),
            "refresh_tokens": self._serialize_models(self.refresh_tokens),
            "access_to_refresh_map": dict(self._access_to_refresh_map),
            "refresh_to_access_map": dict(self._refresh_to_access_map),
        }
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._storage_path)

    def _load_state(self) -> None:
        if not self._storage_path.exists():
            return
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            self.clients = self._deserialize_models(payload.get("clients", {}), OAuthClientInformationFull)
            self.auth_codes = self._deserialize_models(payload.get("auth_codes", {}), AuthorizationCode)
            self.access_tokens = self._deserialize_models(payload.get("access_tokens", {}), AccessToken)
            self.refresh_tokens = self._deserialize_models(payload.get("refresh_tokens", {}), RefreshToken)
            self._access_to_refresh_map = {str(k): str(v) for k, v in payload.get("access_to_refresh_map", {}).items()}
            self._refresh_to_access_map = {str(k): str(v) for k, v in payload.get("refresh_to_access_map", {}).items()}
        except Exception as exc:
            LOGGER.warning("Failed to load OAuth state from %s: %s", self._storage_path, exc)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await super().register_client(client_info)
        self._persist_state()

    async def authorize(self, client: OAuthClientInformationFull, params):
        redirect_uri = await super().authorize(client, params)
        self._persist_state()
        return redirect_uri

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str):
        had_code = authorization_code in self.auth_codes
        result = await super().load_authorization_code(client, authorization_code)
        if had_code and authorization_code not in self.auth_codes:
            self._persist_state()
        return result

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code):
        token = await super().exchange_authorization_code(client, authorization_code)
        self._persist_state()
        return token

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str):
        had_token = refresh_token in self.refresh_tokens
        result = await super().load_refresh_token(client, refresh_token)
        if had_token and refresh_token not in self.refresh_tokens:
            self._persist_state()
        return result

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token, scopes: list[str]):
        token = await super().exchange_refresh_token(client, refresh_token, scopes)
        self._persist_state()
        return token

    async def load_access_token(self, token: str):  # type: ignore[override]
        had_token = token in self.access_tokens
        result = await super().load_access_token(token)
        if had_token and token not in self.access_tokens:
            self._persist_state()
        return result

    async def revoke_token(self, token) -> None:
        await super().revoke_token(token)
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



SEARCH_TOOL_NAMES = [
    "semantic_code_search",
    "lexical_code_search",
    "hybrid_code_search",
    "server_health",
    "list_indexed_repositories",
    "index_repository",
    "remove_indexed_repository",
    "list_auto_index_repositories",
    "add_auto_index_repository",
    "remove_auto_index_repository",
]

VSCODE_TOOL_NAMES = [
    "create_vscode_session",
    "close_vscode_session",
    "list_vscode_sessions",
    "get_vscode_session",
    "get_vscode_context",
    "get_vscode_context_summary",
    "get_vscode_file_range",
    "get_vscode_diagnostics",
    "request_vscode_edit",
    "request_vscode_workspace_edit",
    "safe_vscode_edit",
    "open_vscode_file",
]


@dataclass
class ManagedRepository:
    repo_root: str
    watch: bool = True
    auto_index_on_start: bool = True
    last_indexed_at: str = ""
    last_index_reason: str = ""
    last_result: dict[str, object] = field(default_factory=dict)
    last_error: str = ""


@dataclass
class Config:
    mode: str
    search_engine_dir: str
    node_exe: str = field(default="node")
    engine_timeout_seconds: int = field(default=600)
    managed_repositories_path: str = field(default="")
    watch_debounce_ms: int = field(default=1600)
    watch_force_polling: bool = field(default=False)
    oauth_enabled: bool = field(default=False)
    oauth_base_url: str = field(default="")
    oauth_required_scopes: list[str] = field(default_factory=list)
    oauth_client_id: str = field(default="")
    oauth_client_secret: str = field(default="")
    oauth_redirect_uris: list[str] = field(default_factory=list)
    oauth_token_endpoint_auth_method: str = field(default="client_secret_post")
    oauth_valid_scopes: list[str] = field(default_factory=list)
    oauth_allow_dynamic_client_registration: bool = field(default=False)
    oauth_state_path: str = field(default="")
    vscode_bridge_enabled: bool = field(default=True)
    vscode_bridge_host: str = field(default="127.0.0.1")
    vscode_bridge_port: int = field(default=8876)
    vscode_bridge_token: str = field(default="")


class Transport(Enum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"

    def __str__(self) -> str:
        return self.value


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_list(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = value.replace("\r", "\n").replace(",", "\n")
    return [item.strip() for item in normalized.split("\n") if item.strip()]


def server_root() -> Path:
    return Path(__file__).resolve().parent


def normalize_repo_root(repo_root: str) -> str:
    normalized = str(Path(repo_root).expanduser().resolve())
    if not Path(normalized).exists():
        raise FileNotFoundError(f"Repository path not found: {normalized}")
    if not Path(normalized).is_dir():
        raise NotADirectoryError(f"Repository path is not a directory: {normalized}")
    return normalized


def path_is_within(candidate: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(candidate), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False


def index_root_display() -> str:
    return str(Path(os.getenv("INDEX_ROOT", r"E:\mcp-index-data")).expanduser().resolve())


def coerce_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def format_index_result_summary(result: dict[str, object]) -> str:
    indexed_files = coerce_int(result.get("indexedFiles", 0))
    changed_files = coerce_int(result.get("changedFiles", 0))
    unchanged_files = coerce_int(result.get("unchangedFiles", 0))
    deleted_files = coerce_int(result.get("deletedFiles", 0))

    qdrant_value = result.get("qdrant")
    qdrant = qdrant_value if isinstance(qdrant_value, dict) else {}
    upserted_points = coerce_int(qdrant.get("upsertedPoints", 0))
    deleted_points = coerce_int(qdrant.get("deletedPoints", 0))

    return (
        f"files={indexed_files} changed={changed_files} unchanged={unchanged_files} "
        f"deleted={deleted_files} qdrant_upserted={upserted_points} qdrant_deleted={deleted_points}"
    )


def build_config(host: str, port: int) -> Config:
    oauth_base_url = os.getenv("OAUTH_BASE_URL", "").strip()
    if not oauth_base_url:
        oauth_base_url = f"http://{host}:{port}"

    return Config(
        mode=os.getenv("MODE", "local").lower(),
        search_engine_dir=os.getenv(
            "SEARCH_ENGINE_DIR",
            r"E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp",
        ).strip(),
        node_exe=os.getenv("NODE_EXE", "node").strip() or "node",
        engine_timeout_seconds=int(os.getenv("SEARCH_ENGINE_TIMEOUT_SECONDS", "600")),
        managed_repositories_path=os.getenv(
            "AUTO_INDEX_CONFIG_PATH",
            str(server_root() / "managed-repositories.json"),
        ).strip(),
        watch_debounce_ms=int(os.getenv("AUTO_INDEX_WATCH_DEBOUNCE_MS", "1600")),
        watch_force_polling=parse_bool(os.getenv("AUTO_INDEX_FORCE_POLLING"), False),
        oauth_enabled=parse_bool(os.getenv("OAUTH_ENABLED"), False),
        oauth_base_url=oauth_base_url,
        oauth_required_scopes=parse_list(os.getenv("OAUTH_REQUIRED_SCOPES")),
        oauth_client_id=os.getenv("OAUTH_CLIENT_ID", "").strip(),
        oauth_client_secret=os.getenv("OAUTH_CLIENT_SECRET", "").strip(),
        oauth_redirect_uris=parse_list(os.getenv("OAUTH_REDIRECT_URIS")),
        oauth_token_endpoint_auth_method=os.getenv(
            "OAUTH_TOKEN_ENDPOINT_AUTH_METHOD",
            "client_secret_post",
        ).strip(),
        oauth_valid_scopes=parse_list(os.getenv("OAUTH_VALID_SCOPES")),
        oauth_allow_dynamic_client_registration=parse_bool(
            os.getenv("OAUTH_ALLOW_DYNAMIC_CLIENT_REGISTRATION"),
            False,
        ),
        oauth_state_path=os.getenv(
            "OAUTH_STATE_PATH",
            str(server_root() / "oauth-state.json"),
        ).strip(),
        vscode_bridge_enabled=parse_bool(os.getenv("VSCODE_BRIDGE_ENABLED"), True),
        vscode_bridge_host=os.getenv("VSCODE_BRIDGE_HOST", "127.0.0.1").strip() or "127.0.0.1",
        vscode_bridge_port=int(os.getenv("VSCODE_BRIDGE_PORT", "8876")),
        vscode_bridge_token=os.getenv("VSCODE_BRIDGE_TOKEN", "").strip(),
    )


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
