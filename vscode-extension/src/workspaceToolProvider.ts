import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { BridgeClient } from './bridgeClient';
import { DiffApplicator } from './diffApplicator';
import type {
  InboundToolCallRequest,
  InboundToolCallCancel,
  InboundWorkspaceProviderReplaced,
  OutboundToolCallResult,
  WorkspaceToolName,
  ToolCallErrorCode,
} from './types';

const ALL_CAPABILITIES: WorkspaceToolName[] = [
  'read_file', 'list_directory', 'search_code', 'glob_files', 'proposed_edit',
  'read_diagnostics', 'read_git_status', 'write_file', 'create_file',
  'delete_file', 'rename_file', 'run_command', 'read_open_editors',
];

const MAX_READ_LINES = 500;
const MAX_SEARCH_RESULTS = 50;

type ToolResult = Omit<OutboundToolCallResult, 'type' | 'request_id' | 'tool' | 'duration_ms'>;
type ProposedEditOutcome =
  | { action: 'accepted' | 'rejected' | 'cancelled' }
  | { action: 'failed'; error: string };

export class WorkspaceToolProvider implements vscode.Disposable {
  private bridge: BridgeClient;
  private diffApplicator: DiffApplicator;
  private workspaceRoot: vscode.Uri | null = null;
  private disposables: vscode.Disposable[] = [];
  private active = false;
  private pendingEdits = new Map<string, {
    resolve: (result: ProposedEditOutcome) => void;
    proposedUri: vscode.Uri;
  }>();

  constructor(bridge: BridgeClient, diffApplicator: DiffApplicator) {
    this.bridge = bridge;
    this.diffApplicator = diffApplicator;

    const folders = vscode.workspace.workspaceFolders;
    if (folders && folders.length > 0) {
      this.workspaceRoot = folders[0].uri;
    }

    this.bridge.on('tool_call_request', this.handleToolCall.bind(this));
    this.bridge.on('tool_call_cancel', this.handleCancel.bind(this));
    this.bridge.on('login_success', this.register.bind(this));
    this.bridge.on('workspace_provider_replaced', this.handleReplaced.bind(this));
  }

  private register(): void {
    if (!this.workspaceRoot) { return; }
    this.active = true;
    this.bridge.send({
      type: 'workspace_provider_register',
      provider_id: `vscode-${Date.now()}`,
      workspace_root: this.workspaceRoot.fsPath,
      capabilities: ALL_CAPABILITIES,
      vscode_version: vscode.version,
      extension_version: '0.1.0',
    });
  }

  private handleReplaced(_msg: InboundWorkspaceProviderReplaced): void {
    this.active = false;
    this.dismissAllPendingEdits();
  }

  private async handleToolCall(msg: InboundToolCallRequest): Promise<void> {
    if (!this.active) { return; }

    const start = Date.now();
    try {
      if (msg.tool === 'proposed_edit') {
        this.bridge.send({ type: 'tool_call_ack', request_id: msg.request_id });
      }
      const result = await this.dispatch(msg.tool, msg.params, msg.request_id);
      this.bridge.send({
        type: 'tool_call_result',
        request_id: msg.request_id,
        tool: msg.tool,
        ...result,
        duration_ms: Date.now() - start,
      });
    } catch (err) {
      this.bridge.send({
        type: 'tool_call_result',
        request_id: msg.request_id,
        tool: msg.tool,
        success: false,
        error: String(err),
        error_code: this.classifyError(err),
        duration_ms: Date.now() - start,
      });
    }
  }

  private handleCancel(msg: InboundToolCallCancel): void {
    const pending = this.pendingEdits.get(msg.request_id);
    if (pending) {
      pending.resolve({ action: 'cancelled' });
      this.pendingEdits.delete(msg.request_id);
      this.closeDiffEditorsForRequest(msg.request_id);
    }
  }

  private classifyError(err: unknown): ToolCallErrorCode {
    const msg = String(err);
    if (msg.includes('FileNotFound') || msg.includes('ENOENT') || msg.includes('does not exist')) {
      return 'FILE_NOT_FOUND';
    }
    if (msg.includes('NoPermissions') || msg.includes('EACCES') || msg.includes('permission denied')) {
      return 'PERMISSION_DENIED';
    }
    if (msg.includes('outside workspace') || msg.includes('traversal') || msg.includes('not within')) {
      return 'PATH_TRAVERSAL';
    }
    return 'UNKNOWN';
  }

  private async dispatch(tool: WorkspaceToolName, params: Record<string, unknown>, requestId: string): Promise<ToolResult> {
    switch (tool) {
      case 'read_file':         return this.handleReadFile(params);
      case 'list_directory':    return this.handleListDirectory(params);
      case 'search_code':       return this.handleSearchCode(params);
      case 'glob_files':        return this.handleGlobFiles(params);
      case 'proposed_edit':     return this.handleProposedEdit(params, requestId);
      case 'read_diagnostics':  return this.handleReadDiagnostics(params);
      case 'read_git_status':   return this.handleReadGitStatus();
      case 'write_file':        return this.handleWriteFile(params);
      case 'create_file':       return this.handleCreateFile(params);
      case 'delete_file':       return this.handleDeleteFile(params);
      case 'rename_file':       return this.handleRenameFile(params);
      case 'run_command':       return this.handleRunCommand(params);
      case 'read_open_editors': return this.handleReadOpenEditors();
      default:
        return { success: false, error: `Unknown tool: ${tool}`, error_code: 'UNKNOWN' };
    }
  }

  // ── P0 Tools ──

  private async handleReadFile(params: Record<string, unknown>): Promise<ToolResult> {
    const filePath = String(params.path || '');
    const uri = this.resolveUri(filePath);
    this.assertWithinWorkspace(uri);

    try {
      await vscode.workspace.fs.stat(uri);
    } catch {
      return { success: false, error: `File not found: ${filePath}`, error_code: 'FILE_NOT_FOUND' };
    }

    const raw = await vscode.workspace.fs.readFile(uri);
    if (this.isBinary(raw)) {
      return { success: false, error: `Binary file cannot be read as text: ${filePath}`, error_code: 'BINARY_FILE' };
    }

    const text = Buffer.from(raw).toString('utf-8');
    const lines = text.split('\n');
    const offset = Math.max(0, Number(params.offset || 0));
    const limit = Number(params.limit || MAX_READ_LINES);
    const slice = lines.slice(offset, offset + limit);
    const numbered = slice.map((line, i) => `${String(offset + i + 1).padStart(6)}|${line}`).join('\n');
    const truncated = lines.length > offset + limit;

    const doc = vscode.workspace.textDocuments.find(d => d.uri.fsPath === uri.fsPath);
    const languageId = doc?.languageId || path.extname(filePath).replace('.', '') || 'unknown';

    return {
      success: true,
      content: numbered,
      metadata: {
        path: uri.fsPath,
        total_lines: lines.length,
        showing_lines: slice.length,
        offset,
        truncated,
        language: languageId,
        size_bytes: raw.length,
      },
    };
  }

  private async handleListDirectory(params: Record<string, unknown>): Promise<ToolResult> {
    const dirPath = String(params.path || '.');
    const uri = this.resolveUri(dirPath);
    this.assertWithinWorkspace(uri);

    const entries = await vscode.workspace.fs.readDirectory(uri);
    const sorted = entries.sort((a, b) => {
      if (a[1] !== b[1]) { return b[1] - a[1]; }
      return a[0].localeCompare(b[0]);
    });

    const formatted = sorted.map(([name, type]) => {
      const kind = type === vscode.FileType.Directory ? 'dir' : type === vscode.FileType.SymbolicLink ? 'link' : 'file';
      return `${kind}\t${name}`;
    }).join('\n');

    return {
      success: true,
      content: formatted,
      metadata: { path: uri.fsPath, entry_count: entries.length },
    };
  }

  private async handleSearchCode(params: Record<string, unknown>): Promise<ToolResult> {
    const pattern = String(params.pattern || params.query || '');
    if (!pattern) {
      return { success: false, error: 'Search pattern is required', error_code: 'UNKNOWN' };
    }

    const maxResults = Number(params.max_results || MAX_SEARCH_RESULTS);
    const glob = params.glob ? String(params.glob) : undefined;
    const cwd = this.workspaceRoot?.fsPath;
    if (!cwd) {
      return { success: false, error: 'No workspace folder open', error_code: 'UNKNOWN' };
    }

    const args = [
      '--line-number', '--no-heading', '--color', 'never',
      '--max-count', String(maxResults),
    ];
    if (glob) { args.push('--glob', glob); }
    if (!params.regex) { args.push('--fixed-strings'); }
    args.push('--', pattern);

    return new Promise<ToolResult>((resolve) => {
      const { execFile } = require('child_process');
      execFile('rg', args, { cwd, timeout: 15000, maxBuffer: 2 * 1024 * 1024 }, (err: any, stdout: string, stderr: string) => {
        if (err && err.code === 1) {
          resolve({
            success: true,
            content: `No results for "${pattern}"`,
            metadata: { pattern, match_count: 0, truncated: false },
          });
          return;
        }
        if (err && err.code !== 0) {
          resolve(this.handleSearchCodeFallback(params, pattern, maxResults, glob));
          return;
        }
        const lines = stdout.trim().split('\n').filter(Boolean);
        resolve({
          success: true,
          content: lines.length > 0 ? lines.join('\n') : `No results for "${pattern}"`,
          metadata: { pattern, match_count: lines.length, truncated: lines.length >= maxResults },
        });
      });
    });
  }

  private async handleSearchCodeFallback(
    params: Record<string, unknown>, pattern: string, maxResults: number, glob?: string,
  ): Promise<ToolResult> {
    const matches: string[] = [];
    const includePattern = glob || '**/*';
    const excludePattern = '{**/node_modules/**,**/.git/**,**/build/**,**/dist/**}';

    const files = await vscode.workspace.findFiles(
      new vscode.RelativePattern(this.workspaceRoot!, includePattern),
      excludePattern,
      500,
    );

    const regex = Boolean(params.regex)
      ? new RegExp(pattern, 'gim')
      : new RegExp(pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gim');

    for (const fileUri of files) {
      if (matches.length >= maxResults) { break; }
      try {
        const doc = await vscode.workspace.openTextDocument(fileUri);
        const text = doc.getText();
        let match: RegExpExecArray | null;
        regex.lastIndex = 0;
        while ((match = regex.exec(text)) !== null) {
          if (matches.length >= maxResults) { break; }
          const pos = doc.positionAt(match.index);
          const lineText = doc.lineAt(pos.line).text.trim();
          const relPath = vscode.workspace.asRelativePath(fileUri);
          matches.push(`${relPath}:${pos.line + 1}: ${lineText}`);
        }
      } catch {
        // skip binary or unreadable files
      }
    }

    return {
      success: true,
      content: matches.length > 0 ? matches.join('\n') : `No results for "${pattern}"`,
      metadata: { pattern, match_count: matches.length, truncated: matches.length >= maxResults },
    };
  }

  private async handleGlobFiles(params: Record<string, unknown>): Promise<ToolResult> {
    const pattern = String(params.pattern || params.glob || '');
    if (!pattern) {
      return { success: false, error: 'Glob pattern is required (e.g. "**/*.mdc")', error_code: 'UNKNOWN' };
    }
    if (!this.workspaceRoot) {
      return { success: false, error: 'No workspace folder open', error_code: 'UNKNOWN' };
    }

    const maxResults = Number(params.max_results || 500);
    const exclude = params.exclude ? String(params.exclude) : '{**/node_modules/**,**/.git/**}';

    const files = await vscode.workspace.findFiles(
      new vscode.RelativePattern(this.workspaceRoot, pattern),
      exclude,
      maxResults,
    );

    const entries: Array<{ path: string; size: number; mtime: number }> = [];
    for (const uri of files) {
      try {
        const stat = await vscode.workspace.fs.stat(uri);
        entries.push({
          path: vscode.workspace.asRelativePath(uri),
          size: stat.size,
          mtime: stat.mtime,
        });
      } catch {
        entries.push({ path: vscode.workspace.asRelativePath(uri), size: 0, mtime: 0 });
      }
    }

    entries.sort((a, b) => b.mtime - a.mtime);

    const formatted = entries.map(e => e.path).join('\n');

    return {
      success: true,
      content: entries.length > 0 ? formatted : `No files matching "${pattern}"`,
      metadata: {
        pattern,
        match_count: entries.length,
        truncated: entries.length >= maxResults,
      },
    };
  }

  private async handleProposedEdit(params: Record<string, unknown>, requestId: string): Promise<ToolResult> {
    const filePath = String(params.path || params.file || '');
    const newContent = String(params.content || params.new_content || '');

    if (!filePath) {
      return { success: false, error: 'File path is required for proposed_edit', error_code: 'UNKNOWN' };
    }

    const uri = this.resolveUri(filePath);
    this.assertWithinWorkspace(uri);

    const result = await new Promise<ProposedEditOutcome>((resolve) => {
      const proposedUri = vscode.Uri.parse(`sovereign-proposed:${uri.fsPath}?req=${requestId}`);
      this.pendingEdits.set(requestId, { resolve, proposedUri });
      this.showDiffForEdit(uri, newContent, requestId, resolve);
    });

    this.pendingEdits.delete(requestId);

    if (result.action === 'cancelled') {
      return { success: false, action: 'cancelled', error: 'Edit cancelled by user', error_code: 'CANCELLED' };
    }
    if (result.action === 'rejected') {
      return { success: false, action: 'rejected', error: 'Edit rejected by user', error_code: 'USER_REJECTED' };
    }
    if (result.action === 'failed') {
      return { success: false, error: result.error, error_code: this.classifyError(result.error) };
    }

    return { success: true, action: 'accepted', content: `Applied changes to ${filePath}` };
  }

  private async showDiffForEdit(
    fileUri: vscode.Uri,
    newContent: string,
    requestId: string,
    resolve: (result: ProposedEditOutcome) => void,
  ): Promise<void> {
    const scheme = 'sovereign-proposed';
    const proposedUri = vscode.Uri.parse(`${scheme}:${fileUri.fsPath}?req=${requestId}`);

    let isNew = false;
    try {
      await vscode.workspace.fs.stat(fileUri);
    } catch {
      isNew = true;
    }

    this.diffApplicator.setProposedContent(proposedUri, newContent);

    if (isNew) {
      const emptyUri = vscode.Uri.parse(`${scheme}:empty`);
      this.diffApplicator.setProposedContent(emptyUri, '');
      await vscode.commands.executeCommand('vscode.diff',
        emptyUri, proposedUri,
        `Nate: New File — ${path.basename(fileUri.fsPath)}`,
      );
    } else {
      await vscode.commands.executeCommand('vscode.diff',
        fileUri, proposedUri,
        `Nate: Proposed Changes — ${path.basename(fileUri.fsPath)}`,
      );
    }

    const choice = await vscode.window.showInformationMessage(
      `Nate proposed changes to ${path.basename(fileUri.fsPath)}`,
      'Accept', 'Reject',
    );

    if (!this.pendingEdits.has(requestId)) {
      return;
    }

    if (choice === 'Accept') {
      try {
        if (isNew) {
          const dir = vscode.Uri.file(path.dirname(fileUri.fsPath));
          await vscode.workspace.fs.createDirectory(dir);
          await vscode.workspace.fs.writeFile(fileUri, Buffer.from(newContent, 'utf-8'));
        } else {
          const doc = await vscode.workspace.openTextDocument(fileUri);
          const edit = new vscode.WorkspaceEdit();
          edit.replace(fileUri, new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length)), newContent);
          await vscode.workspace.applyEdit(edit);
        }
        await vscode.window.showTextDocument(fileUri);
        resolve({ action: 'accepted' });
      } catch (err) {
        resolve({ action: 'failed', error: String(err) });
      }
    } else {
      resolve({ action: 'rejected' });
    }

    this.closeDiffEditorsForFile(fileUri.fsPath);
  }

  // ── P1 Tools ──

  private async handleReadDiagnostics(params: Record<string, unknown>): Promise<ToolResult> {
    const filePath = params.path ? String(params.path) : undefined;
    let diagnostics: [vscode.Uri, readonly vscode.Diagnostic[]][];

    if (filePath) {
      const uri = this.resolveUri(filePath);
      diagnostics = [[uri, vscode.languages.getDiagnostics(uri)]];
    } else {
      diagnostics = vscode.languages.getDiagnostics();
    }

    const entries: Array<{ file: string; line: number; severity: string; message: string }> = [];
    const severityNames = ['Error', 'Warning', 'Information', 'Hint'];

    for (const [uri, diags] of diagnostics) {
      for (const d of diags) {
        entries.push({
          file: vscode.workspace.asRelativePath(uri),
          line: d.range.start.line + 1,
          severity: severityNames[d.severity] || 'Unknown',
          message: d.message,
        });
      }
    }

    return {
      success: true,
      content: entries.length > 0
        ? entries.map(e => `${e.file}:${e.line} [${e.severity}] ${e.message}`).join('\n')
        : 'No diagnostics found.',
      metadata: { count: entries.length },
    };
  }

  private async handleReadGitStatus(): Promise<ToolResult> {
    const gitExt = vscode.extensions.getExtension('vscode.git');
    if (!gitExt) {
      return { success: false, error: 'Git extension not available', error_code: 'UNKNOWN' };
    }

    const git = gitExt.isActive ? gitExt.exports : await gitExt.activate();
    const api = git.getAPI(1);
    if (!api || api.repositories.length === 0) {
      return { success: false, error: 'No git repository found', error_code: 'UNKNOWN' };
    }

    const repo = api.repositories[0];
    const changes = repo.state.workingTreeChanges || [];
    const staged = repo.state.indexChanges || [];

    const lines: string[] = [];
    lines.push(`Branch: ${repo.state.HEAD?.name || 'detached'}`);
    if (staged.length > 0) {
      lines.push(`\nStaged (${staged.length}):`);
      for (const c of staged) { lines.push(`  ${c.status} ${vscode.workspace.asRelativePath(c.uri)}`); }
    }
    if (changes.length > 0) {
      lines.push(`\nModified (${changes.length}):`);
      for (const c of changes) { lines.push(`  ${c.status} ${vscode.workspace.asRelativePath(c.uri)}`); }
    }
    if (staged.length === 0 && changes.length === 0) {
      lines.push('Working tree clean.');
    }

    return { success: true, content: lines.join('\n'), metadata: { staged: staged.length, modified: changes.length } };
  }

  private async handleWriteFile(params: Record<string, unknown>): Promise<ToolResult> {
    const filePath = String(params.path || '');
    const content = String(params.content || '');
    const uri = this.resolveUri(filePath);
    this.assertWithinWorkspace(uri);

    const confirm = await vscode.window.showWarningMessage(
      `Nate wants to write to ${path.basename(filePath)}. Allow?`, { modal: true }, 'Allow',
    );
    if (confirm !== 'Allow') {
      return { success: false, error: 'User declined write', error_code: 'PERMISSION_DENIED' };
    }

    const data = Buffer.from(content, 'utf-8');
    await vscode.workspace.fs.writeFile(uri, data);
    return { success: true, content: `Written ${data.length} bytes to ${filePath}`, metadata: { path: filePath, bytes: data.length } };
  }

  private async handleCreateFile(params: Record<string, unknown>): Promise<ToolResult> {
    const filePath = String(params.path || '');
    const content = String(params.content || '');
    const uri = this.resolveUri(filePath);
    this.assertWithinWorkspace(uri);

    try {
      await vscode.workspace.fs.stat(uri);
      return { success: false, error: `File already exists: ${filePath}`, error_code: 'UNKNOWN' };
    } catch {
      // expected — file should not exist
    }

    const confirm = await vscode.window.showWarningMessage(
      `Nate wants to create ${path.basename(filePath)}. Allow?`, { modal: true }, 'Allow',
    );
    if (confirm !== 'Allow') {
      return { success: false, error: 'User declined file creation', error_code: 'PERMISSION_DENIED' };
    }

    const dir = vscode.Uri.file(path.dirname(uri.fsPath));
    await vscode.workspace.fs.createDirectory(dir);
    const data = Buffer.from(content, 'utf-8');
    await vscode.workspace.fs.writeFile(uri, data);
    return { success: true, content: `Created ${filePath} (${data.length} bytes)`, metadata: { path: filePath, bytes: data.length } };
  }

  // ── P2 Tools ──

  private async handleDeleteFile(params: Record<string, unknown>): Promise<ToolResult> {
    const filePath = String(params.path || '');
    const uri = this.resolveUri(filePath);
    this.assertWithinWorkspace(uri);

    const confirm = await vscode.window.showWarningMessage(
      `Nate wants to DELETE ${path.basename(filePath)}. This cannot be undone. Allow?`, { modal: true }, 'Delete',
    );
    if (confirm !== 'Delete') {
      return { success: false, error: 'User declined deletion', error_code: 'PERMISSION_DENIED' };
    }

    await vscode.workspace.fs.delete(uri);
    return { success: true, content: `Deleted ${filePath}` };
  }

  private async handleRenameFile(params: Record<string, unknown>): Promise<ToolResult> {
    const oldPath = String(params.old_path || params.path || '');
    const newPath = String(params.new_path || '');
    const oldUri = this.resolveUri(oldPath);
    const newUri = this.resolveUri(newPath);
    this.assertWithinWorkspace(oldUri);
    this.assertWithinWorkspace(newUri);

    const confirm = await vscode.window.showWarningMessage(
      `Nate wants to rename ${path.basename(oldPath)} to ${path.basename(newPath)}. Allow?`, { modal: true }, 'Rename',
    );
    if (confirm !== 'Rename') {
      return { success: false, error: 'User declined rename', error_code: 'PERMISSION_DENIED' };
    }

    await vscode.workspace.fs.rename(oldUri, newUri);
    return { success: true, content: `Renamed ${oldPath} -> ${newPath}` };
  }

  private async handleRunCommand(params: Record<string, unknown>): Promise<ToolResult> {
    const command = String(params.command || '');
    if (!command) {
      return { success: false, error: 'Command is required', error_code: 'UNKNOWN' };
    }

    const confirm = await vscode.window.showWarningMessage(
      `Nate wants to run a command:\n\n${command}\n\nAllow?`, { modal: true }, 'Run',
    );
    if (confirm !== 'Run') {
      return { success: false, error: 'User declined command', error_code: 'USER_REJECTED' };
    }

    const timeoutMs = Number(params.timeout || 30000);
    const cwd = this.workspaceRoot?.fsPath || process.cwd();

    return new Promise<ToolResult>((resolve) => {
      const { execFile } = require('child_process');
      const timer = setTimeout(() => {
        resolve({ success: false, error: `Command timed out after ${timeoutMs}ms`, error_code: 'TIMEOUT' });
      }, timeoutMs);

      const shell = process.platform === 'win32' ? 'cmd.exe' : '/bin/sh';
      const shellArgs = process.platform === 'win32' ? ['/c', command] : ['-c', command];

      execFile(shell, shellArgs, { cwd, timeout: timeoutMs, maxBuffer: 1024 * 1024 }, (err: any, stdout: string, stderr: string) => {
        clearTimeout(timer);
        const exitCode = err ? err.code || 1 : 0;
        resolve({
          success: exitCode === 0,
          content: stdout || stderr || '(no output)',
          error: exitCode !== 0 ? (stderr || String(err)) : undefined,
          metadata: { exit_code: exitCode, command },
        });
      });
    });
  }

  private handleReadOpenEditors(): ToolResult {
    const editors: Array<{ file: string; language: string; active: boolean; dirty: boolean }> = [];

    for (const group of vscode.window.tabGroups.all) {
      for (const tab of group.tabs) {
        const input = tab.input;
        if (input && typeof input === 'object' && 'uri' in input) {
          const uri = (input as { uri: vscode.Uri }).uri;
          const doc = vscode.workspace.textDocuments.find(d => d.uri.fsPath === uri.fsPath);
          editors.push({
            file: vscode.workspace.asRelativePath(uri),
            language: doc?.languageId || path.extname(uri.fsPath).replace('.', '') || 'unknown',
            active: tab.isActive,
            dirty: Boolean(tab.isDirty),
          });
        }
      }
    }

    return {
      success: true,
      content: editors.length > 0
        ? editors.map(e => `${e.active ? '>' : ' '} ${e.dirty ? '*' : ' '} ${e.file} [${e.language}]`).join('\n')
        : 'No open editors.',
      metadata: { count: editors.length },
    };
  }

  // ── Workspace Event Subscriptions (Phase 4) ──

  setupEventSubscriptions(): void {
    this.disposables.push(
      vscode.workspace.onDidSaveTextDocument((doc) => {
        if (!this.active) { return; }
        this.bridge.send({
          type: 'workspace_event',
          event_type: 'file_saved',
          file: vscode.workspace.asRelativePath(doc.uri),
          language: doc.languageId,
        });
      }),

      vscode.workspace.onDidCreateFiles((e) => {
        if (!this.active) { return; }
        for (const file of e.files) {
          this.bridge.send({
            type: 'workspace_event',
            event_type: 'file_created',
            file: vscode.workspace.asRelativePath(file),
          });
        }
      }),

      vscode.workspace.onDidDeleteFiles((e) => {
        if (!this.active) { return; }
        for (const file of e.files) {
          this.bridge.send({
            type: 'workspace_event',
            event_type: 'file_deleted',
            file: vscode.workspace.asRelativePath(file),
          });
        }
      }),

      vscode.languages.onDidChangeDiagnostics((e) => {
        if (!this.active) { return; }
        for (const uri of e.uris) {
          const diags = vscode.languages.getDiagnostics(uri);
          const errors = diags
            .filter(d => d.severity === vscode.DiagnosticSeverity.Error)
            .map(d => ({ message: d.message, line: d.range.start.line + 1, severity: 'Error' }));
          this.bridge.send({
            type: 'workspace_event',
            event_type: 'diagnostic_change',
            file: vscode.workspace.asRelativePath(uri),
            errors,
          });
        }
      }),

      vscode.window.onDidChangeActiveTextEditor((editor) => {
        if (!this.active || !editor) { return; }
        this.bridge.send({
          type: 'workspace_event',
          event_type: 'active_editor_change',
          file: vscode.workspace.asRelativePath(editor.document.uri),
          language: editor.document.languageId,
        });
      }),
    );
  }

  // ── Utilities ──

  private resolveUri(filePath: string): vscode.Uri {
    if (path.isAbsolute(filePath)) {
      return vscode.Uri.file(filePath);
    }
    if (!this.workspaceRoot) {
      throw new Error('No workspace folder open');
    }
    return vscode.Uri.joinPath(this.workspaceRoot, filePath);
  }

  private assertWithinWorkspace(uri: vscode.Uri): void {
    if (!this.workspaceRoot) { return; }
    const wsRoot = this.resolveRealOrProjectedPath(this.workspaceRoot.fsPath);
    const resolved = this.resolveRealOrProjectedPath(uri.fsPath);
    const relative = path.relative(wsRoot, resolved);
    if (relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))) {
      return;
    }
    throw new Error(`Path ${resolved} is outside workspace (not within ${wsRoot})`);
  }

  private isBinary(buffer: Uint8Array): boolean {
    const sample = buffer.slice(0, Math.min(8192, buffer.length));
    let nullCount = 0;
    for (const byte of sample) {
      if (byte === 0) { nullCount++; }
    }
    return nullCount > sample.length * 0.01;
  }

  private dismissAllPendingEdits(): void {
    for (const [requestId, pending] of this.pendingEdits) {
      pending.resolve({ action: 'cancelled' });
    }
    this.pendingEdits.clear();
  }

  private closeDiffEditorsForRequest(requestId: string): void {
    const pending = this.pendingEdits.get(requestId);
    const targetUri = pending?.proposedUri.toString();
    for (const group of vscode.window.tabGroups.all) {
      for (const tab of group.tabs) {
        const input = tab.input as {
          modified?: { uri?: vscode.Uri };
          original?: { uri?: vscode.Uri };
          uri?: vscode.Uri;
        };
        const matchesRequest =
          input?.modified?.uri?.toString() === targetUri ||
          input?.original?.uri?.toString() === targetUri ||
          input?.uri?.toString() === targetUri;
        if (matchesRequest) {
          vscode.window.tabGroups.close(tab);
        }
      }
    }
  }

  private closeDiffEditorsForFile(filePath: string): void {
    const basename = path.basename(filePath);
    for (const group of vscode.window.tabGroups.all) {
      for (const tab of group.tabs) {
        if (tab.label.includes(basename) && tab.label.includes('Nate:')) {
          vscode.window.tabGroups.close(tab);
        }
      }
    }
  }

  private resolveRealOrProjectedPath(targetPath: string): string {
    const absolutePath = path.resolve(targetPath);
    try {
      return fs.realpathSync.native(absolutePath);
    } catch {
      let current = absolutePath;
      while (!fs.existsSync(current)) {
        const parent = path.dirname(current);
        if (parent === current) {
          break;
        }
        current = parent;
      }
      const existingBase = fs.existsSync(current) ? fs.realpathSync.native(current) : current;
      const relativeTail = path.relative(current, absolutePath);
      return path.resolve(existingBase, relativeTail);
    }
  }

  dispose(): void {
    this.active = false;
    this.dismissAllPendingEdits();
    for (const d of this.disposables) { d.dispose(); }
    this.disposables = [];
  }
}
