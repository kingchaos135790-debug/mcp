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
exports.looksBinary = looksBinary;
exports.createSnippetItem = createSnippetItem;
exports.createSelectionItem = createSelectionItem;
exports.createDocumentItem = createDocumentItem;
exports.createFolderSummaryItem = createFolderSummaryItem;
exports.buildFolderSummary = buildFolderSummary;
exports.collectFolderFiles = collectFolderFiles;
exports.tryResolveDroppedUri = tryResolveDroppedUri;
const path = __importStar(require("path"));
const vscode = __importStar(require("vscode"));
const constants_1 = require("./constants");
function looksBinary(content) {
    return content.slice(0, 2048).includes('\u0000');
}
function createSnippetItem(content) {
    return {
        id: `snippet-${Date.now().toString(36)}`,
        kind: 'snippet',
        label: content.split(/\r?\n/, 1)[0].slice(0, 60) || 'Snippet',
        content,
        source: 'snippet',
        addedAt: new Date().toISOString()
    };
}
function createSelectionItem(editor) {
    const selection = editor.selection;
    return {
        id: `${editor.document.uri.toString()}#${selection.start.line}:${selection.end.line}`,
        kind: 'selection',
        label: `${path.basename(editor.document.uri.fsPath)}:${selection.start.line + 1}-${selection.end.line + 1}`,
        filePath: editor.document.uri.fsPath,
        language: editor.document.languageId,
        content: editor.document.getText(selection),
        source: 'selection',
        addedAt: new Date().toISOString(),
        startLine: selection.start.line + 1,
        endLine: selection.end.line + 1
    };
}
function createDocumentItem(document, content = document.getText()) {
    return {
        id: document.uri.toString(),
        kind: 'file',
        label: path.basename(document.uri.fsPath),
        filePath: document.uri.fsPath,
        language: document.languageId,
        content,
        source: 'file',
        addedAt: new Date().toISOString()
    };
}
function createFolderSummaryItem(folder, summary) {
    return {
        id: `summary:${folder.toString()}`,
        kind: 'summary',
        label: `${path.basename(folder.fsPath) || folder.fsPath} (names only)`,
        filePath: folder.fsPath,
        language: 'text',
        content: summary.content,
        source: 'folder-summary',
        addedAt: new Date().toISOString(),
        metadataOnly: true
    };
}
async function buildFolderSummary(root) {
    const lines = [
        `Folder summary: ${root.fsPath}`,
        'Mode: names only',
        ''
    ];
    const queue = [{ uri: root, relativePath: '' }];
    let fileCount = 0;
    let directoryCount = 0;
    let truncated = false;
    while (queue.length > 0) {
        const current = queue.shift();
        if (!current) {
            break;
        }
        let entries = [];
        try {
            entries = await vscode.workspace.fs.readDirectory(current.uri);
        }
        catch {
            continue;
        }
        for (const [name, type] of entries.sort(([left], [right]) => left.localeCompare(right))) {
            if (lines.length >= constants_1.MAX_FOLDER_SUMMARY_ENTRIES) {
                truncated = true;
                break;
            }
            const relativePath = current.relativePath ? `${current.relativePath}/${name}` : name;
            const child = vscode.Uri.joinPath(current.uri, name);
            if (type & vscode.FileType.Directory) {
                if (constants_1.SKIPPED_DIRECTORY_NAMES.has(name.toLowerCase())) {
                    continue;
                }
                directoryCount += 1;
                lines.push(`[D] ${relativePath}/`);
                queue.push({ uri: child, relativePath });
                continue;
            }
            if (type & vscode.FileType.File) {
                fileCount += 1;
                lines.push(`[F] ${relativePath}`);
            }
        }
        if (truncated) {
            break;
        }
    }
    if (truncated) {
        lines.push('');
        lines.push(`[truncated after ${constants_1.MAX_FOLDER_SUMMARY_ENTRIES} lines]`);
    }
    lines.splice(2, 0, `Directories: ${directoryCount}`, `Files: ${fileCount}`);
    return {
        content: lines.join('\n'),
        fileCount,
        directoryCount,
        truncated
    };
}
async function collectFolderFiles(root) {
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
function tryResolveDroppedUri(candidate) {
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
//# sourceMappingURL=contextHelpers.js.map