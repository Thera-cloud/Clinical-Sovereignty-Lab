/**
 * BigNateChat — 8-mode command execution interface for Sovereign Command.
 * Unified backend: POST /api/skyeye/chat, GET /api/skyeye/chat for persistent history.
 * POST /api/skyeye/chat/execute for confirmed actions.
 *
 * Features:
 * - 8 command modes (strategy, command, briefing, inquiry, swarm, marketing, defense, admin)
 * - Action confirmation cards with Execute/Cancel
 * - Quick action buttons per mode
 * - Structured data display for metrics/tables
 * - Real-time status indicators in side panel
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';

const API_BASE = process.env.REACT_APP_API_BASE_URL || window.location.origin.replace(':3000', ':8000');

const colors = {
  bgDark: '#0A0A0A',
  bgCard: '#111111',
  bgElevated: '#1A1A1A',
  border: '#252525',
  gold: '#C9A962',
  goldDim: 'rgba(201, 169, 98, 0.2)',
  red: '#EF4444',
  redDim: 'rgba(239, 68, 68, 0.15)',
  green: '#00E5A0',
  greenDim: 'rgba(0, 229, 160, 0.12)',
  orange: '#FF9500',
  orangeDim: 'rgba(255, 149, 0, 0.12)',
  cyan: '#4ECDC4',
  cyanDim: 'rgba(78, 205, 196, 0.1)',
  purple: '#9D4EDD',
  purpleDim: 'rgba(157, 78, 221, 0.15)',
  blue: '#38BDF8',
  blueDim: 'rgba(56, 189, 248, 0.12)',
  textPrimary: '#FFFFFF',
  textSecondary: '#888888',
};

const MODES = [
  { id: 'strategy', label: 'Strategy', icon: '\u2693', desc: 'Collaborative strategy', color: colors.green },
  { id: 'command', label: 'Command', icon: '\u26A1', desc: 'Direct swarm directives', color: colors.blue },
  { id: 'briefing', label: 'Briefing', icon: '\uD83D\uDCCB', desc: 'Synthesized intelligence', color: colors.purple },
  { id: 'inquiry', label: 'Inquiry', icon: '\uD83D\uDD0D', desc: 'Data questions', color: colors.blue },
  { id: 'swarm', label: 'Swarm', icon: '\uD83D\uDC1D', desc: 'Real-time oversight', color: colors.gold },
  { id: 'marketing', label: 'Marketing', icon: '\uD83D\uDCE3', desc: 'Campaigns, playbook, funnel', color: colors.orange },
  { id: 'defense', label: 'Defense', icon: '\uD83D\uDEE1\uFE0F', desc: 'Hive Defense, threats', color: colors.red },
  { id: 'admin', label: 'Admin', icon: '\u2699\uFE0F', desc: 'Users, billing, audit', color: colors.gold },
];

const MODE_COLOR_MAP = MODES.reduce((acc, m) => { acc[m.id] = m.color; return acc; }, {});

function getModeColor(modeId) {
  return MODE_COLOR_MAP[modeId] || colors.green;
}

const QUICK_ACTIONS = {
  strategy: [
    { label: 'Review Standing Orders', msg: 'Review current standing orders' },
    { label: 'Propose Campaign', msg: 'Propose a new content campaign' },
    { label: 'Performance Review', msg: 'How are we performing this week?' },
  ],
  command: [
    { label: 'Show Pending', msg: 'Show pending commands' },
    { label: 'Approve Latest', msg: 'Approve latest proposal' },
    { label: 'Reject Latest', msg: 'Reject latest proposal' },
  ],
  briefing: [
    { label: 'Full Briefing', msg: 'Give me a full sovereign briefing' },
    { label: 'Coherence Trends', msg: 'Deep dive into coherence trends' },
    { label: 'Foresight Alerts', msg: 'Expand on foresight alerts' },
  ],
  inquiry: [
    { label: 'TikTok Stats', msg: 'Show me TikTok performance' },
    { label: 'New Prospects', msg: 'How many new prospects this week?' },
    { label: 'Conversion Rate', msg: "What's our conversion rate?" },
  ],
  swarm: [
    { label: 'Fibre Inventory', msg: 'Show fibre inventory' },
    { label: 'Mesh Health', msg: 'Show mesh health status' },
    { label: 'Convergence', msg: 'Show convergence alerts' },
  ],
  marketing: [
    { label: 'Review Playbook', msg: 'Review the playbook' },
    { label: 'Funnel Stats', msg: 'Show funnel stats' },
    { label: 'Pending Campaigns', msg: 'What campaigns are pending?' },
    { label: 'Design Campaign', msg: 'Design a new campaign about ' },
  ],
  defense: [
    { label: 'Threat Scan', msg: 'Run a full threat scan' },
    { label: 'Hive Status', msg: 'Check hive defense status' },
    { label: 'Guardian Fibre', msg: 'Check guardian fibre status' },
    { label: 'Webhook Fortress', msg: 'Check webhook fortress status' },
  ],
  admin: [
    { label: 'User Stats', msg: 'Show all users' },
    { label: 'Revenue Report', msg: 'Show revenue stats' },
    { label: 'Audit Log', msg: 'Show audit log' },
    { label: 'System Health', msg: 'Check system health' },
  ],
};

/* Render structured data as cards instead of raw JSON */
function StructuredDataCard({ data, type, color }) {
  if (!data) return null;
  const c = color || colors.gold;

  if (type === 'user_list' && data.users) {
    return (
      <div style={{ marginTop: 8 }}>
        <div style={{ fontSize: 10, color: c, marginBottom: 6, fontWeight: 700 }}>
          USERS ({data.count || data.users.length})
        </div>
        <div style={{ display: 'grid', gap: 4 }}>
          {data.users.slice(0, 15).map((u, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, fontSize: 11, padding: '4px 8px', background: colors.bgDark, borderRadius: 4 }}>
              <span style={{ color: colors.textPrimary, minWidth: 80 }}>{u.username || u.email || `#${u.id}`}</span>
              <span style={{ color: colors.textSecondary }}>{u.role}</span>
              <span style={{ color: c }}>{u.tier || '-'}</span>
              <span style={{ color: u.status === 'active' ? colors.green : colors.red, marginLeft: 'auto' }}>{u.status}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (type === 'audit_log' && data.entries) {
    return (
      <div style={{ marginTop: 8 }}>
        <div style={{ fontSize: 10, color: c, marginBottom: 6, fontWeight: 700 }}>AUDIT LOG</div>
        {data.entries.slice(0, 10).map((e, i) => (
          <div key={i} style={{ fontSize: 11, padding: '4px 8px', background: colors.bgDark, borderRadius: 4, marginBottom: 2 }}>
            <span style={{ color: c }}>{e.action}</span>
            <span style={{ color: colors.textSecondary }}> on {e.target_type} </span>
            <span style={{ color: colors.textSecondary, fontSize: 9 }}>{e.at}</span>
          </div>
        ))}
      </div>
    );
  }

  if (type === 'threat_scan' && data.services) {
    return (
      <div style={{ marginTop: 8 }}>
        <div style={{ fontSize: 10, color: c, marginBottom: 6, fontWeight: 700 }}>
          THREAT SCAN — {data.threats_found} threats found
        </div>
        {data.services.map((s, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, fontSize: 11, padding: '4px 8px', background: colors.bgDark, borderRadius: 4, marginBottom: 2 }}>
            <span style={{ color: s.status === 'healthy' ? colors.green : colors.red }}>
              {s.status === 'healthy' ? '\u25CF' : '\u25CF'}
            </span>
            <span style={{ color: colors.textPrimary }}>{s.name}</span>
            <span style={{ color: s.status === 'healthy' ? colors.green : colors.red, marginLeft: 'auto' }}>{s.status}</span>
          </div>
        ))}
      </div>
    );
  }

  if (type === 'fibre_inventory' && data.fibres) {
    return (
      <div style={{ marginTop: 8 }}>
        <div style={{ fontSize: 10, color: c, marginBottom: 6, fontWeight: 700 }}>
          FIBRE INVENTORY ({data.count})
        </div>
        {data.fibres.slice(0, 10).map((f, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, fontSize: 11, padding: '4px 8px', background: colors.bgDark, borderRadius: 4, marginBottom: 2 }}>
            <span style={{ color: colors.textPrimary }}>{f.name || `Fibre ${i}`}</span>
            <span style={{ color: colors.textSecondary }}>{f.type}</span>
            <span style={{ color: f.status === 'active' ? colors.green : colors.orange, marginLeft: 'auto' }}>{f.status}</span>
          </div>
        ))}
      </div>
    );
  }

  // Generic key-value display
  if (typeof data === 'object' && !Array.isArray(data)) {
    const entries = Object.entries(data).filter(([, v]) => v !== null && v !== undefined);
    if (entries.length > 0 && entries.length <= 20) {
      return (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10, color: c, marginBottom: 6, fontWeight: 700 }}>
            {(type || 'DATA').toUpperCase().replace(/_/g, ' ')}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 12px', fontSize: 11 }}>
            {entries.map(([k, v], i) => (
              <React.Fragment key={i}>
                <span style={{ color: colors.textSecondary }}>{k.replace(/_/g, ' ')}</span>
                <span style={{ color: colors.textPrimary }}>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
              </React.Fragment>
            ))}
          </div>
        </div>
      );
    }
  }

  return null;
}

/* Action confirmation card */
function ActionCard({ action, onExecute, onCancel, executing }) {
  const c = getModeColor(action.mode);
  return (
    <div style={{
      margin: '8px 0',
      padding: 12,
      background: `${c}10`,
      border: `1px solid ${c}40`,
      borderRadius: 8,
      borderLeft: `4px solid ${c}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: c, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          {action.mode} Action
        </span>
        <span style={{ fontSize: 10, color: colors.textSecondary }}>
          requires confirmation
        </span>
      </div>
      <div style={{ fontSize: 12, color: colors.textPrimary, marginBottom: 4 }}>
        {action.description}
      </div>
      {action.params && Object.keys(action.params).length > 0 && (
        <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 8 }}>
          {Object.entries(action.params).map(([k, v]) => v ? `${k}: ${v}` : '').filter(Boolean).join(' | ')}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={() => onExecute(action.action_id)}
          disabled={executing}
          style={{
            padding: '6px 16px', borderRadius: 6, fontSize: 11, fontWeight: 600, cursor: 'pointer',
            background: c, color: '#000', border: 'none', opacity: executing ? 0.5 : 1,
          }}
        >
          {executing ? 'Executing...' : 'Execute'}
        </button>
        <button
          onClick={() => onCancel(action.action_id)}
          disabled={executing}
          style={{
            padding: '6px 16px', borderRadius: 6, fontSize: 11, fontWeight: 600, cursor: 'pointer',
            background: 'transparent', color: colors.textSecondary, border: `1px solid ${colors.border}`,
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export default function BigNateChat() {
  const [mode, setMode] = useState('strategy');
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [pendingActions, setPendingActions] = useState([]);
  const [executingAction, setExecutingAction] = useState(null);
  const [modeStatus, setModeStatus] = useState({});
  const chatEndRef = useRef(null);

  const loadHistory = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/skyeye/chat?limit=500`);
      if (!res.ok) throw new Error('Failed to load history');
      const data = await res.json();
      if (data && data.length > 0) {
        setMessages(data.map((m) => {
          const sender = (m.sender || '').toLowerCase();
          const isBig = sender.includes('big') || sender === 'user' || sender === 'admin';
          const meta = m.metadata || {};
          return {
            role: isBig ? 'user' : 'assistant',
            mode: meta.mode || '',
            content: m.message || m.content || '',
          };
        }));
      }
    } catch {
      // History load failure is non-critical
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function handleSend(overrideMsg) {
    const content = (overrideMsg || input).trim();
    if (!content || loading) return;

    setMessages((m) => [...m, { role: 'user', mode, content }]);
    if (!overrideMsg) setInput('');
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/api/skyeye/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: content, mode }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Request failed');

      const reply = data.message || data.response || data.content || data.text || '';
      const text = typeof reply === 'object' ? JSON.stringify(reply, null, 2) : String(reply);

      // Collect executed results for structured display
      const executedResults = data.executed_results || [];
      const newPending = data.pending_actions || [];

      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          mode: data.mode || mode,
          content: text,
          followUp: data.follow_up_suggestions,
          executedResults,
        },
      ]);

      if (newPending.length > 0) {
        setPendingActions((prev) => [...prev, ...newPending]);
      }

      // Update mode status with any executed data
      if (executedResults.length > 0) {
        const latest = executedResults[executedResults.length - 1];
        setModeStatus((prev) => ({ ...prev, [data.mode || mode]: latest }));
      }
    } catch (err) {
      setError(err.message || 'Failed to send');
      setMessages((m) => [...m, { role: 'assistant', error: true, content: err.message }]);
    } finally {
      setLoading(false);
    }
  }

  async function handleExecuteAction(actionId) {
    setExecutingAction(actionId);
    try {
      const res = await fetch(`${API_BASE}/api/skyeye/chat/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_id: actionId }),
      });
      const result = await res.json();

      setPendingActions((prev) => prev.filter((a) => a.action_id !== actionId));
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          mode,
          content: result.success
            ? `Action executed: ${result.type || 'done'}`
            : `Action failed: ${result.error || 'unknown error'}`,
          executedResults: result.success ? [result] : [],
          isSystemAction: true,
        },
      ]);

      if (result.success) {
        setModeStatus((prev) => ({ ...prev, [mode]: result }));
      }
    } catch (err) {
      setMessages((m) => [...m, { role: 'assistant', error: true, content: `Execute failed: ${err.message}` }]);
    } finally {
      setExecutingAction(null);
    }
  }

  function handleCancelAction(actionId) {
    setPendingActions((prev) => prev.filter((a) => a.action_id !== actionId));
  }

  async function handleClearChat(archive = true) {
    const label = archive ? 'archive to memory and clear' : 'permanently clear';
    if (!window.confirm(`Are you sure you want to ${label} all chat history?`)) return;
    try {
      const res = await fetch(`${API_BASE}/api/skyeye/chat?archive=${archive}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.cleared) {
        setMessages([]);
        setPendingActions([]);
        setModeStatus({});
        alert(data.message || 'Chat cleared.');
        if (archive) loadArchives();
      }
    } catch (err) {
      alert('Failed to clear chat: ' + err.message);
    }
  }

  const [archives, setArchives] = useState([]);
  const [archivesOpen, setArchivesOpen] = useState(false);
  const [viewingArchive, setViewingArchive] = useState(null);
  const [archiveTranscript, setArchiveTranscript] = useState('');

  const loadArchives = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/skyeye/chat/archives`);
      if (res.ok) {
        const data = await res.json();
        setArchives(data || []);
      }
    } catch {}
  }, []);

  async function viewArchiveDetail(entryId) {
    try {
      const res = await fetch(`${API_BASE}/api/skyeye/chat/archives/${entryId}`);
      const data = await res.json();
      setViewingArchive(data);
      setArchiveTranscript(data.transcript || '');
    } catch (err) {
      alert('Failed to load archive: ' + err.message);
    }
  }

  async function restoreArchive(entryId) {
    if (!window.confirm('Restore this archived conversation into the active chat?')) return;
    try {
      const res = await fetch(`${API_BASE}/api/skyeye/chat/archives/${entryId}/restore`, { method: 'POST' });
      const data = await res.json();
      alert(data.message || 'Restored.');
      setViewingArchive(null);
      loadHistory();
    } catch (err) {
      alert('Failed to restore: ' + err.message);
    }
  }

  function handleFollowUp(suggestion) {
    setInput(suggestion);
  }

  function handleQuickAction(msg) {
    if (msg.endsWith(' ')) {
      setInput(msg);
    } else {
      handleSend(msg);
    }
  }

  function getSidePanelContent() {
    const modeObj = MODES.find((m) => m.id === mode);
    const desc = modeObj ? modeObj.desc : '';
    const c = getModeColor(mode);
    const status = modeStatus[mode];

    const panels = {
      strategy: 'Brainstorm content strategy, propose campaigns, discuss performance. Nate proactively brings insights from Marketing Intelligence.',
      command: 'Approve or reject pending proposals. Say "approved", "go for it", "reject", or "hold" to control the execution pipeline.',
      briefing: 'Request a structured sovereign briefing pulling from all 6 strategic memory layers: Standing Orders, Insights, Proposals, Coherence, Foresight, Swarm.',
      inquiry: 'Ask data questions: "How many prospects?", "What\'s our TikTok doing?", "Show me conversion rates." Returns structured data with context.',
      swarm: 'View active Fibre inventory, Wisdom Mesh health, convergence alerts. Spawn or prune Fibres with approval.',
      marketing: 'Full marketing authority. Review the playbook, pending campaigns, funnel stats, content pillars, audience targeting, and content mix.',
      defense: 'Full defense authority. Hive Defense v4 service readiness, active threat alerts, Guardian Fibre status, webhook fortress integrity.',
      admin: 'Full administration overview. User stats by role/tier, subscription billing, MRR, churn, audit log entries, system health.',
    };

    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <span style={{ fontSize: 16 }}>{modeObj?.icon}</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: c }}>{modeObj?.label || mode}</span>
        </div>
        <div style={{ fontSize: 11, color: colors.textSecondary, lineHeight: 1.6, marginBottom: 16 }}>
          {panels[mode] || desc}
        </div>

        {/* Real-time status indicator */}
        {status && status.success && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 10, color: c, fontWeight: 700, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              Latest Status
            </div>
            <div style={{ padding: 8, background: colors.bgElevated, borderRadius: 6, border: `1px solid ${colors.border}` }}>
              <div style={{ fontSize: 11, color: colors.green, marginBottom: 4 }}>
                {'\u25CF'} {(status.type || '').replace(/_/g, ' ')}
              </div>
              {status.data && typeof status.data === 'object' && (
                <div style={{ fontSize: 10, color: colors.textSecondary }}>
                  {Object.entries(status.data).slice(0, 3).map(([k, v]) => (
                    <div key={k}>{k.replace(/_/g, ' ')}: {typeof v === 'object' ? JSON.stringify(v).slice(0, 40) : String(v)}</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Quick Actions */}
        <div style={{ fontSize: 10, color: c, fontWeight: 700, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          Quick Actions
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {(QUICK_ACTIONS[mode] || []).map((qa, i) => (
            <button
              key={i}
              onClick={() => handleQuickAction(qa.msg)}
              style={{
                padding: '6px 10px',
                borderRadius: 6,
                fontSize: 10,
                fontWeight: 500,
                cursor: 'pointer',
                border: `1px solid ${colors.border}`,
                background: colors.bgElevated,
                color: colors.textSecondary,
                textAlign: 'left',
                transition: 'all 0.15s',
              }}
              onMouseEnter={(e) => { e.target.style.borderColor = c; e.target.style.color = c; }}
              onMouseLeave={(e) => { e.target.style.borderColor = colors.border; e.target.style.color = colors.textSecondary; }}
            >
              {qa.label}
            </button>
          ))}
        </div>

        {/* Archive Browser */}
        <div style={{ marginTop: 20, borderTop: `1px solid ${colors.border}`, paddingTop: 12 }}>
          <button
            onClick={() => { setArchivesOpen(!archivesOpen); if (!archivesOpen) loadArchives(); }}
            style={{
              width: '100%', padding: '8px 10px', borderRadius: 6, fontSize: 10, fontWeight: 700,
              cursor: 'pointer', border: `1px solid ${colors.gold}`, textAlign: 'left',
              background: archivesOpen ? `${colors.gold}30` : colors.bgElevated,
              color: colors.gold, letterSpacing: 0.5, textTransform: 'uppercase',
            }}
          >
            {'\uD83D\uDCC2'} Archived Sessions {archivesOpen ? '\u25B2' : '\u25BC'}
          </button>

          {archivesOpen && !viewingArchive && (
            <div style={{ marginTop: 8, maxHeight: 280, overflowY: 'auto' }}>
              {archives.length === 0 ? (
                <div style={{ fontSize: 10, color: colors.textSecondary, padding: 12, textAlign: 'center' }}>
                  No archives yet. Use "Archive & Clear" to save sessions.
                </div>
              ) : archives.map((a) => {
                const d = a.created_at ? new Date(a.created_at) : null;
                const dateStr = d ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '?';
                return (
                  <div
                    key={a.entry_id}
                    onClick={() => viewArchiveDetail(a.entry_id)}
                    style={{
                      padding: '8px 10px', marginBottom: 4, borderRadius: 6, cursor: 'pointer',
                      border: `1px solid ${colors.border}`, background: colors.bgElevated,
                      transition: 'border-color 0.15s',
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.borderColor = colors.gold}
                    onMouseLeave={(e) => e.currentTarget.style.borderColor = colors.border}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                      <span style={{ color: colors.gold, fontWeight: 600 }}>{dateStr}</span>
                      <span style={{ color: colors.textSecondary, fontSize: 9 }}>{a.message_count || 0} msgs</span>
                    </div>
                    <div style={{ fontSize: 9, color: colors.textSecondary, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {(a.preview || '').substring(0, 80)}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {archivesOpen && viewingArchive && (
            <div style={{ marginTop: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: colors.gold }}>
                  {viewingArchive.created_at ? new Date(viewingArchive.created_at).toLocaleDateString() : 'Archive'}
                </span>
                <button onClick={() => setViewingArchive(null)} style={{ background: 'none', border: 'none', color: colors.textSecondary, cursor: 'pointer', fontSize: 10 }}>{'\u2190'} Back</button>
              </div>
              <div style={{
                maxHeight: 200, overflowY: 'auto', fontSize: 10, lineHeight: 1.6,
                color: colors.textPrimary, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                background: colors.bgDark, borderRadius: 6, padding: 10,
                border: `1px solid ${colors.border}`,
              }}>
                {archiveTranscript}
              </div>
              <button
                onClick={() => restoreArchive(viewingArchive.entry_id)}
                style={{
                  marginTop: 6, width: '100%', padding: '7px 10px', borderRadius: 6, fontSize: 10, fontWeight: 600,
                  cursor: 'pointer', border: `1px solid ${colors.green}`, background: `${colors.green}18`, color: colors.green,
                }}
              >
                {'\u21A9'} Restore This Conversation
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  const dividerIdx = 5;

  return (
    <div style={{ padding: 24, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <h2 style={{ color: colors.gold, margin: 0 }}>Big Nate Chat</h2>
        <span style={{ fontSize: 10, color: colors.green, background: colors.greenDim, padding: '3px 10px', borderRadius: 10, fontWeight: 600 }}>
          {'\u25CF'} Connected
        </span>
        {pendingActions.length > 0 && (
          <span style={{ fontSize: 10, color: colors.orange, background: colors.orangeDim, padding: '3px 10px', borderRadius: 10, fontWeight: 600 }}>
            {pendingActions.length} pending action{pendingActions.length > 1 ? 's' : ''}
          </span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button
            onClick={() => handleClearChat(true)}
            title="Archive chat to strategic memory and start fresh"
            style={{
              padding: '5px 12px', fontSize: 10, fontWeight: 600, cursor: 'pointer',
              background: colors.purpleDim, border: `1px solid ${colors.purple}`,
              color: colors.purple, borderRadius: 8,
            }}
          >
            Archive & Clear
          </button>
          <button
            onClick={() => handleClearChat(false)}
            title="Clear chat without archiving"
            style={{
              padding: '5px 12px', fontSize: 10, fontWeight: 600, cursor: 'pointer',
              background: colors.redDim, border: `1px solid ${colors.red}`,
              color: colors.red, borderRadius: 8,
            }}
          >
            Clear Chat
          </button>
        </div>
      </div>

      {/* Mode selector */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        {MODES.map((m, i) => (
          <React.Fragment key={m.id}>
            {i === dividerIdx && (
              <span style={{ width: 1, height: 24, background: colors.border, flexShrink: 0 }} />
            )}
            <button
              onClick={() => setMode(m.id)}
              title={m.desc}
              style={{
                padding: '8px 14px',
                background: mode === m.id ? `${m.color}20` : colors.bgCard,
                border: `1px solid ${mode === m.id ? m.color : colors.border}`,
                color: mode === m.id ? m.color : colors.textSecondary,
                borderRadius: 20,
                fontSize: 11,
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            >
              <span style={{ marginRight: 4 }}>{m.icon}</span>
              {m.label}
            </button>
          </React.Fragment>
        ))}
      </div>

      <div style={{ flex: 1, display: 'flex', gap: 24, minHeight: 0 }}>
        {/* Chat + input */}
        <div style={{ flex: 2, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              background: colors.bgCard,
              border: `1px solid ${colors.border}`,
              borderRadius: 8,
              padding: 16,
              marginBottom: 16,
            }}
          >
            {loading && messages.length === 0 && (
              <div style={{ color: colors.textSecondary }}>Loading chat history...</div>
            )}
            {!loading && messages.length === 0 && (
              <div style={{ textAlign: 'center', padding: 40, color: colors.textSecondary }}>
                <div style={{ fontSize: 28, marginBottom: 12 }}>{'\uD83D\uDCAC'}</div>
                <div style={{ fontSize: 14, marginBottom: 4 }}>Big Nate {'\u2194'} Little Nate</div>
                <div style={{ fontSize: 12, marginBottom: 16 }}>Select a mode and send a message to start</div>
                <div style={{ fontSize: 11 }}>Use quick actions in the side panel or type a command</div>
              </div>
            )}
            {messages.map((msg, i) => {
              const msgModeColor = getModeColor(msg.mode);
              return (
                <div
                  key={i}
                  style={{
                    marginBottom: 12,
                    padding: 12,
                    background: msg.isSystemAction
                      ? `${msgModeColor}08`
                      : msg.role === 'user'
                        ? colors.cyanDim
                        : colors.bgElevated,
                    borderRadius: 8,
                    borderLeft: `4px solid ${msg.role === 'user' ? colors.cyan : msg.error ? colors.red : msgModeColor}`,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 10, color: colors.textSecondary }}>
                      {msg.isSystemAction ? 'System' : msg.role === 'user' ? 'You' : 'Nate'}
                    </span>
                    {msg.mode && (
                      <span
                        style={{
                          fontSize: 9,
                          fontWeight: 700,
                          padding: '2px 8px',
                          borderRadius: 10,
                          background: `${msgModeColor}20`,
                          color: msgModeColor,
                          textTransform: 'uppercase',
                          letterSpacing: 0.5,
                        }}
                      >
                        {msg.mode}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                    {msg.content}
                  </div>

                  {/* Structured data display for executed results */}
                  {msg.executedResults && msg.executedResults.length > 0 && msg.executedResults.map((r, ri) => (
                    <StructuredDataCard key={ri} data={r.data} type={r.type} color={msgModeColor} />
                  ))}

                  {msg.followUp && msg.followUp.length > 0 && (
                    <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                      {msg.followUp.map((s, j) => (
                        <button
                          key={j}
                          onClick={() => handleFollowUp(s)}
                          style={{
                            padding: '4px 10px',
                            borderRadius: 12,
                            fontSize: 10,
                            fontWeight: 500,
                            cursor: 'pointer',
                            border: `1px solid ${colors.greenDim}`,
                            background: 'rgba(0,229,160,0.06)',
                            color: colors.green,
                          }}
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Pending action confirmation cards */}
            {pendingActions.map((action) => (
              <ActionCard
                key={action.action_id}
                action={action}
                onExecute={handleExecuteAction}
                onCancel={handleCancelAction}
                executing={executingAction === action.action_id}
              />
            ))}

            <div ref={chatEndRef} />
          </div>

          {error && (
            <div style={{ marginBottom: 8, padding: 8, background: colors.redDim, borderRadius: 8, color: colors.red, fontSize: 12 }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: 8 }}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
              placeholder={`Type a ${mode} command...`}
              disabled={loading}
              style={{
                flex: 1,
                padding: '12px 16px',
                background: colors.bgElevated,
                border: `1px solid ${colors.border}`,
                borderRadius: 8,
                color: colors.textPrimary,
                fontSize: 12,
              }}
            />
            <button
              onClick={() => handleSend()}
              disabled={loading || !input.trim()}
              style={{
                padding: '12px 24px',
                background: colors.goldDim,
                border: `1px solid ${colors.gold}`,
                color: colors.gold,
                borderRadius: 8,
                fontSize: 12,
                fontWeight: 600,
                cursor: loading ? 'not-allowed' : 'pointer',
                opacity: loading || !input.trim() ? 0.5 : 1,
              }}
            >
              {loading ? '...' : 'Send'}
            </button>
          </div>
        </div>

        {/* Side panel */}
        <div
          style={{
            width: 280,
            background: colors.bgCard,
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            padding: 16,
            overflowY: 'auto',
          }}
        >
          <div style={{ color: colors.gold, fontSize: 11, marginBottom: 12, textTransform: 'uppercase', letterSpacing: 1 }}>
            Context {'\u2014'} {mode}
          </div>
          {getSidePanelContent()}
        </div>
      </div>
    </div>
  );
}
