import * as vscode from 'vscode';
import * as path from 'path';
import type { InboundCliChatOutput } from './types';
import type { Ln7Api } from './ln7Api';

const SCHEME = 'sovereign-proposed';

/**
 * Handles LN-FAB generated code by showing inline diffs.
 * The user can Accept (apply the edit) or Reject (close the diff).
 */
export class DiffApplicator {
  private pendingEdits: Map<string, { content: string; uri: vscode.Uri; isNew: boolean }> = new Map();
  private contentProvider: ProposedContentProvider;
  private providerDisposable: vscode.Disposable;
  private ln7Api: Ln7Api | null = null;

  constructor() {
    this.contentProvider = new ProposedContentProvider();
    this.providerDisposable = vscode.workspace.registerTextDocumentContentProvider(
      SCHEME,
      this.contentProvider,
    );
  }

  setLn7Api(api: Ln7Api): void {
    this.ln7Api = api;
  }

  setProposedContent(uri: vscode.Uri, content: string): void {
    this.contentProvider.set(uri, content);
  }

  async handleOutput(msg: InboundCliChatOutput): Promise<void> {
    const content = msg.content;
    if (!content || !content.trim()) { return; }

    const targetFile = msg.target_file || this.extractFilePath(content);
    if (!targetFile) {
      vscode.window.showInformationMessage(
        'Nate generated code, but no target file was specified. Copy from the chat panel.',
      );
      return;
    }

    const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const fullPath = wsRoot && !path.isAbsolute(targetFile)
      ? path.join(wsRoot, targetFile)
      : targetFile;

    const fileUri = vscode.Uri.file(fullPath);
    let isNew = false;

    try {
      await vscode.workspace.fs.stat(fileUri);
    } catch {
      isNew = true;
    }

    const cleanContent = this.extractCodeContent(content);
    const proposedUri = vscode.Uri.parse(`${SCHEME}:${fullPath}`);
    this.contentProvider.set(proposedUri, cleanContent);

    const editId = fullPath;
    this.pendingEdits.set(editId, { content: cleanContent, uri: fileUri, isNew });

    if (isNew) {
      const emptyUri = vscode.Uri.parse(`${SCHEME}:empty`);
      this.contentProvider.set(emptyUri, '');
      await vscode.commands.executeCommand('vscode.diff',
        emptyUri, proposedUri,
        `Nate: New File — ${path.basename(fullPath)}`,
      );
    } else {
      await vscode.commands.executeCommand('vscode.diff',
        fileUri, proposedUri,
        `Nate: Proposed Changes — ${path.basename(fullPath)}`,
      );
    }

    const action = await vscode.window.showInformationMessage(
      `Nate proposed changes to ${path.basename(fullPath)}`,
      'Accept',
      'Reject',
    );

    if (action === 'Accept') {
      await this.applyEdit(editId);
      void this.ln7Api?.recordUsage('accepted', { path: fullPath });
    } else {
      this.rejectEdit(editId);
      void this.ln7Api?.recordUsage('rejected', { path: fullPath });
    }
  }

  async acceptCurrent(): Promise<void> {
    const firstKey = this.pendingEdits.keys().next().value;
    if (firstKey) {
      await this.applyEdit(firstKey);
      void this.ln7Api?.recordUsage('accepted', { path: String(firstKey) });
    } else {
      vscode.window.showInformationMessage('No pending proposed changes.');
    }
  }

  rejectCurrent(): void {
    const firstKey = this.pendingEdits.keys().next().value;
    if (firstKey) {
      this.rejectEdit(firstKey);
      void this.ln7Api?.recordUsage('rejected', { path: String(firstKey) });
    } else {
      vscode.window.showInformationMessage('No pending proposed changes.');
    }
  }

  private async applyEdit(editId: string): Promise<void> {
    const pending = this.pendingEdits.get(editId);
    if (!pending) { return; }

    try {
      if (pending.isNew) {
        const dir = vscode.Uri.file(path.dirname(pending.uri.fsPath));
        await vscode.workspace.fs.createDirectory(dir);
        await vscode.workspace.fs.writeFile(pending.uri, Buffer.from(pending.content, 'utf-8'));
        await vscode.window.showTextDocument(pending.uri);
      } else {
        const doc = await vscode.workspace.openTextDocument(pending.uri);
        const edit = new vscode.WorkspaceEdit();
        const fullRange = new vscode.Range(
          doc.positionAt(0),
          doc.positionAt(doc.getText().length),
        );
        edit.replace(pending.uri, fullRange, pending.content);
        await vscode.workspace.applyEdit(edit);
        await vscode.window.showTextDocument(pending.uri);
      }
      vscode.window.showInformationMessage(`Changes applied to ${path.basename(pending.uri.fsPath)}`);
    } catch (err) {
      vscode.window.showErrorMessage(`Failed to apply changes: ${err}`);
    }

    this.pendingEdits.delete(editId);
    this.closeDiffEditors(editId);
  }

  private rejectEdit(editId: string): void {
    this.pendingEdits.delete(editId);
    this.closeDiffEditors(editId);
    vscode.window.showInformationMessage('Proposed changes rejected.');
  }

  private closeDiffEditors(filePath: string): void {
    const basename = path.basename(filePath);
    for (const group of vscode.window.tabGroups.all) {
      for (const tab of group.tabs) {
        if (tab.label.includes(basename) && tab.label.includes('Nate:')) {
          vscode.window.tabGroups.close(tab);
        }
      }
    }
  }

  private extractFilePath(content: string): string | null {
    const patterns = [
      /###\s+(.+?)\s+\((?:CREATE|MODIFY)\)/i,
      /^\/\/\s*File:\s*(.+)$/m,
      /^#\s*File:\s*(.+)$/m,
      /^```\w*\s*\/\/\s*(.+)$/m,
    ];

    for (const p of patterns) {
      const m = content.match(p);
      if (m) { return m[1].trim(); }
    }
    return null;
  }

  private extractCodeContent(content: string): string {
    const fenced = content.match(/```[\w]*\n([\s\S]*?)```/);
    if (fenced) { return fenced[1]; }
    return content;
  }

  dispose(): void {
    this.providerDisposable.dispose();
    this.pendingEdits.clear();
  }
}

class ProposedContentProvider implements vscode.TextDocumentContentProvider {
  private contents = new Map<string, string>();
  private _onDidChange = new vscode.EventEmitter<vscode.Uri>();
  onDidChange = this._onDidChange.event;

  set(uri: vscode.Uri, content: string): void {
    this.contents.set(uri.toString(), content);
    this._onDidChange.fire(uri);
  }

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.contents.get(uri.toString()) || '';
  }
}
