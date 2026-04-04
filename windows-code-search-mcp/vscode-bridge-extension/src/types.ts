export type ContextItemKind = 'snippet' | 'file' | 'selection' | 'summary';

export type NoticeKind = 'info' | 'success' | 'warning' | 'error';

export type ContextItem = {
  id: string;
  kind: ContextItemKind;
  label: string;
  filePath?: string;
  language?: string;
  content: string;
  source: string;
  addedAt: string;
  startLine?: number;
  endLine?: number;
  metadataOnly?: boolean;
};

export type BridgeCommand = {
  commandId: string;
  type: string;
  payload: any;
  createdAt: string;
};

export type WebviewState = {
  sessionId: string;
  items: ContextItem[];
  bridgeBaseUrl: string;
  notice?: {
    kind: NoticeKind;
    text: string;
  };
};

export type FolderImportResult = {
  added: number;
  skipped: number;
};

export type FolderSummary = {
  content: string;
  fileCount: number;
  directoryCount: number;
  truncated: boolean;
};
