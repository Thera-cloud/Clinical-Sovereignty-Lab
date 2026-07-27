import * as vscode from 'vscode';
import type { AuthManager } from './auth';

/** Little Nate 7 REST helpers (admin token via bridge login). */
export class Ln7Api {
  constructor(private auth: AuthManager) {}

  private baseUrl(): string {
    return vscode.workspace.getConfiguration('sovereignSanctuary')
      .get<string>('apiBaseUrl', 'https://api.sovereignsanctuary.net')
      .replace(/\/$/, '');
  }

  async post(path: string, body: Record<string, unknown> = {}): Promise<unknown> {
    const creds = await this.auth.getStoredCredentials();
    if (!creds?.token) {
      throw new Error('Not logged in');
    }
    const resp = await fetch(`${this.baseUrl()}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${creds.token}`,
      },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`${resp.status}: ${text.slice(0, 200)}`);
    }
    return resp.json();
  }

  async get(path: string): Promise<unknown> {
    const creds = await this.auth.getStoredCredentials();
    if (!creds?.token) {
      throw new Error('Not logged in');
    }
    const resp = await fetch(`${this.baseUrl()}${path}`, {
      headers: { Authorization: `Bearer ${creds.token}` },
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`${resp.status}: ${text.slice(0, 200)}`);
    }
    return resp.json();
  }

  async recordUsage(
    eventType: 'accepted' | 'rejected' | 'edited_after_apply',
    meta: Record<string, unknown> = {},
  ): Promise<void> {
    try {
      await this.post('/api/ln7/usage-event', {
        event_type: eventType,
        workspace_hint: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
        metadata_json: meta,
      });
    } catch (err) {
      console.warn('LN7 usage-event failed:', err);
    }
  }

  async runBakeoff(mode: string = 'fast'): Promise<unknown> {
    return this.post('/api/ln7/bakeoff', {
      revision_id: 'LN7-baseline',
      mode,
    });
  }

  async leaderboard(): Promise<unknown> {
    return this.get('/api/ln7/leaderboard?days=30');
  }
}
