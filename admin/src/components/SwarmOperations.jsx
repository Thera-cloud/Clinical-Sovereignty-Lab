/**
 * Swarm Operations Dashboard
 * Fibre inventory, spawning, Wisdom Mesh health,
 * Sovereign Immunity, and Swarm Teams management.
 */

import React, { useState, useEffect } from 'react';
import { authFetch } from '../apiClient';

// =============================================================================
// DESIGN SYSTEM
// =============================================================================

const colors = {
  bgVoid: '#050505',
  bgChamber: '#0A0A0A',
  bgElevated: '#111111',
  bgCard: '#1A1A1A',
  border: '#252525',
  gold: '#C9A962',
  goldBright: '#E8D5A3',
  goldDim: '#8B7355',
  cyan: '#4ECDC4',
  purple: '#9D4EDD',
  red: '#EF4444',
  green: '#00FF88',
  orange: '#FF9500',
  textPrimary: '#FFFFFF',
  textSecondary: '#888888',
};

// =============================================================================
// SHARED COMPONENTS
// =============================================================================

const Card = ({ children, style = {} }) => (
  <div style={{
    background: colors.bgElevated,
    border: `1px solid ${colors.border}`,
    borderRadius: 12,
    padding: 16,
    ...style,
  }}>
    {children}
  </div>
);

const Badge = ({ children, color = colors.gold }) => (
  <span style={{
    background: `${color}22`,
    color,
    padding: '3px 8px',
    borderRadius: 10,
    fontSize: 10,
    fontWeight: 'bold',
    whiteSpace: 'nowrap',
  }}>
    {children}
  </span>
);

const SectionTitle = ({ children, badge }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
    <span style={{ color: colors.textSecondary, fontSize: 11, letterSpacing: 1.5, textTransform: 'uppercase' }}>
      {children}
    </span>
    {badge && <Badge>{badge}</Badge>}
  </div>
);

const Button = ({ children, onClick, variant = 'default', style = {}, disabled = false }) => {
  const variants = {
    default: { bg: colors.bgCard, border: colors.border, color: colors.textPrimary },
    primary: { bg: `${colors.gold}22`, border: colors.gold, color: colors.gold },
    danger: { bg: `${colors.red}22`, border: colors.red, color: colors.red },
    success: { bg: `${colors.green}22`, border: colors.green, color: colors.green },
    cyan: { bg: `${colors.cyan}18`, border: colors.cyan, color: colors.cyan },
  };
  const v = variants[variant] || variants.default;
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        background: v.bg,
        border: `1px solid ${v.border}`,
        color: v.color,
        padding: '8px 16px',
        borderRadius: 8,
        fontSize: 12,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        ...style,
      }}
    >
      {children}
    </button>
  );
};

const ProgressBar = ({ value, max, color = colors.cyan }) => (
  <div style={{ background: colors.bgCard, borderRadius: 4, height: 8, overflow: 'hidden' }}>
    <div style={{
      width: `${Math.min((value / max) * 100, 100)}%`,
      height: '100%',
      background: color,
      borderRadius: 4,
      transition: 'width 0.3s ease',
    }} />
  </div>
);

const Spinner = () => (
  <div style={{ textAlign: 'center', padding: 32 }}>
    <div style={{ fontSize: 24, marginBottom: 8 }}>⏳</div>
    <div style={{ fontSize: 11, color: colors.textSecondary }}>Loading...</div>
  </div>
);

const ErrorBox = ({ message, onRetry }) => (
  <div style={{ padding: 16, background: `${colors.red}15`, border: `1px solid ${colors.red}44`, borderRadius: 8, textAlign: 'center' }}>
    <div style={{ fontSize: 12, color: colors.red, marginBottom: 8 }}>{message}</div>
    {onRetry && <Button variant="danger" onClick={onRetry} style={{ fontSize: 10 }}>Retry</Button>}
  </div>
);

const MetricBox = ({ label, value, color = colors.cyan, sub }) => (
  <div style={{ textAlign: 'center', flex: 1 }}>
    <div style={{ fontSize: 24, fontWeight: 'bold', color }}>{value}</div>
    <div style={{ fontSize: 10, color: colors.textSecondary }}>{label}</div>
    {sub && <div style={{ fontSize: 9, color: colors.textSecondary, marginTop: 2 }}>{sub}</div>}
  </div>
);

const formatNum = (n) => {
  if (n == null) return '—';
  if (typeof n === 'number') return n.toLocaleString();
  return n;
};

const formatTime = (ts) => {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
};

// =============================================================================
// SWARM OPERATIONS COMPONENT
// =============================================================================

export default function SwarmOperations() {
  const [fibres, setFibres] = useState([]);
  const [meshHealth, setMeshHealth] = useState(null);
  const [quarantine, setQuarantine] = useState([]);
  const [threats, setThreats] = useState(null);
  const [teams, setTeams] = useState([]);
  const [templates, setTemplates] = useState([]);

  const [loading, setLoading] = useState({
    fibres: true, mesh: true, quarantine: true, threats: true, teams: true, templates: true,
  });
  const [errors, setErrors] = useState({});

  // Spawn form
  const [selectedTemplate, setSelectedTemplate] = useState('');
  const [spawnName, setSpawnName] = useState('');
  const [spawning, setSpawning] = useState(false);

  const fetchData = async (key, url, setter) => {
    setLoading((prev) => ({ ...prev, [key]: true }));
    setErrors((prev) => ({ ...prev, [key]: null }));
    try {
      const res = await authFetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setter(data);
    } catch (err) {
      setErrors((prev) => ({ ...prev, [key]: err.message }));
    } finally {
      setLoading((prev) => ({ ...prev, [key]: false }));
    }
  };

  const loadAll = () => {
    fetchData('fibres', '/api/fibres', (d) => setFibres(Array.isArray(d) ? d : d.fibres || []));
    fetchData('mesh', '/api/mesh/health', setMeshHealth);
    fetchData('quarantine', '/api/immunity/quarantine', (d) => setQuarantine(Array.isArray(d) ? d : d.quarantined || []));
    fetchData('threats', '/api/immunity/threats', setThreats);
    fetchData('teams', '/api/swarm/teams', (d) => setTeams(Array.isArray(d) ? d : d.teams || []));
    fetchData('templates', '/api/swarm/templates', (d) => setTemplates(Array.isArray(d) ? d : d.templates || []));
  };

  useEffect(() => { loadAll(); }, []);

  const spawnFibre = async () => {
    if (!selectedTemplate) return;
    setSpawning(true);
    try {
      const res = await authFetch('/api/fibres/spawn', {
        method: 'POST',
        body: JSON.stringify({
          fibre_type: selectedTemplate,
          name: spawnName || selectedTemplate,
          domain_tags: [],
          reason: 'Spawned from admin dashboard',
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSpawnName('');
      setSelectedTemplate('');
      fetchData('fibres', '/api/fibres', (d) => setFibres(Array.isArray(d) ? d : d.fibres || []));
    } catch (err) {
      setErrors((prev) => ({ ...prev, spawn: err.message }));
    } finally {
      setSpawning(false);
    }
  };

  const statusColor = (s) => {
    const map = { active: colors.green, idle: colors.textSecondary, error: colors.red, quarantined: colors.orange, spawning: colors.cyan };
    return map[(s || '').toLowerCase()] || colors.textSecondary;
  };

  return (
    <div style={{ padding: 24, fontFamily: "'DM Sans', system-ui, sans-serif" }}>
      <h1 style={{ color: colors.gold, fontSize: 20, margin: '0 0 24px 0', fontFamily: "'Cormorant Garamond', serif" }}>
        🐝 Swarm Operations
      </h1>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 20, marginBottom: 20 }}>
        {/* ========== Fibre Inventory ========== */}
        <Card>
          <SectionTitle badge={`${fibres.length} Fibres`}>Fibre Inventory</SectionTitle>

          {loading.fibres ? <Spinner /> : errors.fibres ? (
            <ErrorBox message={errors.fibres} onRetry={() => fetchData('fibres', '/api/fibres', (d) => setFibres(Array.isArray(d) ? d : d.fibres || []))} />
          ) : (
            <div style={{ maxHeight: 360, overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ color: colors.textSecondary, textAlign: 'left' }}>
                    <th style={{ padding: 8 }}>Name</th>
                    <th style={{ padding: 8 }}>Type</th>
                    <th style={{ padding: 8 }}>Status</th>
                    <th style={{ padding: 8 }}>Alignment</th>
                  </tr>
                </thead>
                <tbody>
                  {fibres.length === 0 && (
                    <tr><td colSpan={4} style={{ padding: 16, textAlign: 'center', color: colors.textSecondary }}>No fibres registered.</td></tr>
                  )}
                  {fibres.map((fibre, i) => (
                    <tr key={fibre.id || fibre.fibre_id || i} style={{ borderTop: `1px solid ${colors.border}` }}>
                      <td style={{ padding: 8 }}>
                        <div style={{ fontWeight: 500 }}>{fibre.name || fibre.fibre_id || `Fibre-${i}`}</div>
                        <div style={{ fontSize: 9, color: colors.textSecondary, fontFamily: 'monospace' }}>{fibre.id || fibre.fibre_id || ''}</div>
                      </td>
                      <td style={{ padding: 8 }}>
                        <Badge color={colors.purple}>{fibre.type || fibre.fibre_type || '—'}</Badge>
                      </td>
                      <td style={{ padding: 8 }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          <span style={{ width: 6, height: 6, borderRadius: '50%', background: statusColor(fibre.status), display: 'inline-block' }} />
                          <span style={{ color: statusColor(fibre.status), fontSize: 11 }}>{fibre.status || '—'}</span>
                        </span>
                      </td>
                      <td style={{ padding: 8 }}>
                        {fibre.alignment_score != null ? (
                          <div>
                            <div style={{ fontSize: 11, color: fibre.alignment_score >= 0.8 ? colors.green : fibre.alignment_score >= 0.5 ? colors.orange : colors.red }}>
                              {(typeof fibre.alignment_score === 'number' ? (fibre.alignment_score * 100).toFixed(0) : fibre.alignment_score)}%
                            </div>
                            <ProgressBar value={fibre.alignment_score * 100} max={100} color={fibre.alignment_score >= 0.8 ? colors.green : fibre.alignment_score >= 0.5 ? colors.orange : colors.red} />
                          </div>
                        ) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* ========== Spawn Fibre ========== */}
        <Card>
          <SectionTitle>Spawn Fibre</SectionTitle>

          {loading.templates ? <Spinner /> : errors.templates ? (
            <ErrorBox message={errors.templates} onRetry={() => fetchData('templates', '/api/swarm/templates', (d) => setTemplates(Array.isArray(d) ? d : d.templates || []))} />
          ) : (
            <div>
              <div style={{ marginBottom: 12 }}>
                <label style={{ fontSize: 10, color: colors.textSecondary, display: 'block', marginBottom: 4 }}>Template</label>
                <select
                  value={selectedTemplate}
                  onChange={(e) => setSelectedTemplate(e.target.value)}
                  style={{
                    width: '100%', padding: '10px 12px', background: colors.bgCard,
                    border: `1px solid ${colors.border}`, borderRadius: 8, color: colors.textPrimary, fontSize: 12,
                  }}
                >
                  <option value="">Select a template...</option>
                  {templates.map((t, i) => (
                    <option key={t.id || t.name || i} value={t.id || t.name}>
                      {t.name || t.label || t.id}
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 10, color: colors.textSecondary, display: 'block', marginBottom: 4 }}>Name (optional)</label>
                <input
                  type="text"
                  value={spawnName}
                  onChange={(e) => setSpawnName(e.target.value)}
                  placeholder="Custom fibre name..."
                  style={{
                    width: '100%', padding: '10px 12px', background: colors.bgCard,
                    border: `1px solid ${colors.border}`, borderRadius: 8, color: colors.textPrimary, fontSize: 12,
                    boxSizing: 'border-box',
                  }}
                />
              </div>

              {errors.spawn && (
                <div style={{ fontSize: 11, color: colors.red, marginBottom: 8 }}>Spawn error: {errors.spawn}</div>
              )}

              <Button variant="primary" onClick={spawnFibre} disabled={!selectedTemplate || spawning} style={{ width: '100%' }}>
                {spawning ? '⏳ Spawning...' : '🐝 Spawn Fibre'}
              </Button>
            </div>
          )}
        </Card>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 20 }}>
        {/* ========== Wisdom Mesh Health ========== */}
        <Card>
          <SectionTitle>Wisdom Mesh Health</SectionTitle>

          {loading.mesh ? <Spinner /> : errors.mesh ? (
            <ErrorBox message={errors.mesh} onRetry={() => fetchData('mesh', '/api/mesh/health', setMeshHealth)} />
          ) : meshHealth ? (
            <div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
                <MetricBox
                  label="Total Messages"
                  value={formatNum(meshHealth.total_messages || meshHealth.message_count)}
                  color={colors.cyan}
                />
                <MetricBox
                  label="Msg/sec"
                  value={meshHealth.rate != null ? meshHealth.rate.toFixed(1) : meshHealth.messages_per_second != null ? meshHealth.messages_per_second.toFixed(1) : '—'}
                  color={colors.gold}
                />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                <div>
                  <div style={{ fontSize: 10, color: colors.textSecondary, marginBottom: 4 }}>Latency</div>
                  <div style={{ fontSize: 18, fontWeight: 'bold', color: colors.green }}>
                    {meshHealth.latency_ms != null ? `${meshHealth.latency_ms}ms` : meshHealth.latency != null ? `${meshHealth.latency}ms` : '—'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: colors.textSecondary, marginBottom: 4 }}>Success Rate</div>
                  <div style={{ fontSize: 18, fontWeight: 'bold', color: colors.green }}>
                    {meshHealth.success_rate != null
                      ? `${(typeof meshHealth.success_rate === 'number' && meshHealth.success_rate <= 1 ? (meshHealth.success_rate * 100).toFixed(1) : meshHealth.success_rate)}%`
                      : '—'}
                  </div>
                  {meshHealth.success_rate != null && (
                    <ProgressBar
                      value={meshHealth.success_rate <= 1 ? meshHealth.success_rate * 100 : meshHealth.success_rate}
                      max={100}
                      color={meshHealth.success_rate >= 0.95 || meshHealth.success_rate >= 95 ? colors.green : colors.orange}
                    />
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No mesh data.</div>
          )}
        </Card>

        {/* ========== Sovereign Immunity ========== */}
        <Card>
          <SectionTitle badge={`${quarantine.length} Quarantined`}>Sovereign Immunity</SectionTitle>

          {loading.quarantine || loading.threats ? <Spinner /> : errors.quarantine || errors.threats ? (
            <ErrorBox message={errors.quarantine || errors.threats} onRetry={loadAll} />
          ) : (
            <div>
              {/* Threat Summary */}
              {threats && (
                <div style={{
                  padding: 12, marginBottom: 12, borderRadius: 8,
                  background: `${colors.red}10`, border: `1px solid ${colors.red}33`,
                }}>
                  <div style={{ fontSize: 10, color: colors.textSecondary, marginBottom: 4, textTransform: 'uppercase', letterSpacing: 1 }}>Threat Summary</div>
                  <div style={{ display: 'flex', gap: 12 }}>
                    <MetricBox label="Total" value={formatNum(threats.total || threats.count)} color={colors.red} />
                    <MetricBox label="Critical" value={formatNum(threats.critical || 0)} color={colors.red} />
                    <MetricBox label="Resolved" value={formatNum(threats.resolved || 0)} color={colors.green} />
                  </div>
                </div>
              )}

              {/* Quarantined Fibres */}
              <div style={{ maxHeight: 180, overflowY: 'auto' }}>
                {quarantine.length === 0 ? (
                  <div style={{ fontSize: 11, color: colors.green, textAlign: 'center', padding: 12 }}>
                    ✓ No quarantined fibres
                  </div>
                ) : quarantine.map((item, i) => (
                  <div key={item.id || item.fibre_id || i} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '8px 0', borderBottom: `1px solid ${colors.border}`,
                  }}>
                    <div>
                      <div style={{ fontSize: 11, fontWeight: 500 }}>{item.name || item.fibre_id || `Fibre-${i}`}</div>
                      <div style={{ fontSize: 9, color: colors.textSecondary }}>{item.reason || 'Policy violation'}</div>
                    </div>
                    <Badge color={colors.orange}>QUARANTINED</Badge>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>

        {/* ========== Swarm Teams ========== */}
        <Card>
          <SectionTitle badge={`${teams.length} Teams`}>Swarm Teams</SectionTitle>

          {loading.teams ? <Spinner /> : errors.teams ? (
            <ErrorBox message={errors.teams} onRetry={() => fetchData('teams', '/api/swarm/teams', (d) => setTeams(Array.isArray(d) ? d : d.teams || []))} />
          ) : (
            <div style={{ maxHeight: 300, overflowY: 'auto' }}>
              {teams.length === 0 && (
                <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No teams configured.</div>
              )}
              {teams.map((team, i) => (
                <div key={team.id || team.name || i} style={{
                  padding: 10, marginBottom: 8, borderRadius: 8,
                  background: colors.bgCard, border: `1px solid ${colors.border}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ fontSize: 12, fontWeight: 500, color: colors.goldBright }}>{team.name || `Team-${i}`}</span>
                    <Badge color={team.status === 'active' ? colors.green : colors.textSecondary}>
                      {(team.status || 'unknown').toUpperCase()}
                    </Badge>
                  </div>
                  {team.description && (
                    <div style={{ fontSize: 10, color: colors.textSecondary, marginBottom: 4 }}>{team.description}</div>
                  )}
                  <div style={{ display: 'flex', gap: 8, fontSize: 10, color: colors.textSecondary }}>
                    {team.member_count != null && <span>👥 {team.member_count} members</span>}
                    {team.task && <span>📋 {team.task}</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
