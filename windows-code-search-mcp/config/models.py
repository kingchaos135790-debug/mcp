from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


SEARCH_TOOL_NAMES = [
    "semantic_code_search",
    "lexical_code_search",
    "hybrid_code_search",
    "server_health",
    "list_indexed_repositories",
    "index_repository",
    "diagnose_index_repository",
    "remove_indexed_repository",
    "list_auto_index_repositories",
    "add_auto_index_repository",
    "remove_auto_index_repository",
]

FILE_EDIT_TOOL_NAMES = [
    "get_file_range",
    "get_multiple_file_ranges",
    "request_file_edit",
    "safe_file_edit",
    "anchored_file_edit",
    "multi_anchor_file_edit",
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
