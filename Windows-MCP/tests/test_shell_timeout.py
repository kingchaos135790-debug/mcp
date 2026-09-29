import asyncio
import subprocess
import threading

import pytest

import windows_mcp.desktop.service as service_module
from windows_mcp.desktop.service import Desktop
from windows_mcp.tools.shell import _execute_command_cancellable


class FakeTimedOutProcess:
    pid = 1234
    returncode = None
    stdout = None
    stderr = None
    stdin = None

    def __init__(self):
        self.communicate_calls = 0

    def communicate(self, timeout=None):
        self.communicate_calls += 1
        raise subprocess.TimeoutExpired(cmd=["powershell"], timeout=timeout)


def test_execute_command_timeout_kills_process_tree(monkeypatch):
    process = FakeTimedOutProcess()
    killed_pids = []
    clock = iter([100.0, 102.0])

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(service_module, "perf_counter", lambda: next(clock, 102.0))
    monkeypatch.setattr(
        Desktop,
        "_kill_process_tree",
        staticmethod(lambda pid: killed_pids.append(pid)),
    )

    desktop = Desktop.__new__(Desktop)
    output, status_code = desktop.execute_command("Start-Sleep 60", timeout=1)

    assert status_code == 1
    assert output == "Command execution timed out after 1 seconds"
    assert killed_pids == [1234]
    assert process.communicate_calls == 1


class FakeProcess:
    def __init__(self, pid, ppid):
        self.pid = pid
        self.info = {"pid": pid, "ppid": ppid}
        self.killed = False

    def kill(self):
        self.killed = True


def test_kill_process_tree_finds_children_after_parent_exit(monkeypatch):
    child = FakeProcess(2001, 1234)
    grandchild = FakeProcess(2002, 2001)
    unrelated = FakeProcess(3001, 9999)
    waited = []

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"returncode": 128})(),
    )

    def missing_parent(_pid):
        raise RuntimeError("parent already exited")

    monkeypatch.setattr(service_module, "Process", missing_parent)
    monkeypatch.setattr(
        service_module,
        "process_iter",
        lambda _attrs: [child, grandchild, unrelated],
    )
    monkeypatch.setattr(
        service_module,
        "wait_procs",
        lambda processes, timeout: waited.extend(processes),
    )

    Desktop._kill_process_tree(1234)

    assert child.killed
    assert grandchild.killed
    assert not unrelated.killed
    assert {proc.pid for proc in waited} == {2001, 2002}


class CancellationAwareDesktop:
    def __init__(self):
        self.started = threading.Event()
        self.cleaned_up = threading.Event()

    def execute_command(self, command, timeout, cancel_event=None):
        assert cancel_event is not None
        self.started.set()
        cancel_event.wait(5)
        if cancel_event.is_set():
            self.cleaned_up.set()
            return "Command execution cancelled", 1
        return "unexpected", 0


@pytest.mark.asyncio
async def test_shell_cancellation_waits_for_worker_cleanup():
    desktop = CancellationAwareDesktop()
    task = asyncio.create_task(
        _execute_command_cancellable(desktop, "Start-Sleep 60", 30)
    )

    for _ in range(50):
        if desktop.started.is_set():
            break
        await asyncio.sleep(0.01)

    assert desktop.started.is_set()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert desktop.cleaned_up.is_set()
