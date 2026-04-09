# Windows Code Search Bridge

Starter VS Code extension that connects to `windows-code-search-mcp` through the local VS Code bridge.

## Features

- sidebar context window for snippets and files
- drag text into the context window
- `Add Files...` button for reliable file import
- `Add Folder...` button to recursively add readable files from one or more folders
- `Add Folder Names...` button to send only directory and file names without full file contents
- `Code Search Bridge: Add To Context Window` command in Explorer, editor title, and tab context menus for reliable VS Code file capture
- add active editor, selection, or all open editors into the context set
- push current VS Code diagnostics to the MCP bridge
- poll bridge commands so the MCP server can open files and apply edits through the VS Code API
- return edit mismatch diagnostics with file path, compared range, and truncated `expected` and `actual` text previews for both single-edit and workspace-edit requests

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
- if `request_vscode_edit` or `request_vscode_workspace_edit` fails with an expected-text mismatch, re-read the target range with `get_vscode_file_range`, refresh `expected_text`, and retry with a narrower anchored edit
- mismatch errors now include the file path, compared range, and shortened `expected` and `actual` previews so drift recovery can be done without guesswork
- after changing extension bridge code on disk, reload the VS Code window or restart the extension host so the running bridge picks up the updated `src/out` files

## Settings

- `windowsCodeSearchBridge.bridgeBaseUrl` - optional full URL override
- `windowsCodeSearchBridge.bridgeHost` - default `127.0.0.1`
- `windowsCodeSearchBridge.bridgePort` - default `8876`
- `windowsCodeSearchBridge.bridgeToken` - optional shared token
- `windowsCodeSearchBridge.pollIntervalMs` - command polling interval
- `windowsCodeSearchBridge.autoPushDiagnostics` - automatic Problems sync
- `windowsCodeSearchBridge.saveAfterApplyEdit` - save files after edits are applied

Commands:

- `Code Search Bridge: Restart Bridge Server`
- `Code Search Bridge: Set Bridge Port And Restart Server`

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
