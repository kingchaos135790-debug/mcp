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
exports.CommandHandler = void 0;
exports.toRange = toRange;
const vscode = __importStar(require("vscode"));
class CommandHandler {
    bridgeClient;
    sessionId;
    constructor(bridgeClient, sessionId) {
        this.bridgeClient = bridgeClient;
        this.sessionId = sessionId;
    }
    async execute(command) {
        let payload = {};
        const isEdit = command.type === 'apply_edit' || command.type === 'apply_workspace_edit';
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
        return { payload, isEdit };
    }
    async reportResult(commandId, result) {
        await this.bridgeClient.postJson(`/sessions/${encodeURIComponent(this.sessionId)}/commands/${encodeURIComponent(commandId)}/result`, result);
    }
    async applyEdit(payload) {
        const document = await vscode.workspace.openTextDocument(vscode.Uri.file(String(payload.filePath)));
        const range = toRange(payload.range);
        const expectedText = String(payload.expectedText ?? '');
        if (expectedText) {
            const actual = document.getText(range);
            if (actual !== expectedText) {
                throw new Error(`Expected text mismatch before applying edit. file=${document.uri.fsPath} range=${range.start.line + 1}:${range.start.character + 1}-${range.end.line + 1}:${range.end.character + 1} expected=${JSON.stringify(expectedText.length > 200 ? `${expectedText.slice(0, 200)}...` : expectedText)} actual=${JSON.stringify(actual.length > 200 ? `${actual.slice(0, 200)}...` : actual)}`);
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
            const filePath = String(item.filePath ?? item.file_path ?? '');
            if (!filePath) {
                throw new Error('Workspace edit item is missing filePath.');
            }
            const rangePayload = item.range ?? {
                startLine: item.startLine ?? item.start_line,
                startColumn: item.startColumn ?? item.start_column,
                endLine: item.endLine ?? item.end_line,
                endColumn: item.endColumn ?? item.end_column,
            };
            const document = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
            const range = toRange(rangePayload);
            const expectedText = String(item.expectedText ?? item.expected_text ?? '');
            if (expectedText) {
                const actual = document.getText(range);
                if (actual !== expectedText) {
                    throw new Error(`Expected text mismatch before workspace edit. file=${document.uri.fsPath} range=${range.start.line + 1}:${range.start.character + 1}-${range.end.line + 1}:${range.end.character + 1} expected=${JSON.stringify(expectedText.length > 200 ? `${expectedText.slice(0, 200)}...` : expectedText)} actual=${JSON.stringify(actual.length > 200 ? `${actual.slice(0, 200)}...` : actual)}`);
                }
            }
            workspaceEdit.replace(document.uri, range, String(item.newText ?? item.new_text ?? ''));
        }
        const applied = await vscode.workspace.applyEdit(workspaceEdit);
        if (!applied) {
            throw new Error('VS Code rejected the workspace edit.');
        }
        if (vscode.workspace.getConfiguration('windowsCodeSearchBridge').get('saveAfterApplyEdit', true)) {
            for (const item of edits) {
                const filePath = String(item.filePath ?? item.file_path ?? '');
                if (!filePath) {
                    continue;
                }
                const document = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
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
}
exports.CommandHandler = CommandHandler;
function toRange(input) {
    const startLine = Math.max(1, Number(input?.startLine ?? 1));
    const startColumn = Math.max(1, Number(input?.startColumn ?? 1));
    const endLine = Math.max(1, Number(input?.endLine ?? startLine));
    const endColumn = Math.max(1, Number(input?.endColumn ?? startColumn));
    return new vscode.Range(startLine - 1, startColumn - 1, endLine - 1, endColumn - 1);
}
//# sourceMappingURL=commandHandler.js.map