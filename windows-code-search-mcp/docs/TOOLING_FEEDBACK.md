# MCP Tooling Feedback: Code Search and Edit Workflow

## Context

This feedback comes from an actual multi-file debugging/editing session against the `wasm` repository using the Windows code-search MCP tools. The task required finding Monaco editor startup logic, problem-panel diagnostics, AssemblyScript compiler worker policy checks, and then applying several small JavaScript edits.

The tools were useful, but the workflow exposed several friction points that made simple edits slower and more error-prone than necessary.

## What worked well

- `hybrid_code_search` was useful for broad discovery when the exact file was unknown.
- `get_file_range` and `get_multiple_file_ranges` provided enough local context to make safe edits.
- `safe_file_edit` was effective when the exact target text was known.
- PowerShell execution was valuable for `git diff`, syntax checks, and targeted validation.

## Main friction points

### 1. Too many edit primitives with unclear selection rules

There are several editing tools with overlapping purposes:

- `safe_file_edit`
- `request_file_edit`
- `anchored_file_edit`
- `multi_anchor_file_edit`

In practice, it was not always clear which one should be preferred for a given patch. For example, an anchored edit failed because the end anchor was not found exactly after the start anchor, even though the target block was visible in a recently fetched file range. The fallback was to use line-range editing with a large `expected_text` block.

**Suggested improvement:** provide a single higher-level `replace_range_or_anchor` tool that accepts:

- file path
- optional expected text
- optional start/end anchors
- optional start/end line range
- replacement text
- a dry-run flag

The tool could choose the safest available strategy, report ambiguity, and show the exact matched range before applying when needed.

### 2. Anchored edit errors should include nearby candidate anchors

When `anchored_file_edit` failed, the error only said the end anchor was not found after the start anchor. It did not show nearby matching lines or candidate close matches.

**Suggested improvement:** on anchor failure, return:

- whether the start anchor was found
- the line number of the start anchor if found
- nearby lines after the start anchor that approximately match the end anchor
- whether the end anchor exists elsewhere in the file
- recommended corrected anchor text

This would avoid another round trip through `get_file_range` just to determine why the anchor failed.

### 3. Line-range edits are verbose and brittle

`request_file_edit` required sending the full expected block. For medium-sized blocks, this is noisy and easy to get wrong, especially when line numbers shift after earlier edits.

**Suggested improvement:** support a compact guarded range edit:

```json
{
  "file_path": "...",
  "start_line": 232,
  "end_line": 295,
  "expected_sha256": "...",
  "replacement_text": "..."
}
```

A helper could return stable block hashes from `get_file_range`. That would make guarded edits shorter while preserving safety.

### 4. Search results sometimes bury the actionable lexical hit

For precise symbol/file searches, semantic results sometimes dominated the response while the useful lexical hit was lower down. In the `hostsync_batch_get_caps` case, the exact generated file hit existed, but the response included many unrelated semantic snippets first.

**Suggested improvement:** when the query contains exact identifiers, module paths, or quoted strings, rank exact lexical hits first or provide a separate `exact_matches` section at the top.

### 5. Generated/build-path indexing warnings need more guidance

The search result warned that generated/build paths were excluded from indexed coverage, but lexical search still found a generated file. That was useful, but ambiguous.

**Suggested improvement:** clarify the warning. For example:

> Semantic index excludes generated/build paths, but lexical ripgrep may still search them if present on disk.

Also expose whether each result came from indexed semantic data or live filesystem lexical search.

### 6. PowerShell output handling was inconsistent

Inline `node -e` commands returned no stdout in one case even though the command exited successfully. A temporary `.cjs` file was needed to get visible output.

**Suggested improvement:** improve PowerShell stdout/stderr capture, especially for commands containing nested quotes and inline scripts. At minimum, return the exact command after shell escaping or indicate when stdout may have been swallowed by quoting/parsing.

### 7. Tool errors should suggest the next best call

When an edit tool fails, the user usually needs one of:

- `get_file_range` around the failed anchor
- a broader search for the target text
- a line-range edit using the visible block

**Suggested improvement:** include a `suggested_next_tool_call` object in recoverable errors. The assistant can then call it directly without reasoning from scratch.

### 8. No unified patch summary

After several edits, validation required manually running `git diff` and syntax checks. That works, but the edit tools themselves could provide a better patch summary.

**Suggested improvement:** add a `workspace_patch_summary` tool that returns:

- changed files
- changed line ranges
- insert/delete counts
- whether files still parse, if language checks are configured
- recent edit operations applied by MCP

### 9. Better support for multi-step code-edit sessions

For an assistant-driven coding session, context matters. It would help if the MCP server tracked recent file ranges and edits as structured session state.

**Suggested improvement:** expose a `session_edit_context` tool that returns:

- files opened recently
- ranges read recently
- edits applied recently
- failed edit attempts and error details
- current git diff summary

This would reduce repeated file reads and make recovery from failed edits faster.

## Concrete priority list

1. Add close-match diagnostics to failed anchor edits.
2. Add a single high-level guarded replacement tool that can use anchor, line range, or exact text.
3. Improve exact lexical-hit ranking for identifier/path queries.
4. Add block-hash guarded edits to avoid sending huge expected text blocks.
5. Improve PowerShell stdout capture for inline scripts.
6. Add a patch/session summary tool.

## Expected impact

These changes would reduce tool-call count, lower the chance of accidental stale-range edits, and make assistant-driven repository changes more predictable. The existing tools are already powerful; the main gap is ergonomics and recovery guidance when an edit does not apply cleanly.

## Implementation status in `windows-code-search-mcp`

Implemented in recent commits:

- Close-match diagnostics for failed anchor edits.
- A high-level guarded `replace_range_or_anchor` edit tool.
- Compact `expected_sha256` guarded edits using `contentSha256` from range reads.
- Recoverable edit errors with `suggested_next_tool_call` where applicable.
- A hybrid-search `exact_matches` section for direct lexical identifier/path/string hits.
- `resultSource` hints and clearer generated/build-path warning text explaining semantic-index coverage versus live lexical ripgrep results.

Still open / lower priority:

- PowerShell stdout/stderr capture improvements for nested inline scripts.
- Patch/session summary tooling.
- Full session edit-context tracking across multi-step coding sessions.
