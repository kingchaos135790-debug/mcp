"""PowerShell tool — shell/command execution."""

import asyncio
import os
import threading

from mcp.types import ToolAnnotations
from windows_mcp.analytics import with_analytics
from fastmcp import Context


_CONNECTOR_SAFE_TIMEOUT_ENV = "WINDOWS_MCP_CONNECTOR_SAFE_TIMEOUT_SECONDS"
_DEFAULT_CONNECTOR_SAFE_TIMEOUT_SECONDS = 45
_ACTIVE_SHELL_REQUESTS: dict[str, threading.Event] = {}
_ACTIVE_SHELL_REQUESTS_LOCK = threading.Lock()


def _register_shell_request(request_id: str, cancel_event: threading.Event) -> None:
    key = str(request_id)
    with _ACTIVE_SHELL_REQUESTS_LOCK:
        _ACTIVE_SHELL_REQUESTS[key] = cancel_event


def _unregister_shell_request(request_id: str, cancel_event: threading.Event) -> None:
    key = str(request_id)
    with _ACTIVE_SHELL_REQUESTS_LOCK:
        if _ACTIVE_SHELL_REQUESTS.get(key) is cancel_event:
            _ACTIVE_SHELL_REQUESTS.pop(key, None)


def cancel_shell_request(request_id: str) -> bool:
    with _ACTIVE_SHELL_REQUESTS_LOCK:
        cancel_event = _ACTIVE_SHELL_REQUESTS.get(str(request_id))
    if cancel_event is None:
        return False
    cancel_event.set()
    return True


def _connector_safe_timeout(timeout: int) -> int:
    """Bound shell lifetime below the outer connector request window."""
    try:
        cap = int(os.getenv(
            _CONNECTOR_SAFE_TIMEOUT_ENV,
            str(_DEFAULT_CONNECTOR_SAFE_TIMEOUT_SECONDS),
        ))
    except ValueError:
        cap = _DEFAULT_CONNECTOR_SAFE_TIMEOUT_SECONDS
    if cap <= 0:
        cap = _DEFAULT_CONNECTOR_SAFE_TIMEOUT_SECONDS
    return min(max(0, int(timeout)), cap)


async def _execute_command_cancellable(
    desktop,
    command: str,
    timeout: int,
    cancel_event: threading.Event | None = None,
):
    """Run a shell command while keeping cancellation tied to the subprocess lifetime."""
    cancel_event = cancel_event or threading.Event()
    effective_timeout = _connector_safe_timeout(timeout)
    worker = asyncio.create_task(
        asyncio.to_thread(
            desktop.execute_command,
            command,
            effective_timeout,
            cancel_event,
        )
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # asyncio cannot stop a worker thread. Signal the synchronous runner, keep the
        # worker alive just long enough to reap PowerShell/children, then propagate the
        # MCP request cancellation.
        cancel_event.set()
        try:
            await asyncio.wait_for(asyncio.shield(worker), timeout=10)
        except Exception:
            pass
        raise


def register(mcp, *, get_desktop, get_analytics):
    @mcp.tool(
        name="PowerShell",
        description="Shell/command execution. Keywords: shell, run, execute, cmd, terminal, command line, script. A comprehensive system tool for executing any PowerShell commands. Use it to navigate the file system, manage files and processes, and execute system-level operations. Capable of accessing web content (e.g., via Invoke-WebRequest), interacting with network resources, and performing complex administrative tasks. Use other tools to write code or large text files, because cmd/shell command-length limits make large inline writes unreliable. This tool provides full access to the underlying operating system capabilities, making it the primary interface for system automation, scripting, and deep system interaction.",
        annotations=ToolAnnotations(
            title="PowerShell",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    @with_analytics(get_analytics(), "Powershell-Tool")
    async def powershell_tool(command: str, timeout: int = 30, ctx: Context = None) -> str:
        cancel_event = threading.Event()
        request_id = None
        if ctx is not None and getattr(ctx, "request_context", None) is not None:
            request_id = ctx.request_id
            _register_shell_request(request_id, cancel_event)
        try:
            response, status_code = await _execute_command_cancellable(
                get_desktop(),
                command,
                timeout,
                cancel_event,
            )
            return f"Response: {response}\nStatus Code: {status_code}"
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return f"Error executing command: {str(e)}\nStatus Code: 1"
        finally:
            if request_id is not None:
                _unregister_shell_request(request_id, cancel_event)
