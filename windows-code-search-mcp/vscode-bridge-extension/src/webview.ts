import * as vscode from 'vscode';

export function renderWebview(webview: vscode.Webview): string {
  const nonce = Date.now().toString(36);
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <style>
    :root {
      color-scheme: light dark;
      --bg: var(--vscode-sideBar-background);
      --surface: color-mix(in srgb, var(--vscode-editor-background) 86%, #b45309 14%);
      --border: var(--vscode-panel-border);
      --text: var(--vscode-foreground);
      --muted: var(--vscode-descriptionForeground);
      --accent: #d97706;
      --accent-2: #2563eb;
    }
    body {
      margin: 0;
      background: radial-gradient(circle at top, color-mix(in srgb, var(--accent) 18%, var(--bg) 82%), var(--bg));
      color: var(--text);
      font-family: Georgia, 'Segoe UI', serif;
    }
    .wrap {
      padding: 14px;
      display: grid;
      gap: 12px;
    }
    .card {
      background: color-mix(in srgb, var(--surface) 92%, black 8%);
      border: 1px solid color-mix(in srgb, var(--border) 70%, transparent 30%);
      border-radius: 14px;
      padding: 12px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.16);
    }
    .hero {
      display: grid;
      gap: 6px;
    }
    .title {
      font-size: 16px;
      font-weight: 700;
      letter-spacing: 0.03em;
    }
    .meta {
      color: var(--muted);
      font-size: 12px;
      word-break: break-all;
    }
    .dropzone {
      min-height: 120px;
      border-radius: 12px;
      border: 1px dashed color-mix(in srgb, var(--accent) 65%, var(--border) 35%);
      background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 14%, transparent 86%), color-mix(in srgb, var(--accent-2) 14%, transparent 86%));
      display: grid;
      place-items: center;
      text-align: center;
      padding: 16px;
      font-size: 13px;
    }
    .notice {
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid var(--border);
      font-size: 12px;
      display: none;
    }
    .notice.show {
      display: block;
    }
    .notice.success {
      background: color-mix(in srgb, #16a34a 18%, var(--vscode-editor-background) 82%);
    }
    .notice.warning {
      background: color-mix(in srgb, #f59e0b 20%, var(--vscode-editor-background) 80%);
    }
    .notice.error {
      background: color-mix(in srgb, #dc2626 20%, var(--vscode-editor-background) 80%);
    }
    .notice.info {
      background: color-mix(in srgb, #2563eb 18%, var(--vscode-editor-background) 82%);
    }
    textarea {
      width: 100%;
      min-height: 90px;
      resize: vertical;
      border-radius: 10px;
      border: 1px solid var(--border);
      padding: 10px;
      background: color-mix(in srgb, var(--vscode-input-background) 85%, black 15%);
      color: var(--text);
      box-sizing: border-box;
      font-family: Consolas, 'Courier New', monospace;
    }
    .actions, .mini-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 7px 12px;
      background: linear-gradient(135deg, var(--accent), #f59e0b);
      color: white;
      cursor: pointer;
      font-weight: 700;
    }
    button.secondary {
      background: linear-gradient(135deg, var(--accent-2), #38bdf8);
    }
    ul {
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 8px;
    }
    li {
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 10px;
      background: color-mix(in srgb, var(--vscode-editor-background) 94%, white 6%);
    }
    .row {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: flex-start;
    }
    .kind {
      color: var(--accent);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .preview {
      color: var(--muted);
      font-family: Consolas, 'Courier New', monospace;
      white-space: pre-wrap;
      max-height: 120px;
      overflow: hidden;
      margin-top: 6px;
      font-size: 12px;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="card hero">
      <div class="title">Context Window</div>
      <div class="meta" id="session"></div>
      <div class="meta" id="bridge"></div>
    </section>
    <section class="card notice" id="notice"></section>
    <section class="card">
      <div class="dropzone" id="dropzone">Drop files from the VS Code Explorer, editor tabs, or text from an editor here. If VS Code drag payloads are limited, use the explorer/tab context menu command "Code Search Bridge: Add To Context Window".</div>
    </section>
    <section class="card">
      <textarea id="snippet" placeholder="Paste any code snippet or notes you want the MCP server to see..."></textarea>
      <div class="actions" style="margin-top:10px;">
        <button id="addSnippet">Add Snippet</button>
        <button id="pushNow" class="secondary">Push Now</button>
      </div>
      <div class="mini-actions" style="margin-top:10px;">
        <button id="addFiles" class="secondary">Add Files...</button>
        <button id="addFolder" class="secondary">Add Folder...</button>
        <button id="addFolderSummary" class="secondary">Add Folder Names...</button>
        <button id="addActive" class="secondary">Add Active Editor</button>
        <button id="addSelection" class="secondary">Add Selection</button>
        <button id="addOpen" class="secondary">Add Open Editors</button>
        <button id="clear">Clear</button>
      </div>
    </section>
    <section class="card">
      <div class="title" style="font-size:14px; margin-bottom:8px;">Items</div>
      <ul id="items"></ul>
    </section>
  </div>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const dropzone = document.getElementById('dropzone');
    const snippet = document.getElementById('snippet');
    const items = document.getElementById('items');
    const session = document.getElementById('session');
    const bridge = document.getElementById('bridge');
    const notice = document.getElementById('notice');

    document.getElementById('addSnippet').addEventListener('click', () => {
      vscode.postMessage({ type: 'addSnippet', value: snippet.value });
      snippet.value = '';
    });
    document.getElementById('pushNow').addEventListener('click', () => vscode.postMessage({ type: 'pushNow' }));
    document.getElementById('addFiles').addEventListener('click', () => vscode.postMessage({ type: 'addFiles' }));
    document.getElementById('addFolder').addEventListener('click', () => vscode.postMessage({ type: 'addFolder' }));
    document.getElementById('addFolderSummary').addEventListener('click', () => vscode.postMessage({ type: 'addFolderSummary' }));
    document.getElementById('addActive').addEventListener('click', () => vscode.postMessage({ type: 'addActiveEditor' }));
    document.getElementById('addSelection').addEventListener('click', () => vscode.postMessage({ type: 'addSelection' }));
    document.getElementById('addOpen').addEventListener('click', () => vscode.postMessage({ type: 'addOpenEditors' }));
    document.getElementById('clear').addEventListener('click', () => vscode.postMessage({ type: 'clearItems' }));

    dropzone.addEventListener('dragover', (event) => {
      event.preventDefault();
      dropzone.style.opacity = '0.85';
    });
    dropzone.addEventListener('dragleave', () => {
      dropzone.style.opacity = '1';
    });
    dropzone.addEventListener('drop', (event) => {
      event.preventDefault();
      dropzone.style.opacity = '1';
      const transfer = event.dataTransfer;
      const uriList = transfer.getData('text/uri-list');
      const text = transfer.getData('text/plain');
      const files = Array.from(transfer.files || []).map((file) => file.path || file.name).filter(Boolean);
      const types = Array.from(transfer.types || []);
      const extras = types.map((type) => {
        try {
          return transfer.getData(type);
        } catch {
          return '';
        }
      }).filter(Boolean);
      if (uriList) {
        vscode.postMessage({ type: 'dropUriList', value: uriList });
        return;
      }
      if (files.length || extras.length) {
        vscode.postMessage({ type: 'dropCandidates', values: [...files, ...extras, text] });
        return;
      }
      if (text) {
        vscode.postMessage({ type: 'dropText', value: text });
      }
    });

    window.addEventListener('message', (event) => {
      const message = event.data;
      if (message.type !== 'state') {
        return;
      }
      session.textContent = 'Session: ' + message.sessionId;
      bridge.textContent = 'Bridge: ' + message.bridgeBaseUrl;
      if (message.notice && message.notice.text) {
        notice.className = 'card notice show ' + message.notice.kind;
        notice.textContent = message.notice.text;
      } else {
        notice.className = 'card notice';
        notice.textContent = '';
      }
      items.innerHTML = '';
      for (const item of message.items) {
        const li = document.createElement('li');
        li.innerHTML = '<div class="row"><div><div class="kind">' + item.kind + (item.metadataOnly ? ' - names only' : '') + '</div><div>' + item.label + '</div></div><button data-id="' + item.id + '">Remove</button></div><div class="preview"></div>';
        li.querySelector('.preview').textContent = item.content.slice(0, 500);
        li.querySelector('button').addEventListener('click', () => vscode.postMessage({ type: 'removeItem', id: item.id }));
        items.appendChild(li);
      }
    });

    vscode.postMessage({ type: 'ready' });
  </script>
</body>
</html>`;
}
