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


class QdrantReadinessTests(unittest.TestCase):
    def test_does_not_start_qdrant_when_already_reachable(self) -> None:
        with patch("repo_manager._qdrant_is_reachable", return_value=True):
            with patch("repo_manager.subprocess.Popen") as popen:
                repo_manager._ensure_qdrant_ready()

        popen.assert_not_called()

    def test_starts_qdrant_and_waits_until_reachable(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            launcher = Path(tempdir) / "start-qdrant.bat"
            launcher.touch()
            with patch("repo_manager.DEFAULT_QDRANT_START_BAT", launcher):
                with patch("repo_manager._qdrant_is_reachable", side_effect=[False, False, True]):
                    with patch("repo_manager.time.sleep"):
                        with patch("repo_manager.subprocess.Popen") as popen:
                            repo_manager._ensure_qdrant_ready()

        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0][-1], str(launcher))
        self.assertEqual(popen.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_reports_a_missing_qdrant_launcher(self) -> None:
        missing_launcher = MagicMock()
        missing_launcher.is_file.return_value = False
        with patch("repo_manager.DEFAULT_QDRANT_START_BAT", missing_launcher):
            with patch("repo_manager._qdrant_is_reachable", return_value=False):
                with self.assertRaisesRegex(FileNotFoundError, "Qdrant launcher not found"):
                    repo_manager._ensure_qdrant_ready()


if __name__ == "__main__":
    unittest.main()
