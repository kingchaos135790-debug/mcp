from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from server_config import Config
from runtime.search_engine_bridge import SearchEngineBridge

if TYPE_CHECKING:
    from runtime.repository_auto_indexer import RepositoryAutoIndexer


@dataclass
class ServerContext:
    config: Config
    engine: SearchEngineBridge
    desktop: object | None = None
    watchdog: object | None = None
    analytics: object | None = None
    auto_indexer: "RepositoryAutoIndexer | None" = None
    vscode_bridge: object | None = None

    def get_auto_indexer(self) -> "RepositoryAutoIndexer":
        if self.auto_indexer is None:
            raise RuntimeError("Auto indexer is not initialized")
        return self.auto_indexer

    def get_vscode_bridge(self):
        if self.vscode_bridge is None:
            raise RuntimeError("VS Code bridge is not initialized")
        return self.vscode_bridge
