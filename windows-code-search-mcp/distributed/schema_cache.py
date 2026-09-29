from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from mcp.types import Tool

CACHE_VERSION = 1


class NodeSchemaCache:
    """Persistent last-verified node identity and MCP tool schemas."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @classmethod
    def for_devices_path(cls, devices_path: str) -> "NodeSchemaCache":
        override = os.getenv("MCP_NODE_SCHEMA_CACHE_PATH", "").strip()
        if override:
            return cls(override)
        path = Path(devices_path)
        return cls(path.with_name("node-schema-cache.json"))

    def _read(self) -> dict:
        if not self.path.is_file():
            return {"version": CACHE_VERSION, "devices": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": CACHE_VERSION, "devices": {}}
        if (
            not isinstance(payload, dict)
            or payload.get("version") != CACHE_VERSION
            or not isinstance(payload.get("devices"), dict)
        ):
            return {"version": CACHE_VERSION, "devices": {}}
        return payload

    def load(self, device_id: str) -> tuple[dict, list[Tool], str] | None:
        entry = self._read()["devices"].get(device_id)
        if not isinstance(entry, dict):
            return None
        identity = entry.get("identity")
        raw_schemas = entry.get("tools")
        contract = entry.get("tool_contract", "")
        if not isinstance(identity, dict) or not isinstance(raw_schemas, list) or not isinstance(contract, str):
            return None
        try:
            schemas = [Tool.model_validate(schema) for schema in raw_schemas]
        except Exception:
            return None
        return identity, schemas, contract

    def save(self, device_id: str, identity: dict, schemas: Iterable[Tool], tool_contract: str) -> None:
        payload = self._read()
        payload["devices"][device_id] = {
            "identity": identity,
            "tool_contract": tool_contract,
            "tools": [
                schema.model_dump(mode="json", by_alias=True, exclude_none=True)
                for schema in schemas
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temp, self.path)
