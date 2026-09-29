"""Deployment checks only; never installs packages or configures credentials."""
from __future__ import annotations

import argparse
from importlib import metadata, util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import bootstrap  # noqa: F401
from config.loader import build_config
from .registry import DeviceRegistry
from .roles import validate_role
from .tunnel_manager import resolve_ssh


def check(role: str, host: str, port: int, require_ssh: bool = False) -> list[dict]:
    results = []

    def record(name, operation):
        try:
            detail = operation()
            results.append({"check": name, "ok": True, "detail": str(detail or "OK")})
        except Exception as exc:
            results.append({"check": name, "ok": False, "detail": str(exc)})

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    config = build_config(host, port)
    config.role = role
    record("role configuration", lambda: validate_role(config, host) and "valid")
    record("Python", lambda: require(sys.version_info >= (3, 13), "Python 3.13 or newer is required"))
    def fastmcp_version():
        version = metadata.version("fastmcp")
        require(version == "3.0.1", f"Validated FastMCP version is 3.0.1; installed: {version}")
        return version
    record("FastMCP", fastmcp_version)
    if role == "gateway":
        loaded = []
        def registry():
            registry = DeviceRegistry.load(config.devices_path)
            loaded.append(registry)
            require(all(d.local_forward_port != port for d in registry.enabled), "Gateway and node/forwarded ports conflict")
            return f"{len(registry.enabled)} enabled devices"
        record("device registry", registry)
        if loaded and any(d.transport == "ssh" for d in loaded[0].enabled):
            record("OpenSSH client", resolve_ssh)
        else:
            results.append({"check": "OpenSSH client", "ok": True, "detail": "not required"})
        return results

    for distribution in ("comtypes", "pywin32", "pillow", "watchfiles", "posthog", "dxcam"):
        record(distribution, lambda d=distribution: metadata.version(d))
    record("Windows-MCP source", lambda: require(util.find_spec("windows_mcp") is not None, "Windows-MCP source not found"))
    record("Windows platform", lambda: require(os.name == "nt", "Nodes require Windows"))
    def executable_version(executable):
        path = shutil.which(executable)
        require(path is not None, f"Executable not found: {executable}")
        result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15, check=True)
        return result.stdout.strip().splitlines()[0]
    record("Node.js", lambda: executable_version(config.node_exe))
    record("ripgrep", lambda: executable_version("rg"))
    engine = Path(config.search_engine_dir)
    record("search core build", lambda: require((engine / "dist/cli/run-core.js").is_file(), "Build search core with npm ci and npm run build"))
    record("GitNexus", lambda: require(Path(os.getenv("GITNEXUS_CLI_PATH", str(engine / "node_modules/gitnexus/dist/cli/index.js"))).is_file(), "GitNexus CLI is missing; run npm ci in the search core"))
    record("tree-sitter", lambda: require((engine / "node_modules/tree-sitter/package.json").is_file(), "tree-sitter dependency is missing"))
    def writable_index():
        root = Path(os.getenv("INDEX_ROOT", r"E:\mcp-index-data"))
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=root) as stream:
            stream.write(b"preflight")
        return str(root)
    record("writable index root", writable_index)
    if require_ssh:
        def ssh_server():
            path = shutil.which("sshd") or str(Path(os.getenv("WINDIR", "C:/Windows")) / "System32/OpenSSH/sshd.exe")
            require(Path(path).is_file(), "Install the Windows OpenSSH Server optional feature")
            return path
        record("OpenSSH server installed", ssh_server)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=["node", "gateway"], required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18000)
    parser.add_argument("--require-ssh", action="store_true")
    args = parser.parse_args()
    results = check(args.role, args.host, args.port, args.require_ssh)
    print(json.dumps(results, indent=2))
    raise SystemExit(0 if all(item["ok"] for item in results) else 1)


if __name__ == "__main__":
    main()
