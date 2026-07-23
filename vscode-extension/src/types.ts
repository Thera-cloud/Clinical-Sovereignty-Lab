export * from './types/buildProtocol';

export type CliMode = 'ask' | 'plan' | 'debug' | 'ln_fab';
export type CliType = 'mac' | 'cloud';
export type BridgeTarget = 'auto' | 'local' | 'cloud';

export interface OutboundCliChat {
  type: 'nate_cli_chat';
  mode: CliMode;
  cli: CliType;
  message: string;
  context?: VsCodeContext;
  resume_plan_id?: string;
}

export interface OutboundLoginRequest {
  type: 'login_request';
  username: string;
  password: string;
  expected_role: string;
}

export interface OutboundAuthMessage {
  type: 'auth';
  token: string;
  hardware_id?: string;
}

export interface OutboundDebugResolved {
  type: 'nate_cli_debug_resolved';
  plan_id: string;
  resolution: string;
}

export interface InboundConnected {
  type: 'connected';
  status: 'ready';
}

export interface InboundLoginSuccess {
  type: 'login_success';
  token: string;
  hardware_id: string;
  username: string;
  role: string;
  profile: Record<string, unknown>;
}

export interface InboundLoginFailed {
  type: 'login_failed';
  error?: string;
  message?: string;
}

export interface InboundAuthSuccess {
  type: 'auth_success';
  profile?: Record<string, unknown>;
}

export interface InboundAuthFailed {
  type: 'auth_failed';
  error?: string;
  message?: string;
}

export interface InboundCliChatChunk {
  type: 'nate_cli_chat_chunk';
  delta: string;
  provider: string;
  turn: number;
}

export interface InboundCliChatTool {
  type: 'nate_cli_chat_tool';
  tool_name: string;
  tool_input: Record<string, unknown>;
  tool_output_preview: string;
  status: 'ok' | 'error' | 'denied';
  duration_ms: number;
}

export interface InboundCliChatStatus {
  type: 'nate_cli_chat_status';
  status: 'thinking' | 'tool_executing' | 'debug_cleanup';
  detail?: string;
  rate_limit?: { remaining: number; limit: number };
  cleanup?: Record<string, unknown>;
}

export interface InboundCliChatOutput {
  type: 'nate_cli_chat_output';
  content: string;
  language?: string;
  target_file?: string;
}

export interface ToolCallLog {
  tool_name: string;
  tool_input: Record<string, unknown>;
  tool_output_preview: string;
  status: string;
  duration_ms: number;
  turn: number;
}

export interface Hypothesis {
  id: number;
  title: string;
  confidence: string;
  evidence: string[];
}

export interface CostInfo {
  input_chars: number;
  output_chars: number;
  est_input_tokens: number;
  est_output_tokens: number;
  est_cost_usd: number;
}

export interface DebugInjectionStatus {
  active_count: number;
  files: string[];
}

export interface InboundCliChatDone {
  type: 'nate_cli_chat_done';
  plan_id: string;
  mode: CliMode;
  provider: string;
  files: Array<{ path: string; action: string }>;
  tool_calls: ToolCallLog[];
  duration_ms: number;
  error?: string;
  chars: number;
  total_turns: number;
  outputs: number;
  cli_type: CliType;
  cost: CostInfo;
  hypotheses?: Hypothesis[];
  debug_injections?: DebugInjectionStatus;
}

// ── Workspace Tool Provider types ──

export type WorkspaceToolName =
  | 'read_file' | 'list_directory' | 'search_code' | 'glob_files' | 'proposed_edit'
  | 'read_diagnostics' | 'read_git_status' | 'git_log' | 'write_file' | 'create_file'
  | 'delete_file' | 'rename_file' | 'run_command' | 'read_open_editors';

export type ToolCallErrorCode =
  | 'FILE_NOT_FOUND'
  | 'BINARY_FILE'
  | 'PATH_TRAVERSAL'
  | 'PERMISSION_DENIED'
  | 'TIMEOUT'
  | 'CANCELLED'
  | 'WORKSPACE_DISCONNECTED'
  | 'USER_REJECTED'
  | 'UNKNOWN';

export interface OutboundWorkspaceRegister {
  type: 'workspace_provider_register';
  provider_id: string;
  workspace_root: string;
  capabilities: WorkspaceToolName[];
  vscode_version: string;
  extension_version: string;
}

export interface OutboundToolCallResult {
  type: 'tool_call_result';
  request_id: string;
  tool: string;
  success: boolean;
  content?: string;
  error?: string;
  error_code?: ToolCallErrorCode;
  metadata?: Record<string, unknown>;
  duration_ms: number;
  action?: 'accepted' | 'rejected' | 'cancelled';
}

export interface OutboundToolCallAck {
  type: 'tool_call_ack';
  request_id: string;
}

export interface OutboundWorkspaceEvent {
  type: 'workspace_event';
  event_type: 'file_saved' | 'file_created' | 'file_deleted' |
              'diagnostic_change' | 'active_editor_change';
  file?: string;
  language?: string;
  errors?: Array<{ message: string; line: number; severity: string }>;
}

export interface InboundToolCallRequest {
  type: 'tool_call_request';
  request_id: string;
  tool: WorkspaceToolName;
  params: Record<string, unknown>;
  requesting_cli: string;
}

export interface InboundWorkspaceRegistered {
  type: 'workspace_provider_registered';
  status: 'active';
}

export interface InboundToolCallCancel {
  type: 'tool_call_cancel';
  request_id: string;
  reason?: string;
}

export interface InboundWorkspaceProviderReplaced {
  type: 'workspace_provider_replaced';
  reason: string;
}

export interface InboundWorkspaceProviderAvailable {
  type: 'workspace_provider_available';
  workspace_root: string;
  capabilities: string[];
}

export type InboundMessage =
  | InboundConnected
  | InboundLoginSuccess
  | InboundLoginFailed
  | InboundAuthSuccess
  | InboundAuthFailed
  | InboundCliChatChunk
  | InboundCliChatTool
  | InboundCliChatStatus
  | InboundCliChatOutput
  | InboundCliChatDone
  | InboundToolCallRequest
  | InboundWorkspaceRegistered
  | InboundToolCallCancel
  | InboundWorkspaceProviderReplaced
  | InboundWorkspaceProviderAvailable
  | BuildStatusMessage
  | BuildVerifyRequest
  | BuildVerifyResult
  | BuildPromoteGreen
  | BuildPromoteComplete
  | BuildRollback;

export type OutboundMessage =
  | OutboundCliChat
  | OutboundLoginRequest
  | OutboundAuthMessage
  | OutboundDebugResolved
  | OutboundWorkspaceRegister
  | OutboundToolCallResult
  | OutboundToolCallAck
  | OutboundWorkspaceEvent;

export interface CursorPlanTodo {
  id: string;
  content: string;
  status: 'pending' | 'in_progress' | 'completed' | 'cancelled';
}

export interface CursorPlan {
  file_path: string;
  name: string;
  overview: string;
  todos: CursorPlanTodo[];
  body: string;
}

export interface VsCodeContext {
  active_file?: string;
  selection?: string;
  visible_files?: string[];
  diagnostics?: Array<{
    message: string;
    severity: number;
    range: { start: { line: number; character: number }; end: { line: number; character: number } };
  }>;
  workspace_root?: string;
  cursor_plan?: CursorPlan;
}

export interface StoredCredentials {
  token: string;
  hardware_id: string;
  username: string;
  role: string;
}

/** Messages exchanged between Extension Host and WebView via postMessage */
export interface WebviewToHostMessage {
  cmd: 'send' | 'markFixed' | 'switchMode' | 'openFile' | 'acceptDiff' | 'rejectDiff' | 'clearChat' | 'loadPlan' | 'clearPlan';
  mode?: CliMode;
  message?: string;
  plan_id?: string;
  resolution?: string;
  file_path?: string;
  start_line?: number;
}

export interface ChatEntry {
  role: 'user' | 'nate' | 'status';
  content: string;
  timestamp: number;
  mode?: CliMode;
  provider?: string;
  turn?: number;
}

export interface HostToWebviewMessage {
  cmd: 'chunk' | 'tool' | 'status' | 'output' | 'done' | 'error' | 'connected' | 'disconnected' | 'modeChanged' | 'output_applied' | 'planLoaded' | 'planCleared' | 'restoreHistory';
  delta?: string;
  provider?: string;
  turn?: number;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  tool_output_preview?: string;
  status?: string;
  status_text?: string;
  duration_ms?: number;
  content?: string;
  language?: string;
  plan_id?: string;
  mode?: CliMode;
  error?: string;
  hypotheses?: Hypothesis[];
  cost?: CostInfo;
  bridge_target?: string;
  plan_name?: string;
  plan_overview?: string;
  plan_todos?: CursorPlanTodo[];
  plan_file?: string;
  history?: ChatEntry[];
}
