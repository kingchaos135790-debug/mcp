from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile

from .models import DeviceConfig


class DeviceRegistry:
    def __init__(self, devices: list[DeviceConfig]) -> None:
        self.devices = tuple(devices)
        ids = [d.device_id for d in devices]
        ports = [d.local_forward_port for d in devices]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate device_id in registry")
        if len(ports) != len(set(ports)):
            raise ValueError("Duplicate local_forward_port in registry")

    @property
    def enabled(self) -> tuple[DeviceConfig, ...]:
        return tuple(d for d in self.devices if d.enabled)

    @classmethod
    def load(cls, path: str | Path) -> DeviceRegistry:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or set(payload) != {"version", "devices"}:
            raise ValueError("Registry must contain only version and devices")
        if type(payload["version"]) is not int or payload["version"] != 1:
            raise ValueError("Unsupported device registry version (expected 1)")
        if not isinstance(payload["devices"], list):
            raise ValueError("devices must be a list")
        try:
            return cls([DeviceConfig(**d) for d in payload["devices"]])
        except TypeError as exc:
            raise ValueError("Invalid device fields; credentials and unknown fields are not accepted") from exc

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Replace atomically in the same directory; never persist runtime status.
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "devices": [asdict(d) for d in self.devices]}, stream, indent=2)
                stream.write("\n")
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
