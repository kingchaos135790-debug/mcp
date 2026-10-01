from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import bootstrap  # noqa: F401
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
import uvicorn

from config.models import Config
from distributed.gateway import GatewayApp
from distributed.models import DeviceConfig
from distributed.node_connection import NodeConnection, VerifiedNodeClient, private_http_client
from distributed.registry import DeviceRegistry
from distributed.roles import validate_role
from distributed.schema_cache import NodeSchemaCache
from distributed.search import search_devices
from distributed.tunnel_manager import TunnelManager, tunnel_command


def device(device_id="alpha", port=18101, **kwargs):
    transport = kwargs.pop("transport", "ssh")
    host = kwargs.pop("host", "127.0.0.1")
    ssh_user = kwargs.pop("ssh_user", "local" if transport == "local" else "user")
    remote_mcp_port = kwargs.pop("remote_mcp_port", port if transport == "local" else 18000)
    return DeviceConfig(
        device_id,
        device_id,
        host,
        ssh_user,
        port,
        remote_mcp_port=remote_mcp_port,
        transport=transport,
        **kwargs,
    )


class RegistryTests(unittest.TestCase):
    def test_validation_and_atomic_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "devices.json"
            original = DeviceRegistry([device(), device("beta", 18102, enabled=False)])
            original.save(path)
            self.assertEqual(DeviceRegistry.load(path).devices, original.devices)
            self.assertEqual(len(DeviceRegistry.load(path).enabled), 1)
            self.assertNotIn("state", json.loads(path.read_text())["devices"][0])

    def test_reject_duplicates_bad_ports_and_ssh_injection(self):
        for devices in ([device(), device()], [device(), device("beta")]):
            with self.assertRaises(ValueError):
                DeviceRegistry(devices)
        DeviceRegistry([device(), device("alpha_work", 18102)])
        for changes in ({"local_forward_port": True}, {"remote_mcp_port": 0},
                        {"host": "-oProxyCommand=evil"}, {"ssh_user": "user@host"},
                        {"device_id": "Bad ID"}, {"enabled": "false"}, {"allowed_tools": "PowerShell"}):
            with self.assertRaises(ValueError):
                replace(device(), **changes)

    def test_unknown_fields_and_versions_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "devices.json"
            for payload in ({"version": 2, "devices": []}, {"version": True, "devices": []},
                            {"version": 1, "devices": [{"password": "no"}]}):
                path.write_text(json.dumps(payload))
                with self.assertRaises(ValueError):
                    DeviceRegistry.load(path)

    def test_role_security(self):
        config = Config(mode="local", search_engine_dir=".", role="node", device_id="alpha", oauth_enabled=True)
        self.assertFalse(validate_role(config, "127.0.0.1").oauth_enabled)
        with self.assertRaises(ValueError):
            validate_role(config, "0.0.0.0")
        config = replace(config, role="gateway", oauth_enabled=False)
        with patch.dict(os.environ, {"MCP_GATEWAY_ALLOW_NO_AUTH": "true"}):
            validate_role(config, "127.0.0.1")
            with self.assertRaises(ValueError):
                validate_role(config, "0.0.0.0")
        with patch.dict(os.environ, {"MCP_GATEWAY_ALLOW_NO_AUTH": "false"}):
            with self.assertRaises(ValueError):
                validate_role(config, "127.0.0.1")

    def test_ssh_command(self):
        command = tunnel_command("C:/Windows/System32/OpenSSH/ssh.exe", device())
        self.assertEqual(command[0], "C:/Windows/System32/OpenSSH/ssh.exe")
        for option in ("BatchMode=yes", "StrictHostKeyChecking=yes", "ExitOnForwardFailure=yes", "ForwardAgent=no"):
            self.assertIn(option, command)
        self.assertIn("127.0.0.1:18101:127.0.0.1:18000", command)

    def test_local_transport_is_loopback_only_and_skips_ssh(self):
        local = replace(device(port=18001), transport="local", host="127.0.0.1",
                        ssh_user="local", remote_mcp_port=18001)
        self.assertEqual(local.url, "http://127.0.0.1:18001/mcp")
        with self.assertRaises(ValueError):
            replace(local, host="192.168.5.20")
        with self.assertRaises(ValueError):
            replace(local, local_forward_port=18002)
        with self.assertRaises(ValueError):
            replace(local, transport="rdp")

        config = Config(mode="local", search_engine_dir=".", role="gateway")
        with patch("distributed.gateway.resolve_ssh", side_effect=AssertionError("SSH should not be resolved")):
            app = GatewayApp(config, registry=DeviceRegistry([local]))
        self.assertEqual(app.tunnels[local.device_id].__class__.__name__, "LocalEndpointManager")


class TunnelTests(unittest.IsolatedAsyncioTestCase):
    async def test_premature_exit_has_bounded_backoff(self):
        class Process:
            returncode = 255
            async def wait(self):
                return 255
        sleeps = []
        async def sleep(delay):
            sleeps.append(delay)
            if len(sleeps) == 4:
                raise asyncio.CancelledError()
        manager = TunnelManager(device(), "ssh", max_backoff=3)
        with patch("distributed.tunnel_manager.asyncio.create_subprocess_exec", AsyncMock(return_value=Process())), \
             patch("distributed.tunnel_manager.asyncio.sleep", sleep):
            with self.assertRaises(asyncio.CancelledError):
                await manager._supervise()
        self.assertEqual(sleeps, [1, 2, 3, 3])
        self.assertIn("255", manager.last_error)

    async def test_retry_then_cancel_cleans_up_process(self):
        class Process:
            returncode = None
            terminated = False
            async def wait(self):
                if not self.terminated:
                    await asyncio.Future()
                return 0
            def terminate(self):
                self.terminated = True
                self.returncode = 0
        process = Process()
        create = AsyncMock(side_effect=[OSError("cannot connect"), process])
        manager = TunnelManager(device(), "ssh", max_backoff=0.01)
        # First retry is deliberately one second; the ceiling applies thereafter.
        with patch("distributed.tunnel_manager.asyncio.create_subprocess_exec", create):
            manager.start()
            async with asyncio.timeout(3):
                while create.call_count < 2:
                    await asyncio.sleep(0.02)
            await manager.stop()
        self.assertTrue(process.terminated)
        self.assertIsNone(manager.task)
        self.assertIsNone(manager.process)


class HttpNode:
    def __init__(self, identity, port=0):
        self.identity = identity
        self.calls = 0
        self.fail = False
        self.slow = False
        self.headers = []
        self.list_tools_calls = 0
        self.power_shell_started = asyncio.Event()
        self.power_shell_cancelled = asyncio.Event()
        self.power_shell_cancel_signal = asyncio.Event()
        self.cancel_request_ids = []
        self.tool_contract = "contract-v1"
        self.port = port
        self.mcp = FastMCP(identity)

        def health_payload() -> dict:
            return {"device_id": self.identity, "role": "node", "protocol_version": 1,
                    "tool_contract": self.tool_contract, "search_ready": True}

        @self.mcp.tool()
        def node_health() -> dict:
            return health_payload()

        from starlette.responses import JSONResponse

        @self.mcp.custom_route("/__node_health", methods=["GET"], include_in_schema=False)
        async def node_health_http(_):
            return JSONResponse(health_payload())

        @self.mcp.custom_route("/__cancel_request", methods=["POST"], include_in_schema=False)
        async def cancel_request_http(request):
            payload = await request.json()
            request_id = str(payload.get("request_id") or "")
            self.cancel_request_ids.append(request_id)
            self.power_shell_cancel_signal.set()
            return JSONResponse({"request_id": request_id, "cancelled": True})

        @self.mcp.tool()
        async def PowerShell(command: str) -> str:
            self.calls += 1
            if command == "slow":
                self.power_shell_started.set()
                await self.power_shell_cancel_signal.wait()
                self.power_shell_cancelled.set()
                return f"{self.identity}:cancelled"
            if self.fail:
                raise ValueError("failed after execution")
            return f"{self.identity}:{command}"

        @self.mcp.tool()
        def get_file_range(path: str) -> str:
            return f"{self.identity}:{path}"

        @self.mcp.tool()
        async def hybrid_code_search(query: str, repo: str = "", limit: int = 8) -> str:
            if self.slow:
                await asyncio.sleep(8)
            return json.dumps({"fused": [{"repoId": repo or "same-id", "repoName": "same-name",
                                         "filePath": "C:/repo/file.py", "score": 42, "source": "hybrid_fused"}],
                               "status": {"warnings": ["test diagnostic"]}})

    async def start(self):
        from fastmcp.server.dependencies import get_http_headers
        from fastmcp.server.middleware import Middleware
        owner = self
        class Capture(Middleware):
            async def on_call_tool(self, context, call_next):
                owner.headers.append(get_http_headers(include_all=True))
                return await call_next(context)

            async def on_list_tools(self, context, call_next):
                owner.list_tools_calls += 1
                return await call_next(context)
        self.mcp.add_middleware(Capture())
        sock = socket.socket()
        sock.bind(("127.0.0.1", self.port))
        self.port = sock.getsockname()[1]
        # Several Uvicorn servers share this test process. JSON responses avoid
        # sse-starlette's process-global shutdown flag coupling their lifecycles.
        app = self.mcp.http_app(stateless_http=True, json_response=True)
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
        self.task = asyncio.create_task(self.server.serve(sockets=[sock]))
        async with asyncio.timeout(10):
            while not self.server.started:
                if self.task.done():
                    await self.task
                await asyncio.sleep(0.01)
        return self

    async def stop(self):
        if self.task.done():
            return
        self.server.should_exit = True
        await asyncio.wait_for(self.task, 10)


class GatewayIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.alpha = await HttpNode("alpha").start()
        self.beta = await HttpNode("beta").start()
        self.addAsyncCleanup(self.alpha.stop)
        self.addAsyncCleanup(self.beta.stop)
        self.a = NodeConnection(
            device("alpha", self.alpha.port, transport="local"),
            health_timeout=10,
            call_timeout=15,
        )
        self.b = NodeConnection(device("beta", self.beta.port), health_timeout=10, call_timeout=15)
        self.addAsyncCleanup(self.a.stop)
        self.addAsyncCleanup(self.b.stop)

    async def gateway(self):
        class NoTunnel:
            last_error = None
            def __init__(self, *args): pass
            def start(self): pass
            async def stop(self): pass
        connections = {"alpha": self.a, "beta": self.b}
        app = GatewayApp(Config(mode="local", search_engine_dir=".", role="gateway"),
                         registry=DeviceRegistry([self.a.device, self.b.device]),
                         connection_factory=lambda d, **kwargs: connections[d.device_id], tunnel_factory=NoTunnel)
        return app, app.build()

    async def test_real_http_routing_schemas_origins_and_failure_isolation(self):
        app, mcp = await self.gateway()
        async with Client(mcp) as client:
            tools = {t.name: t for t in await client.list_tools()}
            self.assertIn("PowerShell", tools)
            self.assertIn("hybrid_code_search", tools)
            self.assertNotIn("alpha_PowerShell", tools)
            self.assertNotIn("beta_PowerShell", tools)
            shell_schema = tools["PowerShell"].inputSchema
            self.assertEqual(shell_schema["required"], ["command"])
            self.assertIn("device_id", shell_schema["properties"])

            result = await client.call_tool("PowerShell", {"command": "hostname"})
            self.assertIn("alpha:hostname", result.content[0].text)
            result = await client.call_tool("PowerShell", {"command": "hostname", "device_id": "beta"})
            self.assertIn("beta:hostname", result.content[0].text)

            result = await client.call_tool("get_file_range", {"path": "C:/repo/file.py"})
            self.assertIn("alpha", result.content[0].text)
            result = await client.call_tool(
                "get_file_range",
                {"path": "C:/repo/file.py", "device_id": "beta"},
            )
            self.assertIn("beta", result.content[0].text)

            result = await search_devices(app.connections, "query")
            self.assertEqual([h["deviceId"] for h in result["results"]], ["alpha", "beta"])
            self.assertTrue(all(h["score"] == 42 and h["repoId"] == "same-id" for h in result["results"]))
            self.assertFalse(result["partial"])
            self.assertEqual(result["nodeStatus"]["alpha"]["warnings"], ["test diagnostic"])
            aggregate = await client.call_tool("distributed_code_search", {"query": "query"})
            self.assertEqual(len(aggregate.structured_content["results"]), 2)

            health = await client.call_tool("device_health", {})
            self.assertEqual(health.structured_content["identity"]["device_id"], "alpha")
            remote_health = await client.call_tool("device_health", {"device_id": "beta"})
            self.assertEqual(remote_health.structured_content["identity"]["device_id"], "beta")

            self.alpha.identity = "wrong-device"
            await self.a.refresh()
            self.assertEqual(self.a.status.state, "offline")
            self.assertIn("PowerShell", {t.name for t in await client.list_tools()})
            with self.assertRaises(Exception):
                await client.call_tool("PowerShell", {"command": "must-not-run"})
            self.assertEqual(self.alpha.calls, 1)

            result = await client.call_tool(
                "PowerShell",
                {"command": "still-online", "device_id": "beta"},
            )
            self.assertIn("beta:still-online", result.content[0].text)
            result = await search_devices(app.connections, "query")
            self.assertTrue(result["partial"])
            self.assertEqual([h["deviceId"] for h in result["results"]], ["beta"])

            self.alpha.identity = "alpha"
            await self.a.refresh()
            self.assertEqual(self.a.status.state, "online")
            result = await client.call_tool("PowerShell", {"command": "recovered"})
            self.assertIn("recovered", result.content[0].text)

    async def test_cancelled_node_client_call_cancels_node_tool(self):
        await self.a.refresh()
        async with self.a.client() as client:
            call = asyncio.create_task(
                client.call_tool("PowerShell", {"command": "slow"})
            )
            async with asyncio.timeout(3):
                await self.alpha.power_shell_started.wait()

            call.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await call

            async with asyncio.timeout(3):
                await self.alpha.power_shell_cancelled.wait()

        self.assertTrue(self.alpha.cancel_request_ids)
        self.assertTrue(all(self.alpha.cancel_request_ids))

    async def test_gateway_call_timeout_cancels_node_tool(self):
        self.a.call_timeout = 2.0
        await self.a.refresh()
        _, mcp = await self.gateway()
        async with Client(mcp) as client:
            call = asyncio.create_task(
                client.call_tool("PowerShell", {"command": "slow"})
            )
            async with asyncio.timeout(3):
                await self.alpha.power_shell_started.wait()

            with self.assertRaises(Exception):
                await call

            async with asyncio.timeout(3):
                await self.alpha.power_shell_cancelled.wait()

    async def test_gateway_caps_oversized_tool_results(self):
        self.a.max_result_chars = 4_000
        await self.a.refresh()
        _, mcp = await self.gateway()
        async with Client(mcp) as client:
            result = await client.call_tool("PowerShell", {"command": "x" * 10_000})
            text = "".join(block.text for block in result.content if getattr(block, "type", "") == "text")
            self.assertLessEqual(len(text), 4_000)
            self.assertIn("MCP result truncated", text)
            self.assertIn("result", result.structured_content)
            self.assertLessEqual(len(result.structured_content["result"]), 2_000)
            self.assertIn("MCP result truncated", result.structured_content["result"])

    async def test_late_node_discovery_and_restart(self):
        port = self.beta.port
        await self.beta.stop()
        await self.b.refresh()
        self.assertEqual(await self.b.list_tools(), [])
        self.beta = await HttpNode("beta", port).start()
        self.addAsyncCleanup(self.beta.stop)
        await self.b.refresh()
        self.assertIn("PowerShell", {t.name for t in await self.b.list_tools()})
        result = await self.b.call("PowerShell", {"command": "restarted"})
        self.assertEqual(result, "beta:restarted")

    async def test_health_check_skips_schema_fetch_until_contract_changes(self):
        await self.a.refresh()
        initial = self.alpha.list_tools_calls
        self.assertGreater(initial, 0)
        await self.a.check_health()
        self.assertEqual(self.alpha.list_tools_calls, initial)
        self.alpha.tool_contract = "contract-v2"
        await self.a.check_health()
        refreshed = self.alpha.list_tools_calls
        self.assertGreater(refreshed, initial)
        await self.a.check_health()
        self.assertEqual(self.alpha.list_tools_calls, refreshed)

    async def test_schema_cache_survives_gateway_restart_while_node_offline(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = NodeSchemaCache(Path(folder) / "node-schema-cache.json")
            live = NodeConnection(self.a.device, health_timeout=10, call_timeout=15, schema_cache=cache)
            await live.refresh()
            self.assertIn("PowerShell", {t.name for t in await live.list_tools()})
            await live.stop()
            await self.alpha.stop()

            restored = NodeConnection(self.a.device, health_timeout=1, call_timeout=15, schema_cache=cache)
            self.assertIn("PowerShell", {t.name for t in await restored.list_tools()})
            await restored.check_health()
            self.assertEqual(restored.status.state, "offline")
            self.assertIn("PowerShell", {t.name for t in await restored.list_tools()})
            self.assertEqual(restored.status.identity.get("device_id"), "alpha")

    async def test_allowlist_applies_to_direct_and_aggregate_calls(self):
        self.a.device = replace(self.a.device, allowed_tools=["get_file_range"])
        await self.a.refresh()
        self.assertEqual(set(self.a._tools), {"get_file_range"})
        with self.assertRaises(ValueError):
            await self.a.call("PowerShell", {"command": "no"})
        result = await search_devices({"alpha": self.a}, "query")
        self.assertTrue(result["partial"])
        self.assertEqual(self.alpha.calls, 0)

    async def test_deadline_partial_result_and_repo_qualification(self):
        self.alpha.slow = True
        result = await search_devices({"alpha": self.a, "beta": self.b}, "query", timeout=5)
        self.assertTrue(result["partial"])
        self.assertEqual(result["results"][0]["deviceId"], "beta")
        result = await search_devices({"alpha": self.a, "beta": self.b}, "query",
                                      repo={"deviceId": "beta", "repoId": "unique"})
        self.assertEqual(result["results"][0]["repoId"], "unique")
        with self.assertRaises(ValueError):
            await search_devices({"beta": self.b}, "query", device_ids=["missing"])

    async def test_mutating_call_is_never_retried(self):
        self.alpha.fail = True
        _, mcp = await self.gateway()
        async with Client(mcp) as client:
            with self.assertRaises(Exception):
                await client.call_tool("PowerShell", {"command": "once"})
        self.assertEqual(self.alpha.calls, 1)

    async def test_private_http_strips_credentials_and_preserves_chat_identity(self):
        def factory(**kwargs):
            kwargs["headers"] = {"Authorization": "Bearer private-test", "Cookie": "secret",
                                 "Mcp-Session-Id": "gateway-session", "X-OpenAI-Session": "chat-42"}
            return private_http_client(**kwargs)
        transport = StreamableHttpTransport(self.a.device.url, httpx_client_factory=factory)
        async with VerifiedNodeClient(transport, expected_device="alpha", health_timeout=10, init_timeout=10, timeout=10) as client:
            await client.call_tool("PowerShell", {"command": "headers"})
        for headers in self.alpha.headers:
            self.assertNotIn("authorization", headers)
            self.assertNotIn("cookie", headers)
            self.assertNotEqual(headers.get("mcp-session-id"), "gateway-session")
            self.assertEqual(headers.get("x-openai-session"), "chat-42")


if __name__ == "__main__":
    unittest.main()
