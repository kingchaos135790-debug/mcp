from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import os

import bootstrap  # noqa: F401

from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider
from windows_mcp.auth import StaticClientOAuthProvider


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
    "list_vscode_sessions",
    "get_vscode_session",
    "get_vscode_context",
    "get_vscode_context_summary",
    "get_vscode_file_range",
    "get_vscode_diagnostics",
    "request_vscode_edit",
    "request_vscode_workspace_edit",
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
