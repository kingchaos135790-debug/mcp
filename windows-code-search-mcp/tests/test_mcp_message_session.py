import asyncio
from types import SimpleNamespace
import unittest

import session_context
from mcp_message_session import McpMessageSessionMiddleware


class McpMessageSessionMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        session_context.set_current_chat_session_id("")
        session_context.set_current_access_token("")

    async def asyncTearDown(self) -> None:
        session_context.set_current_chat_session_id("")
        session_context.set_current_access_token("")

    async def test_non_initialize_message_binds_fastmcp_session_and_restores_context(self) -> None:
        observed = {}
        middleware = McpMessageSessionMiddleware()
        context = SimpleNamespace(
            method="tools/call",
            fastmcp_context=SimpleNamespace(session_id="transport-session-a"),
        )

        session_context.set_current_chat_session_id("inherited-session")
        session_context.set_current_access_token("inherited-token")

        async def call_next(_context):
            observed["session"] = session_context.get_current_chat_session_id()
            observed["token"] = session_context.get_current_access_token()
            return "ok"

        result = await middleware.on_message(context, call_next)

        self.assertEqual(result, "ok")
        self.assertEqual(observed["session"], "transport-session-a")
        self.assertEqual(observed["token"], "")
        self.assertEqual(session_context.get_current_chat_session_id(), "inherited-session")
        self.assertEqual(session_context.get_current_access_token(), "inherited-token")

    async def test_initialize_does_not_force_session_id_before_transport_assigns_one(self) -> None:
        observed = {}
        middleware = McpMessageSessionMiddleware()
        context = SimpleNamespace(
            method="initialize",
            fastmcp_context=SimpleNamespace(session_id="would-be-generated-too-early"),
        )
        session_context.set_current_chat_session_id("initialize-fallback")

        async def call_next(_context):
            observed["session"] = session_context.get_current_chat_session_id()
            return "ok"

        await middleware.on_message(context, call_next)
        self.assertEqual(observed["session"], "initialize-fallback")

    async def test_concurrent_messages_do_not_share_execution_session(self) -> None:
        middleware = McpMessageSessionMiddleware()
        observed = []

        async def run_one(session_id: str) -> None:
            context = SimpleNamespace(
                method="tools/call",
                fastmcp_context=SimpleNamespace(session_id=session_id),
            )

            async def call_next(_context):
                before = session_context.get_current_chat_session_id()
                await asyncio.sleep(0.01)
                after = session_context.get_current_chat_session_id()
                observed.append((before, after))
                return None

            await middleware.on_message(context, call_next)

        await asyncio.gather(run_one("session-one"), run_one("session-two"))

        self.assertCountEqual(
            observed,
            [("session-one", "session-one"), ("session-two", "session-two")],
        )


if __name__ == "__main__":
    unittest.main()
