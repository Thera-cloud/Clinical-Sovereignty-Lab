import * as vscode from 'vscode';
import * as path from 'path';
import * as crypto from 'crypto';
import * as fs from 'fs';
import type { BridgeClient } from './bridgeClient';
import type { StatusBarManager } from './statusBar';
import type { DiffApplicator } from './diffApplicator';
import type { PlanManager } from './planManager';
import type { Ln7Api } from './ln7Api';
import type {
  CliMode,
  ChatEntry,
  InboundCliChatChunk,
  InboundCliChatTool,
  InboundCliChatStatus,
  InboundCliChatOutput,
  InboundCliChatDone,
  InboundCliModels,
  WebviewToHostMessage,
  HostToWebviewMessage,
  VsCodeContext,
  BuildStatusMessage,
  BuildPanelState,
} from './types';
import { updateAutonomousStatus } from './statusBarAutonomous';

export class ChatPanel {
  private panel: vscode.WebviewPanel | null = null;
  private webviews = new Set<vscode.Webview>();
  private bridge: BridgeClient;
  private statusBar: StatusBarManager;
  private diffApplicator: DiffApplicator;
  private planManager: PlanManager;
  private extensionUri: vscode.Uri;
  private disposables: vscode.Disposable[] = [];
  private _reconnecting = false;
  private _currentTurn = 0;
  private _chatHistory: ChatEntry[] = [];
  private _currentNateRaw = '';
  private _historyPath = '';
  private _selectedModel = '';
  private _selectedSpace = '';
  private _selectedProvider = '';
  private ln7Api: Ln7Api | null = null;
  private _modelRefreshTimer: ReturnType<typeof setInterval> | null = null;
  private _lastModelCatalog: HostToWebviewMessage | null = null;
  private _buildState: BuildPanelState = {
    isBuilding: false,
    phase: 'idle',
    currentVersion: 'v0.0.0.0',
    buildingVersion: null,
    myRole: 'blue',
    testResults: null,
    soakRemaining: null,
    lastError: null,
  };

  constructor(
    bridge: BridgeClient,
    statusBar: StatusBarManager,
    diffApplicator: DiffApplicator,
    planManager: PlanManager,
    extensionUri: vscode.Uri,
  ) {
    this.bridge = bridge;
    this.statusBar = statusBar;
    this.diffApplicator = diffApplicator;
    this.planManager = planManager;
    this.extensionUri = extensionUri;

    const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (wsRoot) {
      const histDir = path.join(wsRoot, '.sovereign', 'chat-history');
      fs.mkdirSync(histDir, { recursive: true });
      this._historyPath = path.join(histDir, 'current.json');
      this.loadHistory();
    }

    this.setupBridgeListeners();
  }

  setLn7Api(api: Ln7Api): void {
    this.ln7Api = api;
  }

  async show(): Promise<void> {
    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.Beside);
      return;
    }

    this.panel = vscode.window.createWebviewPanel(
      'sovereignSanctuaryChat',
      'Sovereign Sanctuary',
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.joinPath(this.extensionUri, 'dist', 'webview'),
        ],
      },
    );

    await this.attachWebview(this.panel.webview);
    this.panel.iconPath = vscode.Uri.joinPath(this.extensionUri, 'media', 'icon.svg');

    this.panel.onDidDispose(() => {
      if (this.panel) {
        this.webviews.delete(this.panel.webview);
      }
      this.panel = null;
    }, null, this.disposables);
  }

  /** Shared by editor panel + secondary-sidebar WebviewView. */
  async attachWebview(webview: vscode.Webview): Promise<void> {
    webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.joinPath(this.extensionUri, 'dist', 'webview'),
      ],
    };
    webview.html = await this.getHtml(webview);
    this.webviews.add(webview);

    webview.onDidReceiveMessage(
      (msg: WebviewToHostMessage) => this.handleWebviewMessage(msg),
      undefined,
      this.disposables,
    );

    const activePlan = this.planManager.activePlan;
    setTimeout(() => {
      if (this._chatHistory.length > 0) {
        webview.postMessage({ cmd: 'restoreHistory', history: this._chatHistory });
      }
      if (activePlan) {
        webview.postMessage({
          cmd: 'planLoaded',
          plan_name: activePlan.name,
          plan_overview: activePlan.overview,
          plan_todos: activePlan.todos,
          plan_file: activePlan.file_path,
        });
      }
      webview.postMessage({
        cmd: 'cliTarget',
        bridge_target: this.bridge.bridgeTarget || 'cloud',
        cli_type: this.bridge.cliType,
      });
      // Replay last catalog immediately (avoids race where WS reply arrived before attach)
      if (this._lastModelCatalog) {
        webview.postMessage(this._lastModelCatalog);
      }
      this.requestModelCatalog(true);
    }, 150);
  }

  detachWebview(webview: vscode.Webview): void {
    this.webviews.delete(webview);
  }

  sendToWebview(msg: HostToWebviewMessage): void {
    for (const wv of this.webviews) {
      try {
        wv.postMessage(msg);
      } catch {
        this.webviews.delete(wv);
      }
    }
  }

  async sendSelectionToMode(mode: CliMode): Promise<void> {
    await this.show();
    const editor = vscode.window.activeTextEditor;
    if (!editor) { return; }

    const selection = editor.document.getText(editor.selection);
    const file = editor.document.uri.fsPath;
    const lineNum = editor.selection.start.line + 1;

    let message: string;
    if (mode === 'debug') {
      const diagnostics = vscode.languages.getDiagnostics(editor.document.uri);
      const diagText = diagnostics.map(d =>
        `Line ${d.range.start.line + 1}: [${vscode.DiagnosticSeverity[d.severity]}] ${d.message}`
      ).join('\n');

      message = `File: ${file} (line ${lineNum})\n\nSelected code:\n\`\`\`\n${selection}\n\`\`\`\n\nDiagnostics:\n${diagText || 'None'}`;
    } else {
      message = `File: ${file} (line ${lineNum})\n\nSelected code:\n\`\`\`\n${selection}\n\`\`\``;
    }

    this.statusBar.mode = mode;
    this.sendToWebview({ cmd: 'modeChanged', mode });
    this.handleSend(mode, message);
  }

  private handleWebviewMessage(msg: WebviewToHostMessage): void {
    switch (msg.cmd) {
      case 'send':
        if (msg.model) {
          this._selectedModel = msg.model;
          this._selectedSpace = msg.model_space || this._selectedSpace;
          this._selectedProvider = msg.provider || this._selectedProvider;
        }
        this.handleSend(msg.mode as CliMode, msg.message || '');
        break;

      case 'requestModels':
        this.requestModelCatalog(true);
        break;

      case 'refreshModels':
        this.requestModelCatalog(true);
        break;

      case 'selectModel':
        this._selectedModel = msg.model || '';
        this._selectedSpace = msg.model_space || '';
        this._selectedProvider = msg.provider || '';
        break;

      case 'switchMode':
        if (msg.mode) {
          this.statusBar.mode = msg.mode;
        }
        break;

      case 'markFixed':
        if (msg.plan_id) {
          this.bridge.send({
            type: 'nate_cli_debug_resolved',
            plan_id: msg.plan_id,
            resolution: msg.resolution || 'fixed',
          });
        }
        break;

      case 'openFile':
        if (msg.file_path) {
          this.openFile(msg.file_path, msg.start_line);
        }
        break;

      case 'acceptDiff':
        vscode.commands.executeCommand('sovereignSanctuary.acceptDiff');
        break;

      case 'rejectDiff':
        vscode.commands.executeCommand('sovereignSanctuary.rejectDiff');
        break;

      case 'loadPlan':
        this.handleLoadPlan();
        break;

      case 'clearPlan':
        this.planManager.clearActivePlan();
        this.sendToWebview({ cmd: 'planCleared' });
        break;

      case 'clearChat':
        this.clearHistory();
        break;

      case 'ask_user_response':
        this.bridge.send({
          type: 'ask_user_response',
          question_id: msg.question_id || '',
          selected_values: msg.selected_values || [],
          skipped: msg.skipped === true,
        } as unknown as Parameters<BridgeClient['send']>[0]);
        break;

      case 'ln7Bakeoff':
        void this.handleLn7Bakeoff(typeof msg.mode === 'string' ? msg.mode : 'fast');
        break;

      case 'ln7Leaderboard':
        void this.handleLn7Leaderboard();
        break;
    }
  }

  private async handleLn7Bakeoff(mode: string): Promise<void> {
    if (!this.ln7Api) {
      this.sendToWebview({ cmd: 'ln7BakeoffResult', ok: false, error: 'LN7 API not wired' });
      return;
    }
    try {
      const raw = await this.ln7Api.runBakeoff(mode) as Record<string, unknown>;
      const privateRes = (raw.private || {}) as Record<string, unknown>;
      this.sendToWebview({
        cmd: 'ln7BakeoffResult',
        ok: Boolean(raw.ok),
        pass_rate: privateRes.pass_rate as HostToWebviewMessage['pass_rate'],
        public_note: 'Public benchmarks report-only until harness containers land',
        error: typeof raw.error === 'string' ? raw.error : undefined,
      });
    } catch (err) {
      this.sendToWebview({
        cmd: 'ln7BakeoffResult',
        ok: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  private async handleLn7Leaderboard(): Promise<void> {
    if (!this.ln7Api) {
      this.sendToWebview({ cmd: 'ln7LeaderboardResult', rows: [] });
      return;
    }
    try {
      const raw = await this.ln7Api.leaderboard() as Record<string, unknown>;
      this.sendToWebview({
        cmd: 'ln7LeaderboardResult',
        rows: (raw.rows as Array<Record<string, unknown>>) || [],
      });
    } catch (err) {
      this.sendToWebview({
        cmd: 'ln7LeaderboardResult',
        rows: [],
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  private async handleLoadPlan(): Promise<void> {
    const plan = await this.planManager.pickAndLoadCursorPlan();
    if (plan) {
      this.sendToWebview({
        cmd: 'planLoaded',
        plan_name: plan.name,
        plan_overview: plan.overview,
        plan_todos: plan.todos,
        plan_file: plan.file_path,
      });
    }
  }

  private async handleSend(mode: CliMode, message: string): Promise<void> {
    if (!message.trim()) { return; }

    if (this.bridge.connectionState !== 'authenticated') {
      this.sendToWebview({
        cmd: 'error',
        error: 'Not authenticated. Click the LN status bar item to log in.',
      });
      return;
    }

    if (!this.planManager.activePlan) {
      let loaded: Awaited<ReturnType<typeof this.planManager.autoDetectFromActiveEditor>> = null;

      const planPathMatch = message.match(/(\S+\.plan\.md)\b/);
      if (planPathMatch) {
        loaded = await this.planManager.loadFromPath(planPathMatch[1]);
      }

      if (!loaded) {
        loaded = await this.planManager.autoDetectFromActiveEditor();
      }

      if (loaded) {
        this.sendToWebview({
          cmd: 'planLoaded',
          plan_name: loaded.name,
          plan_overview: loaded.overview,
          plan_todos: loaded.todos,
          plan_file: loaded.file_path,
        });
      }
    }

    this.pushHistory({ role: 'user', content: message, timestamp: Date.now(), mode });

    const context = this.gatherVsCodeContext();

    this._currentTurn = 0;
    this._currentNateRaw = '';

    const payload: Record<string, unknown> = {
      type: 'nate_cli_chat',
      mode,
      cli: this.bridge.cliType,
      message,
      context,
    };
    if (this._selectedModel) {
      payload.model = this._selectedModel;
      payload.model_space = this._selectedSpace || 'foundry';
      if (this._selectedProvider) {
        payload.provider = this._selectedProvider;
        payload.llm_provider = this._selectedProvider;
      }
    }

    const sent = this.bridge.send(payload as unknown as Parameters<BridgeClient['send']>[0]);

    if (!sent) {
      this.sendToWebview({
        cmd: 'error',
        error: 'Bridge connection lost. Reconnecting...',
      });
    }
  }

  requestModelCatalog(forceRefresh: boolean): void {
    if (this.bridge.connectionState !== 'authenticated') {
      return;
    }
    this.bridge.send({
      type: forceRefresh ? 'nate_cli_models_refresh' : 'nate_cli_models',
      force_refresh: forceRefresh,
    });
  }

  startModelAutoRefresh(): void {
    if (this._modelRefreshTimer) {
      return;
    }
    const mins = vscode.workspace.getConfiguration('sovereignSanctuary')
      .get<number>('modelCatalogRefreshMinutes', 15);
    if (!mins || mins <= 0) {
      return;
    }
    this._modelRefreshTimer = setInterval(() => {
      this.requestModelCatalog(true);
    }, mins * 60 * 1000);
  }

  private gatherVsCodeContext(): VsCodeContext {
    const editor = vscode.window.activeTextEditor;
    const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

    const ctx: VsCodeContext = {
      workspace_root: wsRoot,
    };

    if (editor) {
      ctx.active_file = editor.document.uri.fsPath;
      if (!editor.selection.isEmpty) {
        ctx.selection = editor.document.getText(editor.selection);
      }
      const diagnostics = vscode.languages.getDiagnostics(editor.document.uri);
      if (diagnostics.length > 0) {
        ctx.diagnostics = diagnostics.slice(0, 10).map(d => ({
          message: d.message,
          severity: d.severity,
          range: {
            start: { line: d.range.start.line, character: d.range.start.character },
            end: { line: d.range.end.line, character: d.range.end.character },
          },
        }));
      }
    }

    ctx.visible_files = vscode.window.visibleTextEditors.map(e => e.document.uri.fsPath);

    const activePlan = this.planManager.activePlan;
    if (activePlan) {
      ctx.cursor_plan = activePlan;
    }

    return ctx;
  }

  private openFile(filePath: string, startLine?: number): void {
    const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    let fullPath = filePath;
    if (wsRoot && !path.isAbsolute(filePath)) {
      fullPath = path.join(wsRoot, filePath);
    }

    const uri = vscode.Uri.file(fullPath);
    const line = (startLine || 1) - 1;

    vscode.window.showTextDocument(uri, {
      selection: new vscode.Range(line, 0, line, 0),
      preview: true,
    });
  }

  private setupBridgeListeners(): void {
    this.bridge.on('cli_chunk', (msg: InboundCliChatChunk) => {
      if (msg.delta) this._currentNateRaw += msg.delta;
      this.sendToWebview({
        cmd: 'chunk',
        delta: msg.delta,
        provider: msg.provider,
        turn: msg.turn,
      });
    });

    this.bridge.on('cli_tool', (msg: InboundCliChatTool) => {
      if (!this._currentTurn) this._currentTurn = 1;
      this.sendToWebview({
        cmd: 'tool',
        tool_name: msg.tool_name,
        tool_input: msg.tool_input,
        tool_output_preview: msg.tool_output_preview,
        duration_ms: msg.duration_ms,
        status: msg.status,
        status_text: msg.status,
        turn: this._currentTurn,
      });
    });

    this.bridge.on('cli_status', (msg: InboundCliChatStatus) => {
      if (msg.status === 'thinking') {
        this._currentTurn++;
      }
      this.sendToWebview({
        cmd: 'status',
        status_text: msg.detail || msg.status,
        turn: this._currentTurn || 1,
      });
    });

    this.bridge.on('cli_output', (msg: InboundCliChatOutput) => {
      this.diffApplicator.handleOutput(msg);
      this.sendToWebview({
        cmd: 'output',
        content: msg.content,
        language: msg.language,
      });
    });

    this.bridge.on('cli_done', (msg: InboundCliChatDone) => {
      if (msg.mode === 'plan' && msg.plan_id) {
        this.planManager.savePlan(msg);
      }

      if (this._currentNateRaw.trim()) {
        this.pushHistory({
          role: 'nate',
          content: this._currentNateRaw,
          timestamp: Date.now(),
          mode: msg.mode as CliMode,
          provider: msg.provider,
          turn: msg.total_turns || this._currentTurn,
        });
      }
      this._currentNateRaw = '';

      this.sendToWebview({
        cmd: 'done',
        plan_id: msg.plan_id,
        mode: msg.mode,
        provider: msg.provider,
        error: msg.error,
        hypotheses: msg.hypotheses,
        cost: msg.cost,
        duration_ms: msg.duration_ms,
        turn: msg.total_turns || this._currentTurn,
      });

      this._currentTurn = 0;
    });

    this.bridge.on('bridge_connected', (target: string) => {
      this._reconnecting = false;
      this.sendToWebview({ cmd: 'connected', bridge_target: target });
      this.sendToWebview({
        cmd: 'cliTarget',
        bridge_target: target,
        cli_type: this.bridge.cliType,
      });
    });

    this.bridge.on('bridge_disconnected', () => {
      this.sendToWebview({ cmd: 'disconnected' });
      if (!this._reconnecting) {
        this._reconnecting = true;
        this.sendToWebview({ cmd: 'status', status_text: 'Reconnecting to bridge...' });
      }
    });

    this.bridge.on('bridge_error', (err: string) => {
      if (!this._reconnecting) {
        this.sendToWebview({ cmd: 'error', error: err });
      }
    });

    this.bridge.on('login_success', () => {
      this.sendToWebview({ cmd: 'authenticated' });
      this.sendToWebview({
        cmd: 'cliTarget',
        bridge_target: this.bridge.bridgeTarget || 'cloud',
        cli_type: this.bridge.cliType,
      });
      this.requestModelCatalog(true);
      this.startModelAutoRefresh();
    });

    this.bridge.on('cli_models', (msg: InboundCliModels) => {
      const payload: HostToWebviewMessage = {
        cmd: 'modelCatalog',
        models: msg.models || [],
        default_model: msg.default_model,
        default_space: msg.default_space,
        ln7_revised_at: msg.ln7_revised_at,
        bridge_target: this.bridge.bridgeTarget || 'cloud',
        counts: msg.counts || msg.picker_counts,
        picker_counts: msg.picker_counts,
        errors: msg.errors,
      };
      this._lastModelCatalog = payload;
      this.sendToWebview(payload);
    });

    this.bridge.on('cli_models_error', (msg: { error?: string }) => {
      this.sendToWebview({
        cmd: 'error',
        error: `Model catalog: ${msg.error || 'failed'}`,
      });
    });

    this.bridge.on('ask_user_prompt', (msg: Record<string, unknown>) => {
      this.sendToWebview({
        cmd: 'ask_user_prompt',
        question_id: msg.question_id as string,
        question: msg.question as string,
        question_type: (msg.question_type as string) || 'single_select',
        options: msg.options as Array<{ id: string; label: string }>,
        context: (msg.context as string) || '',
        allow_skip: (msg.allow_skip as boolean) || false,
      });
    });

    this.bridge.on('build_status', (msg: BuildStatusMessage) => {
      this._buildState = {
        isBuilding: msg.status.phase !== 'idle' && msg.status.phase !== 'complete' && msg.status.phase !== 'failed',
        phase: msg.status.phase,
        currentVersion: msg.status.current_version,
        buildingVersion: msg.status.building_version,
        myRole: msg.status.my_role,
        testResults: null,
        soakRemaining: msg.status.soak_remaining_seconds,
        lastError: msg.status.last_error,
      };
      this.sendToWebview({
        cmd: 'status',
        status_text: `Build ${msg.status.phase}: ${msg.status.building_version || msg.status.current_version}`,
      });
    });

    this.bridge.on('build_verify_request', () => {
      this.sendToWebview({ cmd: 'status', status_text: 'Build verification requested by peer...' });
    });

    this.bridge.on('build_verify_result', (msg: Record<string, unknown>) => {
      const verified = (msg as { verified?: boolean }).verified;
      this.sendToWebview({
        cmd: 'status',
        status_text: verified ? 'Build verified by peer ✓' : 'Build verification FAILED by peer ✗',
      });
    });

    this.bridge.on('build_rollback', (msg: Record<string, unknown>) => {
      const reason = (msg as { reason?: string }).reason || 'unknown';
      this.sendToWebview({ cmd: 'status', status_text: `Build rollback: ${reason}` });
    });

    this.bridge.on('health_status', (msg: Record<string, unknown>) => {
      updateAutonomousStatus(msg as unknown as Parameters<typeof updateAutonomousStatus>[0]);
    });
  }

  private async getHtml(webview: vscode.Webview): Promise<string> {
    const distWebview = vscode.Uri.joinPath(this.extensionUri, 'dist', 'webview');
    const cssUri = webview.asWebviewUri(vscode.Uri.joinPath(distWebview, 'chat.css'));
    const jsUri = webview.asWebviewUri(vscode.Uri.joinPath(distWebview, 'chat.js'));
    const nonce = crypto.randomBytes(16).toString('hex');

    const htmlPath = vscode.Uri.joinPath(distWebview, 'chat.html');
    let html: string;
    try {
      const raw = await vscode.workspace.fs.readFile(htmlPath);
      html = Buffer.from(raw).toString('utf-8');
    } catch {
      html = this.fallbackHtml();
    }

    html = html
      .replace(/\{\{cspSource\}\}/g, webview.cspSource)
      .replace(/\{\{nonce\}\}/g, nonce)
      .replace(/\{\{cssUri\}\}/g, cssUri.toString())
      .replace(/\{\{jsUri\}\}/g, jsUri.toString());

    return html;
  }

  private fallbackHtml(): string {
    return `<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src {{cspSource}} 'unsafe-inline'; script-src 'nonce-{{nonce}}';">
<link rel="stylesheet" href="{{cssUri}}">
</head><body>
<div class="mode-bar">
  <button class="mode-btn active" data-mode="ask">ASK</button>
  <button class="mode-btn" data-mode="plan">PLAN</button>
  <button class="mode-btn" data-mode="ln_fab">LN-FAB</button>
  <button class="mode-btn" data-mode="debug">DEBUG</button>
  <span class="spacer"></span>
  <button class="clear-btn" id="clearBtn">Clear</button>
</div>
<div class="plan-bar">
  <button class="plan-load-btn" id="planLoadBtn">Load Plan</button>
  <div class="plan-info" id="planInfo" style="display:none">
    <span class="plan-name" id="planName"></span>
    <span class="plan-progress" id="planProgress"></span>
    <button class="plan-clear-btn" id="planClearBtn">✕</button>
  </div>
</div>
<div class="chat-log" id="chatLog"></div>
<div class="hypothesis-panel" id="hypothesisPanel"></div>
<div class="mark-fixed-bar" id="markFixedBar">
  <button class="mark-fixed-btn" id="markFixedBtn">Mark Fixed</button>
  <button class="clean-logs-btn" id="cleanLogsBtn">Clean Logs</button>
  <span style="flex:1"></span>
  <span class="cost-badge" id="sessionCost" style="display:none"></span>
</div>
<div class="input-area">
  <textarea id="chatInput" rows="1" placeholder="Ask Little Nate..." autofocus></textarea>
  <button class="send-btn" id="sendBtn">Send</button>
</div>
<script nonce="{{nonce}}" src="{{jsUri}}"></script>
</body></html>`;
  }

  private pushHistory(entry: ChatEntry): void {
    this._chatHistory.push(entry);
    if (this._chatHistory.length > 500) {
      this._chatHistory = this._chatHistory.slice(-400);
    }
    this.saveHistory();
  }

  private saveHistory(): void {
    if (!this._historyPath) return;
    try {
      fs.writeFileSync(this._historyPath, JSON.stringify(this._chatHistory, null, 2), 'utf-8');
    } catch { /* non-fatal */ }
  }

  private loadHistory(): void {
    if (!this._historyPath) return;
    try {
      if (fs.existsSync(this._historyPath)) {
        const raw = fs.readFileSync(this._historyPath, 'utf-8');
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          this._chatHistory = parsed;
        }
      }
    } catch { /* start fresh */ }
  }

  private clearHistory(): void {
    this._chatHistory = [];
    if (this._historyPath) {
      try { fs.unlinkSync(this._historyPath); } catch { /* ok */ }
    }
  }

  dispose(): void {
    if (this._modelRefreshTimer) {
      clearInterval(this._modelRefreshTimer);
      this._modelRefreshTimer = null;
    }
    this.panel?.dispose();
    this.webviews.clear();
    this.disposables.forEach(d => d.dispose());
  }
}
