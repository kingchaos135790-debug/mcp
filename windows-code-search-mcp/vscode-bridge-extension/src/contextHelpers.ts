import * as path from 'path';
import * as vscode from 'vscode';

import { MAX_FOLDER_SUMMARY_ENTRIES, SKIPPED_DIRECTORY_NAMES } from './constants';
import { ContextItem, FolderSummary } from './types';

export function looksBinary(content: string): boolean {
  return content.slice(0, 2048).includes('\u0000');
}

export function createSnippetItem(content: string): ContextItem {
  return {
    id: `snippet-${Date.now().toString(36)}`,
    kind: 'snippet',
    label: content.split(/\r?\n/, 1)[0].slice(0, 60) || 'Snippet',
    content,
    source: 'snippet',
    addedAt: new Date().toISOString()
  };
}

export function createSelectionItem(editor: vscode.TextEditor): ContextItem {
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

export function createDocumentItem(document: vscode.TextDocument, content: string = document.getText()): ContextItem {
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

export function createFolderSummaryItem(folder: vscode.Uri, summary: FolderSummary): ContextItem {
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

export async function buildFolderSummary(root: vscode.Uri): Promise<FolderSummary> {
  const lines = [
    `Folder summary: ${root.fsPath}`,
    'Mode: names only',
    ''
  ];
  const queue: Array<{ uri: vscode.Uri; relativePath: string }> = [{ uri: root, relativePath: '' }];
  let fileCount = 0;
  let directoryCount = 0;
  let truncated = false;

  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) {
      break;
    }

    let entries: [string, vscode.FileType][] = [];
    try {
      entries = await vscode.workspace.fs.readDirectory(current.uri);
    } catch {
      continue;
    }

    for (const [name, type] of entries.sort(([left], [right]) => left.localeCompare(right))) {
      if (lines.length >= MAX_FOLDER_SUMMARY_ENTRIES) {
        truncated = true;
        break;
      }

      const relativePath = current.relativePath ? `${current.relativePath}/${name}` : name;
      const child = vscode.Uri.joinPath(current.uri, name);

      if (type & vscode.FileType.Directory) {
        if (SKIPPED_DIRECTORY_NAMES.has(name.toLowerCase())) {
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
    lines.push(`[truncated after ${MAX_FOLDER_SUMMARY_ENTRIES} lines]`);
  }

  lines.splice(2, 0, `Directories: ${directoryCount}`, `Files: ${fileCount}`);
  return {
    content: lines.join('\n'),
    fileCount,
    directoryCount,
    truncated
  };
}
