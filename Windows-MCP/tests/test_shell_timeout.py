import subprocess

from windows_mcp.desktop.service import Desktop


class FakeTimedOutProcess:
    pid = 1234
    returncode = None

    def __init__(self):
        self.communicate_calls = 0

    def communicate(self, timeout=None):
        self.communicate_calls += 1
        if self.communicate_calls == 1:
            raise subprocess.TimeoutExpired(cmd=["powershell"], timeout=timeout)
        return b"", b""


def test_execute_command_timeout_kills_process_tree(monkeypatch):
    process = FakeTimedOutProcess()
    killed_pids = []

    def fake_popen(*args, **kwargs):
        return process

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
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
    assert process.communicate_calls == 2
