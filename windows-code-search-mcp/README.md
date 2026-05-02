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

The server exposes direct-on-disk file editing tools and no longer registers VS Code bridge or VS Code editing tools.

MCP tools exposed for direct file inspection and edits:

- `get_file_range`
- `get_multiple_file_ranges`
- `request_file_edit`
- `safe_file_edit`
- `anchored_file_edit`
- `multi_anchor_file_edit`

Operational notes:

- After MCP server restarts, prefer the canonical `/Windows MCP/...` tool paths for follow-up calls. Cached linked tool paths can briefly return `Resource not found` until the tool list refreshes.
- Treat search hits, old line numbers, and earlier file reads as navigation hints only. Re-read exact numbered lines with `get_file_range` or `get_multiple_file_ranges` immediately before each write.
- Use `request_file_edit` for one exact direct-on-disk range edit and include `expected_text` by default so drift is detected instead of silently overwriting another change.
- Use `safe_file_edit` for one exact direct-on-disk text replacement when the target text is unique in the selected range.
- Use `anchored_file_edit` for one body replacement between exact start/end anchor lines.
- Use `multi_anchor_file_edit` for one logical change that replaces several anchored bodies in one validated request. Each edit item accepts `filePath`/`file_path`, `startAnchor`/`start_anchor`, `endAnchor`/`end_anchor`, `replacementText`/`replacement_text`, optional `expectedBody`/`expected_body`, and optional line-window fields.
- Multi-anchor edits are resolved and validated before any file is written. Overlapping anchored ranges in the same file are rejected.
- After any successful edit, re-read the affected range before issuing the next write from the same chat.

What this enables:

- MCP clients can inspect one or more files directly on disk with numbered lines before issuing validated edits.
- MCP clients can edit files directly on disk without depending on a VS Code session, bridge process, or editor state.
- MCP clients can batch multiple anchored body replacements across one or more files with `multi_anchor_file_edit`.

Search result normalization:
- `semantic_code_search`, `lexical_code_search`, and `hybrid_code_search` add a normalized `filePath` and `snippet` when available
- when the underlying engine provides location data, normalized hits expose it under `location` instead of synthesizing top-level edit-ready line ranges by default
- lexical hits still preserve their original fields such as `file`, `line`, and `snippet` for backward compatibility
- `hybrid_code_search` now applies a wrapper-level rerank to fused hits before returning them, favoring lexical corroboration, exact query phrase matches, identifier-aware feature-token overlap, and source files over generated artifacts such as `out/`, `dist/`, `.map`, and minified outputs; the original engine score remains a final tie-breaker
- treat search result locations as navigation hints; use `get_file_range` to obtain fresh numbered lines before editing

### Direct edit workflow

1. Read the exact numbered lines you plan to change with `get_file_range`, or read several files with `get_multiple_file_ranges`.
2. For one contiguous patch, call `request_file_edit` with fresh `expected_text`.
3. For one exact unique text replacement, call `safe_file_edit`.
4. For one anchored body replacement, call `anchored_file_edit`; `start_anchor` and `end_anchor` must match full line text exactly.
5. For several anchored body replacements, send one `multi_anchor_file_edit` payload and include `expectedBody` for each changed body when available.
6. If another chat changes the file and causes drift, re-read only the failed range, refresh expected text/body, and retry the narrowest safe edit.

Recommended tool selection:

| Goal | Preferred tool | Why |
| --- | --- | --- |
| Read one direct-on-disk file before an exact or anchored edit | `get_file_range` | returns fresh numbered lines and file metadata |
| Read several direct-on-disk files before coordinated edits | `get_multiple_file_ranges` | returns fresh numbered lines for multiple files from one request |
| Replace one exact range directly on disk | `request_file_edit` | applies one validated line-and-column edit |
| Replace one exact text match directly on disk | `safe_file_edit` | derives exact coordinates from one live on-disk match and validates the replacement |
| Replace one anchored body directly on disk | `anchored_file_edit` | replaces the body between exact start and end anchor lines |
| Replace several anchored bodies directly on disk | `multi_anchor_file_edit` | validates all anchor ranges first, then applies the batch |

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

- `semantic_code_search`
- `lexical_code_search`
- `hybrid_code_search`
- `server_health`
- `list_indexed_repositories`
- `index_repository`
- `diagnose_index_repository`
- `remove_indexed_repository`
- `list_auto_index_repositories`
- `add_auto_index_repository`
- `remove_auto_index_repository`

Search tools accept an optional `repo` argument so you can target one indexed codebase. `index_repository` supports `mode`, `hashMode`, and coverage options for freshness and index-coverage control; `diagnose_index_repository` runs the same engine verification path with `mode=verify` without updating Qdrant, local lexical artifacts, or managed auto-index status. `hybrid_code_search` also performs a post-engine rerank in the MCP wrapper so lexical corroboration and stronger feature matches surface ahead of semantic-only drift, while generated outputs are demoted.

Repo scoping accepts a repository root, repo name, or repo id when it resolves uniquely.

Manual indexing options exposed through `index_repository`:

| Option | Purpose |
| --- | --- |
| `mode` | `incremental`, `force`, or `verify`. Defaults to `incremental`. |
| `hashMode` | `metadata-first`, `hash-changed-candidates`, or `hash-all-candidates`. |
| `includeDocs` | Includes common documentation files such as `.md`, `.mdx`, `.rst`, `.adoc`, and `.txt`. |
| `includeGenerated` | Allows generated/build folders that are excluded by default, except dependency folders and Windows reserved names. |
| `extraExtensions` | Adds indexed extensions such as `.json`, `.yml`, or `.shader`. |
| `extraIncludeGlobs` | Adds include globs. Ignore rules still apply before include globs. |
| `extraExcludeGlobs` | Adds repository-specific exclude globs. |
| `maxFileBytes` | Overrides the maximum indexed file size. |

Use `diagnose_index_repository` when you need a read-only freshness and coverage report. It defaults to `hashMode=hash-all-candidates` and returns manifest, candidate-file, excluded-file, Git, and hash-mismatch diagnostics.

Current hybrid-search caveat:

- if indexed test files contain the exact query text, lexical hits from `tests/` can still outrank the product code
- wrapper reranking reduces semantic helper drift, but it does not replace index-time exclusion rules for `tests/`, generated files, or other non-product content
- for the cleanest results, prefer repo scoping and consider excluding `tests/`, `out/`, `dist/`, and similar paths at index time

## Auto indexing workflow

Local config file:

- `E:\\Program Files\\mcp\\windows-code-search-mcp\\managed-repositories.json`

You can edit that file directly to configure repo paths locally.

If you prefer a folder picker instead of editing JSON, run:

- `E:\\Program Files\\mcp\\open_windows_code_search_repo_manager.bat`

That opens a local Windows GUI where you can:

- browse for repo folders
- enable or disable `watch`
- enable or disable `auto_index_on_start`
- save the config
- trigger a one-off index for the selected repo

Minimal format:

```json
{
  "version": 1,
  "repositories": [
    {
      "repo_root": "E:\\\\src\\\\repo-one",
      "watch": true,
      "auto_index_on_start": true
    },
    {
      "repo_root": "E:\\\\src\\\\repo-two",
      "watch": true,
      "auto_index_on_start": false
    }
  ]
}
```

Notes:

- `repo_root` is required
- `watch` controls file-watch incremental reindexing
- `auto_index_on_start` controls startup reindexing
- `last_*` fields are maintained by the server automatically; you do not need to add them yourself
- startup and watch-driven index results are written back into `managed-repositories.json`

Search/index data locations on this machine:

- managed repo config: `E:\\Program Files\\mcp\\windows-code-search-mcp\\managed-repositories.json`
- manifest and lexical index root: `E:\\mcp-index-data`
- Qdrant vector storage root: `E:\\mcp-index-data\\qdrant`

Recommended MCP flow:

1. Call `add_auto_index_repository` with:
   - `repo_root`
   - optional `watch=true`
   - optional `auto_index_on_start=true`
   - optional `index_now=true`
2. The repo is persisted to `managed-repositories.json`.
3. On later server restarts, repos with `auto_index_on_start=true` are indexed automatically.
4. Repos with `watch=true` are watched for file changes and re-indexed incrementally.

You can also preload repos from the launcher with `AUTO_INDEX_REPOS`.

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

This reduces the chance that a post-crash server restart leaves the chat holding stale stateless tool handles without any transport session to invalidate.

If you explicitly want true stateless request handling again, set:

- `FASTMCP_STATELESS_HTTP=true`

However, the server runtime is still shared process-wide.

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
Because the current transport is stateless HTTP, do not rely on in-memory connection or transport session ids as the isolation key.

Use a stable identity derived from one of:

- OAuth subject
- token claims
- an explicit session header injected by the connector
- a signed session token

That key must stay stable across requests.

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













