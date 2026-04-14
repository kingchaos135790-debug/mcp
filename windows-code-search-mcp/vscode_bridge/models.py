from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any


SESSION_TTL_SECONDS = 300


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    if not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_path(value: str) -> str:
    if not value.strip():
        return value
    try:
        return str(Path(value).expanduser().resolve())
    except Exception:
        return value


@dataclass
class VSCodeCommand:
    command_id: str
    session_id: str
    command_type: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=_now_iso)
    delivered_at: str = ""
    status: str = "queued"
    result: dict[str, Any] | None = None
    completion_event: Event = field(default_factory=Event, repr=False)

    def to_wire(self) -> dict[str, Any]:
        return {
            "commandId": self.command_id,
            "type": self.command_type,
            "payload": self.payload,
            "createdAt": self.created_at,
        }


@dataclass
class VSCodeSession:
    session_id: str
    created_at: str = field(default_factory=_now_iso)
    workspace_root: str = ""
    workspace_name: str = ""
    active_file: str = ""
    context_items: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    last_context_update_at: str = ""
    last_diagnostics_update_at: str = ""
    last_heartbeat_at: str = ""
    last_command_poll_at: str = ""
    last_seen_at: str = field(default_factory=_now_iso)
    pending_commands: dict[str, VSCodeCommand] = field(default_factory=dict, repr=False)

    def to_summary(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "createdAt": self.created_at,
            "workspaceRoot": self.workspace_root,
            "workspaceName": self.workspace_name,
            "activeFile": self.active_file,
            "contextItemCount": len(self.context_items),
            "diagnosticCount": len(self.diagnostics),
            "pendingCommandCount": sum(1 for command in self.pending_commands.values() if command.result is None),
            "lastContextUpdateAt": self.last_context_update_at,
            "lastDiagnosticsUpdateAt": self.last_diagnostics_update_at,
            "lastHeartbeatAt": self.last_heartbeat_at,
            "lastCommandPollAt": self.last_command_poll_at,
            "lastSeenAt": self.last_seen_at,
        }

    def to_snapshot(self) -> dict[str, Any]:
        payload = self.to_summary()
        payload["contextItems"] = self.context_items
        payload["diagnostics"] = self.diagnostics
        return payload
