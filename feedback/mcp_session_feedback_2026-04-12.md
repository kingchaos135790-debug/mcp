# MCP Session Feedback

Date: 2026-04-12
Repo: E:\Program Files\mcp
Relevant logs:
- `E:\Program Files\mcp\logs\launch_mcp_server-stdio-20260412-155907-807.log`
- `E:\Program Files\mcp\logs\launch_mcp_server-runtime-20260412-155907-807.log`
- `E:\Program Files\mcp\logs\launch_mcp_server-launcher-20260412-155907-807.log`

## Summary
The latest logs indicate that the MCP server is healthy. The earlier inability to reliably read and inspect repo content appears to come from session continuity and tooling issues rather than a server crash.

## Findings

### 1. MCP server starts successfully
The launcher log shows normal startup:
- Transport: `streamable-http`
- HTTP session mode: `stateless`
- Qdrant readiness check completed
- Search engine core is up to date
- Python MCP server launched on `127.0.0.1:8000`

### 2. The connection is stateless
The launcher log explicitly reports `HTTP session mode: stateless`.
This likely causes tool/session aliases and context handles to change across calls, which matches the earlier behavior where follow-up reads stopped working consistently after a tool refresh.

### 3. OAuth/auth flow is being re-triggered
The stdio log shows repeated auth traffic such as:
- `GET /authorize ... 302 Found`
- `POST /token ... 200 OK`
- `GET /.well-known/openid-configuration ... 200 OK`

This suggests intermittent reauthorization or token refresh behavior. That would explain why some calls worked and later calls behaved like the session had partially reset.

### 4. The stdio log is encoded in UTF-16
The latest stdio log contains null bytes in direct reads, indicating UTF-16 or Unicode encoding rather than plain UTF-8.
This makes direct file inspection look garbled and can obscure otherwise normal request traces.

### 5. No evidence of a hard server failure
There is no clear sign in the latest logs of:
- MCP process crash
- Qdrant startup failure
- search engine rebuild failure
- Python server startup exception

The paired runtime log is effectively empty, which suggests no runtime traceback was emitted for this launch.

## Conclusion
The main problem is not that MCP failed to launch. The more likely root cause is a combination of:
1. stateless HTTP session behavior,
2. intermittent OAuth reauthorization/token refresh,
3. UTF-16 stdio log encoding that complicates direct reads.

These factors together are sufficient to explain why repo reads and search operations were inconsistent even though the MCP server itself was up.

## Recommended follow-up
- Reduce reliance on ephemeral session aliases across calls.
- Stabilize auth reuse so repeated OAuth redirects are less likely during a single workflow.
- Emit stdio logs in UTF-8, or document that they are UTF-16.
- Prefer shorter, direct file reads when investigating a repo during a stateless session.


## Additional diagnosis: console errors during attempted edit

### 6. The primary block is the VS Code bridge, not the `boot_id` logging error
The actual blocking failure is that the VS Code bridge never polled for the queued edit command.
The `safe_vscode_edit` call timed out with a message stating that no command poll was observed after the command was queued, that the VS Code extension may not be polling `/commands` or may be using the wrong token, and that `lastCommandPollAt=never` and `deliveredAt=not delivered`.

This indicates that the session existed server-side, but the editor-side bridge never fetched the pending command. The most likely causes are:
- the VS Code extension was not running,
- the extension was connected but not polling `/commands`,
- the extension was using the wrong token or session,
- or the bridge session was stale even though it still existed on the server.

### 7. The `boot_id` formatter failure is secondary logging noise
The repeated `KeyError: 'boot_id'` and `ValueError: Formatting field not found in record: 'boot_id'` messages are a separate logging configuration bug.
A logger emitted a record that did not contain the custom formatter fields expected by the configured log format, while the formatter still required fields such as `%(boot_id)s`.

This made the console output noisier, but it was not the original cause of the edit failure. The original failure was the VS Code bridge timeout.

### 8. OAuth traffic was observed, but it does not appear to be the immediate blocker for this edit failure
The console log also showed successful OAuth-related traffic such as:
- `GET /authorize ... 302 Found`
- `POST /token ... 200 OK`
- `GET /.well-known/openid-configuration ... 200 OK`

That activity suggests authentication was active during the session, but it does not explain the immediate edit failure as directly as the bridge timeout does.

## Updated conclusion
The immediate block during the attempted fix was a VS Code bridge connectivity/session problem, specifically that queued editor commands were never polled by the editor-side extension.
The `boot_id` errors are secondary and indicate a formatter/filter mismatch in logging.

## Additional recommended follow-up
- Verify that the VS Code extension is running and actively polling the bridge `/commands` endpoint.
- Verify that the bridge token and session id match between the server and the editor.
- Add a defensive logging filter, adapter, or formatter fallback so records missing `boot_id` and `chat_session_id` do not raise formatting exceptions.
- Keep treating repeated OAuth traffic as a possible stability concern, but not as the primary cause of this specific blocked edit.


## Additional diagnosis: OAuth state vs. token expiration vs. Cloudflare

### 9. The evidence points more strongly to OAuth/session-state rebinding than to simple token expiration
The persisted OAuth state file (`E:\Program Files\mcp\windows-code-search-mcp\oauth-state.json`) shows that refresh tokens are stored with `expires_at: null`, while access tokens have finite `expires_at` values and are linked to refresh tokens.

This means the current behavior is not best explained as a simple short-lived access-token expiration problem by itself. The implementation is designed to persist session continuity through refresh tokens and explicit token-to-session ownership maps.

### 10. The implementation explicitly tracks and repairs token-to-session bindings
The OAuth state and provider logic persist:
- `access_token_session_map`
- `refresh_token_session_map`
- `last_boot_id`
- `run_count`

The provider logic also attempts to recover missing OAuth session bindings during request continuation by reattaching the current request/session to an access token when possible.

This strongly suggests that the observed instability is more likely related to stale, missing, or pruned token-to-session bindings than to plain expiration alone.

### 11. Reauthentication may repair stale handles by creating fresh token/session bindings
A plausible explanation for the observed behavior is:
1. an older token or session binding becomes stale, missing, or no longer matches the current chat/session context,
2. resource handles or linked tool paths become stale as a result,
3. reauthentication issues or refreshes a token and rebinds it to the current session,
4. the stale linked path disappears after the new binding is established.

This interpretation is consistent with the observation that reauthentication can make a stale linked path disappear even when the broader system has not otherwise changed.

### 12. Token-state churn is a likely contributing factor
The launcher sets `OAUTH_STATE_MAX_TOKENS=10`.
The persisted OAuth state currently contains roughly that many access/refresh token entries, which means the installation is operating close to the configured cap.

That makes token-state churn a credible source of instability. If repeated authorizations or refreshes push the state toward or beyond the cap, older token/session bindings may be pruned or displaced, increasing the chance of stale resource handles and missing session rebinds.

### 13. Cloudflare free tier is not the strongest explanation from the current evidence
The current local evidence does not primarily resemble an edge-tier or Cloudflare-plan limitation.
Instead, the observed signs are:
- successful `/authorize` requests,
- successful `/token` exchanges,
- persisted token/session maps,
- explicit boot-aware state persistence,
- and local code paths dedicated to rebinding OAuth tokens to chat sessions.

Taken together, those signs point more toward application-level session continuity and state-persistence problems than to a Cloudflare free-tier limitation.

### 14. Why the official connector may feel more stable
A likely reason the official connector appears more stable is that it probably handles token refresh, session rebinding, stale-handle invalidation, and persistence across restarts more robustly.

This custom connector has several interacting sources of fragility at once:
- OAuth state persistence,
- token-to-session rebinding,
- boot-id transitions,
- stateless HTTP behavior,
- VS Code bridge sessions,
- and session/handle continuity across tool calls.

## Updated assessment
The most likely explanation is not "Cloudflare free tier" and not plain token expiration alone.
The stronger hypothesis is a broader OAuth/session-state continuity problem, likely involving stale or pruned token-to-session bindings that reauthentication happens to repair.

## Additional recommended follow-up
- Raise `OAUTH_STATE_MAX_TOKENS` above 10 to reduce token-state churn.
- Log whenever a token-to-session binding is created, recovered, pruned, or lost.
- Log boot-id transitions together with any state-map cleanup.
- Distinguish in logs between "token expired", "token refreshed", and "token valid but missing session binding".
- Continue treating Cloudflare as a secondary possibility only if edge/network-specific errors later appear in logs.

## Implementation update: logging fix applied on 2026-04-13

### 15. The `boot_id` / `chat_session_id` formatter mismatch has now been patched
A targeted fix was applied in `E:\Program Files\mcp\windows-code-search-mcp\server.py` inside `configure_process_diagnostics()`.

The change keeps the existing root logger filter, and additionally attaches `SessionContextFilter` to each root handler. This matters because formatting happens at the handler level, and propagated records from child loggers can reach root handlers without the custom fields populated on the record.

### 16. What changed in code
The patch added handler-level filter attachment immediately after the existing root-logger filter setup:
- iterate over `root_logger.handlers`
- check whether each handler already has `SessionContextFilter`
- add the filter when it is missing

### 17. Why this addresses the reported error
This directly addresses the reported `KeyError: 'boot_id'` and `ValueError: Formatting field not found in record: 'boot_id'` failure mode by ensuring that records formatted by the configured handlers receive `boot_id` and `chat_session_id` before formatter interpolation.

This patch reduces logging noise and prevents formatter crashes, but it does not by itself resolve the separate VS Code bridge polling/session issue described earlier.

### 18. Updated status
- Fixed now: defensive logging context injection for root handlers in `windows-code-search-mcp/server.py`
- Still outstanding: VS Code bridge `/commands` polling/session continuity problem
- Still worth investigating: OAuth/session-state churn and stale token-to-session bindings

## Implementation update: OAuth token pruning and rebinding changes applied on 2026-04-14

### 19. Token pruning now prefers unbound access tokens first
A targeted fix was applied in `E:\Program Files\mcp\windows-code-search-mcp\config\oauth_state.py` inside `_enforce_max_token_count()`.

The previous logic pruned by insertion order alone. The updated logic now prefers pruning access tokens that do not currently resolve to any chat/session binding, and only falls back to the oldest remaining access token when all remaining tokens are still session-bound.

This reduces the chance that token-count enforcement will discard a token that still has a valid chat/session association.

### 20. Access-token session resolution now repairs missing direct bindings from the refresh-token map
A targeted fix was also applied in `E:\Program Files\mcp\windows-code-search-mcp\config\oauth_state.py` inside `resolve_chat_session_for_access_token()`.

When a direct access-token-to-session binding is missing, the resolver now checks the linked refresh token for a valid session binding, restores the missing access-token binding from that refresh-token session, and persists the repaired mapping.

This makes the state layer more tolerant of partially missing access-token bindings and reduces the chance that a still-valid token appears stale until reauthentication occurs.

### 21. The launcher default token cap was raised
The default launcher setting in `E:\Program Files\mcp\launch_mcp_server.bat` was changed from `OAUTH_STATE_MAX_TOKENS=10` to `OAUTH_STATE_MAX_TOKENS=50`.

This reduces token-state churn and lowers the probability that useful token/session bindings are displaced simply because the persisted state is operating near the configured cap.

### 22. Updated status
- Fixed now: token pruning prefers unbound access tokens before pruning session-bound tokens
- Fixed now: missing direct access-token bindings can be repaired from linked refresh-token session ownership
- Fixed now: default OAuth state token cap raised from 10 to 50
- Still worth investigating: add explicit logs for token/session binding creation, recovery, pruning, and loss
- Still outstanding: VS Code bridge `/commands` polling/session continuity problem


## Implementation update: VS Code bridge fast-fail for missing command polling applied on 2026-04-14

### 23. Bridge command waits now fail earlier when no `/commands` poll is observed
A targeted fix was applied in `E:\Program Files\mcp\windows-code-search-mcp\vscode_bridge\state.py` inside `wait_for_command()`.

Previously, edit and open-file requests could wait for the full request timeout even when the VS Code bridge session had not polled `/commands` after the command was queued.

The updated logic now uses an initial poll-observation window of up to 5 seconds. If no `/commands` poll is observed during that window, the bridge fails early with a specific timeout message indicating that the VS Code extension may not be polling `/commands` or may be using the wrong token.

This reduces wasted wait time and makes the failure mode more actionable when the editor-side bridge is disconnected or stale.

### 24. Timeout reporting was refactored into a dedicated helper
The same patch also introduced `_build_wait_for_command_timeout_message()` in `E:\Program Files\mcp\windows-code-search-mcp\vscode_bridge\state.py`.

This centralizes the timeout diagnosis logic for three distinct cases:
- session disappeared before completion,
- no `/commands` poll was observed after enqueue,
- command was claimed but no result was posted back.

This keeps the user-visible failure messages consistent while preserving the earlier diagnostic detail such as `lastSeenAt`, `lastCommandPollAt`, and `deliveredAt`.

### 25. Focused bridge-state tests now cover the early-failure path
A targeted test was added in `E:\Program Files\mcp\windows-code-search-mcp\tests\test_server_vscode_bridge.py` to verify that a command with no observed polling fails after the initial 5-second observation window rather than consuming the full request timeout.

The focused bridge-state test suite passed after the change:
- `python -m unittest tests.test_server_vscode_bridge`
- result: `Ran 7 tests ... OK`

### 26. Updated status
- Fixed now: bridge wait path fails early when no `/commands` poll is observed after enqueue
- Fixed now: timeout diagnosis is centralized and remains explicit about missing poll vs. missing result
- Still outstanding: extension-side heartbeat/session recovery in `vscode-bridge-extension/src/bridgeController.ts`
- Still outstanding: VS Code bridge `/commands` polling/session continuity problem when no active editor session is connected
