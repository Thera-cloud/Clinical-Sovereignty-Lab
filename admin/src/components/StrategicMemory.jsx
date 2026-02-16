/**
 * Strategic Memory Dashboard
 * Shows all 6 strategic memory layers:
 * Standing Orders, Insights, Strategy Proposals, Coherence Briefings,
 * Foresight Alerts, and Swarm Oversight Log.
 */

import React, { useState, useEffect } from 'react';

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

const SectionTitle = ({ children, badge, action }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
    <span style={{ color: colors.textSecondary, fontSize: 11, letterSpacing: 1.5, textTransform: 'uppercase' }}>
      {children}
    </span>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      {badge && <Badge>{badge}</Badge>}
      {action}
    </div>
  </div>
);

const Button = ({ children, onClick, variant = 'default', style = {}, disabled = false }) => {
  const variants = {
    default: { bg: colors.bgCard, border: colors.border, color: colors.textPrimary },
    primary: { bg: `${colors.gold}22`, border: colors.gold, color: colors.gold },
    danger: { bg: `${colors.red}22`, border: colors.red, color: colors.red },
    success: { bg: `${colors.green}22`, border: colors.green, color: colors.green },
  };
  const v = variants[variant];
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

const Spinner = () => (
  <div style={{ textAlign: 'center', padding: 32 }}>
    <div style={{ fontSize: 24, marginBottom: 8, animation: 'spin 1s linear infinite' }}>⏳</div>
    <div style={{ fontSize: 11, color: colors.textSecondary }}>Loading...</div>
  </div>
);

const ErrorBox = ({ message, onRetry }) => (
  <div style={{ padding: 16, background: `${colors.red}15`, border: `1px solid ${colors.red}44`, borderRadius: 8, textAlign: 'center' }}>
    <div style={{ fontSize: 12, color: colors.red, marginBottom: 8 }}>{message}</div>
    {onRetry && <Button variant="danger" onClick={onRetry} style={{ fontSize: 10 }}>Retry</Button>}
  </div>
);

const formatTime = (ts) => {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
};

// =============================================================================
// STRATEGIC MEMORY COMPONENT
// =============================================================================

export default function StrategicMemory() {
  // State for each layer
  const [standingOrders, setStandingOrders] = useState([]);
  const [insights, setInsights] = useState([]);
  const [proposals, setProposals] = useState([]);
  const [latestBriefing, setLatestBriefing] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [oversight, setOversight] = useState([]);

  // Loading and error state
  const [loading, setLoading] = useState({
    orders: true, insights: true, proposals: true, briefing: true, alerts: true, oversight: true,
  });
  const [errors, setErrors] = useState({});

  // Filters
  const [insightDomain, setInsightDomain] = useState('all');
  const [newOrderText, setNewOrderText] = useState('');
  const [newOrderPriority, setNewOrderPriority] = useState('normal');

  // Data fetching
  const fetchData = async (key, url, setter) => {
    setLoading((prev) => ({ ...prev, [key]: true }));
    setErrors((prev) => ({ ...prev, [key]: null }));
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setter(Array.isArray(data) ? data : (data.items || data.data || data));
    } catch (err) {
      setErrors((prev) => ({ ...prev, [key]: err.message }));
    } finally {
      setLoading((prev) => ({ ...prev, [key]: false }));
    }
  };

  const loadAll = () => {
    fetchData('orders', '/api/strategic-memory/standing-orders', setStandingOrders);
    fetchData('insights', '/api/strategic-memory/insights', setInsights);
    fetchData('proposals', '/api/strategic-memory/proposals', setProposals);
    fetchData('briefing', '/api/strategic-memory/briefings/latest', setLatestBriefing);
    fetchData('alerts', '/api/strategic-memory/alerts', setAlerts);
    fetchData('oversight', '/api/strategic-memory/oversight', setOversight);
  };

  useEffect(() => { loadAll(); }, []);

  // Actions
  const createOrder = async () => {
    if (!newOrderText.trim()) return;
    // Map UI priority labels to numeric values expected by the router (1-10)
    const priorityMap = { normal: 5, high: 8, critical: 10 };
    try {
      await fetch('/api/strategic-memory/standing-orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: newOrderText.trim().substring(0, 256),
          directive: newOrderText.trim(),
          origin: 'big_nate_direct',
          domain_tags: [],
          priority: priorityMap[newOrderPriority] || 5,
        }),
      });
      setNewOrderText('');
      fetchData('orders', '/api/strategic-memory/standing-orders', setStandingOrders);
    } catch (err) {
      setErrors((prev) => ({ ...prev, orders: err.message }));
    }
  };

  const deactivateOrder = async (orderId) => {
    try {
      await fetch(`/api/strategic-memory/standing-orders/${orderId}`, { method: 'DELETE' });
      fetchData('orders', '/api/strategic-memory/standing-orders', setStandingOrders);
    } catch (err) {
      setErrors((prev) => ({ ...prev, orders: err.message }));
    }
  };

  const handleProposal = async (proposalId, action) => {
    try {
      await fetch(`/api/strategic-memory/proposals/${proposalId}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status: action,  // "approved" or "rejected"
          ...(action === 'approved' ? { approved_by: 'big_nate' } : {}),
          ...(action === 'rejected' ? { rejection_reason: 'Rejected from admin dashboard' } : {}),
        }),
      });
      fetchData('proposals', '/api/strategic-memory/proposals', setProposals);
    } catch (err) {
      setErrors((prev) => ({ ...prev, proposals: err.message }));
    }
  };

  // Filter insights by domain
  const filteredInsights = insightDomain === 'all'
    ? insights
    : (Array.isArray(insights) ? insights.filter((i) => i.domain === insightDomain) : insights);

  const uniqueDomains = Array.isArray(insights)
    ? [...new Set(insights.map((i) => i.domain).filter(Boolean))]
    : [];

  return (
    <div style={{ padding: 24, fontFamily: "'DM Sans', system-ui, sans-serif" }}>
      <h1 style={{ color: colors.gold, fontSize: 20, margin: '0 0 24px 0', fontFamily: "'Cormorant Garamond', serif" }}>
        🧠 Strategic Memory
      </h1>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        {/* ========== Standing Orders ========== */}
        <Card>
          <SectionTitle badge={Array.isArray(standingOrders) ? `${standingOrders.length} Active` : null}>
            Standing Orders
          </SectionTitle>

          {loading.orders ? <Spinner /> : errors.orders ? (
            <ErrorBox message={errors.orders} onRetry={() => fetchData('orders', '/api/strategic-memory/standing-orders', setStandingOrders)} />
          ) : (
            <>
              <div style={{ maxHeight: 220, overflowY: 'auto', marginBottom: 12 }}>
                {Array.isArray(standingOrders) && standingOrders.length === 0 && (
                  <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No standing orders.</div>
                )}
                {Array.isArray(standingOrders) && standingOrders.map((order, i) => (
                  <div key={order.id || i} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '10px 0', borderBottom: `1px solid ${colors.border}`,
                  }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12 }}>{order.content || order.text || order.order}</div>
                      <div style={{ fontSize: 10, color: colors.textSecondary, marginTop: 2 }}>
                        {order.priority && <Badge color={order.priority === 'critical' ? colors.red : order.priority === 'high' ? colors.orange : colors.gold}>{order.priority}</Badge>}
                        {order.created_at && <span style={{ marginLeft: 8 }}>{formatTime(order.created_at)}</span>}
                      </div>
                    </div>
                    <Button variant="danger" onClick={() => deactivateOrder(order.id || order.order_id)} style={{ padding: '4px 8px', fontSize: 10 }}>
                      Deactivate
                    </Button>
                  </div>
                ))}
              </div>

              {/* Create new order */}
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  type="text"
                  value={newOrderText}
                  onChange={(e) => setNewOrderText(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && createOrder()}
                  placeholder="New standing order..."
                  style={{
                    flex: 1, padding: '8px 12px', background: colors.bgCard, border: `1px solid ${colors.border}`,
                    borderRadius: 8, color: colors.textPrimary, fontSize: 12,
                  }}
                />
                <select
                  value={newOrderPriority}
                  onChange={(e) => setNewOrderPriority(e.target.value)}
                  style={{ padding: '8px', background: colors.bgCard, border: `1px solid ${colors.border}`, borderRadius: 8, color: colors.textPrimary, fontSize: 11 }}
                >
                  <option value="normal">Normal</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
                <Button variant="primary" onClick={createOrder} style={{ fontSize: 11 }}>+ Create</Button>
              </div>
            </>
          )}
        </Card>

        {/* ========== Recent Insights ========== */}
        <Card>
          <SectionTitle
            badge={Array.isArray(filteredInsights) ? `${filteredInsights.length}` : null}
            action={
              <select
                value={insightDomain}
                onChange={(e) => setInsightDomain(e.target.value)}
                style={{ padding: '4px 8px', background: colors.bgCard, border: `1px solid ${colors.border}`, borderRadius: 6, color: colors.textPrimary, fontSize: 10 }}
              >
                <option value="all">All Domains</option>
                {uniqueDomains.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            }
          >
            Recent Insights
          </SectionTitle>

          {loading.insights ? <Spinner /> : errors.insights ? (
            <ErrorBox message={errors.insights} onRetry={() => fetchData('insights', '/api/strategic-memory/insights', setInsights)} />
          ) : (
            <div style={{ maxHeight: 300, overflowY: 'auto' }}>
              {Array.isArray(filteredInsights) && filteredInsights.length === 0 && (
                <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No insights found.</div>
              )}
              {Array.isArray(filteredInsights) && filteredInsights.map((insight, i) => (
                <div key={insight.id || i} style={{ padding: '10px 0', borderBottom: `1px solid ${colors.border}` }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    {insight.domain && <Badge color={colors.cyan}>{insight.domain}</Badge>}
                    <span style={{ fontSize: 9, color: colors.textSecondary }}>{formatTime(insight.timestamp || insight.created_at)}</span>
                  </div>
                  <div style={{ fontSize: 12, color: colors.textPrimary }}>{insight.content || insight.insight || insight.text}</div>
                  {insight.confidence != null && (
                    <div style={{ fontSize: 10, color: colors.textSecondary, marginTop: 4 }}>
                      Confidence: <span style={{ color: colors.cyan }}>{typeof insight.confidence === 'number' ? (insight.confidence * 100).toFixed(0) + '%' : insight.confidence}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* ========== Strategy Proposals ========== */}
        <Card>
          <SectionTitle badge={Array.isArray(proposals) ? `${proposals.length} Pending` : null}>
            Strategy Proposals
          </SectionTitle>

          {loading.proposals ? <Spinner /> : errors.proposals ? (
            <ErrorBox message={errors.proposals} onRetry={() => fetchData('proposals', '/api/strategic-memory/proposals', setProposals)} />
          ) : (
            <div style={{ maxHeight: 300, overflowY: 'auto' }}>
              {Array.isArray(proposals) && proposals.length === 0 && (
                <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No pending proposals.</div>
              )}
              {Array.isArray(proposals) && proposals.map((proposal, i) => (
                <div key={proposal.id || i} style={{ padding: 12, borderBottom: `1px solid ${colors.border}` }}>
                  <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 4 }}>
                    {proposal.title || proposal.strategy || 'Unnamed Proposal'}
                  </div>
                  <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 8 }}>
                    {proposal.description || proposal.content || proposal.rationale || ''}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', gap: 4 }}>
                      {proposal.source && <Badge color={colors.purple}>{proposal.source}</Badge>}
                      {proposal.priority && <Badge color={proposal.priority === 'critical' ? colors.red : colors.gold}>{proposal.priority}</Badge>}
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <Button variant="success" onClick={() => handleProposal(proposal.id || proposal.proposal_id, 'approved')} style={{ padding: '4px 12px', fontSize: 10 }}>
                        ✓ Approve
                      </Button>
                      <Button variant="danger" onClick={() => handleProposal(proposal.id || proposal.proposal_id, 'rejected')} style={{ padding: '4px 12px', fontSize: 10 }}>
                        ✗ Reject
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* ========== Latest Coherence Briefing ========== */}
        <Card>
          <SectionTitle>Latest Coherence Briefing</SectionTitle>

          {loading.briefing ? <Spinner /> : errors.briefing ? (
            <ErrorBox message={errors.briefing} onRetry={() => fetchData('briefing', '/api/strategic-memory/briefings/latest', setLatestBriefing)} />
          ) : latestBriefing ? (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <span style={{ fontSize: 14, fontWeight: 'bold', color: colors.goldBright }}>
                  {latestBriefing.title || 'Briefing'}
                </span>
                <span style={{ fontSize: 10, color: colors.textSecondary }}>
                  {formatTime(latestBriefing.timestamp || latestBriefing.created_at)}
                </span>
              </div>
              {latestBriefing.coherence_score != null && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                  <div style={{ fontSize: 28, fontWeight: 'bold', color: colors.cyan }}>
                    {typeof latestBriefing.coherence_score === 'number'
                      ? latestBriefing.coherence_score.toFixed(2)
                      : latestBriefing.coherence_score}
                  </div>
                  <div style={{ fontSize: 10, color: colors.textSecondary }}>System Coherence Score</div>
                </div>
              )}
              <div style={{ fontSize: 12, color: colors.textSecondary, lineHeight: 1.6 }}>
                {latestBriefing.summary || latestBriefing.content || JSON.stringify(latestBriefing, null, 2)}
              </div>
              {Array.isArray(latestBriefing.recommendations) && latestBriefing.recommendations.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 10, color: colors.textSecondary, marginBottom: 4, textTransform: 'uppercase', letterSpacing: 1 }}>Recommendations</div>
                  {latestBriefing.recommendations.map((rec, i) => (
                    <div key={i} style={{ fontSize: 11, color: colors.goldBright, padding: '4px 0', borderBottom: `1px solid ${colors.border}` }}>
                      • {typeof rec === 'string' ? rec : rec.text || rec.content}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No briefing available.</div>
          )}
        </Card>

        {/* ========== Active Foresight Alerts ========== */}
        <Card>
          <SectionTitle badge={Array.isArray(alerts) ? `${alerts.length} Active` : null}>
            Foresight Alerts
          </SectionTitle>

          {loading.alerts ? <Spinner /> : errors.alerts ? (
            <ErrorBox message={errors.alerts} onRetry={() => fetchData('alerts', '/api/strategic-memory/alerts', setAlerts)} />
          ) : (
            <div style={{ maxHeight: 300, overflowY: 'auto' }}>
              {Array.isArray(alerts) && alerts.length === 0 && (
                <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No active alerts.</div>
              )}
              {Array.isArray(alerts) && alerts.map((alert, i) => (
                <div key={alert.id || i} style={{
                  padding: 10, marginBottom: 8, borderRadius: 8,
                  background: alert.severity === 'critical' ? `${colors.red}15` : alert.severity === 'warning' ? `${colors.orange}15` : `${colors.cyan}10`,
                  border: `1px solid ${alert.severity === 'critical' ? `${colors.red}44` : alert.severity === 'warning' ? `${colors.orange}44` : `${colors.cyan}33`}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <Badge color={alert.severity === 'critical' ? colors.red : alert.severity === 'warning' ? colors.orange : colors.cyan}>
                      {(alert.severity || 'info').toUpperCase()}
                    </Badge>
                    <span style={{ fontSize: 9, color: colors.textSecondary }}>{formatTime(alert.timestamp || alert.created_at)}</span>
                  </div>
                  <div style={{ fontSize: 12 }}>{alert.message || alert.content || alert.text}</div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* ========== Swarm Oversight Log ========== */}
        <Card>
          <SectionTitle badge={Array.isArray(oversight) ? `${oversight.length} Events` : null}>
            Swarm Oversight Log
          </SectionTitle>

          {loading.oversight ? <Spinner /> : errors.oversight ? (
            <ErrorBox message={errors.oversight} onRetry={() => fetchData('oversight', '/api/strategic-memory/oversight', setOversight)} />
          ) : (
            <div style={{ maxHeight: 300, overflowY: 'auto' }}>
              {Array.isArray(oversight) && oversight.length === 0 && (
                <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No oversight events.</div>
              )}
              {Array.isArray(oversight) && oversight.map((entry, i) => (
                <div key={entry.id || i} style={{
                  display: 'flex', gap: 12, padding: '8px 0',
                  borderBottom: `1px solid ${colors.border}`,
                }}>
                  <div style={{ fontSize: 9, color: colors.textSecondary, minWidth: 80, fontFamily: 'monospace' }}>
                    {formatTime(entry.timestamp || entry.created_at)}
                  </div>
                  <div>
                    {entry.action && <Badge color={colors.purple}>{entry.action}</Badge>}
                    <div style={{ fontSize: 11, marginTop: 2 }}>
                      {entry.description || entry.message || entry.content}
                    </div>
                    {entry.fibre_id && (
                      <div style={{ fontSize: 9, color: colors.textSecondary, fontFamily: 'monospace', marginTop: 2 }}>
                        Fibre: {entry.fibre_id}
                      </div>
                    )}
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
