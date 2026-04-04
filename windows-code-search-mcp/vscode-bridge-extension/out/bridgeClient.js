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
exports.BridgeClient = void 0;
const vscode = __importStar(require("vscode"));
class BridgeClient {
    extensionContext;
    constructor(extensionContext) {
        this.extensionContext = extensionContext;
    }
    get baseUrl() {
        return this.connection.baseUrl;
    }
    get connection() {
        const config = vscode.workspace.getConfiguration('windowsCodeSearchBridge');
        const configuredBaseUrl = config.get('bridgeBaseUrl', '').trim();
        if (configuredBaseUrl) {
            const normalizedBaseUrl = configuredBaseUrl.replace(/\/$/, '');
            try {
                const parsed = new URL(normalizedBaseUrl);
                const parsedPort = parsed.port ? Number(parsed.port) : (parsed.protocol === 'https:' ? 443 : 80);
                return {
                    baseUrl: normalizedBaseUrl,
                    host: parsed.hostname,
                    port: parsedPort,
                    baseUrlOverride: configuredBaseUrl
                };
            }
            catch {
                return {
                    baseUrl: normalizedBaseUrl,
                    host: '127.0.0.1',
                    port: 8876,
                    baseUrlOverride: configuredBaseUrl
                };
            }
        }
        const host = config.get('bridgeHost', '127.0.0.1').trim() || '127.0.0.1';
        const port = config.get('bridgePort', 8876);
        return {
            baseUrl: `http://${host}:${port}`,
            host,
            port,
            baseUrlOverride: ''
        };
    }
    get lastSuccessfulBaseUrl() {
        return this.extensionContext.workspaceState.get('windowsCodeSearchBridge.lastSuccessfulBridgeBaseUrl', '').trim();
    }
    get token() {
        return vscode.workspace.getConfiguration('windowsCodeSearchBridge').get('bridgeToken', '').trim();
    }
    normalizeBaseUrl(baseUrl) {
        return (baseUrl?.trim() || this.baseUrl).replace(/\/$/, '');
    }
    buildHeaders() {
        const headers = {
            'Content-Type': 'application/json'
        };
        if (this.token) {
            headers['X-Bridge-Token'] = this.token;
        }
        return headers;
    }
    async rememberSuccessfulBaseUrl(baseUrl) {
        await this.extensionContext.workspaceState.update('windowsCodeSearchBridge.lastSuccessfulBridgeBaseUrl', baseUrl);
    }
    async getJson(route, baseUrl) {
        const resolvedBaseUrl = this.normalizeBaseUrl(baseUrl);
        const response = await fetch(`${resolvedBaseUrl}${route}`, {
            headers: this.buildHeaders()
        });
        if (!response.ok) {
            throw new Error(await response.text());
        }
        await this.rememberSuccessfulBaseUrl(resolvedBaseUrl);
        return await response.json();
    }
    async postJson(route, payload, baseUrl) {
        const resolvedBaseUrl = this.normalizeBaseUrl(baseUrl);
        const response = await fetch(`${resolvedBaseUrl}${route}`, {
            method: 'POST',
            headers: this.buildHeaders(),
            body: JSON.stringify(payload)
        });
        if (!response.ok) {
            throw new Error(await response.text());
        }
        await this.rememberSuccessfulBaseUrl(resolvedBaseUrl);
        return await response.json();
    }
}
exports.BridgeClient = BridgeClient;
//# sourceMappingURL=bridgeClient.js.map