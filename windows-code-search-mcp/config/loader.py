from __future__ import annotations

import os
from pathlib import Path

from .models import Config


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
    return Path(__file__).resolve().parent.parent


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
