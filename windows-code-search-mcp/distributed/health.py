from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import socket

from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import PROTOCOL_VERSION, VERSION


def register_node_health(mcp, context) -> None:
    contract_hash: str | None = None

    async def tool_contract() -> str:
        nonlocal contract_hash
        if contract_hash is None:
            tools = await mcp.list_tools(run_middleware=False)
            schemas = [
                tool.to_mcp_tool().model_dump(mode="json", by_alias=True, exclude_none=True)
                for tool in tools
            ]
            canonical = json.dumps(
                sorted(schemas, key=lambda item: item["name"]),
                sort_keys=True,
                separators=(",", ":"),
            )
            contract_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return contract_hash

    async def payload() -> dict:
        repositories = await context.get_auto_indexer().load_repositories() if context.auto_indexer else []
        return {
            "device_id": context.config.device_id,
            "hostname": socket.gethostname(),
            "version": VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "role": "node",
            "tool_contract": await tool_contract(),
            "search_ready": bool(
                context.auto_indexer
                and context.engine.entrypoint.is_file()
                and shutil.which(context.config.node_exe)
            ),
            "managed_repository_count": len(repositories),
            "capabilities": ["search", "indexing", "file_edits", "workspace", "desktop", "powershell"],
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True))
    async def node_health() -> dict:
        """Node identity/readiness and stable tool-contract hash."""
        return await payload()

    @mcp.custom_route("/__node_health", methods=["GET"], include_in_schema=False)
    async def node_health_http(_: Request) -> Response:
        return JSONResponse(await payload())


async def monitor_node(connection, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        await connection.check_health()
