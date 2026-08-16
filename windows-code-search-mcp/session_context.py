from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import logging
import re
from typing import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

LOGGER = logging.getLogger(__name__)

_CURRENT_CHAT_SESSION_ID: ContextVar[str] = ContextVar("current_chat_session_id", default="")
_CURRENT_ACCESS_TOKEN: ContextVar[str] = ContextVar("current_access_token", default="")
_CURRENT_BOOT_ID: ContextVar[str] = ContextVar("current_boot_id", default="")
_SESSION_ID_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
_TOKEN_SESSION_BINDER: Callable[[str, str], None] | None = None
_MCP_SESSION_HEADER = b"mcp-session-id"


def normalize_chat_session_id(value: str | None) -> str:
    normalized = (value or "").strip()
    if not normalized:
        return ""
    normalized = _SESSION_ID_PATTERN.sub("-", normalized).strip("-.")
    if not normalized:
        return ""
    return normalized[:96]


def set_current_boot_id(boot_id: str | None) -> None:
    _CURRENT_BOOT_ID.set((boot_id or "").strip())


def get_current_boot_id() -> str:
    return _CURRENT_BOOT_ID.get().strip()


def set_current_access_token(token: str | None) -> None:
    _CURRENT_ACCESS_TOKEN.set((token or "").strip())


def get_current_access_token() -> str:
    return _CURRENT_ACCESS_TOKEN.get().strip()


def set_current_chat_session_id(session_id: str | None) -> None:
    _CURRENT_CHAT_SESSION_ID.set(normalize_chat_session_id(session_id))


def get_current_chat_session_id() -> str:
    return normalize_chat_session_id(_CURRENT_CHAT_SESSION_ID.get())


def register_token_session_binder(callback: Callable[[str, str], None] | None) -> None:
    global _TOKEN_SESSION_BINDER
    _TOKEN_SESSION_BINDER = callback


def bind_current_request_session(session_id: str | None) -> str:
    normalized = normalize_chat_session_id(session_id)
    if not normalized:
        return ""
    set_current_chat_session_id(normalized)
    access_token = get_current_access_token()
    if access_token and _TOKEN_SESSION_BINDER is not None:
        try:
            _TOKEN_SESSION_BINDER(access_token, normalized)
        except Exception as exc:
            LOGGER.warning("Failed to bind access token to chat session %s: %s", normalized, exc)
    return normalized


def _scope_header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1", errors="replace").strip()
    return ""


def _message_header(message: Message, name: bytes) -> str:
    for key, value in message.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1", errors="replace").strip()
    return ""


class McpSessionContextMiddleware:
    """Bind each HTTP request to its MCP transport session without sharing ContextVars across chats."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        previous_session_id = get_current_chat_session_id()
        previous_access_token = get_current_access_token()
        request_session_id = normalize_chat_session_id(_scope_header(scope, _MCP_SESSION_HEADER))
        response_session_id = ""
        response_status = 0

        # ContextVars are task-local, but clear both values explicitly so a reused task cannot
        # inherit authentication/session identity from an earlier request.
        set_current_access_token("")
        set_current_chat_session_id("")
        if request_session_id:
            bind_current_request_session(request_session_id)

        async def send_with_session_context(message: Message) -> None:
            nonlocal response_session_id, response_status
            if message.get("type") == "http.response.start":
                response_status = int(message.get("status", 0) or 0)
                response_session_id = normalize_chat_session_id(_message_header(message, _MCP_SESSION_HEADER))
                # The first initialize request has no Mcp-Session-Id header. FastMCP returns the
                # newly allocated session in the response, so capture it before the request exits.
                if response_session_id and not request_session_id:
                    bind_current_request_session(response_session_id)
                    LOGGER.info("MCP transport session established: session=%s", response_session_id)
            await send(message)

        try:
            LOGGER.debug(
                "MCP HTTP request start: method=%s path=%s session=%s",
                str(scope.get("method", "")),
                str(scope.get("path", "")),
                request_session_id or "(new)",
            )
            await self.app(scope, receive, send_with_session_context)
        finally:
            LOGGER.debug(
                "MCP HTTP request end: method=%s path=%s request_session=%s response_session=%s status=%s",
                str(scope.get("method", "")),
                str(scope.get("path", "")),
                request_session_id or "(new)",
                response_session_id or "(none)",
                response_status or "(unknown)",
            )
            set_current_access_token(previous_access_token)
            set_current_chat_session_id(previous_session_id)


@contextmanager
def active_chat_session(session_id: str | None):
    previous = get_current_chat_session_id()
    normalized = bind_current_request_session(session_id)
    if not normalized and previous:
        set_current_chat_session_id(previous)
    try:
        yield get_current_chat_session_id()
    finally:
        set_current_chat_session_id(previous)
