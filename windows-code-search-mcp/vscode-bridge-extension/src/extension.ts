import * as vscode from 'vscode';

import { BridgeController } from './bridgeController';

export function activate(context: vscode.ExtensionContext): void {
  const controller = new BridgeController(context);
  context.subscriptions.push(controller);
  context.subscriptions.push(controller.registerWebviewProvider());
  context.subscriptions.push(vscode.commands.registerCommand('windowsCodeSearchBridge.pushNow', () => controller.pushNow()));
  context.subscriptions.push(vscode.commands.registerCommand('windowsCodeSearchBridge.restartBridgeServer', () => controller.restartBridgeServer()));
  context.subscriptions.push(vscode.commands.registerCommand('windowsCodeSearchBridge.setBridgePortAndRestart', () => controller.setBridgePortAndRestart()));
  context.subscriptions.push(vscode.commands.registerCommand('windowsCodeSearchBridge.addFiles', () => controller.addFiles()));
  context.subscriptions.push(vscode.commands.registerCommand('windowsCodeSearchBridge.addFolder', () => controller.addFolder()));
  context.subscriptions.push(vscode.commands.registerCommand('windowsCodeSearchBridge.addFolderSummary', () => controller.addFolderSummary()));
  context.subscriptions.push(vscode.commands.registerCommand('windowsCodeSearchBridge.addActiveEditor', () => controller.addActiveEditor()));
  context.subscriptions.push(vscode.commands.registerCommand('windowsCodeSearchBridge.addSelection', () => controller.addSelection()));
  context.subscriptions.push(vscode.commands.registerCommand('windowsCodeSearchBridge.addOpenEditors', () => controller.addOpenEditors()));
  context.subscriptions.push(vscode.commands.registerCommand('windowsCodeSearchBridge.addResource', (resource?: vscode.Uri | vscode.Uri[]) => controller.addResource(resource)));
}

export function deactivate(): void {
  return undefined;
}
