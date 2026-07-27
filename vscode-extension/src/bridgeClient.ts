import * as vscode from 'vscode';
import WebSocket from 'ws';
import { EventEmitter } from 'events';
import type {
  InboundMessage, OutboundMessage, BridgeTarget, StoredCredentials,
  InboundLoginSuccess, InboundLoginFailed, InboundAuthSuccess, InboundAuthFailed,
  InboundToolCallRequest, InboundToolCallCancel, InboundWorkspaceProviderReplaced,
} from './types';

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'authenticating' | 'authenticated';

export class BridgeClient extends EventEmitter {
  private ws: WebSocket | null = null;
  private state: ConnectionState = 'disconnected';
  private retryAttempt = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private activeTarget: 'local' | 'cloud' | null = null;
  private configuredMode: BridgeTarget = 'auto';
  private credentials: StoredCredentials | null = null;
  private disposed = false;

  get connectionState(): ConnectionState {
    return this.state;
  }

  get bridgeTarget(): 'local' | 'cloud' | null {
    return this.activeTarget;
  }

  get cliType(): 'mac' | 'cloud' {
    return this.activeTarget === 'local' ? 'mac' : 'cloud';
  }

  async connect(credentials?: StoredCredentials): Promise<void> {
    if (credentials) {
      this.credentials = credentials;
    }
    this.disposed = false;
    this.cancelRetry();

    const config = vscode.workspace.getConfiguration('sovereignSanctuary');
    this.configuredMode = config.get<BridgeTarget>('bridge', 'auto');
    const localUrl = config.get<string>('bridgeLocalUrl', 'ws://localhost:8765/ws');
    const cloudUrl = config.get<string>('bridgeCloudUrl', 'wss://api.sovereignsanctuary.net/ws');

    if (this.configuredMode === 'local') {
      await this.connectTo(localUrl, 'local');
    } else if (this.configuredMode === 'cloud') {
      await this.connectTo(cloudUrl, 'cloud');
    } else {
      const localOk = await this.tryConnect(localUrl, 'local', 3000);
      if (!localOk) {
        await this.connectTo(cloudUrl, 'cloud');
      }
    }
  }

  send(msg: OutboundMessage): boolean {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      const t = (msg as unknown as Record<string, unknown>).type;
      if (t === 'auth' || t === 'login_request') {
        this.setState('authenticating');
      }
      this.ws.send(JSON.stringify(msg));
      return true;
    }
    this.emit('bridge_error', 'WebSocket not open — message dropped');
    return false;
  }

  disconnect(): void {
    this.disposed = true;
    this.cancelRetry();
    if (this.ws) {
      this.ws.close(1000, 'Extension closing');
      this.ws = null;
    }
    this.setState('disconnected');
    this.activeTarget = null;
  }

  switchTarget(target: 'local' | 'cloud'): void {
    this.disconnect();
    this.disposed = false;

    const config = vscode.workspace.getConfiguration('sovereignSanctuary');
    const url = target === 'local'
      ? config.get<string>('bridgeLocalUrl', 'ws://localhost:8765/ws')
      : config.get<string>('bridgeCloudUrl', 'wss://api.sovereignsanctuary.net/ws');

    this.connectTo(url, target);
  }

  private async tryConnect(url: string, target: 'local' | 'cloud', timeoutMs: number): Promise<boolean> {
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        ws.close();
        resolve(false);
      }, timeoutMs);

      const ws = new WebSocket(url);

      ws.on('open', () => {
        clearTimeout(timer);
        ws.close(1000, 'Probe successful');
        resolve(true);
        this.connectTo(url, target);
      });

      ws.on('error', () => {
        clearTimeout(timer);
        resolve(false);
      });
    });
  }

  private async connectTo(url: string, target: 'local' | 'cloud'): Promise<void> {
    this.cleanup();
    this.activeTarget = target;
    this.setState('connecting');

    try {
      this.ws = new WebSocket(url);

      this.ws.on('open', () => {
        this.retryAttempt = 0;
        this.setState('connected');
        this.emit('bridge_connected', target);
      });

      this.ws.on('message', (raw: WebSocket.Data) => {
        try {
          const msg = JSON.parse(raw.toString()) as InboundMessage;
          this.handleMessage(msg);
        } catch {
          // malformed JSON — ignore
        }
      });

      this.ws.on('close', (code: number) => {
        if (!this.disposed) {
          this.setState('disconnected');
          this.emit('bridge_disconnected', code);
          this.scheduleReconnect();
        }
      });

      this.ws.on('error', (err: Error) => {
        this.emit('bridge_error', err.message);
      });
    } catch (err) {
      this.setState('disconnected');
      this.scheduleReconnect();
    }
  }

  private handleMessage(msg: InboundMessage): void {
    switch (msg.type) {
      case 'connected':
        this.emit('bridge_ready');
        break;

      case 'login_success': {
        const loginMsg = msg as InboundLoginSuccess;
        const profile = loginMsg.profile || {};
        this.credentials = {
          token: loginMsg.token || (profile.token as string) || '',
          hardware_id: loginMsg.hardware_id || (profile.hardware_id as string) || '',
          username: loginMsg.username || (profile.username as string) || '',
          role: loginMsg.role || (profile.role as string) || '',
        };
        this.setState('authenticated');
        this.emit('login_success', this.credentials);
        break;
      }

      case 'auth_success': {
        const authMsg = msg as InboundAuthSuccess;
        const profile = authMsg.profile || {};
        if (profile.hardware_id && profile.username) {
          this.credentials = {
            token: this.credentials?.token || '',
            hardware_id: profile.hardware_id as string,
            username: profile.username as string,
            role: (profile.role as string) || this.credentials?.role || '',
          };
        }
        this.setState('authenticated');
        this.emit('login_success', this.credentials);
        break;
      }

      case 'login_failed': {
        const failMsg = msg as InboundLoginFailed;
        this.setState('connected');
        this.emit('login_failed', failMsg.message || failMsg.error || 'Login failed');
        break;
      }

      case 'auth_failed': {
        const authFailMsg = msg as InboundAuthFailed;
        this.credentials = null;
        this.setState('connected');
        this.emit('auth_failed', authFailMsg.message || authFailMsg.error || 'Token expired');
        break;
      }

      case 'nate_cli_chat_chunk':
        this.emit('cli_chunk', msg);
        break;

      case 'nate_cli_chat_tool':
        this.emit('cli_tool', msg);
        break;

      case 'nate_cli_chat_status':
        this.emit('cli_status', msg);
        break;

      case 'nate_cli_chat_output':
        this.emit('cli_output', msg);
        break;

      case 'nate_cli_chat_done':
        this.emit('cli_done', msg);
        break;

      case 'nate_cli_models':
        this.emit('cli_models', msg);
        break;

      case 'nate_cli_models_error':
        this.emit('cli_models_error', msg);
        break;

      case 'tool_call_request':
        this.emit('tool_call_request', msg as InboundToolCallRequest);
        break;

      case 'workspace_provider_registered':
        this.emit('workspace_registered', msg);
        break;

      case 'tool_call_cancel':
        this.emit('tool_call_cancel', msg as InboundToolCallCancel);
        break;

      case 'workspace_provider_replaced':
        this.emit('workspace_provider_replaced', msg as InboundWorkspaceProviderReplaced);
        break;

      case 'workspace_provider_available':
        this.emit('workspace_provider_available', msg);
        break;

      case 'build_status':
        this.emit('build_status', msg);
        break;

      case 'build_verify_request':
        this.emit('build_verify_request', msg);
        break;

      case 'build_verify_result':
        this.emit('build_verify_result', msg);
        break;

      case 'build_promote_green':
        this.emit('build_promote_green', msg);
        break;

      case 'build_promote_complete':
        this.emit('build_promote_complete', msg);
        break;

      case 'build_rollback':
        this.emit('build_rollback', msg);
        break;

      case 'health_status':
        this.emit('health_status', msg);
        break;

      case 'ask_user_prompt':
        this.emit('ask_user_prompt', msg);
        break;

      default:
        this.emit('unknown_message', msg);
    }
  }

  private scheduleReconnect(): void {
    if (this.disposed || this.retryTimer) { return; }

    const attempt = Math.min(this.retryAttempt, 10);
    const baseMs = Math.min(1000 * Math.pow(2, attempt), 30000);
    const jitter = Math.floor(baseMs * 0.2 * Math.random());
    this.retryAttempt++;

    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      if (this.disposed) { return; }

      if (this.configuredMode === 'auto') {
        this.connect(this.credentials ?? undefined);
        return;
      }

      if (this.activeTarget) {
        const config = vscode.workspace.getConfiguration('sovereignSanctuary');
        const url = this.activeTarget === 'local'
          ? config.get<string>('bridgeLocalUrl', 'ws://localhost:8765/ws')
          : config.get<string>('bridgeCloudUrl', 'wss://api.sovereignsanctuary.net/ws');
        this.connectTo(url!, this.activeTarget);
      }
    }, baseMs + jitter);
  }

  private cancelRetry(): void {
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
  }

  private cleanup(): void {
    this.cancelRetry();
    if (this.ws) {
      this.ws.removeAllListeners();
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close(1000);
      }
      this.ws = null;
    }
  }

  private setState(newState: ConnectionState): void {
    if (this.state !== newState) {
      this.state = newState;
      this.emit('state_changed', newState);
    }
  }

  dispose(): void {
    this.disconnect();
    this.removeAllListeners();
  }
}
