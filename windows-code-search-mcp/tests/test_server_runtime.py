from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import asyncio
import json
import subprocess
import sys
import tempfile
import types
import unittest


watchfiles = types.ModuleType("watchfiles")


async def awatch(*_args, **_kwargs):
    if False:
        yield ()


watchfiles.awatch = awatch
sys.modules["watchfiles"] = watchfiles

server_config = types.ModuleType("server_config")


@dataclass
class Config:
    mode: str = "local"
    search_engine_dir: str = ""
    node_exe: str = "node"
    engine_timeout_seconds: int = 5
    managed_repositories_path: str = ""
    watch_debounce_ms: int = 1000
    watch_force_polling: bool = False


@dataclass
class ManagedRepository:
    repo_root: str
    watch: bool = True
    auto_index_on_start: bool = True
    last_indexed_at: str = ""
    last_index_reason: str = ""
    last_result: dict[str, object] = field(default_factory=dict)
    last_error: str = ""


server_config.Config = Config
server_config.ManagedRepository = ManagedRepository
server_config.format_index_result_summary = lambda result: str(result)
server_config.index_root_display = lambda: "index-root"
server_config.normalize_repo_root = lambda value: value
server_config.parse_bool = lambda value, default=False: default if value is None else value
server_config.parse_list = lambda value: [] if not value else [value]
server_config.path_is_within = lambda _candidate, _root: True
sys.modules["server_config"] = server_config

from server_runtime import RepositoryAutoIndexer, SearchEngineBridge


class SearchEngineBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

        root = Path(self.tempdir.name)
        entrypoint = root / "dist" / "cli" / "run-core.js"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("// test entrypoint\n", encoding="utf-8")

        config = Config(search_engine_dir=str(root), engine_timeout_seconds=7)
        self.bridge = SearchEngineBridge(config)

    def test_parse_json_output_allows_none(self) -> None:
        self.assertEqual(self.bridge._parse_json_output(None), {})

    def test_run_tool_returns_empty_dict_for_none_stdout(self) -> None:
        completed = SimpleNamespace(stdout=None, stderr="", returncode=0)

        with patch("server_runtime.subprocess.run", return_value=completed):
            with self.assertLogs("server_runtime", level="WARNING") as logs:
                result = self.bridge.run_tool("hybrid_code_search", {"query": "needle"})

        self.assertEqual(result, {})
        self.assertIn("empty stdout", "\n".join(logs.output))

    def test_run_tool_prefers_stderr_on_nonzero_exit(self) -> None:
        completed = SimpleNamespace(stdout=None, stderr="engine exploded", returncode=1)

        with patch("server_runtime.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "engine exploded"):
                self.bridge.run_tool("hybrid_code_search", {"query": "needle"})

    def test_run_tool_wraps_timeout(self) -> None:
        timeout_error = subprocess.TimeoutExpired(cmd=["node"], timeout=7, output=None, stderr="still running")

        with patch("server_runtime.subprocess.run", side_effect=timeout_error):
            with self.assertRaisesRegex(RuntimeError, "hybrid_code_search timed out after 7s"):
                self.bridge.run_tool("hybrid_code_search", {"query": "needle"})


class RepositoryAutoIndexerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.config_path = Path(self.tempdir.name) / "managed-repositories.json"
        self.indexer = RepositoryAutoIndexer(
            Config(search_engine_dir=self.tempdir.name, managed_repositories_path=str(self.config_path)),
            SimpleNamespace(),
        )

    def test_load_repositories_repairs_empty_config(self) -> None:
        self.config_path.write_text("", encoding="utf-8")

        repositories = asyncio.run(self.indexer.load_repositories())

        self.assertEqual(repositories, [])
        self.assertEqual(
            json.loads(self.config_path.read_text(encoding="utf-8")),
            {"version": 1, "repositories": []},
        )

    def test_load_repositories_repairs_invalid_json_and_keeps_backup(self) -> None:
        self.config_path.write_text("not-json", encoding="utf-8")

        repositories = asyncio.run(self.indexer.load_repositories())

        self.assertEqual(repositories, [])
        self.assertEqual(
            json.loads(self.config_path.read_text(encoding="utf-8")),
            {"version": 1, "repositories": []},
        )
        backups = list(self.config_path.parent.glob("managed-repositories.invalid-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "not-json")


if __name__ == "__main__":
    unittest.main()
