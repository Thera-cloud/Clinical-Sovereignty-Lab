import * as vscode from 'vscode';
import * as path from 'path';
import * as os from 'os';
import type { InboundCliChatDone, CursorPlan, CursorPlanTodo } from './types';

const SOVEREIGN_PLANS_DIR = '.sovereign/plans';

export class PlanManager implements vscode.TreeDataProvider<PlanItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<PlanItem | undefined | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private plans: PlanItem[] = [];
  private _activeCursorPlan: CursorPlan | null = null;

  constructor() {
    this.refreshPlans();
  }

  get activePlan(): CursorPlan | null {
    return this._activeCursorPlan;
  }

  // ── Cursor Plan Discovery & Loading ──

  async pickAndLoadCursorPlan(): Promise<CursorPlan | null> {
    const planFiles = await this.discoverCursorPlans();
    if (planFiles.length === 0) {
      vscode.window.showInformationMessage('No Cursor plan files found in .cursor/plans/');
      return null;
    }

    const items = planFiles.map(pf => ({
      label: pf.name,
      description: pf.source,
      detail: pf.overview || '',
      filePath: pf.filePath,
    }));

    const pick = await vscode.window.showQuickPick(items, {
      placeHolder: 'Select a Cursor plan to load as context',
      matchOnDescription: true,
      matchOnDetail: true,
    });

    if (!pick) { return null; }

    const plan = await this.parseCursorPlan(pick.filePath);
    if (plan) {
      this._activeCursorPlan = plan;
    }
    return plan;
  }

  clearActivePlan(): void {
    this._activeCursorPlan = null;
  }

  async loadFromPath(filePath: string): Promise<CursorPlan | null> {
    if (!filePath.endsWith('.plan.md')) { return null; }
    const plan = await this.parseCursorPlan(filePath);
    if (plan) {
      this._activeCursorPlan = plan;
    }
    return plan;
  }

  async autoDetectFromActiveEditor(): Promise<CursorPlan | null> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) { return null; }
    const filePath = editor.document.uri.fsPath;
    if (!filePath.endsWith('.plan.md')) { return null; }
    if (this._activeCursorPlan?.file_path === filePath) {
      return this._activeCursorPlan;
    }
    return this.loadFromPath(filePath);
  }

  private async discoverCursorPlans(): Promise<Array<{ filePath: string; name: string; overview: string; source: string }>> {
    const results: Array<{ filePath: string; name: string; overview: string; source: string }> = [];

    const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (wsRoot) {
      const wsPlansDir = path.join(wsRoot, '.cursor', 'plans');
      await this.scanPlanDir(wsPlansDir, 'workspace', results);
    }

    const userPlansDir = path.join(os.homedir(), '.cursor', 'plans');
    await this.scanPlanDir(userPlansDir, 'user', results);

    return results;
  }

  private async scanPlanDir(
    dirPath: string,
    source: string,
    out: Array<{ filePath: string; name: string; overview: string; source: string }>,
  ): Promise<void> {
    const dirUri = vscode.Uri.file(dirPath);
    try {
      const entries = await vscode.workspace.fs.readDirectory(dirUri);
      const planFiles = entries
        .filter(([name, type]) => name.endsWith('.plan.md') && type === vscode.FileType.File)
        .sort(([a], [b]) => b.localeCompare(a));

      for (const [name] of planFiles) {
        const filePath = path.join(dirPath, name);
        const { planName, overview } = await this.quickParseFrontmatter(filePath);
        const displayName = planName || name.replace('.plan.md', '').replace(/_/g, ' ');
        out.push({ filePath, name: displayName, overview, source });
      }
    } catch {
      // directory doesn't exist — skip
    }
  }

  private async quickParseFrontmatter(filePath: string): Promise<{ planName: string; overview: string }> {
    try {
      const raw = await vscode.workspace.fs.readFile(vscode.Uri.file(filePath));
      const text = Buffer.from(raw).toString('utf-8');
      const fm = this.extractFrontmatter(text);
      return { planName: fm.name || '', overview: fm.overview || '' };
    } catch {
      return { planName: '', overview: '' };
    }
  }

  async parseCursorPlan(filePath: string): Promise<CursorPlan | null> {
    try {
      const raw = await vscode.workspace.fs.readFile(vscode.Uri.file(filePath));
      const text = Buffer.from(raw).toString('utf-8');
      const fm = this.extractFrontmatter(text);

      const fmEnd = text.indexOf('---', text.indexOf('---') + 3);
      const body = fmEnd >= 0 ? text.substring(fmEnd + 3).trim() : text;

      return {
        file_path: filePath,
        name: fm.name || path.basename(filePath, '.plan.md').replace(/_/g, ' '),
        overview: fm.overview || '',
        todos: fm.todos || [],
        body,
      };
    } catch (err) {
      vscode.window.showWarningMessage(`Failed to parse plan: ${err}`);
      return null;
    }
  }

  private extractFrontmatter(text: string): { name: string; overview: string; todos: CursorPlanTodo[] } {
    const fmMatch = text.match(/^---\n([\s\S]*?)\n---/);
    if (!fmMatch) {
      return { name: '', overview: '', todos: [] };
    }

    const fmText = fmMatch[1];

    const nameMatch = fmText.match(/^name:\s*(.+)$/m);
    const overviewMatch = fmText.match(/^overview:\s*(.+)$/m);
    const name = nameMatch?.[1]?.trim() || '';
    const overview = overviewMatch?.[1]?.trim() || '';

    const todos: CursorPlanTodo[] = [];
    const todoBlockMatch = fmText.match(/^todos:\n((?:\s+-[\s\S]*?)?)(?=\n\w|\n*$)/m);
    if (todoBlockMatch) {
      const todoBlock = fmText.substring(fmText.indexOf('todos:') + 6);
      const itemRegex = /^\s+-\s+id:\s*(\S+)\n\s+content:\s*(.+)\n\s+status:\s*(\S+)/gm;
      let match;
      while ((match = itemRegex.exec(todoBlock)) !== null) {
        todos.push({
          id: match[1],
          content: match[2].trim(),
          status: match[3] as CursorPlanTodo['status'],
        });
      }
    }

    return { name, overview, todos };
  }

  // ── Sovereign Plans (existing functionality) ──

  async savePlan(msg: InboundCliChatDone): Promise<void> {
    const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!wsRoot) {
      vscode.window.showWarningMessage('No workspace open — cannot save plan.');
      return;
    }

    const plansDir = vscode.Uri.file(path.join(wsRoot, SOVEREIGN_PLANS_DIR));
    try {
      await vscode.workspace.fs.createDirectory(plansDir);
    } catch {
      // directory may already exist
    }

    const fileName = `${msg.plan_id}.md`;
    const filePath = path.join(wsRoot, SOVEREIGN_PLANS_DIR, fileName);
    const fileUri = vscode.Uri.file(filePath);

    const frontmatter = [
      '---',
      `plan_id: ${msg.plan_id}`,
      `mode: ${msg.mode}`,
      `status: ${msg.error ? 'abandoned' : 'completed'}`,
      `provider: ${msg.provider}`,
      `duration_ms: ${msg.duration_ms}`,
      `total_turns: ${msg.total_turns}`,
      `cli_type: ${msg.cli_type}`,
      `cost_usd: ${msg.cost?.est_cost_usd?.toFixed(6) || '0'}`,
      `files:`,
      ...(msg.files || []).map(f => `  - ${f.path} (${f.action})`),
      '---',
      '',
    ].join('\n');

    const content = frontmatter + (msg.error ? `\n## Error\n\n${msg.error}\n` : '');

    await vscode.workspace.fs.writeFile(fileUri, Buffer.from(content, 'utf-8'));
    await this.refreshPlans();

    const action = await vscode.window.showInformationMessage(
      `Plan saved: ${fileName}`,
      'Open Plan',
    );
    if (action === 'Open Plan') {
      await vscode.window.showTextDocument(fileUri);
    }
  }

  async openPlan(): Promise<void> {
    await this.refreshPlans();

    if (this.plans.length === 0) {
      vscode.window.showInformationMessage('No plans found in .sovereign/plans/');
      return;
    }

    const items = this.plans.map(p => ({
      label: p.label as string,
      description: p.description as string,
      uri: p.resourceUri!,
    }));

    const pick = await vscode.window.showQuickPick(items, {
      placeHolder: 'Select a plan to open',
    });

    if (pick) {
      await vscode.window.showTextDocument(pick.uri);
    }
  }

  // ── TreeDataProvider ──

  getTreeItem(element: PlanItem): vscode.TreeItem {
    return element;
  }

  async getChildren(): Promise<PlanItem[]> {
    await this.refreshPlans();
    return this.plans;
  }

  private async refreshPlans(): Promise<void> {
    const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!wsRoot) {
      this.plans = [];
      return;
    }

    const plansDir = vscode.Uri.file(path.join(wsRoot, SOVEREIGN_PLANS_DIR));
    try {
      const entries = await vscode.workspace.fs.readDirectory(plansDir);
      this.plans = entries
        .filter(([name]) => name.endsWith('.md'))
        .sort(([a], [b]) => b.localeCompare(a))
        .map(([name]) => {
          const uri = vscode.Uri.file(path.join(wsRoot, SOVEREIGN_PLANS_DIR, name));
          const item = new PlanItem(
            name.replace('.md', ''),
            uri,
          );
          return item;
        });
    } catch {
      this.plans = [];
    }

    this._onDidChangeTreeData.fire();
  }

  dispose(): void {
    this._onDidChangeTreeData.dispose();
  }
}

class PlanItem extends vscode.TreeItem {
  constructor(label: string, uri: vscode.Uri) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.resourceUri = uri;
    this.tooltip = uri.fsPath;
    this.description = 'plan';
    this.iconPath = new vscode.ThemeIcon('notebook');
    this.command = {
      command: 'vscode.open',
      title: 'Open Plan',
      arguments: [uri],
    };
  }
}
