Windows Code Search MCP combines Windows desktop automation, repository indexing, code search, and a VS Code bridge in one MCP server.

Use these behaviors by default:

- Prefer search tools first to locate candidate files and symbols before reading large files.
- Use repo-scoped search when the target repository is known.
- If the user is only asking a question, use `get_vscode_context_summary` first and `get_vscode_context` only when full context content is actually needed.
- If the user wants a code edit, inspect `get_vscode_context_summary` and `get_vscode_diagnostics` when available, then use `get_vscode_file_range` to read the exact numbered lines immediately before editing.
- Prefer precise minimal edits over full-file rewrites.
- Treat line numbers as temporary coordinates, not stable identifiers.
- Include `expected_text` by default in edit requests to prevent stale-range edits.
- Prefer `request_vscode_workspace_edit` for multiple related edits derived from one fresh file snapshot.
- After any successful edit, re-read the file before issuing another edit because line positions may have shifted.
- If `expected_text` does not match, stop and re-locate the target instead of guessing.
- Treat code search locations as hints for navigation and inspection, not as edit targets.
- Do not assume search hits carry stable edit-ready line numbers by default.

Tool selection guidance:

- `list_vscode_sessions`: discover available VS Code bridge sessions.
- `get_vscode_session`: inspect a full VS Code session snapshot.
- `get_vscode_context_summary`: inspect context item metadata without full content.
- `get_vscode_context`: inspect full context item contents.
- `get_vscode_file_range`: read workspace file content with numbered lines.
- `get_vscode_diagnostics`: inspect Problems data from VS Code.
- `request_vscode_edit`: apply one validated line-and-column text edit.
- `request_vscode_workspace_edit`: apply multiple coordinated validated edits.
- `open_vscode_file`: reveal a file at a specific location in VS Code.

Editing workflow:

1. Find the likely file or symbol with search.
2. Inspect `get_vscode_context_summary` and `get_vscode_diagnostics` when relevant.
3. Read the exact region with `get_vscode_file_range`.
4. Verify the intended change against the freshly returned lines.
5. Apply the smallest safe edit with `expected_text`.
6. Re-read before any follow-up edit.

Question-answering workflow:

1. Find the likely file or symbol with search when needed.
2. Retrieve context with `get_vscode_context` only when the answer depends on full context content.
3. Use `get_vscode_file_range` when numbered line references are needed.
