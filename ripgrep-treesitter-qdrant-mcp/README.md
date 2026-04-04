# ripgrep-treesitter-qdrant-mcp

`ripgrep-treesitter-qdrant-mcp` is a pure code-search and indexing engine repository.

It provides:

- semantic indexing and retrieval through Qdrant
- syntax-aware chunking through Tree-sitter
- lexical search through ripgrep when available
- a Windows-safe local lexical fallback when ripgrep is unavailable
- a CLI bridge that other hosts can call for search and indexing commands

It does not act as the deployed MCP host for this setup anymore.

The combined MCP server now lives in:

`E:\Program Files\mcp\windows-code-search-mcp`

That Python host calls this repository through `dist\cli\run-core.js`.

## Repository layout

- `src/core/search-engine.ts` - reusable semantic, lexical, hybrid, and health operations
- `src/core/index-engine.ts` - reusable repository indexing and cleanup logic
- `src/core/repository-store.ts` - per-repository manifests and registry helpers
- `src/cli/run-core.ts` - CLI bridge used by external hosts such as `windows-code-search-mcp`
- `src/cli/index-repo.ts` - direct repository indexing CLI
- `src/lib/fs-utils.ts` - file discovery and text loading
- `src/lib/tree-sitter-utils.ts` - syntax-aware code chunk extraction
- `src/lib/qdrant-utils.ts` - Qdrant collection and semantic search helpers
- `src/lib/ripgrep-utils.ts` - ripgrep detection and lexical search helpers
- `src/lib/local-lexical-utils.ts` - local lexical index and fallback search helpers
- `scripts.index-repo.ps1` - PowerShell helper for indexing a repository
- `scripts.setup-deps.ps1` - dependency setup reference commands

## Supported engine commands

The CLI bridge in `dist\cli\run-core.js` accepts these commands:

- `semantic_code_search`
- `lexical_code_search`
- `hybrid_code_search`
- `server_health`
- `list_indexed_repositories`
- `index_repository`
- `remove_indexed_repository`

Example:

```powershell
cd "E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp"
node .\dist\cli\run-core.js server_health "{}"
```

Example with payload:

```powershell
cd "E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp"
node .\dist\cli\run-core.js semantic_code_search "{\"query\":\"vector normalize\",\"limit\":5}"
```

## Build

```powershell
cd "E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp"
npm install
npm run build
npm run check
```

## Runtime dependencies

### Qdrant

Expected local URL:

`http://127.0.0.1:16333`

Typical local installation on this machine:

`E:\Program Files\qdrant`

Quick check:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:16333/collections
```

### ripgrep

ripgrep is preferred for lexical search. If it is unavailable, the engine falls back to the local lexical index automatically.

Current machine note:

- the latest upstream Windows build path is still failing
- the engine remains usable because lexical fallback is built in

## Index a repository

```powershell
cd "E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp"
powershell -ExecutionPolicy Bypass -File .\scripts.index-repo.ps1 -RepoRoot C:\path\to\repo
```

Behavior:

- indexes semantic chunks into Qdrant
- writes per-repository manifests under `E:\mcp-index-data\repositories\<repoId>`
- writes a per-repository local lexical index
- uses incremental updates for unchanged, changed, and deleted files

## Multi-repository behavior

- multiple repositories can be indexed side by side
- search accepts an optional repo reference using repo id, repo name, or repo root
- Qdrant points carry `repoId` metadata for repo-scoped semantic search
- lexical fallback indexes are stored per repository

Current machine data locations:

- manifest and lexical index root: `E:\mcp-index-data`
- repository registry: `E:\mcp-index-data\repositories.json`
- per-repo manifests: `E:\mcp-index-data\repositories\<repoId>`
- Qdrant vector storage: `E:\mcp-index-data\qdrant\storage`

## How this repo is intended to be used

This repository is intended to be consumed in one of two ways:

1. directly as an engine CLI for indexing and search operations
2. indirectly through the Python MCP host in `windows-code-search-mcp`

In the current local setup, the ChatGPT-facing launcher is:

`E:\Program Files\mcp\launch_windows_code_search_chatgpt_python.bat`

That launcher starts the Python MCP host, which shells out to this repository's CLI bridge.

## Current limitations

- semantic search still uses a placeholder deterministic embedding function
- ripgrep may be absent on some Windows setups, but the local lexical fallback still keeps lexical search usable
- Tree-sitter extraction currently focuses on JavaScript, TypeScript/TSX, and Python
- this repository no longer includes or documents a standalone MCP host path
