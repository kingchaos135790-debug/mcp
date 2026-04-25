# ripgrep-treesitter-qdrant-mcp

`ripgrep-treesitter-qdrant-mcp` is a pure code-search and indexing engine repository.

It provides:

- semantic indexing and retrieval through Qdrant
- syntax-aware chunking through Tree-sitter
- lexical search through ripgrep when available
- a Windows-safe local lexical fallback when ripgrep is unavailable
- index freshness and coverage diagnostics for repository indexing
- a CLI bridge that other hosts can call for search and indexing commands

It does not act as the deployed MCP host for this setup anymore.

The combined MCP server now lives in:

`E:\Program Files\mcp\windows-code-search-mcp`

That Python host calls this repository through `dist\cli\run-core.js`.

## Repository layout

- `src/core/search-engine.ts` - reusable semantic, lexical, hybrid, health, and query-coverage warning operations
- `src/core/index-engine.ts` - reusable repository indexing, freshness, coverage, verification, and cleanup logic
- `src/core/repository-store.ts` - per-repository manifests and registry helpers
- `src/cli/run-core.ts` - CLI bridge used by external hosts such as `windows-code-search-mcp`
- `src/cli/index-repo.ts` - direct basic repository indexing CLI
- `src/lib/fs-utils.ts` - file discovery, coverage reporting, and text loading
- `src/lib/tree-sitter-utils.ts` - syntax-aware code chunk extraction
- `src/lib/qdrant-utils.ts` - Qdrant collection and semantic search helpers
- `src/lib/ripgrep-utils.ts` - ripgrep detection and lexical search helpers
- `src/lib/local-lexical-utils.ts` - local lexical index and fallback search helpers
- `scripts.index-repo.ps1` - PowerShell helper for basic indexing
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

The ChatGPT-facing Python MCP host also exposes `diagnose_index_repository`, which wraps `index_repository` with `mode=verify` and defaults to `hashMode=hash-all-candidates` for read-only freshness and coverage diagnostics.

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

PowerShell payloads are easier to maintain with `ConvertTo-Json`:

```powershell
cd "E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp"
$payload = @{ query = "vector normalize"; limit = 5 } | ConvertTo-Json -Compress
node .\dist\cli\run-core.js semantic_code_search $payload
```

## Build

```powershell
cd "E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp"
npm install
npm run check
npm run build
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

- the latest upstream Windows build path may fail on some machines
- the engine remains usable because lexical fallback is built in

## Index a repository

Basic indexing through the helper script:

```powershell
cd "E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp"
powershell -ExecutionPolicy Bypass -File .\scripts.index-repo.ps1 -RepoRoot C:\path\to\repo
```

Advanced indexing options are supported through the CLI bridge:

```powershell
cd "E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp"
$payload = @{
  repoRoot = "C:\path\to\repo"
  mode = "incremental"
  hashMode = "metadata-first"
} | ConvertTo-Json -Compress
node .\dist\cli\run-core.js index_repository $payload
```

Behavior:

- indexes semantic chunks into Qdrant
- writes per-repository manifests under `E:\mcp-index-data\repositories\<repoId>`
- writes a per-repository local lexical index
- uses incremental updates for unchanged, changed, and deleted indexed files by default
- reports indexed candidates separately from excluded repository files
- persists effective coverage and freshness strategy in the manifest

## Index modes

`index_repository` accepts a `mode` field. In the ChatGPT-facing Python MCP host, `diagnose_index_repository` is the dedicated wrapper for the `verify` mode.

| Mode | Behavior |
| --- | --- |
| `incremental` | Default. Reuses manifest metadata and only rebuilds indexed files that appear changed. |
| `force` | Rebuilds all indexed candidate files regardless of manifest metadata. |
| `verify` | Does not update Qdrant or local lexical artifacts. Reports manifest, coverage, Git, and optional hash verification diagnostics. |

Examples:

```powershell
$payload = @{ repoRoot = "C:\path\to\repo"; mode = "force" } | ConvertTo-Json -Compress
node .\dist\cli\run-core.js index_repository $payload
```

```powershell
$payload = @{
  repoRoot = "C:\path\to\repo"
  mode = "verify"
  hashMode = "hash-all-candidates"
} | ConvertTo-Json -Compress
node .\dist\cli\run-core.js index_repository $payload
```

## Hash modes

`index_repository` accepts a `hashMode` field.

| Hash mode | Behavior |
| --- | --- |
| `metadata-first` | Default fast path. Treats a file as unchanged when size and `mtimeMs` match the manifest. |
| `hash-changed-candidates` | Hashes files that metadata identifies as possible changes. |
| `hash-all-candidates` | Hashes all indexed candidate files. Slower but useful for stale-index verification. |

`mode=force` defaults to `hash-all-candidates`; other modes default to `metadata-first` unless specified.

## Coverage options

By default, indexing is code-oriented. Documentation, generated files, build outputs, dependencies, and unsupported extensions may be excluded.

`index_repository` accepts these coverage options:

| Option | Purpose |
| --- | --- |
| `includeDocs` | Includes common documentation extensions such as `.md`, `.mdx`, `.rst`, `.adoc`, and `.txt`. |
| `includeGenerated` | Allows common generated/build folders that are excluded by default. Dependency folders and Windows reserved device names remain excluded. |
| `extraExtensions` | Adds file extensions to indexed candidates, for example `.json`, `.yml`, or `.shader`. |
| `extraIncludeGlobs` | Adds include glob patterns. Ignore rules are still applied before include globs. |
| `extraExcludeGlobs` | Adds repository-specific exclude glob patterns. |
| `maxFileBytes` | Overrides the maximum indexed file size. Defaults to `MAX_SOURCE_FILE_BYTES` or `1048576`. |

Example:

```powershell
$payload = @{
  repoRoot = "C:\path\to\repo"
  includeDocs = $true
  includeGenerated = $false
  extraExtensions = @(".json", ".yml", ".yaml")
  extraIncludeGlobs = @("docs/**/*.md")
  maxFileBytes = 524288
} | ConvertTo-Json -Compress
node .\dist\cli\run-core.js index_repository $payload
```

Repositories can also define `.mcp-index.json` at the repository root:

```json
{
  "includeDocs": true,
  "includeGenerated": false,
  "extraExtensions": [".json", ".yml", ".yaml"],
  "extraIncludeGlobs": ["docs/**/*.md"],
  "extraExcludeGlobs": ["**/fixtures/**"],
  "maxFileBytes": 524288
}
```

The config file also accepts `include` and `exclude` aliases, which are merged into `extraIncludeGlobs` and `extraExcludeGlobs`.

## Index result fields

Recent `index_repository` responses include:

- `mode`
- `status`
- `manifestPath`
- `scannedFilesystemEntries`
- `indexedCandidateFiles`
- `changedIndexedFiles`
- `unchangedIndexedFiles`
- `deletedIndexedFiles`
- `excludedFiles.unsupportedExtension`
- `excludedFiles.ignoredGlob`
- `excludedFiles.tooLarge`
- `coverage.indexedExtensions`
- `coverage.ignoredGlobs`
- `coverage.includeDocs`
- `coverage.includeGenerated`
- `freshnessStrategy`
- `warnings`
- `git.available`
- `git.changedFiles`

In `mode=verify`, the response also includes `verification`, with manifest, missing-file, hash-mismatch, Git-changed, and recently excluded file details.

## Query-time coverage warnings

`lexical_code_search` and `hybrid_code_search` can warn when a query appears to target content outside the selected repository's index coverage.

Examples:

- queries containing `proposal`, `README`, `docs`, `documentation`, `markdown`, or `.md` can warn when docs are excluded
- queries containing `generated`, `dist`, `build`, `coverage`, `node_modules`, `bin`, `obj`, or `.next` can warn when generated/build paths are excluded

These warnings are diagnostic. They do not automatically search excluded files.

## Multi-repository behavior

- multiple repositories can be indexed side by side
- search accepts an optional repo reference using repo id, repo name, or repo root
- Qdrant points carry `repoId` metadata for repo-scoped semantic search
- lexical fallback indexes are stored per repository
- `list_indexed_repositories` and `server_health` expose stored coverage and freshness metadata when available

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
- Tree-sitter extraction currently focuses on JavaScript, TypeScript/TSX, and Python; other indexed extensions fall back to file-level chunks
- query-time coverage warnings are heuristic
- dedicated automated tests for the freshness/coverage scenarios have not been added yet
- this repository no longer includes or documents a standalone MCP host path
