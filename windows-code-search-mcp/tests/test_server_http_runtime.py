import os
import sys
import types
import unittest
from enum import Enum
from unittest.mock import patch


bootstrap = types.ModuleType("bootstrap")
sys.modules["bootstrap"] = bootstrap


class _Settings:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.streamable_http_path = ""
        self.stateless_http = None

    def set_setting(self, name: str, value: object) -> None:
        self.calls.append((name, value))
        setattr(self, name, value)


fastmcp = types.ModuleType("fastmcp")
fastmcp.settings = _Settings()
sys.modules["fastmcp"] = fastmcp

server_app = types.ModuleType("server_app")
server_app.ServerApp = object
sys.modules["server_app"] = server_app

server_config = types.ModuleType("server_config")


class Transport(Enum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


server_config.SEARCH_TOOL_NAMES = []
server_config.VSCODE_TOOL_NAMES = []
server_config.Transport = Transport
server_config.build_config = lambda host, port: None
server_config.parse_bool = parse_bool
sys.modules["server_config"] = server_config

server_extensions = types.ModuleType("server_extensions")
server_extensions.SearchExtension = object
server_extensions.VSCodeBridgeExtension = object
server_extensions.WindowsDesktopExtension = object
sys.modules["server_extensions"] = server_extensions

session_context = types.ModuleType("session_context")
session_context.get_current_boot_id = lambda: ""
session_context.get_current_chat_session_id = lambda: ""
session_context.normalize_chat_session_id = lambda value: value or ""
session_context.set_current_boot_id = lambda value: None
sys.modules["session_context"] = session_context

from server import configure_http_runtime  # noqa: E402

sys.modules.pop("server_app", None)
sys.modules.pop("server_config", None)
sys.modules.pop("server_extensions", None)
sys.modules.pop("session_context", None)


class ConfigureHttpRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        fastmcp.settings.calls.clear()

    def test_streamable_http_defaults_to_stateful_mode(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FASTMCP_STATELESS_HTTP", None)

            configure_http_runtime("streamable-http", "127.0.0.1", 8000)

        self.assertIn(("stateless_http", False), fastmcp.settings.calls)

    def test_streamable_http_respects_stateless_override(self) -> None:
        with patch.dict(os.environ, {"FASTMCP_STATELESS_HTTP": "true"}, clear=False):
            configure_http_runtime("streamable-http", "127.0.0.1", 8000)

        self.assertIn(("stateless_http", True), fastmcp.settings.calls)

    def test_non_http_transport_skips_runtime_configuration(self) -> None:
        configure_http_runtime("stdio", "127.0.0.1", 8000)

        self.assertEqual(fastmcp.settings.calls, [])


if __name__ == "__main__":
    unittest.main()
