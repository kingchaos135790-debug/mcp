import * as vscode from 'vscode';

import { ContextItem } from './types';

export class ContextStore {
  private items: ContextItem[] = [];

  constructor(private readonly extensionContext: vscode.ExtensionContext) {
    const saved = this.extensionContext.workspaceState.get<ContextItem[]>('windowsCodeSearchBridge.contextItems', []);
    this.items = Array.isArray(saved) ? saved : [];
  }

  all(): ContextItem[] {
    return [...this.items];
  }

  async replace(items: ContextItem[]): Promise<void> {
    this.items = items;
    await this.persist();
  }

  async add(item: ContextItem): Promise<void> {
    this.items = [item, ...this.items.filter((existing) => existing.id !== item.id)];
    await this.persist();
  }

  async remove(id: string): Promise<void> {
    this.items = this.items.filter((item) => item.id !== id);
    await this.persist();
  }

  async clear(): Promise<void> {
    this.items = [];
    await this.persist();
  }

  private async persist(): Promise<void> {
    await this.extensionContext.workspaceState.update('windowsCodeSearchBridge.contextItems', this.items);
  }
}
