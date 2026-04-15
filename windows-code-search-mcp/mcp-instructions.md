Windows Code Search MCP combines Windows desktop automation, repository indexing, code search, and a VS Code bridge in one MCP server.

Use these behaviors by default:

- Prefer search tools first to locate candidate files and symbols before reading large files.
- Use repo-scoped search when the target repository is known.
- If the user is only asking a question, use `get_vscode_context_summary` first and `get_vscode_context` only when full context content is actually needed.
- If the user wants a code edit, create or choose a VS Code session first, inspect `get_vscode_context_summary` and `get_vscode_diagnostics` when available, then use `get_vscode_file_range` to read the exact numbered lines immediately before editing.
- Prefer precise minimal edits over full-file rewrites.
- Treat line numbers as temporary coordinates, not stable identifiers.
- Include `expected_text` by default in edit requests to prevent stale-range edits.
- Prefer `request_vscode_workspace_edit` for multiple related edits derived from one fresh file snapshot.
- After any successful edit, re-read the file before issuing another edit because line positions may have shifted.
- If `expected_text` does not match, stop and re-locate the target instead of guessing.
- Treat code search locations as hints for navigation and inspection, not as edit targets.
- For exact identifier lookups such as `create_vscode_session`, `hybrid_code_search` can now promote the real source definition into fused results even when that lexical hit was not initially surfaced by the engine; test and documentation matches can still appear lower in the list.
- Do not assume search hits carry stable edit-ready line numbers by default.
- After MCP server restarts, prefer canonical `/Windows MCP/...` tool paths for follow-up calls because cached linked tool paths can briefly return `Resource not found`.
- If an edit fails because `expected_text` does not match or the target drifted, re-read the exact range with `get_vscode_file_range`, refresh `expected_text`, and retry with a narrower anchored change.
- If OAuth or tool-calling appears unresponsive, verify that `/.well-known/openid-configuration` returns `200` and that the public tunnel targets `127.0.0.1:8000` rather than `localhost:8000` to avoid IPv6 `::1` origin mismatches.

Tool selection guidance:

- `create_vscode_session`: reserve a dedicated VS Code bridge session for one chat or task before edits begin.
- `close_vscode_session`: close a VS Code bridge session when the task is done or the session is stale.
- `list_vscode_sessions`: discover available VS Code bridge sessions.
- `get_vscode_session`: inspect a full VS Code session snapshot.
- `get_vscode_context_summary`: inspect context item metadata without full content.
- `get_vscode_context`: inspect full context item contents.
- `get_vscode_file_range`: read workspace file content with numbered lines.
- `get_vscode_diagnostics`: inspect Problems data from VS Code.
- `request_vscode_edit`: apply one validated line-and-column text edit.
- `request_vscode_workspace_edit`: apply multiple coordinated validated edits.
- `safe_vscode_edit`: find one anchored exact text match and convert it into a validated edit.
- `anchored_vscode_edit`: replace the body between a unique start anchor and end anchor with optional body validation.
- `open_vscode_file`: reveal a file at a specific location in VS Code.

Editing workflow:

1. Create or choose a session with `create_vscode_session` or `list_vscode_sessions`.
2. Find the likely file or symbol with search.
3. Inspect `get_vscode_context_summary` and `get_vscode_diagnostics` when relevant.
4. Read the exact region with `get_vscode_file_range`.
5. Verify the intended change against the freshly returned lines.
6. Apply the smallest safe edit with `expected_text`, use `safe_vscode_edit` for one anchored exact-text replacement, or use `anchored_vscode_edit` when a block is best targeted by stable start/end anchors.
7. Re-read before any follow-up edit.
8. Close stale or finished sessions with `close_vscode_session` when they should not be reused.

Question-answering workflow:

1. Find the likely file or symbol with search when needed.
2. Retrieve context with `get_vscode_context` only when the answer depends on full context content.
3. Use `get_vscode_file_range` when numbered line references are needed.


