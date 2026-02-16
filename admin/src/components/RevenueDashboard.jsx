// =============================================================================
// REVENUE DASHBOARD — Admin Billing Analytics & Subscription Management
// Phase 7: E-Commerce & Billing — Admin Console
// =============================================================================

import React, { useState, useEffect, useCallback } from 'react';

// Design tokens — must match SovereignCommand.jsx
const colors = {
  bgVoid: '#050505',
  bgCard: '#111111',
  bgElevated: '#1A1A1A',
  gold: '#C9A962',
  goldBright: '#E8D5A3',
  cyan: '#4ECDC4',
  red: '#EF4444',
  green: '#00FF88',
  purple: '#9D4EDD',
  textPrimary: '#FFFFFF',
  textSecondary: '#888888',
  border: '#252525',
};

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function apiFetch(path) {
  try {
    const res = await fetch(`${API}${path}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// =============================================================================
// REVENUE DASHBOARD COMPONENT
// =============================================================================

const RevenueDashboard = () => {
  const [revenueData, setRevenueData] = useState(null);
  const [subscriptionData, setSubscriptionData] = useState(null);
  const [failedPayments, setFailedPayments] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('overview');

  // Subscription management state
  const [selectedUser, setSelectedUser] = useState(null);
  const [showOverrideModal, setShowOverrideModal] = useState(false);
  const [showRefundModal, setShowRefundModal] = useState(false);
  const [overridePlan, setOverridePlan] = useState('STANDARD');
  const [refundAmount, setRefundAmount] = useState('');
  const [refundReason, setRefundReason] = useState('');
  const [couponCode, setCouponCode] = useState('');
  const [couponDiscount, setCouponDiscount] = useState('10');
  const [couponType, setCouponType] = useState('percent');
  const [actionMessage, setActionMessage] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    const [rev, subs, failed] = await Promise.all([
      apiFetch('/api/admin/billing/revenue'),
      apiFetch('/api/admin/billing/subscriptions'),
      apiFetch('/api/admin/billing/failed-payments'),
    ]);
    setRevenueData(rev);
    setSubscriptionData(subs);
    setFailedPayments(failed);
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const showMessage = (msg, isError = false) => {
    setActionMessage({ text: msg, isError });
    setTimeout(() => setActionMessage(null), 4000);
  };

  // --- Admin Actions ---
  const handleOverridePlan = async () => {
    if (!selectedUser) return;
    try {
      const res = await fetch(`${API}/api/admin/billing/override-plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: selectedUser.hardware_id || selectedUser.id,
          new_plan: overridePlan,
          admin_note: 'Manual override from Sovereign Command',
        }),
      });
      const data = await res.json();
      if (res.ok) {
        showMessage(`Plan overridden to ${overridePlan} for ${selectedUser.name || selectedUser.id}`);
        setShowOverrideModal(false);
        loadData();
      } else {
        showMessage(data.detail || 'Override failed', true);
      }
    } catch (e) {
      showMessage(`Error: ${e.message}`, true);
    }
  };

  const handleRefund = async () => {
    if (!selectedUser || !refundAmount) return;
    try {
      const res = await fetch(`${API}/api/admin/billing/refund`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: selectedUser.hardware_id || selectedUser.id,
          amount: parseFloat(refundAmount),
          reason: refundReason || 'Admin refund',
        }),
      });
      const data = await res.json();
      if (res.ok) {
        showMessage(`Refund of $${refundAmount} processed for ${selectedUser.name || selectedUser.id}`);
        setShowRefundModal(false);
        setRefundAmount('');
        setRefundReason('');
        loadData();
      } else {
        showMessage(data.detail || 'Refund failed', true);
      }
    } catch (e) {
      showMessage(`Error: ${e.message}`, true);
    }
  };

  const handleRetryPayment = async (paymentId) => {
    try {
      const res = await fetch(`${API}/api/admin/billing/retry-payment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payment_id: paymentId }),
      });
      if (res.ok) {
        showMessage('Payment retry initiated');
        loadData();
      } else {
        showMessage('Retry failed', true);
      }
    } catch (e) {
      showMessage(`Error: ${e.message}`, true);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: colors.textSecondary }}>
        Loading revenue data...
      </div>
    );
  }

  const rev = revenueData || {};
  const subs = subscriptionData || {};
  const failed = failedPayments || {};

  return (
    <div style={{ padding: 20 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h2 style={{ color: colors.gold, margin: 0, fontFamily: 'Cormorant Garamond', fontSize: 24, letterSpacing: 2 }}>
            REVENUE COMMAND
          </h2>
          <p style={{ color: colors.textSecondary, margin: '4px 0 0', fontSize: 12 }}>
            Financial intelligence · Updated {new Date().toLocaleString()}
          </p>
        </div>
        <button
          onClick={loadData}
          style={{
            background: colors.gold,
            color: '#000',
            border: 'none',
            padding: '8px 16px',
            borderRadius: 6,
            cursor: 'pointer',
            fontWeight: 'bold',
            fontSize: 12,
          }}
        >
          ↻ Refresh
        </button>
      </div>

      {/* Action message banner */}
      {actionMessage && (
        <div style={{
          padding: '10px 16px',
          marginBottom: 16,
          borderRadius: 8,
          background: actionMessage.isError ? `${colors.red}15` : `${colors.green}15`,
          border: `1px solid ${actionMessage.isError ? colors.red : colors.green}40`,
          color: actionMessage.isError ? colors.red : colors.green,
          fontSize: 13,
        }}>
          {actionMessage.text}
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'subscriptions', label: 'Subscriptions' },
          { id: 'failed', label: 'Failed Payments' },
          { id: 'tools', label: 'Admin Tools' },
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              background: activeTab === tab.id ? `${colors.gold}20` : 'transparent',
              color: activeTab === tab.id ? colors.gold : colors.textSecondary,
              border: `1px solid ${activeTab === tab.id ? colors.gold + '40' : colors.border}`,
              padding: '8px 16px',
              borderRadius: 6,
              cursor: 'pointer',
              fontSize: 12,
              fontWeight: activeTab === tab.id ? 'bold' : 'normal',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && <OverviewTab rev={rev} subs={subs} />}
      {activeTab === 'subscriptions' && (
        <SubscriptionsTab
          subs={subs}
          onSelectUser={(u) => {
            setSelectedUser(u);
            setShowOverrideModal(true);
          }}
          onRefundUser={(u) => {
            setSelectedUser(u);
            setShowRefundModal(true);
          }}
        />
      )}
      {activeTab === 'failed' && <FailedPaymentsTab failed={failed} onRetry={handleRetryPayment} />}
      {activeTab === 'tools' && (
        <AdminToolsTab
          couponCode={couponCode}
          setCouponCode={setCouponCode}
          couponDiscount={couponDiscount}
          setCouponDiscount={setCouponDiscount}
          couponType={couponType}
          setCouponType={setCouponType}
          showMessage={showMessage}
        />
      )}

      {/* Override Plan Modal */}
      {showOverrideModal && selectedUser && (
        <Modal onClose={() => setShowOverrideModal(false)} title="Override User Plan">
          <p style={{ color: colors.textSecondary, fontSize: 13 }}>
            User: <strong style={{ color: colors.textPrimary }}>{selectedUser.name || selectedUser.id}</strong>
          </p>
          <p style={{ color: colors.textSecondary, fontSize: 13 }}>
            Current Plan: <strong style={{ color: colors.cyan }}>{selectedUser.subscription_plan || 'TRIAL'}</strong>
          </p>
          <div style={{ margin: '16px 0' }}>
            <label style={{ color: colors.textSecondary, fontSize: 12 }}>New Plan:</label>
            <select
              value={overridePlan}
              onChange={e => setOverridePlan(e.target.value)}
              style={{
                width: '100%',
                padding: 10,
                marginTop: 6,
                background: colors.bgVoid,
                color: colors.textPrimary,
                border: `1px solid ${colors.border}`,
                borderRadius: 6,
                fontSize: 13,
              }}
            >
              <option value="COACH_ONLY">Coach Only (Free)</option>
              <option value="TRIAL">Threshold — Trial (Free)</option>
              <option value="STANDARD">Inner Chamber ($49/mo)</option>
              <option value="TOP_TIER">Sovereign Circle ($149/mo)</option>
            </select>
          </div>
          <div style={{
            padding: 10,
            background: `${colors.red}10`,
            borderRadius: 6,
            border: `1px solid ${colors.red}30`,
            marginBottom: 16,
          }}>
            <p style={{ color: colors.red, fontSize: 11, margin: 0 }}>
              ⚠ This action is audit-logged. The user's plan will change immediately.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button
              onClick={() => setShowOverrideModal(false)}
              style={{ ...btnStyle, background: 'transparent', color: colors.textSecondary, border: `1px solid ${colors.border}` }}
            >
              Cancel
            </button>
            <button onClick={handleOverridePlan} style={{ ...btnStyle, background: colors.gold, color: '#000' }}>
              Override Plan
            </button>
          </div>
        </Modal>
      )}

      {/* Refund Modal */}
      {showRefundModal && selectedUser && (
        <Modal onClose={() => setShowRefundModal(false)} title="Process Refund">
          <p style={{ color: colors.textSecondary, fontSize: 13 }}>
            User: <strong style={{ color: colors.textPrimary }}>{selectedUser.name || selectedUser.id}</strong>
          </p>
          <div style={{ margin: '16px 0' }}>
            <label style={{ color: colors.textSecondary, fontSize: 12 }}>Amount ($):</label>
            <input
              type="number"
              value={refundAmount}
              onChange={e => setRefundAmount(e.target.value)}
              placeholder="0.00"
              style={inputStyle}
            />
          </div>
          <div style={{ margin: '16px 0' }}>
            <label style={{ color: colors.textSecondary, fontSize: 12 }}>Reason:</label>
            <input
              type="text"
              value={refundReason}
              onChange={e => setRefundReason(e.target.value)}
              placeholder="Reason for refund"
              style={inputStyle}
            />
          </div>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button
              onClick={() => setShowRefundModal(false)}
              style={{ ...btnStyle, background: 'transparent', color: colors.textSecondary, border: `1px solid ${colors.border}` }}
            >
              Cancel
            </button>
            <button onClick={handleRefund} style={{ ...btnStyle, background: colors.red, color: '#fff' }}>
              Process Refund
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
};

// =============================================================================
// SUB-COMPONENTS
// =============================================================================

const MetricCard = ({ label, value, subtext, color = colors.gold, icon }) => (
  <div style={{
    background: colors.bgCard,
    border: `1px solid ${colors.border}`,
    borderRadius: 10,
    padding: 16,
    flex: 1,
    minWidth: 160,
  }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
      <span style={{ color: colors.textSecondary, fontSize: 11, letterSpacing: 1 }}>{label}</span>
      {icon && <span style={{ fontSize: 16 }}>{icon}</span>}
    </div>
    <div style={{ color, fontSize: 24, fontWeight: 'bold', fontFamily: 'Cormorant Garamond' }}>{value}</div>
    {subtext && <div style={{ color: colors.textSecondary, fontSize: 10, marginTop: 4 }}>{subtext}</div>}
  </div>
);

const OverviewTab = ({ rev, subs }) => {
  const mrr = rev.mrr || 0;
  const totalRevenue = rev.total_revenue || 0;
  const coachingRevenue = rev.coaching_revenue || 0;
  const churnRate = rev.churn_rate || 0;
  const conversionRate = rev.trial_conversion_rate || 0;
  const activeSubscriptions = subs.active_count || 0;
  const trialCount = subs.trial_count || 0;

  const tierBreakdown = subs.by_tier || {};

  return (
    <div>
      {/* KPI Cards */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
        <MetricCard
          label="MRR"
          value={`$${mrr.toLocaleString()}`}
          subtext="Monthly Recurring Revenue"
          color={colors.gold}
          icon="💰"
        />
        <MetricCard
          label="TOTAL REVENUE"
          value={`$${totalRevenue.toLocaleString()}`}
          subtext="Lifetime"
          color={colors.green}
          icon="📈"
        />
        <MetricCard
          label="COACHING REVENUE"
          value={`$${coachingRevenue.toLocaleString()}`}
          subtext="Packs + Sessions"
          color={colors.cyan}
          icon="🎓"
        />
        <MetricCard
          label="CHURN RATE"
          value={`${(churnRate * 100).toFixed(1)}%`}
          subtext="Cancellations / Total"
          color={churnRate > 0.05 ? colors.red : colors.green}
          icon="📉"
        />
        <MetricCard
          label="TRIAL → PAID"
          value={`${(conversionRate * 100).toFixed(1)}%`}
          subtext={`${trialCount} active trials`}
          color={conversionRate > 0.2 ? colors.green : colors.textSecondary}
          icon="🔄"
        />
        <MetricCard
          label="SUBSCRIBERS"
          value={activeSubscriptions}
          subtext="Active paid"
          color={colors.purple}
          icon="👥"
        />
      </div>

      {/* Revenue by Tier */}
      <div style={{
        background: colors.bgCard,
        border: `1px solid ${colors.border}`,
        borderRadius: 10,
        padding: 20,
        marginBottom: 20,
      }}>
        <h3 style={{ color: colors.gold, margin: '0 0 16px', fontSize: 14, letterSpacing: 2 }}>REVENUE BY TIER</h3>
        {Object.entries(tierBreakdown).map(([tier, data]) => {
          const tierData = typeof data === 'object' ? data : { count: data, revenue: 0 };
          return (
            <div key={tier} style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '10px 0',
              borderBottom: `1px solid ${colors.border}`,
            }}>
              <div>
                <span style={{ color: tierColor(tier), fontWeight: 'bold', fontSize: 13 }}>{tierLabel(tier)}</span>
                <span style={{ color: colors.textSecondary, fontSize: 11, marginLeft: 8 }}>
                  {tierData.count || 0} subscriber{(tierData.count || 0) !== 1 ? 's' : ''}
                </span>
              </div>
              <span style={{ color: colors.textPrimary, fontWeight: 'bold', fontSize: 14 }}>
                ${(tierData.revenue || 0).toLocaleString()}/mo
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const SubscriptionsTab = ({ subs, onSelectUser, onRefundUser }) => {
  const subscribers = subs.subscribers || [];
  const [search, setSearch] = useState('');
  const [tierFilter, setTierFilter] = useState('ALL');

  const filtered = subscribers.filter(s => {
    const matchSearch = !search || (s.name || '').toLowerCase().includes(search.toLowerCase()) || (s.email || '').toLowerCase().includes(search.toLowerCase());
    const matchTier = tierFilter === 'ALL' || (s.subscription_plan || '').toUpperCase() === tierFilter;
    return matchSearch && matchTier;
  });

  return (
    <div>
      {/* Filters */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        <input
          type="text"
          placeholder="Search by name or email..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ ...inputStyle, flex: 1 }}
        />
        <select
          value={tierFilter}
          onChange={e => setTierFilter(e.target.value)}
          style={{ ...inputStyle, width: 160 }}
        >
          <option value="ALL">All Tiers</option>
          <option value="TOP_TIER">Sovereign Circle</option>
          <option value="STANDARD">Inner Chamber</option>
          <option value="TRIAL">Trial</option>
          <option value="COACH_ONLY">Coach Only</option>
        </select>
      </div>

      {/* Subscribers list */}
      <div style={{ background: colors.bgCard, borderRadius: 10, border: `1px solid ${colors.border}`, overflow: 'hidden' }}>
        {/* Header */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '2fr 1fr 1fr 1fr 120px',
          padding: '10px 16px',
          background: colors.bgElevated,
          fontSize: 11,
          color: colors.textSecondary,
          fontWeight: 'bold',
          letterSpacing: 1,
        }}>
          <span>USER</span>
          <span>PLAN</span>
          <span>STATUS</span>
          <span>SINCE</span>
          <span>ACTIONS</span>
        </div>
        {filtered.length === 0 ? (
          <div style={{ padding: 20, textAlign: 'center', color: colors.textSecondary, fontSize: 13 }}>
            No subscribers found
          </div>
        ) : (
          filtered.map((s, i) => (
            <div key={i} style={{
              display: 'grid',
              gridTemplateColumns: '2fr 1fr 1fr 1fr 120px',
              padding: '12px 16px',
              borderBottom: `1px solid ${colors.border}`,
              alignItems: 'center',
            }}>
              <div>
                <div style={{ color: colors.textPrimary, fontSize: 13 }}>{s.name || 'Unknown'}</div>
                <div style={{ color: colors.textSecondary, fontSize: 10 }}>{s.email || ''}</div>
              </div>
              <span style={{ color: tierColor(s.subscription_plan), fontSize: 12, fontWeight: 'bold' }}>
                {tierLabel(s.subscription_plan)}
              </span>
              <span style={{
                color: (s.subscription_status || '').includes('ACTIVE') ? colors.green : colors.red,
                fontSize: 11,
              }}>
                {s.subscription_status || 'Unknown'}
              </span>
              <span style={{ color: colors.textSecondary, fontSize: 11 }}>
                {s.created_at ? new Date(s.created_at).toLocaleDateString() : '—'}
              </span>
              <div style={{ display: 'flex', gap: 4 }}>
                <button
                  onClick={() => onSelectUser(s)}
                  title="Override Plan"
                  style={{ ...miniBtn, background: `${colors.gold}20`, color: colors.gold }}
                >
                  ✏️
                </button>
                <button
                  onClick={() => onRefundUser(s)}
                  title="Refund"
                  style={{ ...miniBtn, background: `${colors.red}20`, color: colors.red }}
                >
                  💸
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

const FailedPaymentsTab = ({ failed, onRetry }) => {
  const payments = (failed && failed.payments) || [];

  return (
    <div>
      <div style={{ background: colors.bgCard, borderRadius: 10, border: `1px solid ${colors.border}`, overflow: 'hidden' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '2fr 1fr 1fr 1fr 80px',
          padding: '10px 16px',
          background: colors.bgElevated,
          fontSize: 11,
          color: colors.textSecondary,
          fontWeight: 'bold',
          letterSpacing: 1,
        }}>
          <span>USER</span>
          <span>AMOUNT</span>
          <span>REASON</span>
          <span>DATE</span>
          <span>ACTION</span>
        </div>
        {payments.length === 0 ? (
          <div style={{ padding: 20, textAlign: 'center', color: colors.green, fontSize: 13 }}>
            ✓ No failed payments
          </div>
        ) : (
          payments.map((p, i) => (
            <div key={i} style={{
              display: 'grid',
              gridTemplateColumns: '2fr 1fr 1fr 1fr 80px',
              padding: '12px 16px',
              borderBottom: `1px solid ${colors.border}`,
              alignItems: 'center',
            }}>
              <span style={{ color: colors.textPrimary, fontSize: 13 }}>{p.user_name || p.user_id}</span>
              <span style={{ color: colors.red, fontWeight: 'bold', fontSize: 13 }}>${p.amount || '0.00'}</span>
              <span style={{ color: colors.textSecondary, fontSize: 11 }}>{p.failure_reason || 'Unknown'}</span>
              <span style={{ color: colors.textSecondary, fontSize: 11 }}>
                {p.created_at ? new Date(p.created_at).toLocaleDateString() : '—'}
              </span>
              <button
                onClick={() => onRetry(p.id)}
                style={{ ...miniBtn, background: `${colors.cyan}20`, color: colors.cyan }}
              >
                Retry
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

const AdminToolsTab = ({ couponCode, setCouponCode, couponDiscount, setCouponDiscount, couponType, setCouponType, showMessage }) => {
  const createCoupon = async () => {
    if (!couponCode) return;
    try {
      const res = await fetch(`${API}/api/admin/billing/coupon`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: couponCode,
          discount: parseFloat(couponDiscount),
          type: couponType,
        }),
      });
      if (res.ok) {
        showMessage(`Coupon "${couponCode}" created`);
        setCouponCode('');
      } else {
        showMessage('Coupon creation failed', true);
      }
    } catch (e) {
      showMessage(`Error: ${e.message}`, true);
    }
  };

  return (
    <div>
      {/* Coupon Creation */}
      <div style={{
        background: colors.bgCard,
        border: `1px solid ${colors.border}`,
        borderRadius: 10,
        padding: 20,
        marginBottom: 20,
      }}>
        <h3 style={{ color: colors.gold, margin: '0 0 16px', fontSize: 14, letterSpacing: 2 }}>CREATE COUPON</h3>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div style={{ flex: 1, minWidth: 120 }}>
            <label style={{ color: colors.textSecondary, fontSize: 11 }}>Code</label>
            <input
              type="text"
              value={couponCode}
              onChange={e => setCouponCode(e.target.value.toUpperCase())}
              placeholder="WELCOME20"
              style={{ ...inputStyle, marginTop: 4 }}
            />
          </div>
          <div style={{ width: 100 }}>
            <label style={{ color: colors.textSecondary, fontSize: 11 }}>Discount</label>
            <input
              type="number"
              value={couponDiscount}
              onChange={e => setCouponDiscount(e.target.value)}
              style={{ ...inputStyle, marginTop: 4 }}
            />
          </div>
          <div style={{ width: 120 }}>
            <label style={{ color: colors.textSecondary, fontSize: 11 }}>Type</label>
            <select
              value={couponType}
              onChange={e => setCouponType(e.target.value)}
              style={{ ...inputStyle, marginTop: 4 }}
            >
              <option value="percent">Percent Off</option>
              <option value="fixed">Fixed Amount</option>
            </select>
          </div>
          <button onClick={createCoupon} style={{ ...btnStyle, background: colors.gold, color: '#000' }}>
            Create Coupon
          </button>
        </div>
      </div>

      {/* Quick Stats */}
      <div style={{
        background: colors.bgCard,
        border: `1px solid ${colors.border}`,
        borderRadius: 10,
        padding: 20,
      }}>
        <h3 style={{ color: colors.gold, margin: '0 0 16px', fontSize: 14, letterSpacing: 2 }}>BILLING NOTES</h3>
        <div style={{ color: colors.textSecondary, fontSize: 12, lineHeight: 1.6 }}>
          <p>• <strong style={{ color: colors.textPrimary }}>Coaching commission:</strong> 30% platform fee (min $30/session). Client pays coach directly unless coach opts for platform billing.</p>
          <p>• <strong style={{ color: colors.textPrimary }}>Family add-ons:</strong> $15/mo per additional family member (beyond Head of Household).</p>
          <p>• <strong style={{ color: colors.textPrimary }}>Trial period:</strong> 14 days. Grace period: 3 days after expiry. Auto-downgrade after grace.</p>
          <p>• <strong style={{ color: colors.textPrimary }}>Coaching packs:</strong> Single $175 · 4-Pack $600 · 8-Pack $1,120. 24-hour cancellation policy.</p>
          <p>• <strong style={{ color: colors.textPrimary }}>Yearly discount:</strong> Inner Chamber $490/yr · Sovereign Circle $1,490/yr (~17% savings).</p>
        </div>
      </div>
    </div>
  );
};

// =============================================================================
// MODAL
// =============================================================================

const Modal = ({ onClose, title, children }) => (
  <div style={{
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.7)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  }} onClick={onClose}>
    <div
      style={{
        background: colors.bgCard,
        border: `1px solid ${colors.border}`,
        borderRadius: 12,
        padding: 24,
        minWidth: 400,
        maxWidth: 500,
      }}
      onClick={e => e.stopPropagation()}
    >
      <h3 style={{ color: colors.gold, margin: '0 0 16px', fontSize: 16, fontFamily: 'Cormorant Garamond' }}>{title}</h3>
      {children}
    </div>
  </div>
);

// =============================================================================
// HELPERS
// =============================================================================

function tierColor(plan) {
  switch ((plan || '').toUpperCase()) {
    case 'TOP_TIER':
    case 'SOVEREIGN_CIRCLE':
      return colors.gold;
    case 'STANDARD':
    case 'INNER_CHAMBER':
      return colors.cyan;
    case 'TRIAL':
    case 'THRESHOLD':
      return colors.textSecondary;
    case 'COACH_ONLY':
      return colors.purple;
    default:
      return colors.textSecondary;
  }
}

function tierLabel(plan) {
  switch ((plan || '').toUpperCase()) {
    case 'TOP_TIER':
    case 'SOVEREIGN_CIRCLE':
      return 'Sovereign Circle';
    case 'STANDARD':
    case 'INNER_CHAMBER':
      return 'Inner Chamber';
    case 'TRIAL':
    case 'THRESHOLD':
      return 'Threshold';
    case 'COACH_ONLY':
      return 'Coach Only';
    default:
      return plan || 'Unknown';
  }
}

const btnStyle = {
  padding: '8px 16px',
  borderRadius: 6,
  border: 'none',
  cursor: 'pointer',
  fontWeight: 'bold',
  fontSize: 12,
};

const miniBtn = {
  padding: '4px 8px',
  borderRadius: 4,
  border: 'none',
  cursor: 'pointer',
  fontSize: 11,
};

const inputStyle = {
  width: '100%',
  padding: 10,
  marginTop: 6,
  background: colors.bgVoid,
  color: colors.textPrimary,
  border: `1px solid ${colors.border}`,
  borderRadius: 6,
  fontSize: 13,
  outline: 'none',
  boxSizing: 'border-box',
};

export default RevenueDashboard;
