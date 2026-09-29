from __future__ import annotations

from dataclasses import replace
import ipaddress
import os

from .models import validate_device_id


def is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_role(config, host: str):
    if config.role not in {"standalone", "node", "gateway"}:
        raise ValueError("MCP_ROLE must be standalone, node or gateway")
    if config.role == "node":
        validate_device_id(config.device_id)
        if not is_loopback(host):
            raise ValueError("Node HTTP must bind to loopback; use SSH forwarding for remote access")
        # Node authentication is the SSH boundary, independent of inherited
        # public OAuth settings. Existing standalone OAuth remains unchanged.
        return replace(config, oauth_enabled=False)
    if config.role == "gateway" and not config.oauth_enabled:
        if not is_loopback(host) or os.getenv("MCP_GATEWAY_ALLOW_NO_AUTH", "").lower() != "true":
            raise ValueError("Gateway requires OAuth. Local tests may set MCP_GATEWAY_ALLOW_NO_AUTH=true on loopback only")
    return config
