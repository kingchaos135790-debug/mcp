# windows-code-search-mcp

Single MCP server that combines:

- Windows desktop/system tools from `Windows-MCP`
- code search/indexing tools from `ripgrep-treesitter-qdrant-mcp`

It reuses the Windows-MCP OAuth environment format and does not modify the original `Windows-MCP` source tree.

## Files

- `server.py` - integrated FastMCP server
- `server_app.py` - application composition and lifecycle orchestration
- `server_extensions.py` - pluggable MCP feature registration layer
- `server_runtime.py` - shared runtime services for search and auto-indexing
- `server_vscode_bridge.py` - local HTTP bridge for VS Code context, diagnostics, and edit requests
- `server_config.py` - config parsing and shared server settings
- `repo_manager.py` - local folder-picker GUI for managed repo paths
- `managed-repositories.json` - local persisted repo config
- `vscode-bridge-extension` - starter VS Code extension for context-window and IDE bridge sync
- `..\launch_windows_code_search_chatgpt_python.bat` - ChatGPT/OAuth launcher
- `..\open_windows_code_search_repo_manager.bat` - open the local repo manager window

## Extending the server

The server now composes features through extension classes instead of registering
everything in one monolithic file.

- add new MCP functionality by creating another extension in `server_extensions.py`
- register it in `server.py` when constructing `ServerApp`
- use `ServerContext` from `server_runtime.py` to access shared services like the search bridge, auto-indexer, desktop service, or analytics

This keeps future features isolated from startup/shutdown wiring and avoids adding more global state.

## VS Code bridge

The server now includes a lightweight local HTTP bridge so a VS Code extension can share editor state with MCP tools.

Bridge defaults:

- `VSCODE_BRIDGE_ENABLED=true`
- `VSCODE_BRIDGE_HOST=127.0.0.1`
- `VSCODE_BRIDGE_PORT=8876`
- `VSCODE_BRIDGE_TOKEN=` optional shared secret sent as `X-Bridge-Token`
- `MCP_INSTRUCTIONS_PATH=` optional path to a markdown file used as server instructions; defaults to `mcp-instructions.md`

MCP tools exposed for the bridge:

- `list_vscode_sessions`
- `get_vscode_session`
- `get_vscode_context`
- `get_vscode_context_summary`
- `get_vscode_file_range`
- `get_vscode_diagnostics`
- `request_vscode_edit`
- `request_vscode_workspace_edit`
- `open_vscode_file`

What this enables:

- a VS Code context window can push dropped snippets and file contents into a named editor session
- MCP clients can inspect lightweight VS Code context metadata without fetching full file contents
- MCP clients can read exact file ranges with numbered lines immediately before issuing validated edits
- MCP clients can inspect current IDE diagnostics from VS Code Problems data
- MCP clients can ask VS Code to apply exact line-and-column edits through the editor API instead of writing files blindly on disk; callers should include `expected_text` and re-read before follow-up edits

Search result normalization:

- `semantic_code_search`, `lexical_code_search`, and `hybrid_code_search` add a normalized `filePath` and `snippet` when available
- when the underlying engine provides location data, normalized hits expose it under `location` instead of synthesizing top-level edit-ready line ranges by default
- lexical hits still preserve their original fields such as `file`, `line`, and `snippet` for backward compatibility
- treat search result locations as navigation hints; use `get_vscode_file_range` to obtain fresh numbered lines before editing

The included starter extension lives in `vscode-bridge-extension` and polls the bridge for queued edit/open-file commands.

Current VS Code bridge UX:

- drag text into the `Code Search Bridge` context window
- use `Add Files...` for a reliable file import path from disk or workspace
- use the `Code Search Bridge: Add To Context Window` command from the Explorer, editor title, or tab context menu for a reliable VS Code-native file capture path
- use `Add Active Editor`, `Add Selection`, or `Add Open Editors` for explicit capture
- use `Push Now` after updating context if you want to force an immediate sync

Development and packaging:

- open `vscode-bridge-extension` in VS Code and press `F5` to launch the extension development host
- the extension includes `.vscode/launch.json` and `.vscode/tasks.json` for build + debug
- a packaged build is generated at `vscode-bridge-extension/windows-code-search-bridge-0.0.1.vsix`

## Launcher behavior

`launch_windows_code_search_chatgpt_python.bat` now:

- validates the integrated server, Windows-MCP, search engine, and Qdrant paths
- starts Qdrant automatically through `E:\Program Files\qdrant\start-qdrant.bat` if it is not already reachable on `http://127.0.0.1:16333`
- uses `E:\Program Files\qdrant\config\local.yaml` so Qdrant stores vectors under `E:\mcp-index-data\qdrant`
- exports `QDRANT_URL`, `QDRANT_COLLECTION`, and `INDEX_ROOT`
- sets `INDEX_ROOT=E:\mcp-index-data` for search manifests and local lexical indexes
- builds the TypeScript search core before starting the Python MCP host
- logs startup index status for each managed repository, including incremental `changedFiles`, `unchangedFiles`, and `deletedFiles`

## Search engine bridge

The Python server shells out to:

- `E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp\dist\cli\run-core.js`

That keeps the TypeScript repository focused on the search/index core instead of acting as the MCP host for this combined setup.

## Search capabilities

The integrated MCP exposes these search-side tools:

- `semantic_code_search`
- `lexical_code_search`
- `hybrid_code_search`
- `server_health`
- `list_indexed_repositories`
- `index_repository`
- `list_auto_index_repositories`
- `add_auto_index_repository`
- `remove_auto_index_repository`

Search tools accept an optional `repo` argument so you can target one indexed codebase, and `index_repository` now performs incremental file-level updates.

Repo scoping accepts a repository root, repo name, or repo id when it resolves uniquely.

## Auto indexing workflow

Local config file:

- `E:\Program Files\mcp\windows-code-search-mcp\managed-repositories.json`

You can edit that file directly to configure repo paths locally.

If you prefer a folder picker instead of editing JSON, run:

- `E:\Program Files\mcp\open_windows_code_search_repo_manager.bat`

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
      "repo_root": "E:\\src\\repo-one",
      "watch": true,
      "auto_index_on_start": true
    },
    {
      "repo_root": "E:\\src\\repo-two",
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

- managed repo config: `E:\Program Files\mcp\windows-code-search-mcp\managed-repositories.json`
- manifest and lexical index root: `E:\mcp-index-data`
- Qdrant vector storage root: `E:\mcp-index-data\qdrant`

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

