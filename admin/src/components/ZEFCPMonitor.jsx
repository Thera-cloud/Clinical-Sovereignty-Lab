/**
 * ZEFCPMonitor — ZEFCP transport layer monitoring dashboard.
 * Fetches from /api/zefcp/health, endpoints, assemblies, metrics/all.
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
  cyan: '#00D4FF',
  cyanDim: 'rgba(0, 212, 255, 0.1)',
  textPrimary: '#FFFFFF',
  textSecondary: '#888888',
};

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

function ProgressBar({ value, max, color = colors.cyan }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div style={{ background: colors.bgElevated, borderRadius: 4, height: 8, overflow: 'hidden' }}>
      <div
        style={{
          width: `${pct}%`,
          height: '100%',
          background: color,
          borderRadius: 4,
          transition: 'width 0.3s ease',
        }}
      />
    </div>
  );
}

export default function ZEFCPMonitor() {
  const [health, setHealth] = useState(null);
  const [endpoints, setEndpoints] = useState([]);
  const [assemblies, setAssemblies] = useState({ pending_count: 0, assemblies: [] });
  const [metrics, setMetrics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchAll() {
      setLoading(true);
      setError(null);
      try {
        const [healthRes, endpointsRes, assembliesRes, metricsRes] = await Promise.all([
          authFetch('/api/zefcp/health'),
          authFetch('/api/zefcp/endpoints'),
          authFetch('/api/zefcp/assemblies'),
          authFetch('/api/zefcp/metrics/all'),
        ]);

        if (cancelled) return;

        setHealth(healthRes.ok ? await healthRes.json() : null);
        setEndpoints(endpointsRes.ok ? await endpointsRes.json() : []);
        setAssemblies(assembliesRes.ok ? await assembliesRes.json() : { pending_count: 0, assemblies: [] });
        setMetrics(metricsRes.ok ? await metricsRes.json() : []);
      } catch (err) {
        if (!cancelled) {
          setError(err.message || 'Failed to fetch ZEFCP data');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchAll();
    const id = setInterval(fetchAll, 30000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (loading && !health) {
    return (
      <div style={{ padding: 24, color: colors.textSecondary }}>
        Loading ZEFCP data…
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

  const assembliesList = Array.isArray(assemblies.assemblies) ? assemblies.assemblies : [];
  const metricsList = Array.isArray(metrics) ? metrics : [];

  return (
    <div style={{ padding: 24, overflowY: 'auto' }}>
      <h2 style={{ color: colors.gold, marginBottom: 24 }}>📡 ZEFCP Monitor</h2>

      {/* 1. Health Status */}
      <SectionTitle>Health Status</SectionTitle>
      <Card style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <div
            style={{
              width: 12,
              height: 12,
              borderRadius: '50%',
              background: health?.status === 'healthy' ? colors.green : health?.status === 'degraded' ? colors.orange : colors.red,
            }}
          />
          <span style={{ fontWeight: 'bold', textTransform: 'uppercase' }}>{health?.status ?? 'unknown'}</span>
          <span style={{ color: colors.textSecondary }}>Endpoints: {health?.total_endpoints ?? 0}</span>
          <span style={{ color: colors.textSecondary }}>Observations/hr: {health?.observations_last_hour ?? 0}</span>
          <span style={{ color: colors.textSecondary }}>Avg fragment loss: {(health?.avg_fragment_loss ?? 0).toFixed(4)}</span>
        </div>
      </Card>

      {/* 2. Endpoint Registry */}
      <SectionTitle>Endpoint Registry</SectionTitle>
      <Card style={{ marginBottom: 24 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ color: colors.textSecondary, textAlign: 'left' }}>
              <th style={{ padding: 8 }}>id</th>
              <th style={{ padding: 8 }}>environment</th>
              <th style={{ padding: 8 }}>density</th>
              <th style={{ padding: 8 }}>last active</th>
            </tr>
          </thead>
          <tbody>
            {endpoints.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ padding: 16, color: colors.textSecondary }}>
                  No endpoints registered
                </td>
              </tr>
            ) : (
              endpoints.map((ep, i) => (
                <tr key={i} style={{ borderTop: `1px solid ${colors.border}` }}>
                  <td style={{ padding: 8, fontFamily: 'monospace' }}>{ep.endpoint_id ?? ep.id}</td>
                  <td style={{ padding: 8 }}>{ep.environment ?? '—'}</td>
                  <td style={{ padding: 8 }}>{(ep.avg_density ?? ep.density ?? 0).toFixed(2)}</td>
                  <td style={{ padding: 8 }}>{ep.last_active ?? '—'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>

      {/* 3. Assembly Status */}
      <SectionTitle>Assembly Status</SectionTitle>
      <Card style={{ marginBottom: 24 }}>
        <div style={{ marginBottom: 12, color: colors.textSecondary }}>
          Pending: {assemblies.pending_count ?? 0}
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ color: colors.textSecondary, textAlign: 'left' }}>
              <th style={{ padding: 8 }}>key</th>
              <th style={{ padding: 8 }}>total</th>
              <th style={{ padding: 8 }}>received</th>
              <th style={{ padding: 8 }}>progress</th>
            </tr>
          </thead>
          <tbody>
            {assembliesList.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ padding: 16, color: colors.textSecondary }}>
                  No active assemblies
                </td>
              </tr>
            ) : (
              assembliesList.slice(0, 20).map((a, i) => (
                <tr key={i} style={{ borderTop: `1px solid ${colors.border}` }}>
                  <td style={{ padding: 8, fontFamily: 'monospace' }}>{(a.key ?? '').slice(0, 24)}</td>
                  <td style={{ padding: 8 }}>{a.total ?? 0}</td>
                  <td style={{ padding: 8 }}>{a.received ?? 0}</td>
                  <td style={{ padding: 8, width: 120 }}>
                    <ProgressBar value={a.received ?? 0} max={Math.max(a.total ?? 1, 1)} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>

      {/* 4. Transport Metrics */}
      <SectionTitle>Transport Metrics</SectionTitle>
      <Card>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 16 }}>
          {metricsList.length === 0 ? (
            <div style={{ color: colors.textSecondary }}>No metrics yet</div>
          ) : (
            metricsList.slice(0, 6).map((m, i) => (
              <div
                key={i}
                style={{
                  padding: 12,
                  background: colors.bgElevated,
                  borderRadius: 8,
                }}
              >
                <div style={{ fontSize: 10, color: colors.textSecondary, marginBottom: 4 }}>
                  {m.endpoint_id ?? `Endpoint ${i + 1}`}
                </div>
                <div style={{ fontSize: 14, fontWeight: 'bold', color: colors.cyan }}>
                  PDUs: {(m.total_ble_pdus_scanned ?? 0).toLocaleString()}
                </div>
                <div style={{ fontSize: 11, color: colors.textSecondary }}>
                  Fragments: {m.valid_fragments_detected ?? 0} • FP: {m.false_positives_discarded ?? 0}
                </div>
              </div>
            ))
          )}
        </div>
        {/* Inline Bar Charts for Transport Metrics */}
        <div style={{ marginTop: 16, padding: 16, background: colors.bgElevated, borderRadius: 8 }}>
          <div style={{ fontSize: 10, color: colors.textSecondary, marginBottom: 12, textTransform: 'uppercase', letterSpacing: 1 }}>
            Transport Metrics Visualization
          </div>
          {(Array.isArray(metrics) ? metrics : []).map((m, i) => {
            const pdus = m.total_ble_pdus_scanned ?? 0;
            const frags = m.valid_fragments_detected ?? 0;
            const fps = m.false_positives_discarded ?? 0;
            const maxVal = Math.max(pdus, frags, fps, 1);
            const barStyle = (val, color) => ({
              height: 14,
              borderRadius: 3,
              background: color,
              width: `${Math.max((val / maxVal) * 100, 2)}%`,
              transition: 'width 0.5s ease',
              display: 'inline-block',
            });
            return (
              <div key={m.endpoint_id ?? i} style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 10, color: colors.textSecondary, marginBottom: 4 }}>
                  {m.endpoint_id ?? `Endpoint ${i + 1}`}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                  <span style={{ fontSize: 9, color: colors.cyan, width: 70 }}>PDUs</span>
                  <div style={{ flex: 1, background: '#1a1a2e', borderRadius: 3, height: 14, overflow: 'hidden' }}>
                    <div style={barStyle(pdus, colors.cyan)} />
                  </div>
                  <span style={{ fontSize: 9, color: colors.textSecondary, width: 50, textAlign: 'right' }}>{pdus.toLocaleString()}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                  <span style={{ fontSize: 9, color: colors.green, width: 70 }}>Fragments</span>
                  <div style={{ flex: 1, background: '#1a1a2e', borderRadius: 3, height: 14, overflow: 'hidden' }}>
                    <div style={barStyle(frags, colors.green)} />
                  </div>
                  <span style={{ fontSize: 9, color: colors.textSecondary, width: 50, textAlign: 'right' }}>{frags.toLocaleString()}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 9, color: colors.red, width: 70 }}>False Pos</span>
                  <div style={{ flex: 1, background: '#1a1a2e', borderRadius: 3, height: 14, overflow: 'hidden' }}>
                    <div style={barStyle(fps, colors.red)} />
                  </div>
                  <span style={{ fontSize: 9, color: colors.textSecondary, width: 50, textAlign: 'right' }}>{fps.toLocaleString()}</span>
                </div>
                {pdus > 0 && (
                  <div style={{ fontSize: 9, color: colors.textSecondary, marginTop: 2 }}>
                    FP Rate: {((fps / pdus) * 100).toFixed(2)}% • Detection Rate: {((frags / pdus) * 100).toFixed(2)}%
                  </div>
                )}
              </div>
            );
          })}
          {(!Array.isArray(metrics) || metrics.length === 0) && (
            <div style={{ color: colors.textSecondary, fontSize: 11 }}>No transport metrics available yet. ZEFCP endpoints will appear when active.</div>
          )}
        </div>
      </Card>
    </div>
  );
}
