"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.BridgeController = void 0;
const path = __importStar(require("path"));
const vscode = __importStar(require("vscode"));
const bridgeClient_1 = require("./bridgeClient");
const constants_1 = require("./constants");
const contextHelpers_1 = require("./contextHelpers");
const contextStore_1 = require("./contextStore");
const webview_1 = require("./webview");
class BridgeController {
    extensionContext;
    bridgeClient;
    contextStore;
    sessionId;
    workspaceName;
    workspaceRoot;
    disposables = [];
    statusBarItem;
    view;
    pollTimer;
    polling = false;
    notice;
    constructor(extensionContext) {
        this.extensionContext = extensionContext;
        this.bridgeClient = new bridgeClient_1.BridgeClient(extensionContext);
        this.contextStore = new contextStore_1.ContextStore(extensionContext);
        const folder = vscode.workspace.workspaceFolders?.[0];
        this.workspaceRoot = folder?.uri.fsPath ?? '';
        this.workspaceName = folder?.name ?? 'workspace';
        const savedSessionId = extensionContext.workspaceState.get('windowsCodeSearchBridge.sessionId');
        this.sessionId = savedSessionId ?? `${this.workspaceName.replace(/[^a-zA-Z0-9_-]+/g, '-').toLowerCase() || 'workspace'}-${Date.now().toString(36)}`;
        void extensionContext.workspaceState.update('windowsCodeSearchBridge.sessionId', this.sessionId);
        this.statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 10);
        this.statusBarItem.command = 'windowsCodeSearchBridge.pushNow';
        this.statusBarItem.text = `Code Search: ${this.sessionId}`;
        this.statusBarItem.tooltip = 'Push code search context now';
        this.statusBarItem.show();
        this.disposables.push(this.statusBarItem);
        this.disposables.push(vscode.languages.onDidChangeDiagnostics(() => {
            if (this.autoPushDiagnosticsEnabled()) {
                void this.pushDiagnostics();
            }
        }), vscode.workspace.onDidChangeConfiguration((event) => {
            this.handleConfigurationChange(event);
        }), vscode.workspace.onDidSaveTextDocument(() => {
            void this.pushContext();
        }), vscode.window.onDidChangeActiveTextEditor(() => {
            void this.pushContext();
            if (this.autoPushDiagnosticsEnabled()) {
                void this.pushDiagnostics();
            }
        }));
        this.startPolling();
        void this.pushNow();
    }
    dispose() {
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
        }
        vscode.Disposable.from(...this.disposables).dispose();
    }
    registerWebviewProvider() {
        return vscode.window.registerWebviewViewProvider('windowsCodeSearchBridge.contextView', {
            resolveWebviewView: (webviewView) => {
                this.view = webviewView;
                webviewView.onDidDispose(() => {
                    this.view = undefined;
                }, undefined, this.disposables);
                webviewView.webview.options = { enableScripts: true };
                webviewView.webview.html = (0, webview_1.renderWebview)(webviewView.webview);
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
    async addActiveEditor() {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showWarningMessage('No active editor to add.');
            this.setNotice('warning', 'No active editor to add.');
            this.refreshWebview();
            return;
        }
        await this.addDocument(editor.document, 'file');
    }
    async addFiles() {
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
    async addFolder() {
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
    async addFolderSummary() {
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
            const summary = await (0, contextHelpers_1.buildFolderSummary)(folder);
            await this.contextStore.add((0, contextHelpers_1.createFolderSummaryItem)(folder, summary));
            added += 1;
        }
        this.setNotice('success', `Added ${added} folder name summary${added === 1 ? '' : 'ies'} to the context window.`);
        await this.pushContext();
        this.refreshWebview();
    }
    async addSelection() {
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
        await this.contextStore.add((0, contextHelpers_1.createSelectionItem)(editor));
        await this.pushContext();
        this.refreshWebview();
    }
    async addOpenEditors() {
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
    async restartBridgeServer(requestBaseUrl) {
        const target = this.bridgeClient.connection;
        const candidateBaseUrls = [requestBaseUrl, this.bridgeClient.lastSuccessfulBaseUrl, this.bridgeClient.baseUrl]
            .map((value) => value?.trim() ?? '')
            .filter((value, index, values) => Boolean(value) && values.indexOf(value) === index);
        if (!candidateBaseUrls.length) {
            throw new Error('No bridge URL is available for restart.');
        }
        let lastError;
        for (const candidateBaseUrl of candidateBaseUrls) {
            try {
                const result = await this.bridgeClient.postJson('/admin/restart', {
                    host: target.host,
                    port: target.port
                }, candidateBaseUrl);
                const nextBaseUrl = String(result.nextBaseUrl ?? target.baseUrl);
                await this.waitForBridge(nextBaseUrl);
                this.setNotice('success', `Bridge server restarted on ${nextBaseUrl}.`);
                this.refreshWebview();
                void vscode.window.showInformationMessage(`Code Search Bridge restarted on ${nextBaseUrl}.`);
                return;
            }
            catch (error) {
                lastError = error;
            }
        }
        this.showBridgeError('Failed to restart bridge server', lastError ?? 'Unknown error');
    }
    async setBridgePortAndRestart() {
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
    async pushNow() {
        await this.pushContext();
        await this.pushDiagnostics();
        this.setNotice('success', 'Pushed context and diagnostics to the bridge.');
        this.refreshWebview();
        vscode.window.setStatusBarMessage('Code search bridge pushed context and diagnostics.', 2500);
    }
    async pushContext() {
        try {
            const items = await this.hydrateContextItems();
            await this.bridgeClient.postJson(`/sessions/${encodeURIComponent(this.sessionId)}/context`, {
                workspaceRoot: this.workspaceRoot,
                workspaceName: this.workspaceName,
                activeFile: vscode.window.activeTextEditor?.document.uri.fsPath ?? '',
                items
            });
        }
        catch (error) {
            this.showBridgeError('Failed to push context', error, false);
        }
    }
    async pushDiagnostics() {
        try {
            await this.bridgeClient.postJson(`/sessions/${encodeURIComponent(this.sessionId)}/diagnostics`, {
                workspaceRoot: this.workspaceRoot,
                workspaceName: this.workspaceName,
                activeFile: vscode.window.activeTextEditor?.document.uri.fsPath ?? '',
                diagnostics: this.collectDiagnostics()
            });
        }
        catch (error) {
            this.showBridgeError('Failed to push diagnostics', error, false);
        }
    }
    async addResource(resource) {
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
            }
            catch {
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
    async hydrateContextItems() {
        const hydrated = [];
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
            }
            catch {
                hydrated.push(item);
            }
        }
        await this.contextStore.replace(hydrated);
        return hydrated;
    }
    collectDiagnostics() {
        const mapped = [];
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
    mapSeverity(severity) {
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
    async addSnippet(value) {
        const content = value.trim();
        if (!content) {
            this.setNotice('warning', 'Ignored empty snippet.');
            this.refreshWebview();
            return;
        }
        await this.contextStore.add((0, contextHelpers_1.createSnippetItem)(content));
        this.setNotice('success', 'Added snippet to the context window.');
        await this.pushContext();
        this.refreshWebview();
    }
    async addUriList(value) {
        const uris = value.split(/\r?\n/).map((entry) => entry.trim()).filter(Boolean);
        await this.addDropCandidates(uris);
    }
    async addDropCandidates(values) {
        const candidates = values
            .flatMap((value) => typeof value === 'string' ? value.split(/\r?\n/) : [])
            .map((entry) => entry.trim())
            .filter(Boolean);
        let added = 0;
        for (const candidate of candidates) {
            const uri = this.tryResolveDroppedUri(candidate);
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
            }
            catch {
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
    tryResolveDroppedUri(candidate) {
        const cleaned = candidate.replace(/^file:\/\//i, 'file://').trim();
        try {
            const parsed = vscode.Uri.parse(cleaned);
            if (parsed.scheme === 'file' && parsed.fsPath) {
                return parsed;
            }
        }
        catch {
            // Ignore and try path-based resolution next.
        }
        const stripped = cleaned.replace(/^['"]|['"]$/g, '');
        if (path.isAbsolute(stripped)) {
            return vscode.Uri.file(stripped);
        }
        const folder = vscode.workspace.workspaceFolders?.[0];
        if (folder) {
            return vscode.Uri.joinPath(folder.uri, stripped);
        }
        return undefined;
    }
    async addDocument(document, kind, pushImmediately = true) {
        if (document.uri.scheme !== 'file') {
            vscode.window.showWarningMessage(`Skipping non-file document: ${document.uri.toString()}`);
            this.setNotice('warning', `Skipping non-file document: ${document.uri.toString()}`);
            this.refreshWebview();
            return;
        }
        await this.contextStore.add((0, contextHelpers_1.createDocumentItem)(document));
        this.setNotice('success', `Added ${path.basename(document.uri.fsPath)} to the context window.`);
        if (pushImmediately) {
            await this.pushContext();
        }
        this.refreshWebview();
    }
    async addFolderResource(folder, pushImmediately = true) {
        const fileUris = await this.collectFolderFiles(folder);
        let added = 0;
        let skipped = 0;
        for (const uri of fileUris) {
            try {
                const stat = await vscode.workspace.fs.stat(uri);
                if (stat.size > constants_1.MAX_FILE_BYTES) {
                    skipped += 1;
                    continue;
                }
                const document = await vscode.workspace.openTextDocument(uri);
                if ((0, contextHelpers_1.looksBinary)(document.getText())) {
                    skipped += 1;
                    continue;
                }
                await this.addDocument(document, 'file', false);
                added += 1;
            }
            catch {
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
    async collectFolderFiles(root) {
        const results = [];
        const queue = [root];
        while (queue.length > 0 && results.length < constants_1.MAX_FOLDER_FILES) {
            const current = queue.shift();
            if (!current) {
                break;
            }
            let entries = [];
            try {
                entries = await vscode.workspace.fs.readDirectory(current);
            }
            catch {
                continue;
            }
            for (const [name, type] of entries.sort(([left], [right]) => left.localeCompare(right))) {
                if (results.length >= constants_1.MAX_FOLDER_FILES) {
                    break;
                }
                const child = vscode.Uri.joinPath(current, name);
                if (type & vscode.FileType.Directory) {
                    if (!constants_1.SKIPPED_DIRECTORY_NAMES.has(name.toLowerCase())) {
                        queue.push(child);
                    }
                    continue;
                }
                if (type & vscode.FileType.File) {
                    results.push(child);
                }
            }
        }
        return results;
    }
    startPolling() {
        const interval = Math.max(500, vscode.workspace.getConfiguration('windowsCodeSearchBridge').get('pollIntervalMs', 1500));
        this.pollTimer = setInterval(() => {
            void this.pollCommands();
        }, interval);
        void this.pollCommands();
    }
    restartPolling() {
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = undefined;
        }
        this.startPolling();
    }
    async pollCommands() {
        if (this.polling) {
            return;
        }
        this.polling = true;
        try {
            const response = await this.bridgeClient.getJson(`/sessions/${encodeURIComponent(this.sessionId)}/commands`);
            for (const command of response.commands ?? []) {
                await this.handleCommand(command);
            }
        }
        catch (error) {
            this.showBridgeError('Bridge polling failed', error, false);
        }
        finally {
            this.polling = false;
        }
    }
    async handleCommand(command) {
        try {
            let payload = {};
            switch (command.type) {
                case 'apply_edit':
                    payload = await this.applyEdit(command.payload);
                    break;
                case 'apply_workspace_edit':
                    payload = await this.applyWorkspaceEdit(command.payload);
                    break;
                case 'open_file':
                    payload = await this.openFile(command.payload);
                    break;
                default:
                    throw new Error(`Unsupported bridge command: ${command.type}`);
            }
            await this.reportCommandResult(command.commandId, {
                status: 'ok',
                payload
            });
            if (command.type === 'apply_edit' || command.type === 'apply_workspace_edit') {
                await this.pushContext();
                if (this.autoPushDiagnosticsEnabled()) {
                    await this.pushDiagnostics();
                }
            }
        }
        catch (error) {
            await this.reportCommandResult(command.commandId, {
                status: 'error',
                error: error instanceof Error ? error.message : String(error)
            });
        }
    }
    async applyEdit(payload) {
        const document = await vscode.workspace.openTextDocument(vscode.Uri.file(String(payload.filePath)));
        const range = this.toRange(payload.range);
        const expectedText = String(payload.expectedText ?? '');
        if (expectedText) {
            const actual = document.getText(range);
            if (actual !== expectedText) {
                throw new Error('Expected text mismatch before applying edit.');
            }
        }
        const edit = new vscode.WorkspaceEdit();
        edit.replace(document.uri, range, String(payload.newText ?? ''));
        const applied = await vscode.workspace.applyEdit(edit);
        if (!applied) {
            throw new Error('VS Code rejected the edit.');
        }
        if (vscode.workspace.getConfiguration('windowsCodeSearchBridge').get('saveAfterApplyEdit', true)) {
            await document.save();
        }
        return {
            filePath: document.uri.fsPath,
            applied: true
        };
    }
    async applyWorkspaceEdit(payload) {
        const edits = Array.isArray(payload.edits) ? payload.edits : [];
        const workspaceEdit = new vscode.WorkspaceEdit();
        for (const item of edits) {
            const document = await vscode.workspace.openTextDocument(vscode.Uri.file(String(item.filePath)));
            const range = this.toRange(item.range);
            const expectedText = String(item.expectedText ?? '');
            if (expectedText) {
                const actual = document.getText(range);
                if (actual !== expectedText) {
                    throw new Error(`Expected text mismatch before workspace edit in ${document.uri.fsPath}.`);
                }
            }
            workspaceEdit.replace(document.uri, range, String(item.newText ?? ''));
        }
        const applied = await vscode.workspace.applyEdit(workspaceEdit);
        if (!applied) {
            throw new Error('VS Code rejected the workspace edit.');
        }
        if (vscode.workspace.getConfiguration('windowsCodeSearchBridge').get('saveAfterApplyEdit', true)) {
            for (const item of edits) {
                const document = await vscode.workspace.openTextDocument(vscode.Uri.file(String(item.filePath)));
                await document.save();
            }
        }
        return {
            applied: true,
            editCount: edits.length,
            label: String(payload.label ?? 'MCP workspace edit')
        };
    }
    async openFile(payload) {
        const document = await vscode.workspace.openTextDocument(vscode.Uri.file(String(payload.filePath)));
        const line = Math.max(1, Number(payload.line ?? 1));
        const column = Math.max(1, Number(payload.column ?? 1));
        const position = new vscode.Position(line - 1, column - 1);
        await vscode.window.showTextDocument(document, {
            preserveFocus: Boolean(payload.preserveFocus),
            selection: new vscode.Range(position, position)
        });
        return {
            filePath: document.uri.fsPath,
            line,
            column
        };
    }
    toRange(input) {
        const startLine = Math.max(1, Number(input?.startLine ?? 1));
        const startColumn = Math.max(1, Number(input?.startColumn ?? 1));
        const endLine = Math.max(1, Number(input?.endLine ?? startLine));
        const endColumn = Math.max(1, Number(input?.endColumn ?? startColumn));
        return new vscode.Range(startLine - 1, startColumn - 1, endLine - 1, endColumn - 1);
    }
    async reportCommandResult(commandId, payload) {
        await this.bridgeClient.postJson(`/sessions/${encodeURIComponent(this.sessionId)}/commands/${encodeURIComponent(commandId)}/result`, payload);
    }
    autoPushDiagnosticsEnabled() {
        return vscode.workspace.getConfiguration('windowsCodeSearchBridge').get('autoPushDiagnostics', true);
    }
    handleConfigurationChange(event) {
        if (event.affectsConfiguration('windowsCodeSearchBridge.pollIntervalMs')) {
            this.restartPolling();
        }
        if (event.affectsConfiguration('windowsCodeSearchBridge.bridgeBaseUrl') ||
            event.affectsConfiguration('windowsCodeSearchBridge.bridgeHost') ||
            event.affectsConfiguration('windowsCodeSearchBridge.bridgePort')) {
            this.setNotice('info', `Bridge target is now ${this.bridgeClient.baseUrl}. Run "Code Search Bridge: Restart Bridge Server" to apply it.`);
            this.refreshWebview();
        }
    }
    async waitForBridge(baseUrl, timeoutMs = 10000) {
        const deadline = Date.now() + timeoutMs;
        let lastError;
        while (Date.now() < deadline) {
            try {
                await this.bridgeClient.getJson('/health', baseUrl);
                return;
            }
            catch (error) {
                lastError = error;
                await new Promise((resolve) => setTimeout(resolve, 250));
            }
        }
        throw new Error(`Timed out waiting for bridge health at ${baseUrl}: ${lastError instanceof Error ? lastError.message : String(lastError)}`);
    }
    refreshWebview() {
        const state = {
            sessionId: this.sessionId,
            items: this.contextStore.all(),
            bridgeBaseUrl: this.bridgeClient.baseUrl,
            notice: this.notice
        };
        this.view?.webview.postMessage({ type: 'state', ...state });
    }
    showBridgeError(prefix, error, notify = true) {
        const message = `${prefix}: ${error instanceof Error ? error.message : String(error)}`;
        this.setNotice('error', message);
        this.refreshWebview();
        if (notify) {
            void vscode.window.showWarningMessage(message);
        }
        this.statusBarItem.tooltip = message;
    }
    setNotice(kind, text) {
        this.notice = { kind, text };
    }
}
exports.BridgeController = BridgeController;
//# sourceMappingURL=bridgeController.js.map