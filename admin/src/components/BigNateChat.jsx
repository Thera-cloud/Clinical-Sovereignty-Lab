/**
 * BigNateChat — 8-mode conversation interface for Sovereign Command.
 * Unified backend: POST /api/skyeye/chat, GET /api/skyeye/chat for persistent history.
 *
 * Modes: strategy, command, briefing, inquiry, swarm, marketing, defense, admin
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
  { id: 'strategy', label: 'Strategy', desc: 'Collaborative strategy', color: colors.green },
  { id: 'command', label: 'Command', desc: 'Direct swarm directives', color: colors.blue },
  { id: 'briefing', label: 'Briefing', desc: 'Synthesized intelligence', color: colors.purple },
  { id: 'inquiry', label: 'Inquiry', desc: 'Data questions', color: colors.blue },
  { id: 'swarm', label: 'Swarm', desc: 'Real-time oversight', color: colors.gold },
  { id: 'marketing', label: 'Marketing', desc: 'Campaigns, playbook, funnel', color: colors.orange },
  { id: 'defense', label: 'Defense', desc: 'Hive Defense, threats', color: colors.red },
  { id: 'admin', label: 'Admin', desc: 'Users, billing, audit', color: colors.gold },
];

const MODE_COLOR_MAP = MODES.reduce((acc, m) => { acc[m.id] = m.color; return acc; }, {});

function getModeColor(modeId) {
  return MODE_COLOR_MAP[modeId] || colors.green;
}

export default function BigNateChat() {
  const [mode, setMode] = useState('strategy');
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const chatEndRef = useRef(null);

  const loadHistory = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/skyeye/chat?limit=50`);
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

  async function handleSend() {
    const content = input.trim();
    if (!content || loading) return;

    setMessages((m) => [...m, { role: 'user', mode, content }]);
    setInput('');
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
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          mode: data.mode || mode,
          content: text,
          followUp: data.follow_up_suggestions,
        },
      ]);
    } catch (err) {
      setError(err.message || 'Failed to send');
      setMessages((m) => [...m, { role: 'assistant', error: true, content: err.message }]);
    } finally {
      setLoading(false);
    }
  }

  function handleFollowUp(suggestion) {
    setInput(suggestion);
  }

  function getSidePanelContent() {
    const modeObj = MODES.find((m) => m.id === mode);
    const desc = modeObj ? modeObj.desc : '';

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
        <div style={{ fontSize: 13, fontWeight: 600, color: getModeColor(mode), marginBottom: 8 }}>
          {modeObj?.label || mode}
        </div>
        <div style={{ fontSize: 12, color: colors.textSecondary, lineHeight: 1.6 }}>
          {panels[mode] || desc}
        </div>
      </div>
    );
  }

  const dividerIdx = 5;

  return (
    <div style={{ padding: 24, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <h2 style={{ color: colors.gold, marginBottom: 24 }}>Big Nate Chat</h2>

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
                <div style={{ fontSize: 28, marginBottom: 12 }}>💬</div>
                <div style={{ fontSize: 14, marginBottom: 4 }}>Big Nate ↔ Little Nate</div>
                <div style={{ fontSize: 12 }}>Select a mode and send a message to start</div>
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
                    background: msg.role === 'user' ? colors.cyanDim : colors.bgElevated,
                    borderRadius: 8,
                    borderLeft: `4px solid ${msg.role === 'user' ? colors.cyan : msg.error ? colors.red : msgModeColor}`,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 10, color: colors.textSecondary }}>
                      {msg.role === 'user' ? 'You' : 'Nate'}
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
              placeholder="Type a message..."
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
              onClick={handleSend}
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
            Context — {mode}
          </div>
          {getSidePanelContent()}
        </div>
      </div>
    </div>
  );
}
