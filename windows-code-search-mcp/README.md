# windows-code-search-mcp

Single MCP server that combines:

- Windows desktop/system tools from `Windows-MCP`
- code search/indexing tools from `ripgrep-treesitter-qdrant-mcp`

It reuses the Windows-MCP OAuth environment format and does not modify the original `Windows-MCP` source tree.

## Files and packages

- `server.py` - integrated FastMCP server entrypoint
- `server_app.py` - application composition and lifecycle orchestration
- `server_extensions.py` - thin compatibility and composition layer for MCP feature registration
- `server_runtime.py` - thin compatibility re-export layer for the `runtime` package
- `server_config.py` - thin compatibility re-export layer for the `config` package
- `server_vscode_bridge.py` - thin compatibility re-export layer for the `vscode_bridge` package
- `extensions/` - feature registration modules for search, desktop, VS Code session, and VS Code edit tools
- `runtime/` - shared runtime services such as `ServerContext`, the search bridge, and repository auto-indexing
- `config/` - config models, environment loading, managed-repository helpers, and OAuth persistence
- `vscode_bridge/` - internal bridge package for bridge models, state, transport, and server orchestration
- `utils/` - extracted helper modules for normalization and file-range behavior
- `repo_manager.py` - local folder-picker GUI for managed repo paths
- `managed-repositories.json` - local persisted repo config
- `oauth-state.json` - local persisted OAuth provider state
- `vscode-bridge-extension` - starter VS Code extension for context-window and IDE bridge sync
- `..\\launch_windows_code_search_chatgpt_python.bat` - ChatGPT/OAuth launcher
- `..\\open_windows_code_search_repo_manager.bat` - open the local repo manager window

## Extending the server

The server now composes features through extension classes instead of registering
everything in one monolithic file.

- add new MCP functionality by creating another extension in `extensions/` and keep `server_extensions.py` as the thin composition layer
- register it in `server.py` when constructing `ServerApp`
- use `ServerContext` from `server_runtime.py` to access shared services like the search bridge, auto-indexer, desktop service, or analytics

This keeps future features isolated from startup/shutdown wiring and avoids adding more global state.

## File editing tools

The server exposes a compact direct-on-disk inspection/edit surface and does not register the older VS Code editing wrappers.

MCP tools exposed for direct file inspection and edits:

- `get_file_range`
- `get_multiple_file_ranges`
- `replace_range_or_anchor`
- `multi_anchor_file_edit`

Operational notes:

- Treat search hits, old line numbers, and earlier file reads as navigation hints only. Re-read exact numbered lines with `get_file_range` or `get_multiple_file_ranges` immediately before each write.
- Use `replace_range_or_anchor` for normal edits. It supports a unique `expected_text` match, exact start/end anchors, or an explicit line/column range. It also accepts `expected_sha256` from the read tools and supports `dry_run`.
- Use `multi_anchor_file_edit` for one logical change that replaces several anchored bodies in one validated request. All anchor ranges are resolved before any file is written, and overlapping ranges are rejected.
- After a successful edit, re-read the affected range before issuing the next dependent write.

Search result normalization:

- `hybrid_code_search` returns normalized `filePath` and `snippet` fields when available.
- Hybrid search internally combines semantic and lexical search, adds `exact_matches` for strong live lexical matches, and annotates result sources such as `semantic_index`, `live_lexical`, and `hybrid_fused`.
- Search result locations are navigation hints; use `get_file_range` to obtain fresh numbered lines before editing.

### Direct edit workflow

1. Read the exact numbered lines with `get_file_range`, or read several files with `get_multiple_file_ranges`.
2. Use `replace_range_or_anchor` with `expected_text`, exact anchors, or line/column coordinates. Prefer `expected_sha256` when a fresh read supplied it.
3. Use `dry_run=true` when you want to verify the selected anchor/range without writing.
4. For several anchored replacements, use `multi_anchor_file_edit` and include `expectedBody` for each changed body when available.

Recommended tool selection:

| Goal | Preferred tool | Why |
| --- | --- | --- |
| Read one file before editing | `get_file_range` | returns fresh numbered lines, metadata, and a content hash |
| Read several files before coordinated edits | `get_multiple_file_ranges` | batches fresh numbered reads |
| Replace one guarded range using text, anchors, or coordinates | `replace_range_or_anchor` | consolidates the former single-edit variants and supports hash guards/dry-run |
| Replace several anchored bodies | `multi_anchor_file_edit` | validates the full batch before writing |

## Workspace summary tools

The server exposes one read-only Git workspace summary tool:

- `workspace_patch_summary` summarizes current Git status, changed files, diff stats, staged changes, and optionally a bounded raw diff.

Use it after a series of edits or before handoff to report the current patch.

## Windows system tools

Only these Windows-side tools are registered by the integrated server:

- `PowerShell`
- `FileSystem`

Desktop/UI automation tools such as `Screenshot`, `Snapshot`, `Click`, `Type`, `Scroll`, `Move`, `Shortcut`, `MultiSelect`, `MultiEdit`, `Clipboard`, `Process`, `Notification`, `Registry`, `App`, `Scrape`, and `Wait` are not registered.

## Launcher behavior

`launch_windows_code_search_chatgpt_python.bat` now:

- validates the integrated server, Windows-MCP, search engine, and Qdrant paths
- starts Qdrant automatically through `E:\\Program Files\\qdrant\\start-qdrant.bat` if it is not already reachable on `http://127.0.0.1:16333`
- uses `E:\\Program Files\\qdrant\\config\\local.yaml` so Qdrant stores vectors under `E:\\mcp-index-data\\qdrant`
- exports `QDRANT_URL`, `QDRANT_COLLECTION`, and `INDEX_ROOT`
- sets `INDEX_ROOT=E:\\mcp-index-data` for search manifests and local lexical indexes
- builds the TypeScript search core before starting the Python MCP host
- logs runtime diagnostics to the console, and to `windows-code-search-mcp-runtime.log` when `MCP_LOG_DIR` is set
- logs startup index status for each managed repository, including incremental `changedFiles`, `unchangedFiles`, and `deletedFiles`

## Search engine bridge

The Python server shells out to:

- `E:\\Program Files\\mcp\\ripgrep-treesitter-qdrant-mcp\\dist\\cli\\run-core.js`

That keeps the TypeScript repository focused on the search/index core instead of acting as the MCP host for this combined setup.

## Search capabilities

The integrated MCP exposes these search-side tools:

- `hybrid_code_search`
- `server_health`
- `list_indexed_repositories`

`hybrid_code_search` is the single agent-facing code-search entry point. It internally combines semantic and lexical retrieval, supplements live lexical matches, and reranks fused results before returning them.

`list_indexed_repositories` remains available so clients can discover repository names, IDs, and roots for repo-scoped lookup. Repo scoping accepts a repository root, repo name, or repo id when it resolves uniquely.

Repository index creation, removal, diagnostics, and auto-index enrollment are intentionally not exposed as MCP tools. Those operations remain available to the server runtime or external index-management tooling rather than the agent-facing surface.

Current hybrid-search caveat:

- if indexed test files contain the exact query text, lexical hits from `tests/` can still outrank the product code
- wrapper reranking reduces semantic helper drift, but it does not replace index-time exclusion rules for `tests/`, generated files, or other non-product content
- for the cleanest results, prefer repo scoping and appropriate index coverage/exclusion settings

## Auto indexing workflow

The auto-indexer runtime remains enabled because it owns startup indexing and file-change incremental reindexing. Removing that runtime would disable automatic reindexing when watched repositories change.

Managed repository config:

- `E:\\Program Files\\mcp\\windows-code-search-mcp\\managed-repositories.json`

Behavior:

- repositories with `auto_index_on_start=true` are incrementally indexed when the MCP server starts
- repositories with `watch=true` are watched for file changes and incrementally reindexed by the runtime watcher
- managed coverage settings such as `include_docs`, `include_generated`, `extra_extensions`, include/exclude globs, and `max_file_bytes` are reused for startup/watch indexing
- startup and watch-driven results are written back into `managed-repositories.json`

The agent-facing index-management tools have been removed. Repository enrollment and index-management changes should be made externally, for example through the managed config, `open_windows_code_search_repo_manager.bat`, launcher configuration such as `AUTO_INDEX_REPOS`, or a separate index-management tool. `list_indexed_repositories` remains exposed for discovering repositories that can be searched.

Search/index data locations on this machine:

- managed repo config: `E:\\Program Files\\mcp\\windows-code-search-mcp\\managed-repositories.json`
- manifest and lexical index root: `E:\\mcp-index-data`
- Qdrant vector storage root: `E:\\mcp-index-data\\qdrant`

## Authentication, restart behavior, and multi-chat isolation

### Current authentication model

The current OAuth provider is token-based, not connection-based, and token state is now persisted locally so it can survive Python server restarts.

Relevant implementation details:

- `server_config.py` now builds auth with `PersistentStaticClientOAuthProvider` or `PersistentInMemoryOAuthProvider`
- both wrappers persist the underlying FastMCP in-memory OAuth state to disk and reload it on startup
- the default state file is `E:\\Program Files\\mcp\\windows-code-search-mcp\\oauth-state.json`
- you can override the location with `OAUTH_STATE_PATH`

Practical consequences:

- bearer tokens are not tied to one TCP connection
- a plain Cloudflare tunnel reconnect should not invalidate auth by itself if the Python server process stays alive and the public base URL is unchanged
- a Python server restart should preserve existing OAuth clients, authorization codes, access tokens, and refresh tokens by reloading the persisted state file
- if the state file is deleted, corrupted, or was never populated before the restart, clients can still see `401 Unauthorized` and may need to complete OAuth again once

### Tunnel reconnects versus server restarts

Observed behavior can look connection-based even though it is process-lifetime based.

Use this rule of thumb:

- tunnel reconnect only: auth should usually continue to work if the MCP server process did not restart
- MCP server restart: auth should usually continue to work because token state is now persisted and reloaded on startup

In practice, one fresh successful OAuth flow may still be needed after deploying this change so the persisted state file is populated for future restarts.

### OAuth discovery metadata and tunnel origin requirements

The server now exposes both standard OAuth discovery endpoints:

- `/.well-known/openid-configuration`
- `/.well-known/oauth-authorization-server`

These endpoints return metadata derived from `OAUTH_BASE_URL`, including the issuer, authorization endpoint, token endpoint, supported grant types, supported response types, supported PKCE method, token endpoint auth method, and configured scopes.

Why this matters:

- some MCP clients and connector flows expect OAuth discovery to succeed before or during tool-calling setup
- a missing discovery document can make the server look unresponsive even when `/mcp`, `/authorize`, and `/token` are otherwise reachable

Tunnel and origin notes:

- prefer a tunnel origin of `127.0.0.1:8000`, not `localhost:8000`
- this avoids IPv6 `::1` resolution mismatches where the tunnel reaches `localhost` over IPv6 but the MCP server is only listening on `127.0.0.1`
- if Cloudflare logs show connection failures to `dial tcp [::1]:8000`, treat that as an origin-binding problem, not a tool-handler failure

### Concurrent access today

The launcher now defaults to stateful streamable HTTP and leaves true stateless mode opt-in:

- `FASTMCP_STATELESS_HTTP=false`

Stateful requests are now bound to the MCP transport's `Mcp-Session-Id` in request-local `ContextVar` state. The transport session is authoritative for the active request; OAuth token-to-session mappings are only a fallback because one ChatGPT OAuth credential may be reused by several MCP sessions.

OAuth state mutations and persistence are serialized. The launcher also defaults `OAUTH_STATE_MAX_TOKENS=0`; if a positive soft cap is configured, valid credentials are retained and only expired token pairs are removed. A new chat must not revoke another live connector merely because its token lacks a custom chat-session binding.

If you explicitly want true stateless request handling again, set:

- `FASTMCP_STATELESS_HTTP=true`

However, the interactive server runtime is still shared process-wide.

`server_app.py` creates one shared:

- `ServerContext`
- `Desktop`
- `WatchDog`
- `RepositoryAutoIndexer`

`server_runtime.py` adds some protection for shared mutating operations:

- `_config_lock` serializes repo config updates
- `_index_lock` serializes indexing runs

The integrated launcher also disables the Windows UIA watchdog thread by default:

- `WINDOWS_MCP_WATCHDOG_ENABLED=false`

That watchdog is only needed for live desktop focus monitoring, and disabling it avoids the `comtypes` event-pump crash path that was taking down the whole combined server during otherwise non-desktop repo work.

Practical consequences:

- multiple chat sessions can access the same MCP server concurrently
- read-heavy search workflows are the safest for concurrent use
- desktop automation, clipboard, active-window interactions, process operations, shell commands, and VS Code editing still operate on shared machine state and can interfere across chats
- this is concurrent access, not per-chat runtime isolation

### Multi-chat edit behavior today

The VS Code bridge already has one useful isolation primitive: `session_id`.

Context reads, diagnostics, open-file requests, and edit requests are all scoped to one bridge session, so separate chats can keep separate editor context snapshots as long as they use different session ids.

However, `session_id` is not a file lock.

Two chats can still edit the same on-disk file if their sessions point at the same workspace copy. The current safety model is optimistic concurrency based on fresh reads plus `expected_text` or `expectedText`.

Practical rules for multi-chat editing today:

- use a distinct `session_id` per chat when possible
- batch related changes into one `request_vscode_workspace_edit` call instead of many sequential edits
- re-read the exact range before each follow-up edit after any failed, delayed, or cross-chat operation
- do not assume window focus, clipboard state, or desktop automation are isolated just because VS Code session context is separated

### Per-chat isolation guidance
For stateful Streamable HTTP, use `Mcp-Session-Id` as the request-local isolation key whenever it is present. The initialization response establishes the new transport session, and subsequent requests restore that session before authentication and tool execution.

Do not use a bearer token as a one-to-one chat identity. ChatGPT can reuse one OAuth credential across several MCP transport sessions, so the persisted token-to-session association is deliberately fallback-only and is never allowed to overwrite the current transport session.

If a future connector or transport does not provide `Mcp-Session-Id`, derive a stable fallback identity from an authenticated subject, token claims, an explicit connector session header, or a signed session token.

This protects connector/auth state across concurrent chats. It does not make Windows desktop, clipboard, shell/process state, or other machine-global interactive resources independent per chat; those still require a per-session runtime if stronger isolation is needed.

Recommended architecture:

1. Keep search and indexing as shared infrastructure.
   - Qdrant
   - repo manifests
   - lexical and semantic search
   - repo add/remove/index operations guarded by locks
2. Move interactive runtime state behind a per-chat or per-session runtime.
   - desktop automation
   - clipboard
   - shell/process/window tools
   - DOM-active browser scraping
   - VS Code edit context
3. Resolve the runtime from a stable authenticated session key on each request instead of storing one global interactive context for all callers.
4. Add TTL cleanup for idle per-session runtimes.

### Isolation options

#### Option 1: one server worker per chat

Best isolation and simplest reasoning model.

Each chat gets its own worker process with its own runtime objects. This is the cleanest option if the system will be used by multiple chats concurrently for interactive tools.

#### Option 2: one shared HTTP server with a per-session runtime registry

Lower overhead, but requires more refactoring.

Conceptually:

```python
contexts: dict[str, SessionRuntime]

async def get_runtime(session_key: str) -> SessionRuntime:
    runtime = contexts.get(session_key)
    if runtime is None:
        runtime = SessionRuntime(session_key)
        contexts[session_key] = runtime
    return runtime
```

Tool handlers should resolve runtime state from the current request identity instead of reading from one shared global `ServerContext.desktop` or similar singleton fields.

#### Option 3: mixed model

Use one shared server for read-only search tools and separate per-session workers only for interactive tools.

This is usually the best tradeoff for this repository.

### Recommended next refactor in this repo

If refactoring incrementally, prefer this order:

1. keep the existing shared search/indexing backend
2. introduce a `SessionRuntimeManager` for interactive tools
3. derive a stable session key from OAuth or connector-provided identity
4. route interactive tools through session-scoped runtimes
5. keep repo and search tools shared unless stronger isolation is needed later

This avoids relying on transport connection state while making the most conflict-prone tools safe for concurrent multi-chat use.

### Recommended edit contract for multiple chats

Until interactive runtimes become session-scoped, document the edit contract as:

- search first to locate the right file or symbol
- use the current VS Code session, context, and diagnostics when available
- read exact numbered lines immediately before the change
- apply the smallest safe edit
- include `expected_text` or `expectedText` by default
- batch related edits from a single fresh snapshot
- re-read the file after each successful write before issuing another edit

That contract does not eliminate conflicts, but it makes multi-chat edits predictable, reviewable, and recoverable.













