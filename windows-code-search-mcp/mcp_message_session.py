from __future__ import annotations

import logging

from fastmcp.server.middleware import Middleware, MiddlewareContext

from session_context import (
    get_current_access_token,
    get_current_chat_session_id,
    get_current_request_session_id,
    normalize_chat_session_id,
    set_current_access_token,
    set_current_chat_session_id,
)

LOGGER = logging.getLogger(__name__)


class McpMessageSessionMiddleware(Middleware):
    """Bind FastMCP message execution to the logical MCP session, not the server task."""

    async def on_message(self, context: MiddlewareContext, call_next):
        # The initialize request has no FastMCP transport session yet. Avoid touching
        # Context.session_id here because that can create a synthetic fallback UUID.
        if context.method == "initialize" or context.fastmcp_context is None:
            return await call_next(context)

        # Prefer identity already bound by the current HTTP request. For ChatGPT this is
        # normally X-OpenAI-Session, which survives transport reconnects. Only fall back
        # to FastMCP's transport session when the request middleware had no stable key.
        session_id = get_current_request_session_id()
        if not session_id:
            try:
                session_id = normalize_chat_session_id(context.fastmcp_context.session_id)
            except RuntimeError:
                session_id = ""

        if not session_id:
            return await call_next(context)

        previous_session_id = get_current_chat_session_id()
        previous_access_token = get_current_access_token()

        set_current_access_token("")
        set_current_chat_session_id(session_id)
        try:
            LOGGER.debug(
                "FastMCP message bound to session: method=%s session=%s",
                context.method or "(unknown)",
                session_id,
            )
            return await call_next(context)
        finally:
            set_current_access_token(previous_access_token)
            set_current_chat_session_id(previous_session_id)
