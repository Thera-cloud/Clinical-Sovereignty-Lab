import * as vscode from 'vscode';
import type { ChatPanel } from './chatPanel';

/**
 * Secondary-sidebar WebviewView — CLI agent chat + model picker.
 * Reuses ChatPanel HTML/JS and message routing.
 */
export class AgentSidebarProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'sovereignAgentChat';

  private view?: vscode.WebviewView;
  private chatPanel: ChatPanel;

  constructor(chatPanel: ChatPanel) {
    this.chatPanel = chatPanel;
  }

  async resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken,
  ): Promise<void> {
    this.view = webviewView;
    webviewView.description = 'CLI Agent';

    await this.chatPanel.attachWebview(webviewView.webview);

    webviewView.onDidDispose(() => {
      this.chatPanel.detachWebview(webviewView.webview);
      this.view = undefined;
    });
  }

  async reveal(): Promise<void> {
    try {
      await vscode.commands.executeCommand('workbench.action.focusAuxiliaryBar');
    } catch {
      /* older code-server may lack auxiliary bar focus */
    }
    try {
      await vscode.commands.executeCommand(`${AgentSidebarProvider.viewType}.focus`);
    } catch {
      /* view may not be registered yet */
    }
    this.view?.show?.(true);
  }
}
