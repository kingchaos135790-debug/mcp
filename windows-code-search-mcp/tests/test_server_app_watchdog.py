import os
import sys
import types
import unittest
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch


bootstrap = types.ModuleType("bootstrap")
sys.modules["bootstrap"] = bootstrap

fastmcp = types.ModuleType("fastmcp")
fastmcp.FastMCP = object
sys.modules["fastmcp"] = fastmcp

starlette_requests = types.ModuleType("starlette.requests")
starlette_requests.Request = object
sys.modules["starlette.requests"] = starlette_requests

starlette_responses = types.ModuleType("starlette.responses")
starlette_responses.JSONResponse = object
starlette_responses.Response = object
sys.modules["starlette.responses"] = starlette_responses


class PostHogAnalytics:
    async def close(self) -> None:
        return None


analytics_module = types.ModuleType("windows_mcp.analytics")
analytics_module.PostHogAnalytics = PostHogAnalytics
sys.modules["windows_mcp.analytics"] = analytics_module


class Desktop:
    def __init__(self) -> None:
        self.tree = types.SimpleNamespace(on_focus_change=object())


desktop_module = types.ModuleType("windows_mcp.desktop.service")
desktop_module.Desktop = Desktop
sys.modules["windows_mcp.desktop.service"] = desktop_module


class WatchDog:
    def __init__(self) -> None:
        self.callback = None
        self.started = False

    def set_focus_callback(self, callback) -> None:
        self.callback = callback

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


watchdog_module = types.ModuleType("windows_mcp.watchdog.service")
watchdog_module.WatchDog = WatchDog
sys.modules["windows_mcp.watchdog.service"] = watchdog_module

server_config = types.ModuleType("server_config")


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    mode: str = "local"


server_config.Config = Config
server_config.build_auth = lambda config: None
server_config.parse_bool = parse_bool
sys.modules["server_config"] = server_config

server_extensions = types.ModuleType("server_extensions")
server_extensions.ServerExtension = object
sys.modules["server_extensions"] = server_extensions

server_runtime = types.ModuleType("server_runtime")


class SearchEngineBridge:
    def __init__(self, config) -> None:
        self.config = config


class RepositoryAutoIndexer:
    def __init__(self, config, engine) -> None:
        self.config = config
        self.engine = engine
        self.started = False
        self.launch_status_logged = False

    async def start(self) -> None:
        self.started = True

    async def log_launch_status(self) -> None:
        self.launch_status_logged = True

    async def stop(self) -> None:
        self.started = False


class ServerContext:
    def __init__(self, config, engine) -> None:
        self.config = config
        self.engine = engine
        self.analytics = None
        self.desktop = None
        self.watchdog = None
        self.auto_indexer = None
        self.vscode_bridge = None


server_runtime.RepositoryAutoIndexer = RepositoryAutoIndexer
server_runtime.SearchEngineBridge = SearchEngineBridge
server_runtime.ServerContext = ServerContext
sys.modules["server_runtime"] = server_runtime

import server_app as server_app_module  # noqa: E402
from server_app import ServerApp, _watchdog_enabled  # noqa: E402

sys.modules.pop("server_config", None)
sys.modules.pop("server_extensions", None)
sys.modules.pop("server_runtime", None)


class ServerAppWatchdogTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_core_services_skips_watchdog_by_default(self) -> None:
        app = ServerApp(Config(), [])

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WINDOWS_MCP_WATCHDOG_ENABLED", None)
            with patch.object(server_app_module.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
                await app._start_core_services()

        self.assertIsNotNone(app.context.desktop)
        self.assertIsNone(app.context.watchdog)
        self.assertTrue(app.context.auto_indexer.started)
        self.assertTrue(app.context.auto_indexer.launch_status_logged)
        sleep_mock.assert_not_awaited()

    async def test_start_core_services_starts_watchdog_when_enabled(self) -> None:
        app = ServerApp(Config(), [])

        with patch.dict(os.environ, {"WINDOWS_MCP_WATCHDOG_ENABLED": "true"}, clear=False):
            with patch.object(server_app_module.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
                await app._start_core_services()

        self.assertIsNotNone(app.context.watchdog)
        self.assertTrue(app.context.watchdog.started)
        self.assertIs(app.context.watchdog.callback, app.context.desktop.tree.on_focus_change)
        sleep_mock.assert_awaited_once_with(1)

    def test_watchdog_flag_defaults_to_disabled(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WINDOWS_MCP_WATCHDOG_ENABLED", None)
            self.assertFalse(_watchdog_enabled())

    def test_watchdog_flag_respects_true_values(self) -> None:
        with patch.dict(os.environ, {"WINDOWS_MCP_WATCHDOG_ENABLED": "yes"}, clear=False):
            self.assertTrue(_watchdog_enabled())


if __name__ == "__main__":
    unittest.main()
