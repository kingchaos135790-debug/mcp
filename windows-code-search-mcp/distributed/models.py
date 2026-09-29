from __future__ import annotations

from dataclasses import dataclass, field
import re


def validate_device_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,23}", value):
        raise ValueError("device_id must be 1-24 lowercase letters, digits, underscores or hyphens, starting with a letter")
    return value


@dataclass(frozen=True)
class DeviceConfig:
    device_id: str
    name: str
    host: str
    ssh_user: str
    local_forward_port: int
    remote_mcp_port: int = 18000
    ssh_port: int = 22
    enabled: bool = True
    allowed_tools: list[str] | None = None
    transport: str = "ssh"

    def __post_init__(self) -> None:
        validate_device_id(self.device_id)
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must not be empty")
        if self.transport not in {"ssh", "local"}:
            raise ValueError("transport must be ssh or local")
        if not isinstance(self.host, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]*", self.host):
            raise ValueError("host must be a hostname or IP address, not SSH options")
        if not isinstance(self.ssh_user, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.\\-]*", self.ssh_user):
            raise ValueError("ssh_user contains unsupported characters")
        for key in ("local_forward_port", "remote_mcp_port", "ssh_port"):
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= 65535:
                raise ValueError(f"{key} must be an integer between 1 and 65535")
        if self.transport == "local":
            if self.host.lower() not in {"127.0.0.1", "localhost"}:
                raise ValueError("local transport must use a loopback host")
            if self.local_forward_port != self.remote_mcp_port:
                raise ValueError("local transport requires local_forward_port to equal remote_mcp_port")
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if self.allowed_tools is not None and (
            not isinstance(self.allowed_tools, list)
            or any(not isinstance(t, str) or not t for t in self.allowed_tools)
            or len(set(self.allowed_tools)) != len(self.allowed_tools)
        ):
            raise ValueError("allowed_tools must be null or a list of unique tool names")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.local_forward_port}/mcp"

    def permits(self, tool: str) -> bool:
        return self.allowed_tools is None or tool in self.allowed_tools


@dataclass
class DeviceStatus:
    state: str = "connecting"
    last_success: str | None = None
    last_error: str | None = None
    identity: dict = field(default_factory=dict)
    advertised_tools: list[str] = field(default_factory=list)
