from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import logging
import re
from typing import Callable

LOGGER = logging.getLogger(__name__)

_CURRENT_CHAT_SESSION_ID: ContextVar[str] = ContextVar("current_chat_session_id", default="")
_CURRENT_ACCESS_TOKEN: ContextVar[str] = ContextVar("current_access_token", default="")
_CURRENT_BOOT_ID: ContextVar[str] = ContextVar("current_boot_id", default="")
_SESSION_ID_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
_TOKEN_SESSION_BINDER: Callable[[str, str], None] | None = None


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
