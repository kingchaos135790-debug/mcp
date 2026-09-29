"""PowerShell tool — shell/command execution."""

import asyncio
import threading

from mcp.types import ToolAnnotations
from windows_mcp.analytics import with_analytics
from fastmcp import Context


async def _execute_command_cancellable(desktop, command: str, timeout: int):
    """Run a shell command while keeping cancellation tied to the subprocess lifetime."""
    cancel_event = threading.Event()
    worker = asyncio.create_task(
        asyncio.to_thread(
            desktop.execute_command,
            command,
            timeout,
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
        try:
            response, status_code = await _execute_command_cancellable(
                get_desktop(),
                command,
                timeout,
            )
            return f"Response: {response}\nStatus Code: {status_code}"
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return f"Error executing command: {str(e)}\nStatus Code: 1"
