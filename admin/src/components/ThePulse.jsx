/**
 * SOVEREIGN SWARM — The Pulse Dashboard (React)
 * Live coherence visualization, foresight timeline, and Swarm activity map.
 * Phase 5E.
 */

import React, { useState, useEffect, useCallback } from 'react';

const API_BASE = process.env.REACT_APP_API_BASE_URL || window.location.origin.replace(':3000', ':8000');
const POLL_INTERVAL = 30000;

/* ─── Design Tokens ─── */
const colors = {
  void: '#050505',
  chamber: '#0A0A0A',
  elevated: '#111111',
  border: '#1a1a1a',
  gold: '#C9A962',
  goldBright: '#E8D5A3',
  goldDim: '#8B7355',
  cyan: '#4ECDC4',
  purple: '#9D4EDD',
  red: '#EF4444',
  green: '#22C55E',
  text: '#E8D5A3',
  textDim: '#8B7355',
};

/* ─── Utility ─── */
function formatScore(val) {
  if (val === null || val === undefined || isNaN(val)) return '--';
  return (val * 100).toFixed(1);
}

function formatDelta(delta) {
  if (delta === null || delta === undefined) return null;
  const pct = (delta * 100).toFixed(1);
  if (delta > 0) return { text: `+${pct}%`, color: colors.green };
  if (delta < 0) return { text: `${pct}%`, color: colors.red };
  return { text: '0.0%', color: colors.textDim };
}

/* ─── Sub-components ─── */

function ScoreCard({ title, badge, badgeColor, score, color, metrics = [] }) {
  const pct = (score || 0) * 100;
  return (
    <div style={{
      background: colors.chamber,
      border: `1px solid ${colors.border}`,
      borderRadius: 10,
      padding: 24,
      transition: 'border-color 0.3s',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 15, color: colors.gold, textTransform: 'uppercase', letterSpacing: 1.5 }}>{title}</span>
        {badge && (
          <span style={{
            fontSize: 10, padding: '3px 10px', borderRadius: 20,
            background: `${badgeColor}22`, color: badgeColor,
            textTransform: 'uppercase', letterSpacing: 1,
          }}>{badge}</span>
        )}
      </div>
      <div style={{ fontSize: 36, fontWeight: 700, fontFamily: "'Cormorant Garamond', serif", color: color || colors.cyan }}>
        {formatScore(score)}
      </div>
      <div style={{ height: 4, background: colors.elevated, borderRadius: 2, margin: '12px 0', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: `linear-gradient(90deg, ${colors.goldDim}, ${color || colors.cyan})`, borderRadius: 2, transition: 'width 1s ease' }} />
      </div>
      {metrics.map(([label, value], i) => (
        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', fontSize: 12, borderBottom: i < metrics.length - 1 ? `1px solid ${colors.border}` : 'none' }}>
          <span style={{ color: colors.textDim }}>{label}</span>
          <span style={{ color: colors.text, fontWeight: 500 }}>{value}</span>
        </div>
      ))}
    </div>
  );
}

function GapVisualization({ gap }) {
  if (!gap) return <div style={{ color: colors.textDim, fontSize: 12, textAlign: 'center', padding: 20 }}>Gap analysis unavailable</div>;

  return (
    <div style={{ background: colors.chamber, border: `1px solid ${colors.border}`, borderRadius: 10, padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 15, color: colors.gold, textTransform: 'uppercase', letterSpacing: 1.5 }}>Inside / Outside Gap</span>
        <span style={{ fontSize: 10, padding: '3px 10px', borderRadius: 20, background: `${colors.cyan}22`, color: colors.cyan, textTransform: 'uppercase' }}>Cultural</span>
      </div>

      {/* Internal bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <span style={{ fontSize: 11, color: colors.textDim, minWidth: 60, textTransform: 'uppercase', letterSpacing: 1 }}>Internal</span>
        <span style={{ fontSize: 18, fontWeight: 600, color: colors.cyan, minWidth: 48, textAlign: 'right' }}>{formatScore(gap.internal_score)}</span>
        <div style={{ flex: 1, height: 24, background: colors.elevated, borderRadius: 6, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${(gap.internal_score || 0) * 100}%`, background: `linear-gradient(90deg, ${colors.cyan}, rgba(78,205,196,0.6))`, borderRadius: 6, transition: 'width 1s' }} />
        </div>
      </div>

      {/* External bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <span style={{ fontSize: 11, color: colors.textDim, minWidth: 60, textTransform: 'uppercase', letterSpacing: 1 }}>External</span>
        <span style={{ fontSize: 18, fontWeight: 600, color: colors.purple, minWidth: 48, textAlign: 'right' }}>{formatScore(gap.external_score)}</span>
        <div style={{ flex: 1, height: 24, background: colors.elevated, borderRadius: 6, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${(gap.external_score || 0) * 100}%`, background: `linear-gradient(90deg, ${colors.purple}, rgba(157,78,221,0.6))`, borderRadius: 6, transition: 'width 1s' }} />
        </div>
      </div>

      <div style={{ textAlign: 'center' }}>
        <span style={{ fontSize: 12, color: colors.textDim }}>Gap Magnitude: </span>
        <span style={{ fontSize: 16, fontWeight: 600, color: Math.abs(gap.gap_magnitude || 0) > 0.2 ? colors.red : colors.green }}>
          {gap.gap_magnitude >= 0 ? '+' : ''}{formatScore(gap.gap_magnitude)}%
        </span>
      </div>
    </div>
  );
}

/* ─── Main Component ─── */
export default function ThePulse() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchPulse = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/coherence/pulse`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPulse();
    const interval = setInterval(fetchPulse, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchPulse]);

  const layers = data?.layer_scores || {};

  return (
    <div style={{ background: colors.void, minHeight: '100vh', fontFamily: "'DM Sans', sans-serif", color: colors.text }}>
      {/* Header */}
      <div style={{ background: colors.chamber, borderBottom: `1px solid ${colors.border}`, padding: '20px 32px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 28, fontWeight: 600, color: colors.gold, letterSpacing: 2, margin: 0 }}>THE PULSE</h1>
          <div style={{ fontSize: 12, color: colors.textDim, letterSpacing: 1, textTransform: 'uppercase' }}>Sovereign Coherence Intelligence</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: error ? colors.red : colors.green, animation: 'pulse 2s infinite' }} />
          <span style={{ fontSize: 11, color: colors.textDim }}>
            {loading ? 'Loading...' : error ? `Error: ${error}` : `Updated ${new Date(data?.generated_at || Date.now()).toLocaleTimeString()}`}
          </span>
        </div>
      </div>

      {/* Dashboard Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, padding: '24px 32px', maxWidth: 1600, margin: '0 auto' }}>

        {/* Global Coherence Index */}
        <div style={{
          gridColumn: '1 / -1', background: colors.chamber,
          border: `1px solid ${colors.border}`, borderRadius: 12,
          padding: 32, textAlign: 'center', position: 'relative', overflow: 'hidden',
        }}>
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: `linear-gradient(90deg, ${colors.goldDim}, ${colors.gold}, ${colors.goldDim})` }} />
          <h2 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 14, color: colors.textDim, textTransform: 'uppercase', letterSpacing: 3, marginBottom: 12 }}>Global Coherence Index</h2>
          <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 72, fontWeight: 700, color: colors.goldBright, lineHeight: 1 }}>
            {formatScore(data?.global_coherence_index)}
          </div>
          <div style={{ fontSize: 13, color: colors.textDim, marginTop: 8 }}>
            {(data?.global_coherence_index || 0) >= 0.7 ? 'Coherence is strong across all layers' :
             (data?.global_coherence_index || 0) >= 0.4 ? 'Moderate coherence — room for growth' :
             'Measuring coherence across all layers...'}
          </div>
        </div>

        {/* Layer Cards */}
        <ScoreCard title="Individual" badge="Layer 1" badgeColor={colors.green}
          score={layers.individual} color={colors.cyan}
          metrics={[['CEE Aggregate', formatScore(layers.individual)], ['Sample', data ? 'Active' : '--']]} />

        <ScoreCard title="Family System" badge="Layer 2" badgeColor={colors.green}
          score={layers.family} color={colors.cyan}
          metrics={[['Resonance', formatScore(layers.family)], ['Families', 'Active']]} />

        <ScoreCard title="Community" badge="Layer 3" badgeColor={colors.gold}
          score={layers.community} color={colors.purple}
          metrics={[['Threshold', '50 families'], ['Status', layers.community ? 'Active' : 'Pending']]} />

        {/* Gap Analysis (spans 2 cols) */}
        <div style={{ gridColumn: 'span 2' }}>
          <GapVisualization gap={data?.gap_analysis} />
        </div>

        {/* Foresight Alerts */}
        <div style={{ background: colors.chamber, border: `1px solid ${colors.border}`, borderRadius: 10, padding: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
            <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 15, color: colors.gold, textTransform: 'uppercase', letterSpacing: 1.5 }}>Foresight Alerts</span>
            <span style={{
              fontSize: 10, padding: '3px 10px', borderRadius: 20,
              background: (data?.active_alerts || 0) > 0 ? `${colors.red}22` : `${colors.green}22`,
              color: (data?.active_alerts || 0) > 0 ? colors.red : colors.green,
            }}>{data?.active_alerts || 0}</span>
          </div>
          <div style={{ color: colors.textDim, fontSize: 12, textAlign: 'center', padding: 20 }}>
            {(data?.active_alerts || 0) > 0 ? `${data.active_alerts} active alerts` : 'No active alerts'}
          </div>
        </div>

        {/* Trending Themes (spans 2 cols) */}
        <div style={{ gridColumn: 'span 2', background: colors.chamber, border: `1px solid ${colors.border}`, borderRadius: 10, padding: 24 }}>
          <div style={{ marginBottom: 16 }}>
            <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 15, color: colors.gold, textTransform: 'uppercase', letterSpacing: 1.5 }}>Trending Themes</span>
          </div>
          <div>
            {(data?.trending_themes || []).length > 0
              ? data.trending_themes.map((t, i) => (
                  <span key={i} style={{
                    display: 'inline-block', background: colors.elevated,
                    border: `1px solid ${colors.border}`, borderRadius: 20,
                    padding: '4px 12px', fontSize: 11, color: colors.textDim, margin: '3px 4px 3px 0',
                  }}>{t}</span>
                ))
              : <span style={{ fontSize: 12, color: colors.textDim }}>No themes detected</span>
            }
          </div>
        </div>

        {/* Notable Changes */}
        <div style={{ background: colors.chamber, border: `1px solid ${colors.border}`, borderRadius: 10, padding: 24 }}>
          <div style={{ marginBottom: 16 }}>
            <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 15, color: colors.gold, textTransform: 'uppercase', letterSpacing: 1.5 }}>Notable Changes</span>
          </div>
          {(data?.notable_changes || []).length > 0
            ? data.notable_changes.map((c, i) => (
                <div key={i} style={{ padding: '8px 0', fontSize: 12, color: colors.text, borderBottom: i < data.notable_changes.length - 1 ? `1px solid ${colors.border}` : 'none' }}>{c}</div>
              ))
            : <div style={{ color: colors.textDim, fontSize: 12 }}>Monitoring for changes...</div>
          }
        </div>
      </div>
    </div>
  );
}
