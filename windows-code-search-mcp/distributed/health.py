from __future__ import annotations

import asyncio
import shutil
import socket

from mcp.types import ToolAnnotations

from . import PROTOCOL_VERSION, VERSION


def register_node_health(mcp, context) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True))
    async def node_health() -> dict:
        """Lightweight node identity and local runtime readiness; server_health provides deep search diagnostics."""
        repositories = await context.get_auto_indexer().load_repositories() if context.auto_indexer else []
        return {
            "device_id": context.config.device_id, "hostname": socket.gethostname(),
            "version": VERSION, "protocol_version": PROTOCOL_VERSION, "role": "node",
            "search_ready": bool(context.auto_indexer and context.engine.entrypoint.is_file()
                                 and shutil.which(context.config.node_exe)),
            "managed_repository_count": len(repositories),
            "capabilities": ["search", "indexing", "file_edits", "workspace", "desktop", "powershell"],
        }


async def monitor_node(connection, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        await connection.refresh()
