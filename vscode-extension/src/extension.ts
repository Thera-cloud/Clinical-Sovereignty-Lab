import * as vscode from 'vscode';
import { BridgeClient } from './bridgeClient';
import { AuthManager } from './auth';
import { StatusBarManager } from './statusBar';
import { ChatPanel } from './chatPanel';
import { DiffApplicator } from './diffApplicator';
import { PlanManager } from './planManager';
import { WorkspaceToolProvider } from './workspaceToolProvider';
import {
  createHealthStatusBarItem,
  registerHealthDetailsCommand,
  disposeHealthStatusBar,
} from './statusBarAutonomous';

let bridge: BridgeClient;
let auth: AuthManager;
let statusBar: StatusBarManager;
let chatPanel: ChatPanel;
let diffApplicator: DiffApplicator;
let planManager: PlanManager;
let workspaceProvider: WorkspaceToolProvider;

export function activate(context: vscode.ExtensionContext): void {
  bridge = new BridgeClient();
  auth = new AuthManager(context, bridge);
  statusBar = new StatusBarManager(bridge);
  diffApplicator = new DiffApplicator();
  planManager = new PlanManager();
  workspaceProvider = new WorkspaceToolProvider(bridge, diffApplicator);
  workspaceProvider.setupEventSubscriptions();
  chatPanel = new ChatPanel(bridge, statusBar, diffApplicator, planManager, context.extensionUri);

  const healthBar = createHealthStatusBarItem(99);
  context.subscriptions.push(healthBar);
  context.subscriptions.push(registerHealthDetailsCommand());

  const treeView = vscode.window.createTreeView('sovereignPlans', {
    treeDataProvider: planManager,
    showCollapseAll: false,
  });

  context.subscriptions.push(
    bridge,
    statusBar,
    diffApplicator,
    planManager,
    workspaceProvider,
    treeView,
    { dispose: () => chatPanel.dispose() },
    { dispose: () => auth.dispose() },
  );

  // ── Commands ──

  context.subscriptions.push(
    vscode.commands.registerCommand('sovereignSanctuary.openChat', () => {
      chatPanel.show();
    }),

    vscode.commands.registerCommand('sovereignSanctuary.askAboutSelection', () => {
      chatPanel.sendSelectionToMode('ask');
    }),

    vscode.commands.registerCommand('sovereignSanctuary.debugSelection', () => {
      chatPanel.sendSelectionToMode('debug');
    }),

    vscode.commands.registerCommand('sovereignSanctuary.switchMode', () => {
      statusBar.showModeQuickPick();
    }),

    vscode.commands.registerCommand('sovereignSanctuary.switchBridge', () => {
      statusBar.showBridgeQuickPick();
    }),

    vscode.commands.registerCommand('sovereignSanctuary.logout', () => {
      auth.logout();
    }),

    vscode.commands.registerCommand('sovereignSanctuary.login', () => {
      auth.promptLogin();
    }),

    vscode.commands.registerCommand('sovereignSanctuary.openPlan', () => {
      planManager.openPlan();
    }),

    vscode.commands.registerCommand('sovereignSanctuary.loadCursorPlan', async () => {
      const plan = await planManager.pickAndLoadCursorPlan();
      if (plan) {
        chatPanel.sendToWebview({
          cmd: 'planLoaded',
          plan_name: plan.name,
          plan_overview: plan.overview,
          plan_todos: plan.todos,
          plan_file: plan.file_path,
        });
      }
    }),

    vscode.commands.registerCommand('sovereignSanctuary.markFixed', () => {
      chatPanel.sendToWebview({ cmd: 'done' });
    }),

    vscode.commands.registerCommand('sovereignSanctuary.acceptDiff', () => {
      diffApplicator.acceptCurrent();
    }),

    vscode.commands.registerCommand('sovereignSanctuary.rejectDiff', () => {
      diffApplicator.rejectCurrent();
    }),
  );

  // ── Auto-connect on activation ──
  initializeConnection(context);
}

async function initializeConnection(_context: vscode.ExtensionContext): Promise<void> {
  const stored = await auth.getStoredCredentials();
  bridge.connect(stored || undefined);
}

export function deactivate(): void {
  bridge?.dispose();
  statusBar?.dispose();
  diffApplicator?.dispose();
  planManager?.dispose();
  workspaceProvider?.dispose();
  chatPanel?.dispose();
  disposeHealthStatusBar();
}
