# Refactor Next-Step Handoff

## Scope

This handoff captures the current refactor status for `E:\Program Files\mcp\windows-code-search-mcp` after:

- the helper extraction pass
- the desktop/search extension split
- the VS Code bridge extension split
- the first targeted test-strengthening pass for the new extension layout
- the `server_config.py` split into a focused `config` package
- the `server_runtime.py` split into a focused `runtime` package
- the second targeted test-strengthening pass for the remaining VS Code edit-safety paths

The goal remains:

- make the repo more AI-friendly
- reduce responsibility drift
- keep source files below the preferred ceiling of 700 lines
- preserve the existing MCP tool surface while refactoring internally

## Current status

Seven refactor slices have now been applied.

### Completed in slice 1

Pure helper logic was extracted out of `server_extensions.py` into a new `utils` package.

Files added in that slice:

- `utils\__init__.py`
- `utils\search_normalization.py`
- `utils\file_ranges.py`
- `utils\text_normalization.py`

### Completed in slice 2

The registration surface was split further by moving the desktop and search extensions into a new `extensions` package.

Files added in that slice:

- `extensions\__init__.py`
- `extensions\search.py`
- `extensions\desktop.py`

### Completed in slice 3

The remaining VS Code bridge registration surface was split into focused extension modules, and the shared extension-layer helpers were moved into a common module.

Files added in that slice:

- `extensions\common.py`
- `extensions\vscode_sessions.py`
- `extensions\vscode_edits.py`

Files updated in that slice:

- `extensions\__init__.py`
- `extensions\search.py`
- `server_extensions.py`

### Completed in slice 4

The first focused test-strengthening pass was added for the refactored extension layout.

Files added in that slice:

- `tests\test_extensions_refactor.py`

Primary coverage added in that slice:

- direct tests for `extensions\common.py` helper behavior
- compatibility re-export checks through `server_extensions.py`
- direct registration-boundary assertions for `VSCodeSessionExtension` and `VSCodeEditExtension`
- targeted normalization coverage for `request_vscode_workspace_edit`

One important test-isolation cleanup was also confirmed during this slice:

- temporary stub modules used to import the refactored extensions must be removed from `sys.modules` immediately after import so later tests still resolve the real `server_config` module

### Completed in slice 5

`server_config.py` was split into a focused `config` package while preserving the external import surface used by runtime code and the existing tests.

Files added in that slice:

- `config\__init__.py`
- `config\models.py`
- `config\loader.py`
- `config\managed_repositories.py`
- `config\oauth_state.py`

Files updated in that slice:

- `server_config.py`

Primary outcomes in that slice:

- configuration models and stable tool-name constants moved to `config\models.py`
- environment parsing and config construction moved to `config\loader.py`
- managed-repository helper behavior moved to `config\managed_repositories.py`
- persistent OAuth provider state and auth construction moved to `config\oauth_state.py`
- `server_config.py` now acts as a thin compatibility re-export module
- the repository `unittest` suite still passed after the split

### Completed in slice 6

`server_runtime.py` was split into a focused `runtime` package while preserving the import surface used by `server_app.py`, the extensions, and the existing tests.

Files added in that slice:

- `runtime\__init__.py`
- `runtime\context.py`
- `runtime\search_engine_bridge.py`
- `runtime\repository_auto_indexer.py`

Files updated in that slice:

- `server_runtime.py`

Primary outcomes in that slice:

- `SearchEngineBridge` moved to `runtime\search_engine_bridge.py`
- `ServerContext` moved to `runtime\context.py`
- `RepositoryAutoIndexer` moved to `runtime\repository_auto_indexer.py`
- `server_runtime.py` now acts as a thin compatibility re-export module
- the runtime split preserved the existing import surface used by application code and tests

### Completed in slice 7

A second focused direct test pass was added for the remaining VS Code edit-safety paths.

Files updated in that slice:

- `tests\test_extensions_refactor.py`

Primary coverage added in that slice:

- drift retry behavior for `request_vscode_edit`
- ranged refresh behavior for `request_vscode_workspace_edit`
- single-match validation for `safe_vscode_edit`
- multi-match rejection for `safe_vscode_edit`
- expected-body mismatch handling for `anchored_vscode_edit`

## Current module boundaries

### `extensions\common.py`

Contains shared extension-layer helpers and session binding logic:

- `format_tool_result`
- `is_vscode_edit_drift_error`
- `resolve_vscode_workspace_root`
- `run_engine_tool`
- `require_vscode_command_success`
- `get_vscode_bridge`
- `bind_chat_session`
- `session_bound_tool`

### `extensions\vscode_sessions.py`

Contains the VS Code bridge tools that are primarily read/session/context oriented:

- `create_vscode_session`
- `close_vscode_session`
- `list_vscode_sessions`
- `get_vscode_session`
- `get_vscode_context`
- `get_vscode_context_summary`
- `get_vscode_diagnostics`
- `get_vscode_file_range`

### `extensions\vscode_edits.py`

Contains the VS Code bridge tools that perform writes or edit orchestration:

- `request_vscode_edit`
- `request_vscode_workspace_edit`
- `safe_vscode_edit`
- `anchored_vscode_edit`
- `open_vscode_file`

### `config\models.py`

Contains the configuration dataclasses, transport enum, and stable MCP tool-name lists:

- `SEARCH_TOOL_NAMES`
- `VSCODE_TOOL_NAMES`
- `ManagedRepository`
- `Config`
- `Transport`

### `config\loader.py`

Contains environment parsing and configuration construction helpers:

- `parse_bool`
- `parse_list`
- `server_root`
- `build_config`

### `config\managed_repositories.py`

Contains managed-repository path and result-formatting helpers:

- `normalize_repo_root`
- `path_is_within`
- `index_root_display`
- `coerce_int`
- `format_index_result_summary`

### `config\oauth_state.py`

Contains persistent OAuth provider behavior and auth construction:

- `_PersistentOAuthStateMixin`
- `PersistentInMemoryOAuthProvider`
- `PersistentStaticClientOAuthProvider`
- `build_auth`

### `runtime\search_engine_bridge.py`

Contains the search-engine command bridge implementation:

- `SearchEngineBridge`

### `runtime\context.py`

Contains shared runtime service wiring state:

- `ServerContext`

### `runtime\repository_auto_indexer.py`

Contains repository auto-index configuration persistence, startup indexing, watcher orchestration, and index result recording:

- `RepositoryAutoIndexer`

### `server_config.py`

`server_config.py` now acts as a thin compatibility re-export module for the `config` package and retains only the bootstrap import plus the preserved import surface used by runtime code and tests.

### `server_runtime.py`

`server_runtime.py` now acts as a thin compatibility re-export module for the `runtime` package and preserves the runtime import surface used by application code and tests.

### `server_extensions.py`

`server_extensions.py` now acts as a compatibility composition module for:

- `ServerExtension`
- `VSCodeBridgeExtension`
- re-exported `SearchExtension`
- re-exported `WindowsDesktopExtension`
- re-exported shared helper functions still imported by tests or legacy import paths

`VSCodeBridgeExtension` now delegates registration to:

- `VSCodeSessionExtension`
- `VSCodeEditExtension`

and retains responsibility only for:

- composing those sub-extensions
- owning the VS Code bridge lifecycle in `start()` / `stop()`

## Compatibility outcome

The public MCP tool names were preserved.

The compatibility import surfaces used by `server.py` were also preserved:

- `server.py` still imports `SearchExtension`, `VSCodeBridgeExtension`, and `WindowsDesktopExtension` from `server_extensions.py`
- `server.py` still imports `SEARCH_TOOL_NAMES`, `Transport`, `VSCODE_TOOL_NAMES`, and `build_config` from `server_config.py`

The test-facing helper imports were preserved as well:

- `run_engine_tool`
- `require_vscode_command_success`
- `bind_chat_session`
- `session_bound_tool`

These names resolve through re-exports from `extensions\common.py`.

## Dependency cleanup completed

One important cleanup from the earlier structural slices was removing the remaining back-reference from `extensions\search.py` to `server_extensions.py`.

`extensions\search.py` now imports shared helper functions from `extensions\common.py` instead of importing through the compatibility layer.

The config split similarly leaves `server_config.py` as a true compatibility layer rather than the implementation home for all configuration-related behavior.

## Size outcome

Observed current result:

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
- `server_extensions.py` is **69 lines**
- `extensions\common.py` is **133 lines**
- `extensions\vscode_sessions.py` is **228 lines**
- `extensions\vscode_edits.py` is **394 lines**
- `extensions\search.py` is **187 lines**
- `extensions\desktop.py` is **17 lines**

This keeps the compatibility modules thin while moving the runtime implementation into ownership-aligned modules.

## What is now done

The following items from the previous handoff are now complete:

1. splitting `VSCodeBridgeExtension` into smaller extension modules
2. separating session/context tools from edit/open-file tools
3. moving shared extension-layer helpers into `extensions\common.py`
4. preserving compatibility while shifting implementation into the `extensions` package
5. adding the first direct test coverage for the extracted helper module and the new extension boundaries
6. splitting `server_config.py` into ownership-aligned `config` modules while preserving the external import surface
7. splitting `server_runtime.py` into ownership-aligned `runtime` modules while preserving the external import surface
8. adding a second direct test pass for the remaining edit-safety edge cases in `extensions\vscode_edits.py`

## What remains undone

The following work remains:

1. optionally add more direct tests for session/file-range behavior in `extensions\vscode_sessions.py`
2. optionally reduce `extensions\vscode_edits.py` further if future edit orchestration additions begin to accumulate there
3. optionally reduce `runtime\repository_auto_indexer.py` further if watcher, persistence, and indexing concerns begin to drift together again

## Validation status

### What was confirmed

- the `utils` package exists and is in use
- the `extensions` package exists and is in use
- the `config` package exists and is in use
- the `runtime` package now exists and is in use
- the `vscode_bridge` package now exists and is in use
- `SearchExtension` remains in `extensions\search.py`
- `WindowsDesktopExtension` remains in `extensions\desktop.py`
- `VSCodeSessionExtension` exists in `extensions\vscode_sessions.py`
- `VSCodeEditExtension` exists in `extensions\vscode_edits.py`
- `extensions\common.py` exists and holds the shared extension-layer helpers
- `config\models.py`, `config\loader.py`, `config\managed_repositories.py`, and `config\oauth_state.py` exist and own the extracted `server_config.py` responsibilities
- `runtime\context.py`, `runtime\search_engine_bridge.py`, and `runtime\repository_auto_indexer.py` exist and own the extracted `server_runtime.py` responsibilities
- `server_config.py` remains the compatibility import surface for config-related imports
- `server_runtime.py` remains the compatibility import surface for runtime-related imports
- `server_extensions.py` remains the compatibility import surface
- `server_vscode_bridge.py` remains the compatibility import surface for bridge-related imports
- the public MCP tool names were preserved
- direct tests now exist for the refactored helper surface, the session/edit registration boundary, and the edit-safety retry/mismatch edge cases

### Test execution

Direct `pytest` execution remains unavailable in this environment because `pytest` is not installed.

Attempted command remains:

- `py -3 -m pytest -q` -> failed with `No module named pytest`

The repository tests are `unittest`-compatible modules and were run successfully again after the runtime split and the second edit-path test pass.

Executed command:

- `py -3 -m unittest discover -s tests -v`

Observed result:

- **34 repository tests ran and passed**

Covered test files:

- `tests\test_extensions_refactor.py`
- `tests\test_server_config_oauth.py`
- `tests\test_server_extensions.py`
- `tests\test_server_runtime.py`
- `tests\test_server_vscode_bridge.py`

## Recommended next step

The structural splits of `server_extensions.py`, `server_config.py`, `server_vscode_bridge.py`, and `server_runtime.py` are now in a good state and have regression coverage through the current `unittest` suite.

The next highest-value work is now incremental hardening rather than another large compatibility-surface split.

### Priority

Keep tightening regression coverage around the remaining read/edit safety surfaces while watching the largest implementation modules for renewed responsibility drift.

### Recommended target areas

Focus next on:

- session and file-range behavior in `extensions\vscode_sessions.py`
- edit orchestration density in `extensions\vscode_edits.py`
- watcher/persistence/index orchestration density in `runtime\repository_auto_indexer.py`

## Why this next step matters most

The major compatibility-surface hotspots have already been decomposed.

The remaining structural risk now sits mostly inside the largest implementation modules, especially:

- `extensions\vscode_edits.py`
- `runtime\repository_auto_indexer.py`
- `config\oauth_state.py`

Those modules are still below the preferred ceiling, but they are the clearest places where future growth could reintroduce mixed responsibilities.

## Suggested implementation sequence

### Step A

Add more direct tests for session binding and file-range behavior in `extensions\vscode_sessions.py`.

### Step B

Evaluate whether `extensions\vscode_edits.py` should be narrowed further if edit orchestration continues to accumulate there.

### Step C

Evaluate whether `runtime\repository_auto_indexer.py` should be narrowed further if watcher lifecycle, persistence, and indexing orchestration continue to grow.

## Handoff summary

At handoff:

- the repo now has `utils`, `extensions`, `config`, `runtime`, and `vscode_bridge` packages
- pure helper bulk was extracted from `server_extensions.py`
- desktop and search extension registration were extracted from `server_extensions.py`
- the VS Code bridge registration surface was split into dedicated session and edit modules
- the bridge internals were split into `vscode_bridge\models.py`, `vscode_bridge\state.py`, `vscode_bridge\transport.py`, and `vscode_bridge\server.py`
- shared extension-layer helpers were moved into `extensions\common.py`
- `extensions\search.py` no longer depends on `server_extensions.py`
- `server_extensions.py` now acts as a thin compatibility and lifecycle composition layer
- `server_config.py` was split into `config\models.py`, `config\loader.py`, `config\managed_repositories.py`, and `config\oauth_state.py`
- `server_config.py` now acts as a thin compatibility re-export module
- `server_runtime.py` was split into `runtime\context.py`, `runtime\search_engine_bridge.py`, and `runtime\repository_auto_indexer.py`
- `server_runtime.py` now acts as a thin compatibility re-export module
- `server_vscode_bridge.py` now acts as a thin compatibility re-export module
- direct tests now cover the extracted helper surface, the session/edit registration boundary, and the edit-safety retry/mismatch edge cases
- repository tests passed under `unittest` in this environment after the runtime split and the second edit-path test pass as well
- `pytest` remains unavailable in the current environment
- the next work should focus on incremental hardening and watching the largest implementation modules for renewed responsibility drift
