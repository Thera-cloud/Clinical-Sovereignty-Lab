/**
 * QuaketeMap — Cosmic Ring health, trail map, transfers, beams, memorials dashboard.
 * Fetches from Quakete API endpoints.
 */

import React, { useState, useEffect } from 'react';
import { authFetch } from '../apiClient';

const colors = {
  bgDark: '#0A0A0A',
  bgCard: '#111111',
  bgElevated: '#1A1A1A',
  border: '#252525',
  gold: '#FFD700',
  goldDim: 'rgba(255, 215, 0, 0.2)',
  red: '#FF3B3B',
  redDim: 'rgba(255, 59, 59, 0.15)',
  green: '#00FF88',
  greenDim: 'rgba(0, 255, 136, 0.1)',
  orange: '#FF9500',
  orangeDim: 'rgba(255, 149, 0, 0.15)',
  yellow: '#FFD93D',
  cyan: '#00D4FF',
  cyanDim: 'rgba(0, 212, 255, 0.1)',
  purple: '#9D4EDD',
  textPrimary: '#FFFFFF',
  textSecondary: '#888888',
};

function getRingColor(state) {
  const s = (state || '').toLowerCase();
  if (s === 'healthy') return colors.green;
  if (s === 'supporting') return colors.yellow;
  if (s === 'strained') return colors.orange;
  if (s === 'distressed' || s === 'rescue' || s === 'broken') return colors.red;
  return colors.textSecondary;
}

function Card({ children, style = {} }) {
  return (
    <div
      style={{
        background: colors.bgCard,
        border: `1px solid ${colors.border}`,
        borderRadius: 12,
        padding: 16,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function SectionTitle({ children }) {
  return (
    <div style={{ color: colors.textSecondary, fontSize: 11, letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 12 }}>
      {children}
    </div>
  );
}

export default function QuaketeMap() {
  const [rings, setRings] = useState([]);
  const [trailMap, setTrailMap] = useState(null);
  const [transfers, setTransfers] = useState([]);
  const [beams, setBeams] = useState([]);
  const [memorials, setMemorials] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchAll() {
      setLoading(true);
      setError(null);
      try {
        const [ringsRes, trailRes, transfersRes, beamsRes, memorialsRes] = await Promise.all([
          authFetch('/api/quakete/rings'),
          authFetch('/api/quakete/trail-map'),
          authFetch('/api/quakete/transfers'),
          authFetch('/api/quakete/beams'),
          authFetch('/api/quakete/memorials'),
        ]);

        if (cancelled) return;

        const [ringsData, trailData, transfersData, beamsData, memorialsData] = await Promise.all([
          ringsRes.ok ? ringsRes.json() : [],
          trailRes.ok ? trailRes.json() : null,
          transfersRes.ok ? transfersRes.json() : [],
          beamsRes.ok ? beamsRes.json() : [],
          memorialsRes.ok ? memorialsRes.json() : [],
        ]);

        setRings(Array.isArray(ringsData) ? ringsData : []);
        setTrailMap(trailData);
        setTransfers(Array.isArray(transfersData) ? transfersData : []);
        setBeams(Array.isArray(beamsData) ? beamsData : []);
        setMemorials(Array.isArray(memorialsData) ? memorialsData : []);
      } catch (err) {
        if (!cancelled) {
          setError(err.message || 'Failed to fetch Quakete data');
          setRings([]);
          setTrailMap(null);
          setTransfers([]);
          setBeams([]);
          setMemorials([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchAll();
    return () => { cancelled = true; };
  }, []);

  // Build trail rows from rings -> cords
  const trailRows = rings.flatMap((r) =>
    (r.cords || []).map((c) => ({
      fibre_id: c.fibre_id,
      health: c.current_health ?? 0,
      mode: c.current_mode ?? '—',
      last_seen: '—',
    }))
  );

  if (loading) {
    return (
      <div style={{ padding: 24, color: colors.textSecondary }}>
        Loading Quakete data…
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <div style={{ padding: 16, background: colors.redDim, border: `1px solid ${colors.red}`, borderRadius: 8, color: colors.red }}>
          {error}
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: 24, overflowY: 'auto' }}>
      <h2 style={{ color: colors.gold, marginBottom: 24 }}>⚡ Quakete Map</h2>

      {/* 1. Ring Overview */}
      <SectionTitle>Ring Overview</SectionTitle>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 24 }}>
        {rings.length === 0 ? (
          <Card style={{ flex: 1, minWidth: 200 }}>
            <div style={{ color: colors.textSecondary }}>No rings found</div>
          </Card>
        ) : (
          rings.map((ring) => {
            const stateColor = getRingColor(ring.state);
            return (
              <Card key={ring.ring_id} style={{ flex: 1, minWidth: 200, borderLeft: `4px solid ${stateColor}` }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ color: colors.textPrimary, fontWeight: 'bold' }}>{ring.ring_id}</span>
                  <span style={{ color: stateColor, fontSize: 11, textTransform: 'uppercase' }}>{ring.state}</span>
                </div>
                <div style={{ fontSize: 11, color: colors.textSecondary }}>
                  {(ring.cords || []).length} cords • coherence {(ring.coherence ?? 0).toFixed(2)}
                </div>
              </Card>
            );
          })
        )}
      </div>

      {/* 2. Trail Map */}
      <SectionTitle>Trail Map</SectionTitle>
      <Card style={{ marginBottom: 24 }}>
        {trailMap && (
          <div style={{ display: 'flex', gap: 24, marginBottom: 16, flexWrap: 'wrap' }}>
            <span style={{ color: colors.green }}>Healthy: {trailMap.healthy ?? 0}</span>
            <span style={{ color: colors.yellow }}>Requesting: {trailMap.requesting ?? 0}</span>
            <span style={{ color: colors.cyan }}>Donating: {trailMap.donating ?? 0}</span>
            <span style={{ color: colors.orange }}>Critical: {trailMap.critical ?? 0}</span>
            <span style={{ color: colors.textSecondary }}>Silent: {trailMap.silent ?? 0}</span>
            <span style={{ color: colors.gold }}>Avg health: {(trailMap.avg_health ?? 0).toFixed(2)}</span>
          </div>
        )}
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ color: colors.textSecondary, textAlign: 'left' }}>
              <th style={{ padding: 8 }}>fibre_id</th>
              <th style={{ padding: 8 }}>health</th>
              <th style={{ padding: 8 }}>mode</th>
              <th style={{ padding: 8 }}>last_seen</th>
            </tr>
          </thead>
          <tbody>
            {trailRows.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ padding: 16, color: colors.textSecondary }}>
                  No trail data available
                </td>
              </tr>
            ) : (
              trailRows.map((row, i) => (
                <tr key={i} style={{ borderTop: `1px solid ${colors.border}` }}>
                  <td style={{ padding: 8, fontFamily: 'monospace' }}>{row.fibre_id}</td>
                  <td style={{ padding: 8 }}>{(row.health * 100).toFixed(0)}%</td>
                  <td style={{ padding: 8 }}>{row.mode}</td>
                  <td style={{ padding: 8 }}>{row.last_seen}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>

      {/* 3. Transfer History */}
      <SectionTitle>Transfer History</SectionTitle>
      <Card style={{ marginBottom: 24 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ color: colors.textSecondary, textAlign: 'left' }}>
              <th style={{ padding: 8 }}>recipient / summary</th>
              <th style={{ padding: 8 }}>success</th>
              <th style={{ padding: 8 }}>energy / ions</th>
              <th style={{ padding: 8 }}>timestamp</th>
            </tr>
          </thead>
          <tbody>
            {transfers.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ padding: 16, color: colors.textSecondary }}>
                  No transfers yet
                </td>
              </tr>
            ) : (
              transfers.map((t, i) => (
                <tr key={i} style={{ borderTop: `1px solid ${colors.border}` }}>
                  <td style={{ padding: 8 }}>{t.target_fibre_id || t.recipient || (t._aggregate ? `Total: ${t.total_transfers}` : '—')}</td>
                  <td style={{ padding: 8 }}>{t._aggregate ? '—' : t.success ? '✓' : '✗'}</td>
                  <td style={{ padding: 8 }}>{t.total_energy ?? t.ions_transferred ?? '—'}</td>
                  <td style={{ padding: 8 }}>{t.timestamp || t.created_at || '—'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>

      {/* 4. Active Beams */}
      <SectionTitle>Active Beams</SectionTitle>
      <Card style={{ marginBottom: 24 }}>
        {beams.length === 0 ? (
          <div style={{ padding: 16, color: colors.textSecondary }}>No active beams</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {beams.map((b, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: 12,
                  background: colors.bgElevated,
                  borderRadius: 8,
                }}
              >
                <span style={{ fontWeight: 'bold' }}>{b.target_fibre_id || b.beam_id}</span>
                <span style={{ color: colors.cyan }}>Energy: {(b.remaining_energy ?? b.initial_energy ?? 0).toFixed(2)}</span>
                <span style={{ color: colors.textSecondary, fontSize: 11 }}>{b.created_at || '—'}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* 5. Memorials */}
      <SectionTitle>Memorials</SectionTitle>
      <Card>
        {memorials.length === 0 ? (
          <div style={{ padding: 16, color: colors.textSecondary }}>No memorials</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {memorials.map((m, i) => (
              <div
                key={i}
                style={{
                  padding: 12,
                  background: colors.bgElevated,
                  borderRadius: 8,
                  borderLeft: `4px solid ${colors.purple}`,
                }}
              >
                <div style={{ fontWeight: 'bold' }}>{m.lost_fibre_id} ({m.lost_fibre_type})</div>
                <div style={{ fontSize: 11, color: colors.textSecondary }}>Carried by: {Array.isArray(m.carried_by) ? m.carried_by.join(', ') : m.carried_by || '—'}</div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
