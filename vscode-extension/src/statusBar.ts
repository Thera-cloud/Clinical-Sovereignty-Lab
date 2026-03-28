import * as vscode from 'vscode';
import type { BridgeClient, ConnectionState } from './bridgeClient';
import type { CliMode } from './types';

const MODE_LABELS: Record<CliMode, string> = {
  ask: '$(question) ASK',
  plan: '$(notebook) PLAN',
  debug: '$(debug-alt) DEBUG',
  ln_fab: '$(tools) LN-FAB',
};

export class StatusBarManager {
  private connectionItem: vscode.StatusBarItem;
  private modeItem: vscode.StatusBarItem;
  private bridge: BridgeClient;
  private currentMode: CliMode;

  constructor(bridge: BridgeClient) {
    this.bridge = bridge;
    this.currentMode = vscode.workspace.getConfiguration('sovereignSanctuary').get<CliMode>('defaultMode', 'ask');

    this.connectionItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    this.connectionItem.command = 'sovereignSanctuary.switchBridge';
    this.connectionItem.show();

    this.modeItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 99);
    this.modeItem.command = 'sovereignSanctuary.switchMode';
    this.modeItem.show();

    this.updateConnectionDisplay('disconnected');
    this.updateModeDisplay();

    bridge.on('state_changed', (state: ConnectionState) => {
      this.updateConnectionDisplay(state);
      this.connectionItem.command = state === 'connected'
        ? 'sovereignSanctuary.login'
        : 'sovereignSanctuary.switchBridge';
    });

    bridge.on('bridge_connected', () => {
      this.updateConnectionDisplay('connected');
    });
  }

  get mode(): CliMode {
    return this.currentMode;
  }

  set mode(m: CliMode) {
    this.currentMode = m;
    this.updateModeDisplay();
  }

  async showBridgeQuickPick(): Promise<void> {
    const items: vscode.QuickPickItem[] = [
      { label: '$(home) Switch to Local', description: 'ws://localhost:8765/ws', detail: 'Connect to local dev bridge' },
      { label: '$(cloud) Switch to Cloud', description: 'wss://api.sovereignsanctuary.net/ws', detail: 'Connect to production bridge' },
      { label: '$(sync) Auto-detect', description: 'Try local first, fallback to cloud' },
      { label: '$(sign-out) Logout', description: 'Clear credentials and disconnect' },
    ];

    const pick = await vscode.window.showQuickPick(items, { placeHolder: 'Bridge connection' });
    if (!pick) { return; }

    if (pick.label.includes('Local')) {
      this.bridge.switchTarget('local');
    } else if (pick.label.includes('Cloud')) {
      this.bridge.switchTarget('cloud');
    } else if (pick.label.includes('Auto-detect')) {
      this.bridge.disconnect();
      this.bridge.connect();
    } else if (pick.label.includes('Logout')) {
      vscode.commands.executeCommand('sovereignSanctuary.logout');
    }
  }

  async showModeQuickPick(): Promise<void> {
    const items: vscode.QuickPickItem[] = [
      { label: '$(question) ASK', description: 'Understand — read-only exploration', detail: this.currentMode === 'ask' ? '(current)' : '' },
      { label: '$(notebook) PLAN', description: 'Think — generate implementation plans', detail: this.currentMode === 'plan' ? '(current)' : '' },
      { label: '$(tools) LN-FAB', description: 'Build — generate and apply code changes', detail: this.currentMode === 'ln_fab' ? '(current)' : '' },
      { label: '$(debug-alt) DEBUG', description: 'Fix — hypothesis-driven debugging', detail: this.currentMode === 'debug' ? '(current)' : '' },
    ];

    const pick = await vscode.window.showQuickPick(items, { placeHolder: 'Select chat mode' });
    if (!pick) { return; }

    if (pick.label.includes('ASK')) { this.mode = 'ask'; }
    else if (pick.label.includes('PLAN')) { this.mode = 'plan'; }
    else if (pick.label.includes('LN-FAB')) { this.mode = 'ln_fab'; }
    else if (pick.label.includes('DEBUG')) { this.mode = 'debug'; }
  }

  private updateConnectionDisplay(state: ConnectionState): void {
    const target = this.bridge.bridgeTarget;
    const label = target === 'local' ? 'Local' : 'Cloud';
    const icon = target === 'local' ? '$(zap)' : '$(cloud)';

    switch (state) {
      case 'disconnected':
        this.connectionItem.text = '$(alert) LN: Disconnected';
        this.connectionItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
        this.connectionItem.tooltip = 'Sovereign Sanctuary — Not connected. Click to reconnect.';
        break;
      case 'connecting':
        this.connectionItem.text = '$(sync~spin) LN: Connecting...';
        this.connectionItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
        this.connectionItem.tooltip = 'Sovereign Sanctuary — Connecting...';
        break;
      case 'connected':
        this.connectionItem.text = `$(key) LN: ${label} (login required)`;
        this.connectionItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
        this.connectionItem.tooltip = 'Sovereign Sanctuary — Bridge connected but not authenticated. Click to log in.';
        break;
      case 'authenticating':
        this.connectionItem.text = `$(sync~spin) LN: ${label} (authenticating)`;
        this.connectionItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
        this.connectionItem.tooltip = 'Sovereign Sanctuary — Validating credentials...';
        break;
      case 'authenticated':
        this.connectionItem.text = `${icon} LN: ${label}`;
        this.connectionItem.backgroundColor = undefined;
        this.connectionItem.tooltip = `Sovereign Sanctuary — Authenticated on ${label} bridge`;
        break;
    }
  }

  private updateModeDisplay(): void {
    this.modeItem.text = MODE_LABELS[this.currentMode] || this.currentMode.toUpperCase();
    this.modeItem.tooltip = `Chat Mode: ${this.currentMode.toUpperCase()} — Click to change`;
  }

  dispose(): void {
    this.connectionItem.dispose();
    this.modeItem.dispose();
  }
}
