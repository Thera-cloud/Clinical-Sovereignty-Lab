import * as vscode from 'vscode';
import type { StoredCredentials } from './types';
import type { BridgeClient } from './bridgeClient';

const KEY_TOKEN = 'sovereignSanctuary.token';
const KEY_HW_ID = 'sovereignSanctuary.hardwareId';
const KEY_USERNAME = 'sovereignSanctuary.username';
const KEY_ROLE = 'sovereignSanctuary.role';

export class AuthManager {
  private secrets: vscode.SecretStorage;
  private bridge: BridgeClient;

  constructor(context: vscode.ExtensionContext, bridge: BridgeClient) {
    this.secrets = context.secrets;
    this.bridge = bridge;

    bridge.on('login_success', (creds: StoredCredentials) => {
      this.storeCredentials(creds);
    });

    bridge.on('auth_failed', () => {
      this.clearCredentials();
      this.promptLogin();
    });

    bridge.on('login_failed', (error: string) => {
      vscode.window.showErrorMessage(`Login failed: ${error}`);
      this.promptLogin();
    });

    bridge.on('bridge_ready', async () => {
      const stored = await this.getStoredCredentials();
      if (stored) {
        bridge.send({ type: 'auth', token: stored.token, hardware_id: stored.hardware_id });
      } else {
        this.promptLogin();
      }
    });
  }

  async getStoredCredentials(): Promise<StoredCredentials | null> {
    const token = await this.secrets.get(KEY_TOKEN);
    const hardware_id = await this.secrets.get(KEY_HW_ID);
    const username = await this.secrets.get(KEY_USERNAME);
    const role = await this.secrets.get(KEY_ROLE);

    if (token && hardware_id && username && role) {
      return { token, hardware_id, username, role };
    }
    return null;
  }

  async promptLogin(): Promise<void> {
    const username = await vscode.window.showInputBox({
      prompt: 'Sovereign Sanctuary — Username',
      placeHolder: 'Enter your username',
      ignoreFocusOut: true,
    });

    if (!username) { return; }

    const password = await vscode.window.showInputBox({
      prompt: 'Sovereign Sanctuary — Password',
      placeHolder: 'Enter your password',
      password: true,
      ignoreFocusOut: true,
    });

    if (!password) { return; }

    const role = vscode.workspace.getConfiguration('sovereignSanctuary')
      .get<string>('loginRole', 'ADMIN');

    this.bridge.send({
      type: 'login_request',
      username,
      password,
      expected_role: role,
    });
  }

  async logout(): Promise<void> {
    await this.clearCredentials();
    this.bridge.disconnect();
    vscode.window.showInformationMessage('Sovereign Sanctuary: Logged out.');
  }

  private async storeCredentials(creds: StoredCredentials): Promise<void> {
    await this.secrets.store(KEY_TOKEN, creds.token);
    await this.secrets.store(KEY_HW_ID, creds.hardware_id);
    await this.secrets.store(KEY_USERNAME, creds.username);
    await this.secrets.store(KEY_ROLE, creds.role);
  }

  private async clearCredentials(): Promise<void> {
    await this.secrets.delete(KEY_TOKEN);
    await this.secrets.delete(KEY_HW_ID);
    await this.secrets.delete(KEY_USERNAME);
    await this.secrets.delete(KEY_ROLE);
  }

  dispose(): void {
    // no resources to release
  }
}
