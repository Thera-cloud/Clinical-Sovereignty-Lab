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

const API = process.env.REACT_APP_API_BASE_URL || '';

async function apiFetch(path) {
  try {
    const headers = {};
    const token = sessionStorage.getItem('token');
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(`${API}${path}`, { headers });
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
          { id: 'specials', label: 'Specials' },
          { id: 'school', label: 'School Codes' },
          { id: 'corporate', label: 'Corporate' },
          { id: 'scholarship', label: 'Scholarships' },
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
      {activeTab === 'specials' && <SpecialsTab showMessage={showMessage} />}
      {activeTab === 'school' && <SchoolCodesTab showMessage={showMessage} />}
      {activeTab === 'corporate' && <CorporateSponsorsTab showMessage={showMessage} />}
      {activeTab === 'scholarship' && <ScholarshipFundsTab />}

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

// =============================================================================
// CARD WRAPPER
// =============================================================================

const Card = ({ title, children }) => (
  <div style={{
    background: colors.bgCard,
    border: `1px solid ${colors.border}`,
    borderRadius: 10,
    padding: 16,
    marginBottom: 16,
  }}>
    {title && <h4 style={{ color: colors.gold, margin: '0 0 12px', fontSize: 14, fontFamily: 'Cormorant Garamond' }}>{title}</h4>}
    {children}
  </div>
);

// =============================================================================
// PROMOTIONAL SPECIALS TAB
// =============================================================================

const SpecialsTab = ({ showMessage }) => {
  const [specials, setSpecials] = useState([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState('');
  const [discountType, setDiscountType] = useState('percent');
  const [discountValue, setDiscountValue] = useState('10');
  const [tiers, setTiers] = useState('');
  const [endsAt, setEndsAt] = useState('');
  const [promoCode, setPromoCode] = useState('');
  const [maxRedemptions, setMaxRedemptions] = useState('');

  const loadSpecials = useCallback(async () => {
    const data = await apiFetch('/api/admin/billing/specials');
    if (data) setSpecials(data.specials || []);
    setLoading(false);
  }, []);

  useEffect(() => { loadSpecials(); }, [loadSpecials]);

  const createSpecial = async () => {
    if (!name || !endsAt) return showMessage('Name and end date required', true);
    const token = sessionStorage.getItem('token');
    try {
      const res = await fetch(`${API}/api/admin/billing/special`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          name,
          discount_type: discountType,
          discount_value: parseInt(discountValue) || 10,
          applicable_tiers: tiers ? tiers.split(',').map(t => t.trim()) : [],
          ends_at: new Date(endsAt).toISOString(),
          max_redemptions: maxRedemptions ? parseInt(maxRedemptions) : null,
          promo_code: promoCode || null,
        }),
      });
      if (res.ok) {
        showMessage('Special created');
        setName(''); setEndsAt(''); setPromoCode(''); setMaxRedemptions('');
        loadSpecials();
      } else {
        showMessage('Failed to create special', true);
      }
    } catch { showMessage('Network error', true); }
  };

  const deactivate = async (id) => {
    const token = sessionStorage.getItem('token');
    await fetch(`${API}/api/admin/billing/special/${id}`, {
      method: 'DELETE',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    loadSpecials();
  };

  if (loading) return <p style={{ color: colors.textSecondary }}>Loading specials...</p>;

  return (
    <div>
      <Card title="Create Promotional Special">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <input style={inputStyle} placeholder="Special name" value={name} onChange={e => setName(e.target.value)} />
          <input style={inputStyle} type="datetime-local" value={endsAt} onChange={e => setEndsAt(e.target.value)} />
          <select style={inputStyle} value={discountType} onChange={e => setDiscountType(e.target.value)}>
            <option value="percent">Percent Off</option>
            <option value="amount">Fixed Amount Off</option>
          </select>
          <input style={inputStyle} placeholder="Discount value" value={discountValue} onChange={e => setDiscountValue(e.target.value)} />
          <input style={inputStyle} placeholder="Tiers (comma-sep, e.g. STANDARD,TOP_TIER)" value={tiers} onChange={e => setTiers(e.target.value)} />
          <input style={inputStyle} placeholder="Promo code (optional)" value={promoCode} onChange={e => setPromoCode(e.target.value)} />
          <input style={inputStyle} placeholder="Max redemptions (optional)" value={maxRedemptions} onChange={e => setMaxRedemptions(e.target.value)} />
          <button onClick={createSpecial} style={{ ...btnStyle, background: colors.gold, color: '#000' }}>Create Special</button>
        </div>
      </Card>
      <Card title={`Active Specials (${specials.length})`}>
        {specials.length === 0 ? (
          <p style={{ color: colors.textSecondary, fontSize: 13 }}>No specials configured</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {specials.map(s => (
              <div key={s.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: 10, background: colors.bgVoid, borderRadius: 6, border: `1px solid ${s.is_live ? colors.green + '40' : colors.border}` }}>
                <div>
                  <div style={{ color: colors.textPrimary, fontSize: 13, fontWeight: 'bold' }}>{s.name}</div>
                  <div style={{ color: colors.textSecondary, fontSize: 11 }}>
                    {s.discount_value}{s.discount_type === 'percent' ? '%' : '¢'} off
                    {s.promo_code ? ` · Code: ${s.promo_code}` : ''}
                    {s.max_redemptions ? ` · ${s.current_redemptions}/${s.max_redemptions} used` : ''}
                  </div>
                  <div style={{ color: s.is_live ? colors.green : colors.textSecondary, fontSize: 10 }}>
                    {s.is_live ? 'LIVE' : s.active ? 'Scheduled' : 'Inactive'} · Ends {new Date(s.ends_at).toLocaleDateString()}
                  </div>
                </div>
                {s.active && (
                  <button onClick={() => deactivate(s.id)} style={{ ...miniBtn, background: `${colors.red}20`, color: colors.red }}>Deactivate</button>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};

// =============================================================================
// SCHOOL CODES TAB
// =============================================================================

const SchoolCodesTab = ({ showMessage }) => {
  const [codes, setCodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [schoolName, setSchoolName] = useState('');
  const [schoolCode, setSchoolCode] = useState('');
  const [discount, setDiscount] = useState('10');
  const [maxStudents, setMaxStudents] = useState('');

  const loadCodes = useCallback(async () => {
    const data = await apiFetch('/api/admin/billing/school-codes');
    if (data) setCodes(data.school_codes || []);
    setLoading(false);
  }, []);

  useEffect(() => { loadCodes(); }, [loadCodes]);

  const createCode = async () => {
    if (!schoolName || !schoolCode) return showMessage('School name and code required', true);
    const token = sessionStorage.getItem('token');
    try {
      const res = await fetch(`${API}/api/admin/billing/school-codes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          school_name: schoolName,
          school_code: schoolCode,
          discount_percent: parseInt(discount) || 10,
          max_students: maxStudents ? parseInt(maxStudents) : null,
        }),
      });
      if (res.ok) {
        showMessage('School code created');
        setSchoolName(''); setSchoolCode(''); setMaxStudents('');
        loadCodes();
      } else {
        const err = await res.json().catch(() => ({}));
        showMessage(err.detail || 'Failed to create school code', true);
      }
    } catch { showMessage('Network error', true); }
  };

  const deactivate = async (id) => {
    const token = sessionStorage.getItem('token');
    await fetch(`${API}/api/admin/billing/school-code/${id}`, {
      method: 'DELETE',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    loadCodes();
  };

  if (loading) return <p style={{ color: colors.textSecondary }}>Loading school codes...</p>;

  return (
    <div>
      <Card title="Create School Code">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <input style={inputStyle} placeholder="School name" value={schoolName} onChange={e => setSchoolName(e.target.value)} />
          <input style={inputStyle} placeholder="Code (e.g. STANFORD2026)" value={schoolCode} onChange={e => setSchoolCode(e.target.value)} />
          <input style={inputStyle} placeholder="Discount % (default 10)" value={discount} onChange={e => setDiscount(e.target.value)} />
          <input style={inputStyle} placeholder="Max students (optional)" value={maxStudents} onChange={e => setMaxStudents(e.target.value)} />
        </div>
        <button onClick={createCode} style={{ ...btnStyle, background: colors.gold, color: '#000', marginTop: 10 }}>Create Code</button>
      </Card>
      <Card title={`School Codes (${codes.length})`}>
        {codes.length === 0 ? (
          <p style={{ color: colors.textSecondary, fontSize: 13 }}>No school codes configured</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {codes.map(c => (
              <div key={c.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: 10, background: colors.bgVoid, borderRadius: 6, border: `1px solid ${colors.border}` }}>
                <div>
                  <div style={{ color: colors.textPrimary, fontSize: 13, fontWeight: 'bold' }}>{c.school_name}</div>
                  <div style={{ color: colors.cyan, fontSize: 12 }}>Code: {c.school_code} · {c.discount_percent}% off</div>
                  <div style={{ color: colors.textSecondary, fontSize: 11 }}>
                    {c.current_students}{c.max_students ? `/${c.max_students}` : ''} students · {c.active ? 'Active' : 'Inactive'}
                  </div>
                </div>
                {c.active && (
                  <button onClick={() => deactivate(c.id)} style={{ ...miniBtn, background: `${colors.red}20`, color: colors.red }}>Deactivate</button>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};

// =============================================================================
// CORPORATE SPONSORS TAB
// =============================================================================

const CorporateSponsorsTab = ({ showMessage }) => {
  const [sponsors, setSponsors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [companyName, setCompanyName] = useState('');
  const [sponsorCode, setSponsorCode] = useState('');
  const [discType, setDiscType] = useState('percent');
  const [discValue, setDiscValue] = useState('10');
  const [paysFull, setPaysFull] = useState(false);
  const [maxEmployees, setMaxEmployees] = useState('');
  const [billingEmail, setBillingEmail] = useState('');

  const loadSponsors = useCallback(async () => {
    const data = await apiFetch('/api/admin/billing/corporate-sponsors');
    if (data) setSponsors(data.sponsors || []);
    setLoading(false);
  }, []);

  useEffect(() => { loadSponsors(); }, [loadSponsors]);

  const createSponsor = async () => {
    if (!companyName || !sponsorCode) return showMessage('Company name and code required', true);
    const token = sessionStorage.getItem('token');
    try {
      const res = await fetch(`${API}/api/admin/billing/corporate-sponsors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          company_name: companyName,
          sponsor_code: sponsorCode,
          discount_type: discType,
          discount_value: parseInt(discValue) || 0,
          pays_full: paysFull,
          max_employees: maxEmployees ? parseInt(maxEmployees) : null,
          billing_contact_email: billingEmail || null,
        }),
      });
      if (res.ok) {
        showMessage('Corporate sponsor created');
        setCompanyName(''); setSponsorCode(''); setBillingEmail(''); setMaxEmployees('');
        loadSponsors();
      } else {
        const err = await res.json().catch(() => ({}));
        showMessage(err.detail || 'Failed to create sponsor', true);
      }
    } catch { showMessage('Network error', true); }
  };

  const deactivate = async (id) => {
    const token = sessionStorage.getItem('token');
    await fetch(`${API}/api/admin/billing/corporate-sponsor/${id}`, {
      method: 'DELETE',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    loadSponsors();
  };

  if (loading) return <p style={{ color: colors.textSecondary }}>Loading corporate sponsors...</p>;

  return (
    <div>
      <Card title="Create Corporate Sponsor">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <input style={inputStyle} placeholder="Company name" value={companyName} onChange={e => setCompanyName(e.target.value)} />
          <input style={inputStyle} placeholder="Sponsor code (e.g. ACME100)" value={sponsorCode} onChange={e => setSponsorCode(e.target.value)} />
          <select style={inputStyle} value={discType} onChange={e => setDiscType(e.target.value)}>
            <option value="percent">Percent Off</option>
            <option value="amount">Fixed Amount Off</option>
            <option value="full">Fully Sponsored</option>
          </select>
          <input style={inputStyle} placeholder="Discount value" value={discValue} onChange={e => setDiscValue(e.target.value)} disabled={paysFull} />
          <input style={inputStyle} placeholder="Max employees (optional)" value={maxEmployees} onChange={e => setMaxEmployees(e.target.value)} />
          <input style={inputStyle} placeholder="Billing contact email" value={billingEmail} onChange={e => setBillingEmail(e.target.value)} />
          <label style={{ color: colors.textSecondary, fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={paysFull} onChange={e => { setPaysFull(e.target.checked); if (e.target.checked) setDiscType('full'); }} />
            Corp pays 100%
          </label>
          <button onClick={createSponsor} style={{ ...btnStyle, background: colors.gold, color: '#000' }}>Create Sponsor</button>
        </div>
      </Card>
      <Card title={`Corporate Sponsors (${sponsors.length})`}>
        {sponsors.length === 0 ? (
          <p style={{ color: colors.textSecondary, fontSize: 13 }}>No corporate sponsors configured</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {sponsors.map(s => (
              <div key={s.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: 10, background: colors.bgVoid, borderRadius: 6, border: `1px solid ${colors.border}` }}>
                <div>
                  <div style={{ color: colors.textPrimary, fontSize: 13, fontWeight: 'bold' }}>{s.company_name}</div>
                  <div style={{ color: colors.purple, fontSize: 12 }}>
                    Code: {s.sponsor_code} · {s.pays_full ? 'Fully Sponsored' : `${s.discount_value}${s.discount_type === 'percent' ? '%' : '¢'} off`}
                  </div>
                  <div style={{ color: colors.textSecondary, fontSize: 11 }}>
                    {s.current_employees}{s.max_employees ? `/${s.max_employees}` : ''} employees
                    {s.billing_contact_email ? ` · ${s.billing_contact_email}` : ''}
                    {' · '}{s.active ? 'Active' : 'Inactive'}
                  </div>
                </div>
                {s.active && (
                  <button onClick={() => deactivate(s.id)} style={{ ...miniBtn, background: `${colors.red}20`, color: colors.red }}>Deactivate</button>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};

// =============================================================================
// SCHOLARSHIP FUNDS TAB
// =============================================================================

const ScholarshipFundsTab = () => {
  const [funds, setFunds] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const data = await apiFetch('/api/admin/billing/scholarship-funds');
      if (data) setFunds(data.funds || []);
      setLoading(false);
    })();
  }, []);

  if (loading) return <p style={{ color: colors.textSecondary }}>Loading scholarship funds...</p>;

  return (
    <Card title={`Scholarship Funds (${funds.length})`}>
      {funds.length === 0 ? (
        <p style={{ color: colors.textSecondary, fontSize: 13 }}>No scholarship funds created yet. Sponsors create funds via the API.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {funds.map(f => (
            <div key={f.id} style={{ padding: 12, background: colors.bgVoid, borderRadius: 8, border: `1px solid ${colors.purple}30` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ color: colors.textPrimary, fontSize: 14, fontWeight: 'bold' }}>{f.fund_name}</div>
                  {f.sponsor_name && <div style={{ color: colors.purple, fontSize: 12 }}>Sponsor: {f.sponsor_name}</div>}
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ color: colors.gold, fontSize: 16, fontWeight: 'bold' }}>${(f.balance_cents / 100).toFixed(2)}</div>
                  <div style={{ color: colors.textSecondary, fontSize: 10 }}>Balance</div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 16, marginTop: 8 }}>
                <span style={{ color: colors.green, fontSize: 11 }}>Deposited: ${(f.total_deposited / 100).toFixed(2)}</span>
                <span style={{ color: colors.cyan, fontSize: 11 }}>Disbursed: ${(f.total_disbursed / 100).toFixed(2)}</span>
                <span style={{ color: colors.textSecondary, fontSize: 11 }}>{f.active_beneficiaries} beneficiar{f.active_beneficiaries === 1 ? 'y' : 'ies'}</span>
                <span style={{ color: f.active ? colors.green : colors.red, fontSize: 11 }}>{f.active ? 'Active' : 'Inactive'}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
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
