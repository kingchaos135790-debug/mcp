import * as vscode from 'vscode';

type BridgeConnection = {
  baseUrl: string;
  host: string;
  port: number;
  baseUrlOverride: string;
};

export class BridgeClient {
  constructor(private readonly extensionContext: vscode.ExtensionContext) {}

  get baseUrl(): string {
    return this.connection.baseUrl;
  }

  get connection(): BridgeConnection {
    const config = vscode.workspace.getConfiguration('windowsCodeSearchBridge');
    const configuredBaseUrl = config.get<string>('bridgeBaseUrl', '').trim();
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
      } catch {
        return {
          baseUrl: normalizedBaseUrl,
          host: '127.0.0.1',
          port: 8876,
          baseUrlOverride: configuredBaseUrl
        };
      }
    }

    const host = config.get<string>('bridgeHost', '127.0.0.1').trim() || '127.0.0.1';
    const port = config.get<number>('bridgePort', 8876);
    return {
      baseUrl: `http://${host}:${port}`,
      host,
      port,
      baseUrlOverride: ''
    };
  }

  get lastSuccessfulBaseUrl(): string {
    return this.extensionContext.workspaceState.get<string>('windowsCodeSearchBridge.lastSuccessfulBridgeBaseUrl', '').trim();
  }

  private get token(): string {
    return vscode.workspace.getConfiguration('windowsCodeSearchBridge').get<string>('bridgeToken', '').trim();
  }

  private normalizeBaseUrl(baseUrl?: string): string {
    return (baseUrl?.trim() || this.baseUrl).replace(/\/$/, '');
  }

  private buildHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };
    if (this.token) {
      headers['X-Bridge-Token'] = this.token;
    }
    return headers;
  }

  private async rememberSuccessfulBaseUrl(baseUrl: string): Promise<void> {
    await this.extensionContext.workspaceState.update('windowsCodeSearchBridge.lastSuccessfulBridgeBaseUrl', baseUrl);
  }

  async getJson<T>(route: string, baseUrl?: string): Promise<T> {
    const resolvedBaseUrl = this.normalizeBaseUrl(baseUrl);
    const response = await fetch(`${resolvedBaseUrl}${route}`, {
      headers: this.buildHeaders()
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    await this.rememberSuccessfulBaseUrl(resolvedBaseUrl);
    return await response.json() as T;
  }

  async postJson<T>(route: string, payload: unknown, baseUrl?: string): Promise<T> {
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
    return await response.json() as T;
  }
}
