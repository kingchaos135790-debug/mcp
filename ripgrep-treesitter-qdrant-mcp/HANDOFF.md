# Handoff and Runbook

This document describes the engine-only role of:

`E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp`

The repository is now a pure search and indexing engine. It is no longer the MCP host for the local ChatGPT setup.

## Current status on this PC

Confirmed working:

- project directory exists
- npm dependencies are installed
- TypeScript build succeeds
- `npm run check` succeeds
- compiled CLI output exists in `dist\cli`
- Qdrant is installed locally at `E:\Program Files\qdrant`
- Qdrant is reachable at `http://127.0.0.1:16333`
- repository indexing succeeds when Qdrant is reachable
- per-repository local lexical indexes are generated during indexing
- `lexical_code_search` works through ripgrep when available and the fallback path otherwise
- `hybrid_code_search` works using semantic plus the best lexical backend available

Optional but currently environment-dependent:

- ripgrep may not be installed on every Windows machine yet
- the local lexical fallback covers lexical search when ripgrep is unavailable

## Engine capabilities

### semantic_code_search

Queries Qdrant for semantically similar indexed code chunks.

### lexical_code_search

Queries ripgrep when it is available, otherwise uses the local lexical fallback.

### hybrid_code_search

Returns semantic, lexical, and fused sections using the best lexical backend available.

### server_health

Reports engine configuration, dependency readiness, and repository index state.

### list_indexed_repositories

Lists indexed repositories available for repo-scoped search.

### index_repository

Indexes a repository using incremental file-level updates.

### remove_indexed_repository

Deletes stored artifacts and vectors for a repository.

## Standard operating flow

1. Start Qdrant.
2. Verify Qdrant HTTP is reachable.
3. Build the engine if needed.
4. Index one or more repositories.
5. Call the engine through `dist\cli\run-core.js`, or let `windows-code-search-mcp` call it.

## Commands

### Build

```powershell
cd "E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp"
npm run build
npm run check
```

### Verify Qdrant

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:16333/collections
```

### Index a repo

```powershell
cd "E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp"
powershell -ExecutionPolicy Bypass -File .\scripts.index-repo.ps1 -RepoRoot C:\path\to\repo
```

### Run an engine command directly

```powershell
cd "E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp"
node .\dist\cli\run-core.js server_health "{}"
```

## Paths and ports in use

- project root: `E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp`
- Qdrant binary root: `E:\Program Files\qdrant`
- Qdrant URL: `http://127.0.0.1:16333`
- ripgrep is used directly from `PATH` when available for lexical search
- index root: `E:\mcp-index-data`
- repository registry: `E:\mcp-index-data\repositories.json`
- per-repo manifests: `E:\mcp-index-data\repositories\<repoId>`

## Integration note

The ChatGPT-facing MCP server is:

`E:\Program Files\mcp\windows-code-search-mcp\server.py`

That Python server shells out to this repository's CLI bridge instead of talking to it as a second MCP server.

## Operational notes

- semantic search currently uses a placeholder deterministic embedding function
- Qdrant is installed and reachable on this machine
- ripgrep availability depends on the machine `PATH`
- the built-in local lexical index is the current Windows-safe lexical backend

## Remaining work

Remaining mandatory work: none for baseline engine usage.

Remaining optional work:

- replace the placeholder embedding function with a real embedding model
- install ripgrep on Windows machines that should use the preferred lexical backend
- add more Tree-sitter grammars for additional languages
