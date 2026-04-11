# Global chat session behavior handoff

## Current state after the latest write-based patch

These changes are now on disk:

- `session_context.py` exists and is wired into the current flow.
- `server.py` was previously rewritten so runtime logs are grouped by server boot ID and can duplicate into per-session side logs.
- `server_config.py` has now been fully rewritten to persist boot-retained OAuth state plus token/session ownership.
- `server_extensions.py` has now been fully rewritten to use a shared session-binding wrapper for VS Code session-based tools.
- Fresh backups were created before the final direct-write pass:
  - `server_config.py.bak-chat-session-write`
  - `server_extensions.py.bak-chat-session-write`

## What is now implemented

### `server_config.py`

The persistent OAuth provider mixin now:

- tracks `run_count`
- tracks `last_boot_id`
- persists schema `version = 2`
- persists `access_token_session_map`
- persists `refresh_token_session_map`
- registers the token/session binder from `session_context.py`
- records token ownership during:
  - authorization-code exchange
  - refresh-token exchange
- restores chat-session identity during `load_access_token`
- prunes token/session ownership maps when tokens disappear or are revoked

### `server_extensions.py`

The VS Code extension path now includes:

- `bind_chat_session(session_id, required=True)`
- `session_bound_tool(...)`
- opportunistic binding in `create_vscode_session(...)`
- defaulted `session_id=""` plus `@session_bound_tool` for these tools:
  - `close_vscode_session`
  - `get_vscode_session`
  - `get_vscode_context`
  - `get_vscode_context_summary`
  - `get_vscode_diagnostics`
  - `get_vscode_file_range`
  - `request_vscode_edit`
  - `request_vscode_workspace_edit`
  - `safe_vscode_edit`
  - `open_vscode_file`

## Is it truly global per chat session?

Not fully at the host/platform level.

What is implemented now is:

- boot-retained OAuth state
- token-bound chat-session restoration
- session-bound VS Code tool behavior when the current request is already associated with a chat session or when the caller passes a session id

What is **still not guaranteed** by the current stack is true native host-global per-chat isolation unless one of these is also true:

- the host provides a stable chat/session identifier on every request, or
- each chat session uses a distinct OAuth token

Without one of those guarantees, the practical ceiling remains **token-bound per-chat restoration**, not fully host-native global chat isolation.

## Verification status

What was verified:

- both rewritten files were re-read from disk after the direct write pass
- the expected persistence and wrapper code is present on disk

What was **not** completed yet:

- `py_compile` or equivalent syntax validation
- a live end-to-end run with two chats and two tokens

## Recommended next step

Run a real validation pass:

1. start the server
2. authenticate from two separate chats using two distinct OAuth tokens
3. create or bind one VS Code session per chat
4. confirm that token reuse restores the correct chat session after restart
5. confirm that session-bound VS Code tools work without repeatedly passing `session_id`

## Practical summary

This patch completed the code path that the earlier handoff said was unfinished. The remaining limitation is architectural rather than purely implementation-level.
