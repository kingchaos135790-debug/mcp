import * as path from 'path';
import * as vscode from 'vscode';

import { BridgeClient } from './bridgeClient';
import { CommandHandler } from './commandHandler';
import { MAX_FILE_BYTES } from './constants';
import { buildFolderSummary, collectFolderFiles, createDocumentItem, createFolderSummaryItem, createSelectionItem, createSnippetItem, looksBinary, tryResolveDroppedUri } from './contextHelpers';
import { ContextStore } from './contextStore';
import { BridgeCommand, ContextItem, FolderImportResult, NoticeKind, WebviewState } from './types';
import { renderWebview } from './webview';

export class BridgeController implements vscode.Disposable {
  private readonly bridgeClient: BridgeClient;
  private readonly commandHandler: CommandHandler;
  private readonly contextStore: ContextStore;
  private readonly sessionId: string;
  private readonly workspaceName: string;
  private readonly workspaceRoot: string;
  private readonly disposables: vscode.Disposable[] = [];
  private readonly statusBarItem: vscode.StatusBarItem;
  private view: vscode.WebviewView | undefined;
  private pollTimer: NodeJS.Timeout | undefined;
  private heartbeatTimer: NodeJS.Timeout | undefined;
  private polling = false;
  private notice: WebviewState['notice'];

  constructor(private readonly extensionContext: vscode.ExtensionContext) {
    this.bridgeClient = new BridgeClient(extensionContext);
    this.contextStore = new ContextStore(extensionContext);

    const folder = vscode.workspace.workspaceFolders?.[0];
    this.workspaceRoot = folder?.uri.fsPath ?? '';
    this.workspaceName = folder?.name ?? 'workspace';

    const savedSessionId = extensionContext.workspaceState.get<string>('windowsCodeSearchBridge.sessionId');
    this.sessionId = savedSessionId ?? `${this.workspaceName.replace(/[^a-zA-Z0-9_-]+/g, '-').toLowerCase() || 'workspace'}-${Date.now().toString(36)}`;
    void extensionContext.workspaceState.update('windowsCodeSearchBridge.sessionId', this.sessionId);

    this.commandHandler = new CommandHandler(this.bridgeClient, this.sessionId);

    this.statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 10);
    this.statusBarItem.command = 'windowsCodeSearchBridge.pushNow';
    this.statusBarItem.text = `Code Search: ${this.sessionId}`;
    this.statusBarItem.tooltip = 'Push code search context now';
    this.statusBarItem.show();

    this.disposables.push(this.statusBarItem);
    this.disposables.push(
      vscode.languages.onDidChangeDiagnostics(() => {
        if (this.autoPushDiagnosticsEnabled()) {
          void this.pushDiagnostics();
        }
      }),
      vscode.workspace.onDidChangeConfiguration((event) => {
        this.handleConfigurationChange(event);
      }),
      vscode.workspace.onDidSaveTextDocument(() => {
        void this.pushContext();
      }),
      vscode.window.onDidChangeActiveTextEditor(() => {
        void this.pushContext();
        if (this.autoPushDiagnosticsEnabled()) {
          void this.pushDiagnostics();
        }
      })
    );

    this.startPolling();
    this.startHeartbeat();
    void this.pushNow();
  }

  dispose(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
    }
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
    }
    vscode.Disposable.from(...this.disposables).dispose();
  }

  registerWebviewProvider(): vscode.Disposable {
    return vscode.window.registerWebviewViewProvider('windowsCodeSearchBridge.contextView', {
      resolveWebviewView: (webviewView) => {
        this.view = webviewView;
        webviewView.onDidDispose(() => {
          this.view = undefined;
        }, undefined, this.disposables);
        webviewView.webview.options = { enableScripts: true };
        webviewView.webview.html = renderWebview(webviewView.webview);
        webviewView.webview.onDidReceiveMessage(async (message) => {
          switch (message.type) {
            case 'ready':
              this.refreshWebview();
              break;
            case 'addSnippet':
            case 'dropText':
              await this.addSnippet(String(message.value ?? ''));
              break;
            case 'dropUriList':
              await this.addUriList(String(message.value ?? ''));
              break;
            case 'dropCandidates':
              await this.addDropCandidates(Array.isArray(message.values) ? message.values : []);
              break;
            case 'removeItem':
              await this.contextStore.remove(String(message.id));
              this.setNotice('success', 'Removed item from the context window.');
              await this.pushContext();
              this.refreshWebview();
              break;
            case 'clearItems':
              await this.contextStore.clear();
              this.setNotice('success', 'Cleared all context items.');
              await this.pushContext();
              this.refreshWebview();
              break;
            case 'pushNow':
              await this.pushNow();
              break;
            case 'addFiles':
              await this.addFiles();
              break;
            case 'addFolder':
              await this.addFolder();
              break;
            case 'addFolderSummary':
              await this.addFolderSummary();
              break;
            case 'addActiveEditor':
              await this.addActiveEditor();
              break;
            case 'addSelection':
              await this.addSelection();
              break;
            case 'addOpenEditors':
              await this.addOpenEditors();
              break;
          }
        }, undefined, this.disposables);
      }
    }, { webviewOptions: { retainContextWhenHidden: true } });
  }

  async addActiveEditor(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showWarningMessage('No active editor to add.');
      this.setNotice('warning', 'No active editor to add.');
      this.refreshWebview();
      return;
    }
    await this.addDocument(editor.document, 'file');
  }

  async addFiles(): Promise<void> {
    const selected = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: true,
      openLabel: 'Add To Code Search Context',
      defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri
    });
    if (!selected || !selected.length) {
      this.setNotice('info', 'No files selected.');
      this.refreshWebview();
      return;
    }
    await this.addResource(selected);
  }

  async addFolder(): Promise<void> {
    const selected = await vscode.window.showOpenDialog({
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: true,
      openLabel: 'Add Folder To Code Search Context',
      defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri
    });
    if (!selected || !selected.length) {
      this.setNotice('info', 'No folders selected.');
      this.refreshWebview();
      return;
    }
    await this.addResource(selected);
  }

  async addFolderSummary(): Promise<void> {
    const selected = await vscode.window.showOpenDialog({
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: true,
      openLabel: 'Add Folder Names To Code Search Context',
      defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri
    });
    if (!selected || !selected.length) {
      this.setNotice('info', 'No folders selected for names-only import.');
      this.refreshWebview();
      return;
    }

    let added = 0;
    for (const folder of selected) {
      const summary = await buildFolderSummary(folder);
      await this.contextStore.add(createFolderSummaryItem(folder, summary));
      added += 1;
    }

    this.setNotice('success', `Added ${added} folder name summary${added === 1 ? '' : 'ies'} to the context window.`);
    await this.pushContext();
    this.refreshWebview();
  }

  async addSelection(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showWarningMessage('No active editor selection to add.');
      this.setNotice('warning', 'No active editor selection to add.');
      this.refreshWebview();
      return;
    }
    if (editor.selection.isEmpty) {
      vscode.window.showWarningMessage('Current selection is empty.');
      this.setNotice('warning', 'Current selection is empty.');
      this.refreshWebview();
      return;
    }
    await this.contextStore.add(createSelectionItem(editor));
    await this.pushContext();
    this.refreshWebview();
  }

  async addOpenEditors(): Promise<void> {
    const editors = vscode.window.visibleTextEditors;
    if (!editors.length) {
      vscode.window.showWarningMessage('No visible editors to add.');
      this.setNotice('warning', 'No visible editors to add.');
      this.refreshWebview();
      return;
    }
    for (const editor of editors) {
      await this.addDocument(editor.document, 'file');
    }
    this.setNotice('success', `Added ${editors.length} open editor${editors.length === 1 ? '' : 's'} to context.`);
    this.refreshWebview();
  }

  async restartBridgeServer(requestBaseUrl?: string): Promise<void> {
    const target = this.bridgeClient.connection;
    const candidateBaseUrls = [requestBaseUrl, this.bridgeClient.lastSuccessfulBaseUrl, this.bridgeClient.baseUrl]
      .map((value) => value?.trim() ?? '')
      .filter((value, index, values) => Boolean(value) && values.indexOf(value) === index);

    if (!candidateBaseUrls.length) {
      throw new Error('No bridge URL is available for restart.');
    }

    let lastError: unknown;
    for (const candidateBaseUrl of candidateBaseUrls) {
      try {
        const result = await this.bridgeClient.postJson<{ nextBaseUrl: string }>('/admin/restart', {
          host: target.host,
          port: target.port
        }, candidateBaseUrl);
        const nextBaseUrl = String(result.nextBaseUrl ?? target.baseUrl);
        await this.waitForBridge(nextBaseUrl);
        this.setNotice('success', `Bridge server restarted on ${nextBaseUrl}.`);
        this.refreshWebview();
        void vscode.window.showInformationMessage(`Code Search Bridge restarted on ${nextBaseUrl}.`);
        return;
      } catch (error) {
        lastError = error;
      }
    }

    this.showBridgeError('Failed to restart bridge server', lastError ?? 'Unknown error');
  }

  async setBridgePortAndRestart(): Promise<void> {
    const target = this.bridgeClient.connection;
    const portInput = await vscode.window.showInputBox({
      title: 'Set Code Search Bridge Port',
      prompt: 'Enter the localhost port for the VS Code bridge server.',
      value: String(target.port),
      validateInput: (value) => {
        const port = Number(value.trim());
        if (!Number.isInteger(port) || port < 1 || port > 65535) {
          return 'Enter a whole number between 1 and 65535.';
        }
        return undefined;
      }
    });
    if (!portInput) {
      return;
    }

    const previousBaseUrl = this.bridgeClient.lastSuccessfulBaseUrl || this.bridgeClient.baseUrl;
    const nextPort = Number(portInput.trim());
    const config = vscode.workspace.getConfiguration('windowsCodeSearchBridge');

    await config.update('bridgeHost', target.host, vscode.ConfigurationTarget.Global);
    await config.update('bridgePort', nextPort, vscode.ConfigurationTarget.Global);
    if (target.baseUrlOverride) {
      await config.update('bridgeBaseUrl', '', vscode.ConfigurationTarget.Global);
    }

    await this.restartBridgeServer(previousBaseUrl);
  }

  async pushNow(): Promise<void> {
    const contextOk = await this.pushContext();
    const diagnosticsOk = await this.pushDiagnostics();
    if (contextOk && diagnosticsOk) {
      this.setNotice('success', 'Pushed context and diagnostics to the bridge.');
      vscode.window.setStatusBarMessage('Code search bridge pushed context and diagnostics.', 2500);
    }
    this.refreshWebview();
  }

  async pushContext(): Promise<boolean> {
    try {
      const items = await this.hydrateContextItems();
      await this.bridgeClient.postJson(`/sessions/${encodeURIComponent(this.sessionId)}/context`, {
        workspaceRoot: this.workspaceRoot,
        workspaceName: this.workspaceName,
        activeFile: vscode.window.activeTextEditor?.document.uri.fsPath ?? '',
        items
      });
      return true;
    } catch (error) {
      this.showBridgeError('Failed to push context', error, false);
      return false;
    }
  }

  async pushDiagnostics(): Promise<boolean> {
    try {
      await this.bridgeClient.postJson(`/sessions/${encodeURIComponent(this.sessionId)}/diagnostics`, {
        workspaceRoot: this.workspaceRoot,
        workspaceName: this.workspaceName,
        activeFile: vscode.window.activeTextEditor?.document.uri.fsPath ?? '',
        diagnostics: this.collectDiagnostics()
      });
      return true;
    } catch (error) {
      this.showBridgeError('Failed to push diagnostics', error, false);
      return false;
    }
  }

  async addResource(resource?: vscode.Uri | vscode.Uri[]): Promise<void> {
    const resources = Array.isArray(resource) ? resource : resource ? [resource] : [];
    if (!resources.length) {
      await this.addActiveEditor();
      return;
    }

    let added = 0;
    let folderCount = 0;
    let skippedEntries = 0;

    for (const item of resources) {
      try {
        if (item.scheme !== 'file') {
          continue;
        }
        const stat = await vscode.workspace.fs.stat(item);
        if (stat.type & vscode.FileType.Directory) {
          const result = await this.addFolderResource(item, false);
          added += result.added;
          skippedEntries += result.skipped;
          if (result.added > 0) {
            folderCount += 1;
          }
          continue;
        }
        const document = await vscode.workspace.openTextDocument(item);
        await this.addDocument(document, 'file', false);
        added += 1;
      } catch {
        continue;
      }
    }

    if (added > 0) {
      const resourceLabel = folderCount > 0
        ? `Added ${added} file${added === 1 ? '' : 's'} from ${folderCount} folder${folderCount === 1 ? '' : 's'} and selected resources.`
        : `Added ${added} resource${added === 1 ? '' : 's'} from Explorer or tab.`;
      const skippedLabel = skippedEntries > 0 ? ` Skipped ${skippedEntries} large, binary, or ignored entries.` : '';
      this.setNotice('success', `${resourceLabel}${skippedLabel}`);
      await this.pushContext();
      this.refreshWebview();
      return;
    }

    this.setNotice('warning', 'Could not add the dropped or selected resource.');
    this.refreshWebview();
  }

  private async hydrateContextItems(): Promise<ContextItem[]> {
    const hydrated: ContextItem[] = [];
    for (const item of this.contextStore.all()) {
      if (!item.filePath || item.metadataOnly || item.kind === 'summary') {
        hydrated.push(item);
        continue;
      }
      try {
        const document = await vscode.workspace.openTextDocument(vscode.Uri.file(item.filePath));
        if (item.kind === 'selection' && item.startLine && item.endLine) {
          const startLine = Math.min(Math.max(0, item.startLine - 1), Math.max(0, document.lineCount - 1));
          const endLine = Math.min(Math.max(0, item.endLine - 1), Math.max(0, document.lineCount - 1));
          const start = new vscode.Position(startLine, 0);
          const end = new vscode.Position(endLine, document.lineAt(endLine).text.length);
          hydrated.push({
            ...item,
            content: document.getText(new vscode.Range(start, end)),
            language: document.languageId,
            label: `${path.basename(document.uri.fsPath)}:${item.startLine}-${item.endLine}`
          });
          continue;
        }
        hydrated.push({
          ...item,
          content: document.getText(),
          language: document.languageId,
          label: path.basename(document.uri.fsPath)
        });
      } catch {
        hydrated.push(item);
      }
    }
    await this.contextStore.replace(hydrated);
    return hydrated;
  }

  private collectDiagnostics(): any[] {
    const mapped: any[] = [];
    for (const [uri, diagnostics] of vscode.languages.getDiagnostics()) {
      for (const diagnostic of diagnostics) {
        mapped.push({
          filePath: uri.fsPath,
          message: diagnostic.message,
          severity: this.mapSeverity(diagnostic.severity),
          source: diagnostic.source ?? '',
          code: typeof diagnostic.code === 'object' ? diagnostic.code.value : diagnostic.code ?? '',
          startLine: diagnostic.range.start.line + 1,
          startColumn: diagnostic.range.start.character + 1,
          endLine: diagnostic.range.end.line + 1,
          endColumn: diagnostic.range.end.character + 1
        });
      }
    }
    return mapped;
  }

  private mapSeverity(severity: vscode.DiagnosticSeverity): string {
    switch (severity) {
      case vscode.DiagnosticSeverity.Error:
        return 'error';
      case vscode.DiagnosticSeverity.Warning:
        return 'warning';
      case vscode.DiagnosticSeverity.Information:
        return 'information';
      case vscode.DiagnosticSeverity.Hint:
        return 'hint';
      default:
        return 'unknown';
    }
  }

  private async addSnippet(value: string): Promise<void> {
    const content = value.trim();
    if (!content) {
      this.setNotice('warning', 'Ignored empty snippet.');
      this.refreshWebview();
      return;
    }
    await this.contextStore.add(createSnippetItem(content));
    this.setNotice('success', 'Added snippet to the context window.');
    await this.pushContext();
    this.refreshWebview();
  }

  private async addUriList(value: string): Promise<void> {
    const uris = value.split(/\r?\n/).map((entry) => entry.trim()).filter(Boolean);
    await this.addDropCandidates(uris);
  }

  private async addDropCandidates(values: unknown[]): Promise<void> {
    const candidates = values
      .flatMap((value) => typeof value === 'string' ? value.split(/\r?\n/) : [])
      .map((entry) => entry.trim())
      .filter(Boolean);

    let added = 0;
    for (const candidate of candidates) {
      const uri = tryResolveDroppedUri(candidate);
      if (!uri) {
        continue;
      }
      try {
        const stat = await vscode.workspace.fs.stat(uri);
        if (stat.type & vscode.FileType.Directory) {
          const result = await this.addFolderResource(uri, false);
          added += result.added;
          continue;
        }
        const document = await vscode.workspace.openTextDocument(uri);
        await this.addDocument(document, 'file', false);
        added += 1;
      } catch {
        continue;
      }
    }

    if (added > 0) {
      this.setNotice('success', `Added ${added} dropped file${added === 1 ? '' : 's'} to context.`);
      await this.pushContext();
      this.refreshWebview();
      return;
    }

    const textPayload = candidates.join('\n').trim();
    if (textPayload) {
      await this.addSnippet(textPayload);
      this.setNotice('success', 'Added dropped text to the context window.');
      this.refreshWebview();
      return;
    }

    this.setNotice('warning', 'Drop was detected, but no readable file or text payload was found.');
    this.refreshWebview();
  }

  private async addDocument(document: vscode.TextDocument, kind: 'file' | 'selection', pushImmediately: boolean = true): Promise<void> {
    if (document.uri.scheme !== 'file') {
      vscode.window.showWarningMessage(`Skipping non-file document: ${document.uri.toString()}`);
      this.setNotice('warning', `Skipping non-file document: ${document.uri.toString()}`);
      this.refreshWebview();
      return;
    }
    await this.contextStore.add(createDocumentItem(document));
    this.setNotice('success', `Added ${path.basename(document.uri.fsPath)} to the context window.`);
    if (pushImmediately) {
      await this.pushContext();
    }
    this.refreshWebview();
  }

  private async addFolderResource(folder: vscode.Uri, pushImmediately: boolean = true): Promise<FolderImportResult> {
    const fileUris = await collectFolderFiles(folder);
    let added = 0;
    let skipped = 0;

    for (const uri of fileUris) {
      try {
        const stat = await vscode.workspace.fs.stat(uri);
        if (stat.size > MAX_FILE_BYTES) {
          skipped += 1;
          continue;
        }
        const document = await vscode.workspace.openTextDocument(uri);
        if (looksBinary(document.getText())) {
          skipped += 1;
          continue;
        }
        await this.addDocument(document, 'file', false);
        added += 1;
      } catch {
        skipped += 1;
      }
    }

    if (added > 0) {
      this.setNotice('success', `Added ${added} file${added === 1 ? '' : 's'} from ${path.basename(folder.fsPath) || folder.fsPath}.${skipped > 0 ? ` Skipped ${skipped} large, binary, or ignored entries.` : ''}`);
      if (pushImmediately) {
        await this.pushContext();
      }
      this.refreshWebview();
      return { added, skipped };
    }

    this.setNotice('warning', `No readable files found in ${path.basename(folder.fsPath) || folder.fsPath}.`);
    this.refreshWebview();
    return { added, skipped };
  }

  private startPolling(): void {
    const interval = Math.max(500, vscode.workspace.getConfiguration('windowsCodeSearchBridge').get<number>('pollIntervalMs', 1500));
    this.pollTimer = setInterval(() => {
      void this.pollCommands();
    }, interval);
    void this.pollCommands();
  }

  private restartPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = undefined;
    }
    this.startPolling();
  }

  private startHeartbeat(): void {
    const interval = Math.max(5000, vscode.workspace.getConfiguration('windowsCodeSearchBridge').get<number>('heartbeatIntervalMs', 30000));
    this.heartbeatTimer = setInterval(() => {
      void this.pushContext();
      if (this.autoPushDiagnosticsEnabled()) {
        void this.pushDiagnostics();
      }
    }, interval);
  }

  private restartHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = undefined;
    }
    this.startHeartbeat();
  }

  private async pollCommands(): Promise<void> {
    if (this.polling) {
      return;
    }
    this.polling = true;
    try {
      const response = await this.bridgeClient.getJson<{ commands: BridgeCommand[] }>(`/sessions/${encodeURIComponent(this.sessionId)}/commands`);
      for (const command of response.commands ?? []) {
        await this.handleCommand(command);
      }
    } catch (error) {
      this.showBridgeError('Bridge polling failed', error, false);
    } finally {
      this.polling = false;
    }
  }

  private async handleCommand(command: BridgeCommand): Promise<void> {
    try {
      const { payload, isEdit } = await this.commandHandler.execute(command);
      await this.commandHandler.reportResult(command.commandId, {
        status: 'ok',
        payload
      });
      if (isEdit) {
        await this.pushContext();
        if (this.autoPushDiagnosticsEnabled()) {
          await this.pushDiagnostics();
        }
      }
    } catch (error) {
      await this.commandHandler.reportResult(command.commandId, {
        status: 'error',
        error: error instanceof Error ? error.message : String(error)
      });
    }
  }

  private autoPushDiagnosticsEnabled(): boolean {
    return vscode.workspace.getConfiguration('windowsCodeSearchBridge').get<boolean>('autoPushDiagnostics', true);
  }

  private handleConfigurationChange(event: vscode.ConfigurationChangeEvent): void {
    if (event.affectsConfiguration('windowsCodeSearchBridge.pollIntervalMs')) {
      this.restartPolling();
    }

    if (event.affectsConfiguration('windowsCodeSearchBridge.heartbeatIntervalMs')) {
      this.restartHeartbeat();
    }

    if (
      event.affectsConfiguration('windowsCodeSearchBridge.bridgeBaseUrl') ||
      event.affectsConfiguration('windowsCodeSearchBridge.bridgeHost') ||
      event.affectsConfiguration('windowsCodeSearchBridge.bridgePort')
    ) {
      this.setNotice('info', `Bridge target is now ${this.bridgeClient.baseUrl}. Run "Code Search Bridge: Restart Bridge Server" to apply it.`);
      this.refreshWebview();
    }
  }

  private async waitForBridge(baseUrl: string, timeoutMs: number = 10000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    let lastError: unknown;

    while (Date.now() < deadline) {
      try {
        await this.bridgeClient.getJson('/health', baseUrl);
        return;
      } catch (error) {
        lastError = error;
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
    }

    throw new Error(`Timed out waiting for bridge health at ${baseUrl}: ${lastError instanceof Error ? lastError.message : String(lastError)}`);
  }

  private refreshWebview(): void {
    const state: WebviewState = {
      sessionId: this.sessionId,
      items: this.contextStore.all(),
      bridgeBaseUrl: this.bridgeClient.baseUrl,
      notice: this.notice
    };
    this.view?.webview.postMessage({ type: 'state', ...state });
  }

  private showBridgeError(prefix: string, error: unknown, notify: boolean = true): void {
    const message = `${prefix}: ${error instanceof Error ? error.message : String(error)}`;
    this.setNotice('error', message);
    this.refreshWebview();
    if (notify) {
      void vscode.window.showWarningMessage(message);
    }
    this.statusBarItem.tooltip = message;
  }

  private setNotice(kind: NoticeKind, text: string): void {
    this.notice = { kind, text };
  }
}


