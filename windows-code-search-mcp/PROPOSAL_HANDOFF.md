# Proposal Handoff

## Scope

This handoff captures the recent repo documentation updates and the current investigation status for the repeated mid-session OAuth reauthentication issue.

## What was updated

The repository docs and related configuration were updated to reflect the current tool surface and usage guidance.

Updated files:

- `README.md`
- `mcp-instructions.md`
- `server_config.py`

Notable documentation/config updates:

- Added documentation for `anchored_vscode_edit`
- Updated edit guidance to prefer exact anchored edits for stable block replacement
- Kept the VS Code / MCP tool descriptions aligned with the current tool set

## User-reported problem

The user reports that reauthentication keeps happening in the middle of an active chat session.

They specifically asked for investigation using:

- `oauth-state.json`
- logs around April 11 at approximately 20:59

## Confirmed evidence

### OAuth state file reviewed

Reviewed file:

- `E:\Program Files\mcp\windows-code-search-mcp\oauth-state.json`

Observed state:

- token entries are present
- `access_token_session_map` is empty
- `refresh_token_session_map` is empty

## Current diagnosis

The strongest current explanation is that OAuth token material is being persisted, but the session-token bindings are not being durably preserved or reconstructed.

That means a mid-chat restart, reconnect, bridge reset, or auth-state reload can leave the process with tokens on disk but without the session association needed to continue treating the chat as authenticated.

Likely visible symptom:

- user is forced back through reauthentication during an ongoing chat session

## Likely failure modes

Potential triggers that would expose this bug:

- MCP/server process restart
- Cloudflare tunnel restart or reconnect
- launcher/stdio bridge restart
- auth state reload without map reconstruction
- in-memory-only session linkage

## Relevant logs identified

Relevant files located for the April 11 20:59 window:

- `E:\Program Files\mcp\logs\cloudflare-20260411-205904-836.log`
- `E:\Program Files\mcp\logs\launcher-20260411-205904-836.log`
- `E:\Program Files\mcp\logs\stdio-20260411-205904-836.log`

## Limitation during investigation

The Windows MCP tool registry became unavailable during the deeper log inspection step, so the 20:59 logs were not fully correlated in this pass.

Because of that, the diagnosis is supported by persisted OAuth state evidence, but is not yet fully log-confirmed from the exact event window.

## Recommended code changes

### 1. Persist session-token maps

Ensure these are written whenever tokens are issued, refreshed, rotated, or rebound:

- `access_token_session_map`
- `refresh_token_session_map`

### 2. Rebuild missing mappings on startup

If tokens exist but session maps are empty, reconstruct the association where possible rather than forcing a new auth flow immediately.

### 3. Reduce dependence on transient in-memory linkage

Chat continuity should survive process restart or reconnect when durable OAuth state already exists.

### 4. Add explicit auth continuity logging

Add logs for cases such as:

- token present but no session map
- refresh token present but session lookup missing
- state reload with empty maps
- restart/reconnect followed by auth rebind failure

## Suggested implementation targets

Look for code paths responsible for:

- OAuth state serialization/deserialization
- access token issuance
- refresh token issuance/rotation
- chat/session binding
- startup auth-state restoration
- reconnect/rebind handling after transport restart

## Proposed next steps

1. Inspect the OAuth state manager and session binding code.
2. Patch persistence for token-session maps.
3. Add startup reconstruction for missing mappings.
4. Re-run the April 11 / 20:59 scenario and compare against the identified logs.
5. Add regression coverage for restart/reconnect mid-chat.

## Confidence level

Moderate.

Reason:

- The `oauth-state.json` evidence strongly suggests a missing persistence/rebind problem.
- The exact 20:59 event still needs direct log confirmation.

## Handoff summary

At handoff, the docs are updated, and the most likely root cause of the repeated mid-session reauthentication is that persisted OAuth token state does not include durable or reconstructed session-token bindings.

The highest-value next action is to patch OAuth/session persistence and then verify the fix against the April 11 20:59 restart/reconnect path.
