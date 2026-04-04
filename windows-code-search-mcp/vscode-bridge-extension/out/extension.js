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
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const bridgeController_1 = require("./bridgeController");
function activate(context) {
    const controller = new bridgeController_1.BridgeController(context);
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
    context.subscriptions.push(vscode.commands.registerCommand('windowsCodeSearchBridge.addResource', (resource) => controller.addResource(resource)));
}
function deactivate() {
    return undefined;
}
//# sourceMappingURL=extension.js.map