import asyncio
import unittest

import session_context
from session_context import McpSessionContextMiddleware


def make_scope(session_id: str = "") -> dict:
    headers = []
    if session_id:
        headers.append((b"mcp-session-id", session_id.encode("ascii")))
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }


async def empty_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def make_send(messages: list[dict]):
    async def send(message: dict) -> None:
        messages.append(message)

    return send


class McpSessionContextMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        session_context.set_current_chat_session_id("")
        session_context.set_current_access_token("")
        session_context.register_token_session_binder(None)

    async def asyncTearDown(self) -> None:
        session_context.set_current_chat_session_id("")
        session_context.set_current_access_token("")
        session_context.register_token_session_binder(None)

    async def test_incoming_mcp_session_is_bound_and_previous_context_is_restored(self) -> None:
        observed = {}

        async def app(scope, receive, send):
            observed["session"] = session_context.get_current_chat_session_id()
            observed["token"] = session_context.get_current_access_token()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        session_context.set_current_chat_session_id("outer-session")
        session_context.set_current_access_token("outer-token")
        middleware = McpSessionContextMiddleware(app)
        messages = []

        await middleware(make_scope("session-a"), empty_receive, make_send(messages))

        self.assertEqual(observed["session"], "session-a")
        self.assertEqual(observed["token"], "")
        self.assertEqual(session_context.get_current_chat_session_id(), "outer-session")
        self.assertEqual(session_context.get_current_access_token(), "outer-token")

    async def test_initialize_response_session_overrides_oauth_fallback_and_binds_token(self) -> None:
        bindings = []
        observed_after_response = {}
        session_context.register_token_session_binder(lambda token, session_id: bindings.append((token, session_id)))

        async def app(scope, receive, send):
            # Simulate authentication recovering an older token-level fallback before
            # FastMCP allocates the new transport session for this initialize request.
            session_context.set_current_access_token("shared-token")
            session_context.set_current_chat_session_id("old-fallback")
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"mcp-session-id", b"new-transport-session")],
                }
            )
            observed_after_response["session"] = session_context.get_current_chat_session_id()
            await send({"type": "http.response.body", "body": b""})

        middleware = McpSessionContextMiddleware(app)
        messages = []
        await middleware(make_scope(), empty_receive, make_send(messages))

        self.assertEqual(observed_after_response["session"], "new-transport-session")
        self.assertIn(("shared-token", "new-transport-session"), bindings)

    async def test_concurrent_requests_keep_transport_sessions_task_local(self) -> None:
        observed = []

        async def app(scope, receive, send):
            before = session_context.get_current_chat_session_id()
            await asyncio.sleep(0.01)
            after = session_context.get_current_chat_session_id()
            observed.append((before, after))
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = McpSessionContextMiddleware(app)

        async def run_one(session_id: str) -> None:
            messages = []
            await middleware(make_scope(session_id), empty_receive, make_send(messages))

        await asyncio.gather(run_one("session-a"), run_one("session-b"))

        self.assertCountEqual(
            observed,
            [("session-a", "session-a"), ("session-b", "session-b")],
        )


if __name__ == "__main__":
    unittest.main()
