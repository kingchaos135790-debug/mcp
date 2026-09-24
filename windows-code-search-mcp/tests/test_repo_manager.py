from pathlib import Path
from unittest.mock import MagicMock, patch
import subprocess
import sys
import tempfile
import types
import unittest

try:
    import tkinter  # noqa: F401
except ModuleNotFoundError:
    tkinter = types.ModuleType("tkinter")
    tkinter.filedialog = types.ModuleType("tkinter.filedialog")
    tkinter.messagebox = types.ModuleType("tkinter.messagebox")
    tkinter.ttk = types.ModuleType("tkinter.ttk")
    sys.modules["tkinter"] = tkinter
    sys.modules["tkinter.filedialog"] = tkinter.filedialog
    sys.modules["tkinter.messagebox"] = tkinter.messagebox
    sys.modules["tkinter.ttk"] = tkinter.ttk

import repo_manager


class RepoManagerEngineTests(unittest.TestCase):
    def test_index_runs_without_starting_a_database_service(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            engine = Path(tempdir)
            entry = engine / "dist" / "cli" / "run-core.js"
            entry.parent.mkdir(parents=True)
            entry.touch()
            app = object.__new__(repo_manager.RepoManagerApp)
            completed = subprocess.CompletedProcess([], 0, '{"gitnexus": {}}', '')
            with patch("repo_manager.DEFAULT_SEARCH_ENGINE_DIR", engine):
                with patch("repo_manager.subprocess.Popen") as popen:
                    with patch("repo_manager.subprocess.run", return_value=completed) as run:
                        result = app._run_engine_command("index_repository", {"repoRoot": "C:/repo"})
            self.assertIs(result, completed)
            popen.assert_not_called()
            self.assertEqual(run.call_args.args[0][2], "index_repository")

    def test_engine_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            engine = Path(tempdir)
            entry = engine / "dist" / "cli" / "run-core.js"
            entry.parent.mkdir(parents=True)
            entry.touch()
            app = object.__new__(repo_manager.RepoManagerApp)
            with patch("repo_manager.DEFAULT_SEARCH_ENGINE_DIR", engine):
                with patch("repo_manager.subprocess.run", return_value=subprocess.CompletedProcess([], 1, '', 'GitNexus failed')):
                    with self.assertRaisesRegex(RuntimeError, "GitNexus failed"):
                        app._run_engine_command("index_repository", {})


if __name__ == "__main__":
    unittest.main()
