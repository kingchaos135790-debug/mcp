# MCP Tools Feedback From Session (2026-04-08)

## Scope

This note summarizes concrete problems encountered while using the Windows MCP tools during a real coding and documentation session, along with suggested improvements.

The tools used in this session included:
- `list_indexed_repositories`
- `list_vscode_sessions`
- `get_vscode_diagnostics`
- `get_vscode_file_range`
- `request_vscode_edit`
- `lexical_code_search`
- `PowerShell`
- `FileSystem`

## What worked well

- The Windows MCP tool suite made it possible to move from repo discovery to code search, code editing, runtime execution, and file writing without leaving the tool boundary.
- `get_vscode_file_range` was very useful for reading exact numbered lines before edits.
- `request_vscode_edit` did work for many focused edits once the line target was narrow enough.
- `PowerShell` was reliable for runtime validation, artifact inspection, and file inventory when other paths were brittle.
- `FileSystem` write support was straightforward and useful for direct document creation.

## Problems observed

### 1. Resource path instability across calls

Observed behavior:
- Tool paths sometimes changed from forms like `/Windows MCP/link_<id>/...` to `/Windows MCP/...` between nearby calls.
- A tool call that worked on one turn could fail with `Resource not found` on the next turn unless the path was rewritten.

Why this is a problem:
- It introduces avoidable friction and forces the client to rediscover the active namespace shape.
- It makes multi-step workflows more brittle than necessary.

Suggested improvement:
- Keep resource paths stable for the duration of a session.
- If alias migration is required internally, preserve backward-compatible aliases.
- Return a machine-readable redirect or canonical-path field when a path family changes.

### 2. `request_vscode_edit` is overly sensitive to snapshot drift

Observed behavior:
- `request_vscode_edit` frequently returned `Expected text mismatch before applying edit`.
- This happened even after fresh rereads and even for edits that were logically correct.
- Large or medium block replacements were especially brittle.
- The most reliable pattern was shrinking edits to very small line-level insertions or replacements.

Why this is a problem:
- It increases edit latency and encourages fragmented edits instead of coherent ones.
- It can make straightforward doc updates disproportionately expensive.

Suggested improvement:
- Support a more tolerant edit mode based on line anchors plus optional surrounding context.
- Expose a patch mode that can match by nearby stable context instead of exact full-block text.
- Return richer mismatch diagnostics, such as the current text at the target range.
- Consider a server-side retry helper that re-reads and reapplies if the mismatch is small and localized.

### 3. `get_vscode_file_range` / edit round-tripping can amplify escaping problems in docs

Observed behavior:
- When replacing larger markdown blocks, backslashes in Windows paths became doubled in the visible text after rewrite.
- This is manageable, but it makes doc editing riskier when content contains many Windows paths.

Why this is a problem:
- It can silently degrade documentation quality.
- It makes users cautious about using full-block replacements for docs.

Suggested improvement:
- Make it clearer whether returned content is raw file text or transport-escaped text.
- Provide a raw-text edit/read mode that minimizes representation ambiguity for path-heavy files.
- Add a preview/diff response for larger edits before commit.

### 4. Search quality was uneven for documentation-style queries

Observed behavior:
- `lexical_code_search` worked well for exact symbol lookups such as `save_last_debug_artifacts`.
- Broader mixed-term searches over docs or status content often returned no useful hits.

Why this is a problem:
- It reduces confidence when using search to locate relevant prose or status notes.
- It pushes the workflow toward direct file reads even when search should have been enough.

Suggested improvement:
- Improve ranking and fallback behavior for prose-heavy queries.
- Consider a doc-aware search mode or mixed code/doc search intent.
- When no hits are found, return lightweight suggestions such as likely nearby files or query decomposition hints.

### 5. Error feedback is often correct but not maximally actionable

Observed behavior:
- Errors like `Resource not found` and `Expected text mismatch before applying edit` were accurate, but still required trial-and-error to recover.
- In one case, a recursive `FileSystem` markdown search was blocked by safety checks without much guidance on a safer equivalent.

Why this is a problem:
- Recovery is possible, but slower than it should be.
- The operator has to infer the preferred fallback path.

Suggested improvement:
- Add suggested next actions directly to common error responses.
- For blocked file operations, recommend a safe equivalent command shape automatically.
- For edit mismatches, include a current short excerpt from the target range.

### 6. Session-tooling integration is good, but workflow transitions are still manual

Observed behavior:
- The most reliable workflow was:
  1. search
  2. read exact lines
  3. edit narrowly
  4. reread
  5. run validation
- This worked, but the client had to orchestrate every step manually.

Why this is a problem:
- It is robust, but repetitive.
- Common patterns are obvious enough that the tool could help more.

Suggested improvement:
- Add a higher-level "safe edit" helper that automatically:
  - reads the target range,
  - applies the edit with anchor checking,
  - rereads the result,
  - optionally runs a validation command.
- Add optional diff summaries in the tool response after edits.

## Most important improvements to prioritize

1. Stabilize resource paths across the session.
2. Make `request_vscode_edit` less brittle for normal block edits.
3. Improve recovery guidance in error responses.
4. Make read/edit behavior clearer for Windows-path-heavy markdown content.
5. Improve search quality for documentation and status-note queries.

## Practical recommendation

If only one area is improved first, it should be edit robustness.

During this session, the biggest time cost came from repeated retries around `request_vscode_edit` mismatches and namespace/path churn, not from the underlying coding or validation work itself.
