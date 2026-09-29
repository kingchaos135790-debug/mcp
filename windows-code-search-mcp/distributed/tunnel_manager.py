from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import time

from .models import DeviceConfig


def resolve_ssh() -> str:
    executable = os.getenv("MCP_SSH_EXE") or shutil.which("ssh")
    if not executable or not Path(executable).is_file():
        raise ValueError("OpenSSH not found; set MCP_SSH_EXE to the absolute ssh executable path")
    return str(Path(executable).resolve())


def tunnel_command(executable: str, device: DeviceConfig) -> list[str]:
    if device.transport != "ssh":
        raise ValueError("SSH tunnel requested for a non-SSH device")
    return [
        executable, "-N", "-T", "-o", "BatchMode=yes",
        "-o", "PreferredAuthentications=publickey", "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "StrictHostKeyChecking=yes", "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=10", "-o", "ConnectionAttempts=1",
        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
        "-o", "ForwardAgent=no", "-o", "ForwardX11=no",
        "-o", "PermitLocalCommand=no", "-o", "ControlMaster=no",
        "-o", "ControlPath=none",
        "-p", str(device.ssh_port), "-l", device.ssh_user,
        "-L", f"127.0.0.1:{device.local_forward_port}:127.0.0.1:{device.remote_mcp_port}",
        device.host,
    ]


class LocalEndpointManager:
    """No-op transport manager for a node already listening on local loopback."""

    def __init__(self, device: DeviceConfig) -> None:
        self.device = device
        self.last_error: str | None = None

    def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class TunnelManager:
    """One supervisor per device; no shell and no interactive credentials."""

    def __init__(self, device: DeviceConfig, executable: str, *, max_backoff: float = 30) -> None:
        self.device = device
        self.executable = executable
        self.max_backoff = max_backoff
        self.process = None
        self.task: asyncio.Task | None = None
        self.last_error: str | None = None
        self.attempts = 0

    def start(self) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self._supervise(), name=f"ssh-{self.device.device_id}")

    async def _terminate(self) -> None:
        process, self.process = self.process, None
        if process is None or process.returncode is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()

    async def _supervise(self) -> None:
        delay = 1.0
        try:
            while True:
                started = time.monotonic()
                self.attempts += 1
                try:
                    self.process = await asyncio.create_subprocess_exec(
                        *tunnel_command(self.executable, self.device),
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                    self.last_error = None
                    code = await self.process.wait()
                    self.last_error = f"SSH exited with code {code}; check key authentication, known_hosts and port availability"
                except OSError as exc:
                    self.last_error = f"SSH could not start: {exc}"
                finally:
                    await self._terminate()
                if time.monotonic() - started >= 60:
                    delay = 1.0
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.max_backoff)
        finally:
            await self._terminate()

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        await self._terminate()
