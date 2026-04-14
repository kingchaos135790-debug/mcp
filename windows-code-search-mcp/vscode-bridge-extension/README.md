# Windows Code Search Bridge

VS Code extension that connects to `windows-code-search-mcp` through the local VS Code bridge. It maintains a context window of files, snippets, and selections, and pushes VS Code diagnostics to the MCP server. The MCP server can send commands back (open files, apply edits) through the same bridge.

## Features

- sidebar context window for snippets, files, selections, and folder summaries
- drag text into the context window
- `Add Files...` button for reliable file import
- `Add Folder...` button to recursively add readable files from one or more folders
- `Add Folder Names...` button to send only directory and file names without full file contents
- `Code Search Bridge: Add To Context Window` command in Explorer, editor title, and tab context menus for reliable VS Code file capture
- add active editor, selection, or all open editors into the context set
- push current VS Code diagnostics to the MCP bridge
- periodic heartbeat push (default every 30 s) to keep context fresh even without user activity
- poll bridge commands so the MCP server can open files and apply edits through the VS Code API
- return edit mismatch diagnostics with file path, compared range, and truncated `expected` and `actual` text previews for both single-edit and workspace-edit requests

## Architecture

```
extension.ts          Entry point — registers commands, creates BridgeController
bridgeController.ts   Orchestration — lifecycle, timers, webview, context sync
commandHandler.ts     Command execution — apply_edit, apply_workspace_edit, open_file
bridgeClient.ts       HTTP client — GET/POST to the Python bridge server
contextStore.ts       Persistence — workspace-state-backed context item store
contextHelpers.ts     Pure helpers — item factories, folder collection, URI resolution
constants.ts          Shared constants (limits, skipped directories)
types.ts              Shared TypeScript types
webview.ts            Webview HTML renderer
```

The Python bridge server (`vscode_bridge/`) mirrors this with:

```
server.py             Server lifecycle — start/stop/restart, high-level edit/open API
state.py              Thread-safe session and command-queue state
transport.py          HTTP request handler factory (BaseHTTPRequestHandler)
models.py             Data models (VSCodeSession, VSCodeCommand)
```

## Usage

1. Start `windows-code-search-mcp` so the local bridge is listening on `http://127.0.0.1:8876` by default.
2. Open the `vscode-bridge-extension` folder in VS Code.
3. Press `F5` to launch an Extension Development Host.
4. In the dev host, open your target workspace and open the `Code Search Bridge` activity bar view.
5. Add context by dragging files/tabs/text into the view or by using:
   - `Add Files...`
   - `Add Folder...`
   - `Add Folder Names...`
   - `Add Active Editor`
   - `Add Selection`
   - `Add Open Editors`
   - `Code Search Bridge: Add To Context Window` from Explorer/tab menus
6. Click `Push Now` if you want an immediate context and diagnostics sync.

To change the bridge port at runtime, update the extension setting and then run `Code Search Bridge: Restart Bridge Server`, or use `Code Search Bridge: Set Bridge Port And Restart Server` to do both in one step.

Notes:

- drag text works best; for files, use `Add Files...` or the context-menu command because webview file drag payloads are inconsistent in VS Code
- the webview shows success/warning/error notices after drops and sync actions
- `pushNow()` only reports success when both context and diagnostics actually reach the bridge; a bridge or session failure surfaces the real error instead of masking it with a false success
- if `request_vscode_edit` or `request_vscode_workspace_edit` fails with an expected-text mismatch, re-read the target range with `get_vscode_file_range`, refresh `expected_text`, and retry with a narrower anchored edit
- mismatch errors include the file path, compared range, and shortened `expected` and `actual` previews so drift recovery can be done without guesswork
- after changing extension bridge code on disk, reload the VS Code window or restart the extension host so the running bridge picks up the updated `out/` files

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `windowsCodeSearchBridge.bridgeBaseUrl` | `""` | Optional full URL override |
| `windowsCodeSearchBridge.bridgeHost` | `127.0.0.1` | Bridge server host |
| `windowsCodeSearchBridge.bridgePort` | `8876` | Bridge server port |
| `windowsCodeSearchBridge.bridgeToken` | `""` | Optional shared `X-Bridge-Token` |
| `windowsCodeSearchBridge.pollIntervalMs` | `1500` | Command polling interval (ms) |
| `windowsCodeSearchBridge.heartbeatIntervalMs` | `30000` | Heartbeat push interval (ms, min 5000) |
| `windowsCodeSearchBridge.autoPushDiagnostics` | `true` | Auto-push diagnostics on Problems change |
| `windowsCodeSearchBridge.saveAfterApplyEdit` | `true` | Save files after bridge edits |

## Commands

| Command | Description |
|---------|-------------|
| `Code Search Bridge: Push Context Now` | Immediate context + diagnostics push |
| `Code Search Bridge: Restart Bridge Server` | Restart the Python bridge |
| `Code Search Bridge: Set Bridge Port And Restart Server` | Change port and restart |
| `Code Search Bridge: Add Files To Context Window` | File picker |
| `Code Search Bridge: Add Folder To Context Window` | Folder picker (recursive) |
| `Code Search Bridge: Add Folder Names To Context Window` | Folder names-only import |
| `Code Search Bridge: Add Active Editor` | Current editor file |
| `Code Search Bridge: Add Current Selection` | Current selection range |
| `Code Search Bridge: Add Open Editors` | All visible editors |
| `Code Search Bridge: Add To Context Window` | Explorer/tab context menu |

## Local development

```bash
npm install
npm run compile
```

The workspace includes:

- `.vscode/launch.json` for `F5` extension-host debugging
- `.vscode/tasks.json` for `compile`, `watch`, and `package`

## Packaging

```bash
npm run package
```

This produces `windows-code-search-bridge-0.0.1.vsix` in the extension root.
