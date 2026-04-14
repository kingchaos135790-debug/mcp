# Refactor Proposal for `windows-code-search-mcp`

## Purpose

This document proposes a targeted refactor of `E:\Program Files\mcp\windows-code-search-mcp` to make the codebase easier to maintain, easier to extend, and more AI-friendly for code search, review, and patching.

The goal is **not** to redesign the server from scratch. The goal is to improve module boundaries, reduce responsibility drift, and keep source files below the preferred ceiling of **700 lines per file**.

## Executive Summary

The current architecture is usable and already has a reasonable top-level split:

- `server.py` is relatively thin
- `server_app.py` handles application composition and lifecycle
- `server_runtime.py` now acts as a thin compatibility surface for the extracted `runtime` package
- `server_vscode_bridge.py` isolates the VS Code bridge
- `session_context.py` is small and focused

The original highest-risk hotspot, `server_extensions.py`, has already been decomposed. The next major architectural concerns are now:

- keeping the newly split compatibility surfaces thin and stable
- strengthening tests around edit-safety and session/file-range behavior
- watching growth inside `extensions\vscode_edits.py`
- watching growth inside `runtime\repository_auto_indexer.py` and `config\oauth_state.py`

This makes the repo materially more friendly for AI-assisted editing because future changes can land in narrower files with less unrelated context.

## Current Assessment

### What is working

1. The code is not monolithic at the repo level.
2. The top-level intent of each file is mostly understandable.
3. Runtime services, bridge behavior, and app startup are already separated better than in many single-file MCP servers.
4. There is a focused test surface for the main server areas.
5. The registration and configuration compatibility layers are now thin.

### What still needs improvement

1. **Edit-safety coverage** can still be stronger around the VS Code edit paths.
2. **Runtime services** are now the clearest remaining orchestration-heavy growth point.
3. **Edit orchestration** in extensions\vscode_edits.py should be watched so it does not become the next mixed-responsibility hotspot.
4. Some larger modules still combine state management and orchestration that would benefit from narrower boundaries.

## Why This Matters for AI-Friendliness

AI-assisted maintenance works better when:

- one file maps to one feature area
- helpers are pure and isolated
- tool registration is thin
- symbol lookup is straightforward
- search results land in narrow, relevant files
- edits do not require loading unrelated context

The refactors already applied have improved this substantially, but the bridge and remaining orchestration-heavy modules still benefit from further decomposition.

## Primary Refactor Goals

1. Keep each Python source file under **700 lines**, with a practical preference for **200 to 500 lines** where reasonable.
2. Make each module correspond to **one primary responsibility**.
3. Reduce the amount of logic embedded directly inside large `register()` functions.
4. Separate **tool registration**, **domain logic**, **state management**, and **transport wiring**.
5. Preserve existing behavior and public MCP tool names unless there is a strong reason to change them.
6. Improve confidence for future edits by strengthening tests around the most fragile behavior.

## Hotspots to Refactor First

### 1. `server_extensions.py`

This was the original highest-priority target and has now been addressed through the `extensions` package split and a thin compatibility layer.

### 2. `server_config.py`

This was the next structural hotspot and has now been addressed through the `config` package split and a thin compatibility re-export surface.

### 3. `server_vscode_bridge.py`

This hotspot has now been addressed through the `vscode_bridge` package split and a thin compatibility re-export surface.

### 4. `server_runtime.py`

This hotspot has now been addressed through the `runtime` package split and a thin compatibility re-export surface.

### 5. Current remaining density hotspots

The clearest remaining growth points are now:

- `extensions\vscode_edits.py`
- `runtime\repository_auto_indexer.py`
- `config\oauth_state.py`

These modules are still within the preferred size range, but they are now the main places to watch for renewed responsibility drift.

## Proposed Target Structure

```text
windows-code-search-mcp/
  server.py
  server_app.py
  session_context.py
  bootstrap.py
  repo_manager.py

  config/
    __init__.py
    models.py
    loader.py
    managed_repositories.py
    oauth_state.py

  runtime/
    __init__.py
    context.py
    search_engine_bridge.py
    repository_auto_indexer.py

  extensions/
    __init__.py
    common.py
    search.py
    desktop.py
    vscode_sessions.py
    vscode_edits.py

  vscode_bridge/
    __init__.py
    models.py
    state.py
    transport.py
    server.py

  utils/
    file_ranges.py
    search_normalization.py
    text_normalization.py
```

This layout is not mandatory in exact form, but it captures the intended boundaries.

## Proposed Module Moves

### Split `server_extensions.py`

Completed through:

- `extensions/search.py`
- `extensions/desktop.py`
- `extensions/vscode_sessions.py`
- `extensions/vscode_edits.py`
- `extensions/common.py`
- `utils/file_ranges.py`
- `utils/text_normalization.py`
- `utils/search_normalization.py`

### Split `server_config.py`

Completed through:

- `config/models.py`
- `config/loader.py`
- `config/managed_repositories.py`
- `config/oauth_state.py`
- compatibility re-exports through `server_config.py`

### Split `server_vscode_bridge.py`

Completed through:

- `vscode_bridge/models.py`
  - `VSCodeCommand`, `VSCodeSession`
- `vscode_bridge/state.py`
  - `VSCodeBridgeState` and session/command queue behavior
- `vscode_bridge/transport.py`
  - transport and bridge request/response helpers
- `vscode_bridge/server.py`
  - `VSCodeBridgeServer` and HTTP request handling
- compatibility re-exports through `server_vscode_bridge.py`

### Split `server_runtime.py`

Completed through:

- `runtime/search_engine_bridge.py`
  - `SearchEngineBridge`
- `runtime/context.py`
  - `ServerContext`
- `runtime/repository_auto_indexer.py`
  - `RepositoryAutoIndexer`
- compatibility re-exports through `server_runtime.py`

## Recommended Design Principles

### 1. Thin registration and compatibility modules

Registration files and compatibility shims should mostly do three things:

- define or preserve stable import surfaces
- map tool parameters to domain functions
- format responses consistently

They should **not** own large amounts of parsing, matching, drift recovery, or state logic directly.

### 2. Prefer top-level handlers over deeply nested tool bodies

The current nested-tool style is valid, but it scales poorly. For AI-assisted editing, it is better when handlers are either:

- top-level functions, or
- small methods on focused extension classes

### 3. Separate pure logic from side-effecting logic

Examples:

- text normalization should be pure
- file range calculations should be pure except for the file read boundary
- drift detection and error classification should be pure where possible
- VS Code command dispatch should remain separate from payload normalization

### 4. Keep state containers small and explicit

State-heavy modules should expose a narrow API and avoid taking on formatting and policy logic that belongs elsewhere.

### 5. Preserve public tool surface during refactor

Tool names such as:

- `semantic_code_search`
- `lexical_code_search`
- `hybrid_code_search`
- `get_vscode_file_range`
- `request_vscode_edit`
- `safe_vscode_edit`

should remain stable unless there is a compelling compatibility reason to change them.

## Refactor Phases

### Phase 1: Extract pure helpers from `server_extensions.py`

Completed.

### Phase 2: Split extension registration by feature area

Completed.

### Phase 3: Split config/auth concerns

Completed.

### Phase 4: Split VS Code bridge internals

Completed.

### Phase 5: Runtime cleanup

Completed.

## Suggested Testing Strategy

Before or during the remaining refactors, add targeted tests around the most fragile behavior.

### Highest-value tests to add next

1. VS Code edit drift recovery
2. workspace edit retry behavior
3. anchor matching and mismatch errors
4. file-range reads with workspace-root enforcement
5. session-binding behavior for explicit and implicit session ids

### Testing principle

As logic moves into pure helper modules, add tests at that level instead of only exercising behavior through large integration-style entrypoints.

## Acceptance Criteria

The refactor should be considered successful if the following are true:

1. No primary Python source file exceeds **700 lines**.
2. `server_extensions.py` remains a thin composition layer.
3. `server_config.py` remains a thin compatibility layer and no longer mixes configuration loading and OAuth persistence in one file.
4. `server_vscode_bridge.py` is split or remains clearly below the size ceiling with tighter scope.
5. Public MCP tool names remain backward compatible.
6. Existing tests still pass.
7. New focused tests cover extracted helpers and edit safety logic.
8. A developer or AI can find the correct file for a change with minimal repo exploration.

## Non-Goals

This proposal does **not** recommend:

- rewriting the server in another language
- changing the MCP tool contract unnecessarily
- merging more logic into `server.py`
- introducing a large framework or plugin system beyond what is already needed
- changing behavior simply for stylistic reasons when structure can be improved incrementally

## Risks and Mitigations

### Risk: behavior drift during extraction

Mitigation:

- move pure helpers first
- keep signatures stable where possible
- add tests before changing logic boundaries

### Risk: too many files too quickly

Mitigation:

- split only along real responsibility boundaries
- avoid creating ultra-small files with no clear ownership benefit

### Risk: import churn during staged refactor

Mitigation:

- keep compatibility imports temporarily where useful
- migrate in phases instead of one large patch

## Final Recommendation

Proceed with an **incremental refactor**, not a rewrite.

Priority order now:

1. keep defending the thin compatibility layers with focused tests
2. add more direct coverage for session/file-range behavior and edit-safety paths
3. watch `extensions\vscode_edits.py`, `runtime\repository_auto_indexer.py`, and `config\oauth_state.py` for renewed responsibility drift

This should keep the repo easier to maintain, safer to patch, and more effective for AI-assisted code search and editing while preserving the current architecture and public MCP tool surface.

---

## Implementation Status Addendum

Since the original proposal was written, the refactor has progressed from proposal to implementation across all four original hotspot areas.

### Completed since the proposal draft

- helper extraction into `utils`
- `SearchExtension` moved to `extensions\search.py`
- `WindowsDesktopExtension` moved to `extensions\desktop.py`
- shared extension-layer helpers moved to `extensions\common.py`
- VS Code session/context tools moved to `extensions\vscode_sessions.py`
- VS Code edit/open-file tools moved to `extensions\vscode_edits.py`
- `server_extensions.py` kept as the compatibility composition/import surface for `server.py`
- `server_config.py` split into `config\models.py`, `config\loader.py`, `config\managed_repositories.py`, and `config\oauth_state.py`
- `server_config.py` kept as the compatibility re-export surface for existing imports
- `server_vscode_bridge.py` split into `vscode_bridge\models.py`, `vscode_bridge\state.py`, `vscode_bridge\transport.py`, and `vscode_bridge\server.py`
- `server_vscode_bridge.py` reduced to a thin compatibility re-export surface
- `server_runtime.py` split into `runtime\context.py`, `runtime\search_engine_bridge.py`, and `runtime\repository_auto_indexer.py`
- `server_runtime.py` reduced to a thin compatibility re-export surface
- a first focused test-strengthening pass was added in `tests\test_extensions_refactor.py`
- a second focused direct test pass was added for the remaining edit-safety edge cases

### Current structural state

- `server_runtime.py` is now **8 lines**
- `runtime\__init__.py` is **5 lines**
- `runtime\context.py` is **31 lines**
- `runtime\search_engine_bridge.py` is **151 lines**
- `runtime\repository_auto_indexer.py` is **402 lines**
- `server_config.py` is now **44 lines**
- `config\__init__.py` is **40 lines**
- `config\models.py` is **79 lines**
- `config\loader.py` is **68 lines**
- `config\managed_repositories.py` is **56 lines**
- `config\oauth_state.py` is **370 lines**
- `server_extensions.py` is now **69 lines**
- `extensions\common.py` is **133 lines**
- `extensions\vscode_sessions.py` is **228 lines**
- `extensions\vscode_edits.py` is **394 lines**
- `extensions\search.py` is **187 lines**
- `extensions\desktop.py` is **17 lines**
- desktop, search, session, and edit registration are no longer defined inline in `server_extensions.py`
- configuration/loading, managed-repository helpers, and OAuth persistence are no longer defined inline in `server_config.py`
- runtime bridge/context/indexer implementation is no longer defined inline in `server_runtime.py`
- `server_extensions.py`, `server_config.py`, `server_runtime.py`, and `server_vscode_bridge.py` now act as thin compatibility layers

### Current test state

Direct `pytest` execution is still unavailable in the current environment because `pytest` is not installed.

Attempted command:

- `py -3 -m pytest -q`

Observed result:

- `No module named pytest`

However, the repository tests are `unittest`-compatible and were run successfully with:

- `py -3 -m unittest discover -s tests -v`

Observed result:

- **34 tests ran and passed**

That test surface now includes direct coverage for:

- `extensions\common.py` helper behavior
- compatibility re-exports from `server_extensions.py`
- registration boundaries between `VSCodeSessionExtension` and `VSCodeEditExtension`
- workspace-edit line-ending normalization behavior
- drift retry behavior for `request_vscode_edit`
- ranged refresh behavior for `request_vscode_workspace_edit`
- single-match and multi-match `safe_vscode_edit` behavior
- expected-body mismatch handling for `anchored_vscode_edit`
- persistent OAuth session-ownership continuity paths through `server_config.py`
- runtime command bridge and repository-config repair behavior through `server_runtime.py`

### Updated priority

The `server_extensions.py`, `server_config.py`, `server_vscode_bridge.py`, and `server_runtime.py` splits are now in a good state and no longer represent the primary refactor bottlenecks.

The highest-value supporting safety work still worth adding is:

- more direct tests for session/file-range behavior in `extensions\vscode_sessions.py`

The clearest structural modules to keep watching next are:

- `extensions\vscode_edits.py`
- `runtime\repository_auto_indexer.py`
- `config\oauth_state.py`

### Practical next move

A sensible next implementation sequence is:

1. add more direct tests for session binding and file-range behavior in `extensions\vscode_sessions.py`
2. evaluate whether `extensions\vscode_edits.py` should be narrowed further if edit orchestration continues to accumulate there
3. evaluate whether `runtime\repository_auto_indexer.py` should be narrowed further if watcher lifecycle, persistence, and indexing orchestration continue to grow
