/**
 * LITTLE NATE — Sovereign Command Admin Console
 * Version: 1.0
 * Date: January 21, 2026
 * 
 * Complete admin dashboard with 7 screens:
 * - SC_01: Dashboard
 * - SC_02: User Management
 * - SC_03: Night School
 * - SC_04: The Eye (Analytics)
 * - SC_05: Audit Log
 * - SC_06: Nate Features
 * - SC_07: Nevedal Lab
 * 
 * Built as a single React component file for artifact rendering.
 * In production, split into separate component files.
 */

import React, { useState, useEffect, useCallback } from 'react';
import ThePulse from './components/ThePulse';
import StrategicMemory from './components/StrategicMemory';
import SwarmOperations from './components/SwarmOperations';
import ForesightDashboard from './components/ForesightDashboard';
import FamilyPatterns from './components/FamilyPatterns';
import SovereigntyWireframe from './components/SovereigntyWireframe';
import SovereignSwarmWireDiagram from './components/SovereignSwarmWireDiagram';
import QuaketeMap from './components/QuaketeMap';
import BigNateChat from './components/BigNateChat';
import ZEFCPMonitor from './components/ZEFCPMonitor';
import HiveDefenseDashboard from './components/HiveDefenseDashboard';
import RevenueDashboard from './components/RevenueDashboard';

// =============================================================================
// DESIGN SYSTEM
// =============================================================================

const colors = {
  // Backgrounds
  bgDark: '#0A0A0A',
  bgCard: '#111111',
  bgElevated: '#1A1A1A',
  border: '#252525',
  
  // Primary
  gold: '#FFD700',
  goldDim: 'rgba(255, 215, 0, 0.2)',
  
  // Status
  red: '#FF3B3B',
  redDim: 'rgba(255, 59, 59, 0.15)',
  green: '#00FF88',
  greenDim: 'rgba(0, 255, 136, 0.1)',
  orange: '#FF9500',
  orangeDim: 'rgba(255, 149, 0, 0.15)',
  
  // Features
  cyan: '#00D4FF',
  cyanDim: 'rgba(0, 212, 255, 0.1)',
  purple: '#9D4EDD',
  purpleDim: 'rgba(157, 78, 221, 0.15)',
  blue: '#4A90D9',
  
  // Text
  textPrimary: '#FFFFFF',
  textSecondary: '#888888',
};

// =============================================================================
// API HELPER
// =============================================================================

const API_BASE = '';  // relative — same origin

function _getAuthHeaders() {
  const h = { 'Content-Type': 'application/json' };
  const token = sessionStorage.getItem('token');
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

async function apiFetch(path, options = {}) {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { ..._getAuthHeaders(), ...options.headers },
      ...options,
    });
    if (res.status === 401) { window.location.href = 'index.html'; return null; }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(`API ${path}:`, err);
    return null;
  }
}

function useApi(path, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(() => {
    setLoading(true);
    apiFetch(path).then(d => { setData(d); setLoading(false); });
  }, [path]);
  useEffect(() => { refresh(); }, deps);
  return { data, loading, refresh };
}

// =============================================================================
// SHARED COMPONENTS
// =============================================================================

const Card = ({ children, style = {}, onClick }) => (
  <div
    onClick={onClick}
    style={{
      background: colors.bgCard,
      border: `1px solid ${colors.border}`,
      borderRadius: 12,
      padding: 16,
      cursor: onClick ? 'pointer' : 'default',
      ...style,
    }}
  >
    {children}
  </div>
);

const Badge = ({ children, color = colors.gold, bgColor }) => (
  <span
    style={{
      background: bgColor || `${color}22`,
      color: color,
      padding: '3px 8px',
      borderRadius: 10,
      fontSize: 10,
      fontWeight: 'bold',
    }}
  >
    {children}
  </span>
);

const Button = ({ children, onClick, variant = 'default', style = {} }) => {
  const variants = {
    default: { bg: colors.bgElevated, border: colors.border, color: colors.textPrimary },
    primary: { bg: colors.goldDim, border: colors.gold, color: colors.gold },
    danger: { bg: colors.redDim, border: colors.red, color: colors.red },
    success: { bg: colors.greenDim, border: colors.green, color: colors.green },
  };
  const v = variants[variant];
  
  return (
    <button
      onClick={onClick}
      style={{
        background: v.bg,
        border: `1px solid ${v.border}`,
        color: v.color,
        padding: '10px 20px',
        borderRadius: 8,
        fontSize: 12,
        cursor: 'pointer',
        ...style,
      }}
    >
      {children}
    </button>
  );
};

const ProgressBar = ({ value, max, color = colors.cyan }) => (
  <div style={{ background: colors.bgElevated, borderRadius: 4, height: 8, overflow: 'hidden' }}>
    <div
      style={{
        width: `${Math.min((value / max) * 100, 100)}%`,
        height: '100%',
        background: color,
        borderRadius: 4,
        transition: 'width 0.3s ease',
      }}
    />
  </div>
);

const SectionTitle = ({ children, badge }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
    <span style={{ color: colors.textSecondary, fontSize: 11, letterSpacing: 1.5, textTransform: 'uppercase' }}>
      {children}
    </span>
    {badge && <Badge>{badge}</Badge>}
  </div>
);

const StatusDot = ({ status }) => {
  const statusColors = {
    online: colors.green,
    offline: colors.red,
    training: colors.purple,
    warning: colors.orange,
  };
  return (
    <span
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: statusColors[status] || colors.textSecondary,
        marginRight: 6,
      }}
    />
  );
};

const MetricCard = ({ icon, label, value, color = colors.cyan }) => (
  <Card style={{ textAlign: 'center', flex: 1 }}>
    <div style={{ fontSize: 24, marginBottom: 4 }}>{icon}</div>
    <div style={{ fontSize: 24, fontWeight: 'bold', color }}>{value}</div>
    <div style={{ fontSize: 10, color: colors.textSecondary }}>{label}</div>
  </Card>
);

// =============================================================================
// NAVIGATION
// =============================================================================

const navItems = [
  { id: 'dashboard', icon: '📊', label: 'Dashboard' },
  { id: 'users', icon: '👥', label: 'Users' },
  { id: 'revenue', icon: '💰', label: 'Revenue' },
  { id: 'night-school', icon: '🎓', label: 'Night School' },
  { id: 'the-eye', icon: '👁️', label: 'The Eye' },
  { id: 'audit', icon: '📜', label: 'Audit Log' },
  { id: 'nate', icon: '🧠', label: 'Nate Features' },
  { id: 'nevedal', icon: '🔬', label: 'Nevedal Lab' },
  { id: 'the-pulse', icon: '💓', label: 'The Pulse' },
  { id: 'strategic-memory', icon: '🧠', label: 'Strategic Memory' },
  { id: 'swarm-ops', icon: '🐝', label: 'Swarm Operations' },
  { id: 'foresight', icon: '🔮', label: 'Foresight' },
  { id: 'family-patterns', icon: '🧬', label: 'Family Patterns' },
  { id: 'architecture', icon: '🏗️', label: 'Architecture' },
  { id: 'wire-diagram', icon: '🕸️', label: 'Wire Diagram' },
  { id: 'quakete', icon: '⚡', label: 'Quakete Map' },
  { id: 'big-nate', icon: '💬', label: 'Big Nate Chat' },
  { id: 'zefcp', icon: '📡', label: 'ZEFCP Monitor' },
  { id: 'hive-defense', icon: '🛡️', label: 'Hive Defense' },
  { id: 'dependency-guardian', icon: '📦', label: 'Dep. Guardian' },
];

const Sidebar = ({ activeScreen, setActiveScreen }) => (
  <div
    style={{
      width: 200,
      background: colors.bgCard,
      borderRight: `1px solid ${colors.border}`,
      padding: 16,
      display: 'flex',
      flexDirection: 'column',
    }}
  >
    <div style={{ marginBottom: 24 }}>
      <div style={{ color: colors.gold, fontFamily: 'monospace', fontWeight: 'bold', fontSize: 14, letterSpacing: 2 }}>
        SOVEREIGN
      </div>
      <div style={{ color: colors.textSecondary, fontSize: 10 }}>COMMAND v2.0</div>
    </div>
    
    {navItems.map((item) => (
      <div
        key={item.id}
        onClick={() => setActiveScreen(item.id)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '12px 16px',
          marginBottom: 4,
          borderRadius: 8,
          cursor: 'pointer',
          background: activeScreen === item.id ? colors.goldDim : 'transparent',
          color: activeScreen === item.id ? colors.gold : colors.textSecondary,
          border: activeScreen === item.id ? `1px solid ${colors.gold}33` : '1px solid transparent',
        }}
      >
        <span>{item.icon}</span>
        <span style={{ fontSize: 12 }}>{item.label}</span>
      </div>
    ))}
    
    <div style={{ marginTop: 'auto', padding: 12, background: colors.bgElevated, borderRadius: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{ width: 32, height: 32, borderRadius: '50%', background: colors.gold, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          👤
        </div>
        <div>
          <div style={{ fontSize: 11, color: colors.textPrimary }}>Admin User</div>
          <div style={{ fontSize: 9, color: colors.textSecondary }}>ADMIN</div>
        </div>
      </div>
    </div>
  </div>
);

// =============================================================================
// SC_01: DASHBOARD
// =============================================================================

const DashboardScreen = () => {
  const { data: dash, loading: dashLoading, refresh: refreshDash } = useApi('/api/admin/dashboard');
  const { data: crisisData } = useApi('/api/admin/crisis-watchlist');
  const { data: sessionsData } = useApi('/api/admin/live-sessions');
  const { data: communityData } = useApi('/api/admin/community-health');
  const { data: tokenData } = useApi('/api/admin/token-economics');
  const { data: feedData } = useApi('/api/admin/activity-feed?limit=20');
  const { data: coachData } = useApi('/api/admin/coaches');

  const metrics = dash || {};
  const users = metrics.users || {};
  const sessions = metrics.sessions || {};
  const alerts = metrics.alerts || {};
  const crisisWatchlist = (crisisData && crisisData.watchlist) || [];
  const liveSessions = (sessionsData && sessionsData.sessions) || [];
  const community = communityData || {};
  const tokens = tokenData || {};
  const activityFeed = (feedData && feedData.events) || [];
  const pendingApprovals = (coachData && coachData.coaches || []).filter(c => c.status === 'PENDING_VERIFICATION');

  // Determine system status from health check
  const [sysStatus, setSysStatus] = useState({ bridge: 'offline', azure: 'offline', nightSchool: 'offline' });
  useEffect(() => {
    apiFetch('/health').then(h => {
      if (h && h.status === 'healthy') setSysStatus({ bridge: 'online', azure: 'online', nightSchool: 'online' });
    });
  }, []);

  return (
    <div style={{ padding: 24 }}>
      {/* System Status Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ color: colors.gold, fontSize: 20, margin: 0 }}>System Dashboard</h1>
        <div style={{ display: 'flex', gap: 16 }}>
          <span><StatusDot status={sysStatus.bridge} />Bridge</span>
          <span><StatusDot status={sysStatus.azure} />Azure</span>
          <span><StatusDot status={sysStatus.nightSchool} />Night School</span>
          <Button style={{ padding: '4px 10px', fontSize: 10 }} onClick={refreshDash}>Refresh</Button>
        </div>
      </div>
      
      {dashLoading ? <div style={{ color: colors.textSecondary }}>Loading dashboard...</div> : (
      <>
      {/* Metrics */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 24 }}>
        <MetricCard icon="👥" label="Active Users (7d)" value={users.active_7d || 0} />
        <MetricCard icon="🎥" label="Live Sessions" value={sessions.live || 0} color={colors.green} />
        <MetricCard icon="👨‍⚕️" label="Coaches" value={users.coaches || 0} color={colors.gold} />
        <MetricCard icon="⚠️" label="Critical Alerts" value={alerts.active_crises || 0} color={colors.red} />
      </div>
      
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 24 }}>
        <div>
          {/* Crisis Watchlist */}
          <SectionTitle badge={`${crisisWatchlist.length} Active`}>Crisis Watchlist</SectionTitle>
          <Card style={{ marginBottom: 24 }}>
            {crisisWatchlist.length === 0 && <div style={{ color: colors.textSecondary, fontSize: 12, padding: 12 }}>No active crisis alerts</div>}
            {crisisWatchlist.map((item, idx) => {
              const severity = (item.risk_level || '').toLowerCase();
              const sevMap = { critical: 'critical', high: 'warning', medium: 'monitoring' };
              const sev = sevMap[severity] || 'monitoring';
              return (
                <div
                  key={item.user_id || idx}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '12px 0',
                    borderBottom: `1px solid ${colors.border}`,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <div
                      style={{
                        width: 40, height: 40, borderRadius: '50%',
                        background: sev === 'critical' ? colors.redDim : sev === 'warning' ? colors.orangeDim : colors.cyanDim,
                        border: `2px solid ${sev === 'critical' ? colors.red : sev === 'warning' ? colors.orange : colors.cyan}`,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}
                    >
                      {sev === 'critical' ? '🚨' : sev === 'warning' ? '⚠️' : '👁️'}
                    </div>
                    <div>
                      <div style={{ fontWeight: 'bold', fontSize: 13 }}>{item.name || item.user_id}</div>
                      <div style={{ fontSize: 10, color: colors.textSecondary }}>Coach: {item.assigned_coach || 'Unassigned'}</div>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <Badge color={sev === 'critical' ? colors.red : sev === 'warning' ? colors.orange : colors.cyan}>
                      {(item.risk_level || 'UNKNOWN').toUpperCase()}
                    </Badge>
                    <div style={{ fontSize: 9, color: colors.textSecondary, marginTop: 4 }}>{item.last_login ? `Last: ${item.last_login.split('T')[0]}` : 'No recent login'}</div>
                  </div>
                </div>
              );
            })}
          </Card>
          
          {/* Live Sessions */}
          <SectionTitle badge={`${liveSessions.length} Active`}>Live Sessions</SectionTitle>
          <Card>
            {liveSessions.length === 0 ? (
              <div style={{ color: colors.textSecondary, fontSize: 12, padding: 12 }}>No active sessions</div>
            ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ color: colors.textSecondary, textAlign: 'left' }}>
                  <th style={{ padding: 8 }}>Client</th>
                  <th style={{ padding: 8 }}>Type</th>
                  <th style={{ padding: 8 }}>Started</th>
                  <th style={{ padding: 8 }}>Mood</th>
                </tr>
              </thead>
              <tbody>
                {liveSessions.map((session, idx) => (
                  <tr key={session.session_id || idx} style={{ borderTop: `1px solid ${colors.border}` }}>
                    <td style={{ padding: 8 }}>{session.client_id}</td>
                    <td style={{ padding: 8 }}>
                      <Badge color={session.session_type === 'ai' ? colors.cyan : colors.gold}>{(session.session_type || 'ai').toUpperCase()}</Badge>
                    </td>
                    <td style={{ padding: 8, fontFamily: 'monospace', fontSize: 10 }}>{(session.started_at || '').split('T')[1]?.split('.')[0] || '--'}</td>
                    <td style={{ padding: 8 }}>{session.mood || '--'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            )}
          </Card>
        </div>
        
        <div>
          {/* Community Health */}
          <SectionTitle>Community Nevedal State</SectionTitle>
          <Card style={{ marginBottom: 24 }}>
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                <span>Avg C_emo</span>
                <span style={{ color: colors.cyan }}>{(community.avg_c_emo || 0).toFixed(3)}</span>
              </div>
              <ProgressBar value={(community.avg_c_emo || 0) * 100} max={100} color={colors.cyan} />
            </div>
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                <span>Active CEE Windows</span>
                <span style={{ color: colors.green }}>{community.active_cee_windows || 0}</span>
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 4 }}>Risk Distribution</div>
              {Object.entries(community.risk_distribution || {}).map(([level, count]) => (
                <div key={level} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '2px 0' }}>
                  <span>{level}</span>
                  <Badge color={level === 'CRITICAL' ? colors.red : level === 'HIGH' ? colors.orange : colors.textSecondary}>{count}</Badge>
                </div>
              ))}
            </div>
          </Card>
          
          {/* Token Economics */}
          <SectionTitle>Token Economics</SectionTitle>
          <Card style={{ marginBottom: 24 }}>
            <div style={{ textAlign: 'center', marginBottom: 12 }}>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: colors.gold }}>${tokens.estimated_cost_30d_usd || 0}</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Estimated 30-day cost</div>
            </div>
            <div style={{ textAlign: 'center', marginBottom: 8 }}>
              <div style={{ fontSize: 16, color: colors.cyan }}>{(tokens.total_tokens_30d || 0).toLocaleString()}</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Total tokens (30d)</div>
            </div>
          </Card>
          
          {/* Pending Approvals */}
          <SectionTitle badge={pendingApprovals.length}>Pending Approvals</SectionTitle>
          <Card style={{ marginBottom: 24 }}>
            {pendingApprovals.length === 0 && <div style={{ color: colors.textSecondary, fontSize: 12, padding: 8 }}>No pending approvals</div>}
            {pendingApprovals.map((item, idx) => (
              <div key={item.id || idx} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0' }}>
                <div>
                  <div style={{ fontSize: 12 }}>{item.name}</div>
                  <div style={{ fontSize: 10, color: colors.textSecondary }}>{item.specialty || 'General'}</div>
                </div>
                <Button variant="primary" style={{ padding: '6px 12px', fontSize: 10 }} onClick={() => apiFetch('/api/admin/coaches/approve', { method: 'POST', body: JSON.stringify({ coach_id: item.id }) }).then(refreshDash)}>Approve</Button>
              </div>
            ))}
          </Card>
          
          {/* Activity Feed */}
          <SectionTitle>Activity Feed</SectionTitle>
          <Card>
            {activityFeed.length === 0 && <div style={{ color: colors.textSecondary, fontSize: 12, padding: 8 }}>No recent activity</div>}
            {activityFeed.slice(0, 10).map((item, i) => (
              <div key={i} style={{ display: 'flex', gap: 12, padding: '8px 0', borderBottom: i < Math.min(activityFeed.length, 10) - 1 ? `1px solid ${colors.border}` : 'none' }}>
                <div style={{ fontSize: 9, color: colors.textSecondary, width: 70 }}>{(item.date || '').split('T')[0]}</div>
                <div style={{ fontSize: 11, color: item.type === 'notification' && item.priority === 'HIGH' ? colors.red : colors.textPrimary }}>
                  {item.message}
                </div>
              </div>
            ))}
          </Card>
        </div>
      </div>
      </>
      )}
    </div>
  );
};

// =============================================================================
// SC_02: USER MANAGEMENT
// =============================================================================

const UserManagementScreen = () => {
  const [selectedUser, setSelectedUser] = useState(null);
  const [selectedDetail, setSelectedDetail] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [roleFilter, setRoleFilter] = useState('ALL');
  const { data: usersData, loading, refresh: refreshUsers } = useApi('/api/admin/users?limit=500');
  const allUsers = (usersData && usersData.users) || [];
  
  const filteredUsers = allUsers.filter((user) => {
    const matchesSearch = (user.name || '').toLowerCase().includes(searchTerm.toLowerCase()) || (user.id || '').toLowerCase().includes(searchTerm.toLowerCase());
    const matchesRole = roleFilter === 'ALL' || user.role === roleFilter;
    return matchesSearch && matchesRole;
  });

  // Load detailed user info when selected
  useEffect(() => {
    if (selectedUser) {
      apiFetch(`/api/admin/user/${selectedUser.id}`).then(d => setSelectedDetail(d));
    }
  }, [selectedUser?.id]);
  
  return (
    <div style={{ display: 'flex', height: '100%' }}>
      {/* Sidebar */}
      <div style={{ width: 280, background: colors.bgCard, borderRight: `1px solid ${colors.border}`, padding: 16, overflowY: 'auto' }}>
        <input
          type="text"
          placeholder="Search users..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          style={{
            width: '100%',
            padding: '10px 12px',
            background: colors.bgElevated,
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            color: colors.textPrimary,
            fontSize: 12,
            marginBottom: 12,
          }}
        />
        
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          {['ALL', 'CLIENT', 'COACH', 'ADMIN'].map((role) => (
            <button
              key={role}
              onClick={() => setRoleFilter(role)}
              style={{
                flex: 1,
                padding: '6px 8px',
                fontSize: 9,
                background: roleFilter === role ? colors.goldDim : colors.bgElevated,
                border: `1px solid ${roleFilter === role ? colors.gold : colors.border}`,
                color: roleFilter === role ? colors.gold : colors.textSecondary,
                borderRadius: 6,
                cursor: 'pointer',
              }}
            >
              {role}
            </button>
          ))}
        </div>
        
        {filteredUsers.map((user) => (
          <div
            key={user.id}
            onClick={() => setSelectedUser(user)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: 12,
              marginBottom: 8,
              background: selectedUser?.id === user.id ? colors.bgElevated : 'transparent',
              border: `1px solid ${selectedUser?.id === user.id ? colors.border : 'transparent'}`,
              borderRadius: 8,
              cursor: 'pointer',
            }}
          >
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: '50%',
                background: user.role === 'ADMIN' ? colors.gold : user.role === 'COACH' ? colors.gold : colors.cyan,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 14,
              }}
            >
              {user.role === 'ADMIN' ? '👑' : user.role === 'COACH' ? '👨‍⚕️' : '👤'}
            </div>
            <div>
              <div style={{ fontSize: 12, fontWeight: 500 }}>{user.name}</div>
              <div style={{ fontSize: 9, color: colors.textSecondary }}>{user.id} • {user.role}</div>
            </div>
          </div>
        ))}
      </div>
      
      {/* Main Content */}
      <div style={{ flex: 1, padding: 24, overflowY: 'auto' }}>
        {selectedUser ? (
          (() => {
            const ns = (selectedDetail && selectedDetail.metrics) || {};
            const profile = (selectedDetail && selectedDetail.profile) || selectedUser;
            const cEmo = ns.c_emo || 0;
            const pEnt = ns.p_ent || 0;
            const gammaEnv = ns.gamma_env || 0;
            return (
            <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
              <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
                <div
                  style={{
                    width: 64, height: 64, borderRadius: '50%',
                    background: selectedUser.role === 'ADMIN' ? colors.gold : selectedUser.role === 'COACH' ? colors.gold : colors.cyan,
                    display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 28,
                  }}
                >
                  {selectedUser.role === 'ADMIN' ? '👑' : selectedUser.role === 'COACH' ? '👨‍⚕️' : '👤'}
                </div>
                <div>
                  <h2 style={{ margin: 0, fontSize: 20 }}>{selectedUser.name || selectedUser.id}</h2>
                  <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                    <Badge color={selectedUser.role === 'ADMIN' ? colors.gold : selectedUser.role === 'COACH' ? colors.gold : colors.cyan}>
                      {selectedUser.role}
                    </Badge>
                    <Badge color={(selectedUser.tier || '').includes('TOP') || (selectedUser.tier || '').includes('MASTER') ? colors.gold : colors.textSecondary}>
                      {selectedUser.tier || 'TRIAL'}
                    </Badge>
                    <Badge color={colors.green}>{selectedUser.subscription_status || 'ACTIVE'}</Badge>
                  </div>
                </div>
              </div>
            </div>
            
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
              <Card>
                <SectionTitle>Basic Information</SectionTitle>
                <div style={{ fontSize: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: `1px solid ${colors.border}` }}>
                    <span style={{ color: colors.textSecondary }}>User ID</span>
                    <span style={{ fontFamily: 'monospace' }}>{selectedUser.id}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: `1px solid ${colors.border}` }}>
                    <span style={{ color: colors.textSecondary }}>Role</span>
                    <span>{selectedUser.role}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: `1px solid ${colors.border}` }}>
                    <span style={{ color: colors.textSecondary }}>Tier</span>
                    <span>{selectedUser.tier || 'TRIAL'}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: `1px solid ${colors.border}` }}>
                    <span style={{ color: colors.textSecondary }}>Email</span>
                    <span>{selectedUser.email || 'N/A'}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: `1px solid ${colors.border}` }}>
                    <span style={{ color: colors.textSecondary }}>Sessions</span>
                    <span>{selectedUser.total_sessions || 0}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0' }}>
                    <span style={{ color: colors.textSecondary }}>Joined</span>
                    <span>{selectedUser.joined_date || 'Unknown'}</span>
                  </div>
                </div>
              </Card>
              
              <Card>
                <SectionTitle>Nevedal State</SectionTitle>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                    <span>C_emo (Coherence)</span>
                    <span style={{ color: colors.cyan }}>{(ns.C_emo || cEmo)?.toFixed ? (ns.C_emo || cEmo).toFixed(3) : (ns.C_emo || cEmo)}</span>
                  </div>
                  <ProgressBar value={(ns.C_emo || cEmo) * 100} max={100} color={colors.cyan} />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                    <span>GAP (Growth Attunement)</span>
                    <span style={{ color: colors.gold }}>{(ns.GAP || 0)?.toFixed ? (ns.GAP || 0).toFixed(3) : (ns.GAP || 0)}</span>
                  </div>
                  <ProgressBar value={(ns.GAP || 0) * 100} max={100} color={colors.gold} />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                    <span>Quantum Depth</span>
                    <span style={{ color: colors.purple }}>{(ns.Quantum || 0)?.toFixed ? (ns.Quantum || 0).toFixed(3) : (ns.Quantum || 0)}</span>
                  </div>
                  <ProgressBar value={(ns.Quantum || 0) * 100} max={100} color={colors.purple} />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 8, fontSize: 11 }}>
                  <div style={{ textAlign: 'center', padding: 6, background: `${colors.cyan}11`, borderRadius: 6 }}>
                    <div style={{ color: colors.cyan, fontWeight: 700 }}>{ns.session_count || 0}</div>
                    <div style={{ color: colors.textSecondary }}>Sessions</div>
                  </div>
                  <div style={{ textAlign: 'center', padding: 6, background: `${colors.green}11`, borderRadius: 6 }}>
                    <div style={{ color: colors.green, fontWeight: 700 }}>{ns.breakthrough_count || 0}</div>
                    <div style={{ color: colors.textSecondary }}>CEE</div>
                  </div>
                  <div style={{ textAlign: 'center', padding: 6, background: `${colors.orange}11`, borderRadius: 6 }}>
                    <div style={{ color: colors.orange, fontWeight: 700 }}>{ns.risk_level || 'LOW'}</div>
                    <div style={{ color: colors.textSecondary }}>Risk</div>
                  </div>
                </div>
              </Card>
              
              <Card>
                <SectionTitle>CEE Experiences & Drift</SectionTitle>
                <div style={{ fontSize: 12 }}>
                  {selectedDetail?.cee_experiences?.length > 0 ? (
                    <>
                      <div style={{ color: colors.green, fontWeight: 600, marginBottom: 8 }}>
                        {selectedDetail.cee_experiences.length} CEE Mismatch Events
                      </div>
                      {selectedDetail.cee_experiences.slice(-5).reverse().map((ce, i) => (
                        <div key={i} style={{ padding: '6px 0', borderBottom: `1px solid ${colors.border}`, fontSize: 11 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ color: colors.textSecondary }}>{ce.timestamp?.substring(0, 16)}</span>
                            <span style={{ color: colors.green }}>+{ce.delta?.toFixed(3)}</span>
                          </div>
                          <div style={{ color: colors.cyan }}>C_emo {ce.c_emo_before?.toFixed(3)} → {ce.c_emo_after?.toFixed(3)}</div>
                        </div>
                      ))}
                    </>
                  ) : (
                    <div style={{ color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No CEE events yet</div>
                  )}
                  {selectedDetail?.drift_periods?.length > 0 && (
                    <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${colors.border}` }}>
                      <div style={{ color: colors.textSecondary, fontWeight: 600, marginBottom: 6 }}>Drift Periods</div>
                      {selectedDetail.drift_periods.map((dp, i) => (
                        <div key={i} style={{ padding: '4px 0', fontSize: 11 }}>
                          <span style={{ color: colors.orange }}>{dp.gap_days}d away</span>
                          <span style={{ color: colors.textSecondary }}> — {dp.explored ? '✅ explored' : '⏳ unexplored'}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {selectedDetail?.legacy_healing?.length > 0 && (
                    <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${colors.border}` }}>
                      <div style={{ color: colors.purple, fontWeight: 600, marginBottom: 6 }}>Legacy Healing</div>
                      {selectedDetail.legacy_healing.map((lh, i) => (
                        <div key={i} style={{ padding: '4px 0', fontSize: 11 }}>
                          <span>{lh.pattern?.replace(/_/g, ' ')}</span>
                          <span style={{ color: colors.green, marginLeft: 8 }}>{lh.corrective_count} corrective exp.</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </Card>

              <Card>
                <SectionTitle>Reply Therapy (3+3+3)</SectionTitle>
                <div style={{ fontSize: 12 }}>
                  {selectedDetail?.reply_therapy?.themes && Object.keys(selectedDetail.reply_therapy.themes).length > 0 ? (
                    <>
                      {selectedDetail.reply_therapy.active_theme && (
                        <div style={{ background: `${colors.purple}22`, border: `1px solid ${colors.purple}`, borderRadius: 6, padding: '6px 10px', marginBottom: 10, fontSize: 11 }}>
                          <span style={{ color: colors.purple, fontWeight: 700 }}>ACTIVE: </span>
                          <span>{selectedDetail.reply_therapy.active_theme.replace(/_/g, ' ').toUpperCase()}</span>
                        </div>
                      )}
                      {selectedDetail.reply_therapy.completed_count > 0 && (
                        <div style={{ color: colors.green, fontWeight: 600, marginBottom: 8 }}>
                          {selectedDetail.reply_therapy.completed_count} completed Reply Therapy cycles
                        </div>
                      )}
                      {Object.entries(selectedDetail.reply_therapy.themes).map(([theme, data]) => (
                        <div key={theme} style={{ padding: '6px 0', borderBottom: `1px solid ${colors.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ color: data.threshold_met ? colors.green : colors.textPrimary }}>
                            {theme.replace(/_/g, ' ')}
                            {data.reply_completed && ' ✅'}
                          </span>
                          <div style={{ display: 'flex', gap: 6 }}>
                            <span style={{ color: colors.cyan, fontSize: 11 }}>M:{data.mismatch}/3</span>
                            <span style={{ color: colors.gold, fontSize: 11 }}>R:{data.reconsolidation}/3</span>
                            <span style={{ color: colors.purple, fontSize: 11 }}>E:{data.evocative}/3</span>
                          </div>
                        </div>
                      ))}
                    </>
                  ) : (
                    <div style={{ color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No Reply Therapy themes yet</div>
                  )}
                </div>
              </Card>

              <Card>
                <SectionTitle>Matchmaker Protocol</SectionTitle>
                <div style={{ textAlign: 'center', marginBottom: 16 }}>
                  <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 8 }}>Assigned Coach</div>
                  <div style={{ fontSize: 16, fontWeight: 'bold', color: colors.gold }}>{selectedUser.assigned_coach || 'Unassigned'}</div>
                </div>
                <Button variant="primary" style={{ width: '100%' }} onClick={() => apiFetch('/api/coach/matchmaker', { method: 'POST', body: JSON.stringify({ client_id: selectedUser.id }) }).then(r => r && alert(`Match: ${JSON.stringify(r)}`))}>Run Matchmaker Analysis</Button>
              </Card>
              
              <Card>
                <SectionTitle>Identity Resolution</SectionTitle>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <Button onClick={async () => {
                    if (!window.confirm('Reset password for ' + selectedUser.name + '?')) return;
                    const pw = window.prompt('Enter new password (min 6 chars):');
                    if (!pw || pw.length < 6) { alert('Password must be at least 6 characters.'); return; }
                    const r = await apiFetch('/api/admin/reset-password', { method: 'POST', body: JSON.stringify({ user_id: selectedUser.id, new_password: pw }) });
                    alert(r ? (r.message || 'Password reset.') : 'Failed to reset password.');
                  }}>🔑 Reset Password</Button>
                  <Button onClick={async () => {
                    if (!window.confirm('Reset biometrics for ' + selectedUser.name + '? They will need to re-enroll.')) return;
                    const r = await apiFetch('/api/admin/reset-biometrics', { method: 'POST', body: JSON.stringify({ user_id: selectedUser.id }) });
                    alert(r ? (r.message || 'Biometrics reset.') : 'Failed to reset biometrics.');
                  }}>🔐 Reset Biometrics</Button>
                  <Button variant="danger" onClick={async () => {
                    if (!window.confirm('BAN ' + selectedUser.name + '? This is irreversible.')) return;
                    const reason = window.prompt('Ban reason (optional):') || '';
                    const r = await apiFetch('/api/admin/ban-user', { method: 'POST', body: JSON.stringify({ user_id: selectedUser.id, reason }) });
                    alert(r ? (r.message || 'User banned.') : 'Failed to ban user.');
                  }}>🚫 Ban User</Button>
                  <Button variant="danger" onClick={async () => {
                    if (!window.confirm('WIPE ALL MEMORY for ' + selectedUser.name + '? This cannot be undone.')) return;
                    if (!window.confirm('FINAL CONFIRMATION: All conversation history, metrics, and session data will be permanently deleted. Proceed?')) return;
                    const r = await apiFetch('/api/admin/wipe-memory', { method: 'POST', body: JSON.stringify({ user_id: selectedUser.id }) });
                    alert(r ? (r.message || 'Memory wiped.') : 'Failed to wipe memory.');
                  }}>🗑️ Wipe Memory</Button>
                </div>
                <div style={{ marginTop: 12 }}>
                  <Button variant="danger" style={{ width: '100%' }} onClick={async () => {
                    if (selectedUser.role === 'ADMIN') { alert('Cannot delete admin accounts.'); return; }
                    if (!window.confirm('PERMANENTLY DELETE ' + selectedUser.name + '? This will remove all data, vault files, and anonymize the account. THIS CANNOT BE UNDONE.')) return;
                    const reason = window.prompt('Deletion reason (required):');
                    if (!reason || reason.trim().length < 3) { alert('A deletion reason is required.'); return; }
                    if (!window.confirm('FINAL CONFIRMATION: Delete ' + selectedUser.name + ' permanently?')) return;
                    const r = await apiFetch('/api/admin/delete-user', { method: 'POST', body: JSON.stringify({ user_id: selectedUser.id, reason }) });
                    if (r && r.status === 'deleted') {
                      alert(r.message || 'User deleted.');
                      setSelectedUser(null);
                      setSelectedDetail(null);
                      refreshUsers();
                    } else {
                      alert(r ? (r.detail || r.message || 'Failed to delete user.') : 'Failed to delete user.');
                    }
                  }}>⛔ Delete Account Permanently</Button>
                </div>
              </Card>
            </div>
            </>
            );
          })()
        ) : (
          <div style={{ textAlign: 'center', color: colors.textSecondary, marginTop: 100 }}>
            {loading ? 'Loading users...' : 'Select a user to view details'}
          </div>
        )}
      </div>
    </div>
  );
};

// =============================================================================
// SC_03: NIGHT SCHOOL
// =============================================================================

const NightSchoolScreen = () => {
  const [activeTab, setActiveTab] = useState('wisdom');
  const { data: nsStatus, refresh: refreshNS } = useApi('/api/admin/night-school/status');
  const { data: wisdomData, refresh: refreshWisdom } = useApi('/api/night-school/wisdom?limit=50');
  const { data: notesData, refresh: refreshNotes } = useApi('/api/night-school/notes?status=pending&limit=50');
  const { data: versionsData } = useApi('/api/night-school/versions');
  const { data: dojoScenariosData, refresh: refreshScenarios } = useApi('/api/night-school/dojo/scenarios?status=all');
  const { data: dojoMemoriesData } = useApi('/api/night-school/memories/dojo?limit=10');
  const [dojoPersona, setDojoPersona] = useState(null);

  const wisdomEntries = (wisdomData && wisdomData.entries) || [];
  const pendingNotes = (notesData && notesData.notes) || [];
  const versions = (versionsData && versionsData.versions) || [];
  const status = nsStatus || {};

  const handleApproveNote = async (noteId) => {
    await apiFetch(`/api/night-school/notes/${noteId}/review`, { method: 'POST', body: JSON.stringify({ action: 'approve' }) });
    refreshNotes();
  };
  const handleRejectNote = async (noteId) => {
    await apiFetch(`/api/night-school/notes/${noteId}/review`, { method: 'POST', body: JSON.stringify({ action: 'reject' }) });
    refreshNotes();
  };
  const handleRedactNote = async (noteId) => {
    await apiFetch(`/api/night-school/notes/${noteId}/review`, { method: 'POST', body: JSON.stringify({ action: 'redact' }) });
    refreshNotes();
  };
  const handleSnapshot = async () => {
    const result = await apiFetch('/api/night-school/snapshot', { method: 'POST' });
    if (result) alert('Snapshot created: ' + (result.version || 'OK'));
    refreshWisdom();
  };
  const handleStartDojo = async () => {
    if (!dojoPersona) { alert('Select a persona first'); return; }
    const result = await apiFetch('/api/night-school/dojo/start', { method: 'POST', body: JSON.stringify({ persona: dojoPersona }) });
    if (result) alert('Dojo session started: ' + JSON.stringify(result.session_id || result));
  };

  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ color: colors.purple, fontSize: 20, margin: '0 0 24px 0' }}>🎓 Night School Director</h1>
      
      <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
        {['wisdom', 'notes', 'dojo', 'versions'].map((tab) => (
          <button key={tab} onClick={() => setActiveTab(tab)} style={{
            padding: '10px 20px',
            background: activeTab === tab ? colors.purpleDim : colors.bgCard,
            border: `1px solid ${activeTab === tab ? colors.purple : colors.border}`,
            color: activeTab === tab ? colors.purple : colors.textSecondary,
            borderRadius: 8, fontSize: 12, cursor: 'pointer', textTransform: 'capitalize',
          }}>
            {tab === 'wisdom' ? '📚 Wisdom' : tab === 'notes' ? '📝 Notes Queue' : tab === 'dojo' ? '🥋 The Dojo' : '⏱️ Versions'}
          </button>
        ))}
      </div>
      
      {activeTab === 'wisdom' && (
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 24 }}>
          <Card>
            <SectionTitle badge={wisdomEntries.length}>Wisdom Entries</SectionTitle>
            {wisdomEntries.length === 0 && <div style={{ color: colors.textSecondary, fontSize: 12, padding: 12 }}>No wisdom entries yet</div>}
            {wisdomEntries.map((entry, idx) => (
              <div key={entry.id || idx} style={{ padding: 12, borderBottom: `1px solid ${colors.border}` }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <Badge color={colors.purple}>{entry.category || 'general'}</Badge>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 10, color: colors.textSecondary }}>Confidence: {((entry.confidence || 0) * 100).toFixed(0)}%</span>
                    <Badge color={entry.approved ? colors.green : colors.orange}>{entry.approved ? 'APPROVED' : 'PENDING'}</Badge>
                  </div>
                </div>
                <div style={{ fontSize: 12, color: colors.textSecondary }}>{entry.content}</div>
              </div>
            ))}
          </Card>
          
          <Card>
            <SectionTitle>Quick Stats</SectionTitle>
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: colors.purple }}>{status.total_learnings || wisdomEntries.length}</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Total Entries</div>
            </div>
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: colors.green }}>{wisdomEntries.filter(e => e.approved).length}</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Approved</div>
            </div>
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: colors.orange }}>{wisdomEntries.filter(e => !e.approved).length}</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Pending Review</div>
            </div>
            <div style={{ fontSize: 10, color: colors.textSecondary, marginBottom: 8 }}>Last synthesis: {status.last_synthesis || 'Never'}</div>
            <Button style={{ marginTop: 8, width: '100%' }} onClick={handleSnapshot}>📸 Create Snapshot</Button>
          </Card>
        </div>
      )}
      
      {activeTab === 'notes' && (
        <Card>
          <SectionTitle badge={pendingNotes.length}>Pending Coach Notes</SectionTitle>
          {pendingNotes.length === 0 && <div style={{ color: colors.textSecondary, fontSize: 12, padding: 12 }}>No pending notes</div>}
          {pendingNotes.map((note, idx) => (
            <div key={note.id || idx} style={{ padding: 16, borderBottom: `1px solid ${colors.border}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div>
                  <span style={{ fontWeight: 'bold' }}>{note.coach_name || note.coach_id || 'Coach'}</span>
                  <span style={{ color: colors.textSecondary }}> → {note.client_name || note.client_id || 'Client'}</span>
                </div>
                {note.pii_detected && <Badge color={colors.orange}>⚠️ PII DETECTED</Badge>}
              </div>
              <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 12, padding: 12, background: colors.bgElevated, borderRadius: 8 }}>
                {note.content}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Button variant="success" style={{ flex: 1 }} onClick={() => handleApproveNote(note.id)}>✓ Approve</Button>
                <Button variant="danger" style={{ flex: 1 }} onClick={() => handleRejectNote(note.id)}>✗ Reject</Button>
                <Button style={{ flex: 1 }} onClick={() => handleRedactNote(note.id)}>✏️ Redact</Button>
              </div>
            </div>
          ))}
        </Card>
      )}
      
      {activeTab === 'dojo' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
          <Card>
            <SectionTitle>🥋 The Dojo - Adversarial Testing</SectionTitle>
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 8 }}>Select Persona:</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
                {['HOSTILE', 'CRISIS', 'SKEPTIC', 'MINOR', 'MANIPULATIVE', 'BOUNDARY'].map((persona) => (
                  <Button key={persona} style={{ fontSize: 10, border: dojoPersona === persona ? `2px solid ${colors.purple}` : undefined }} onClick={() => setDojoPersona(persona)}>{persona}</Button>
                ))}
              </div>
            </div>
            <Button variant="primary" style={{ width: '100%' }} onClick={handleStartDojo}>Start Dojo Session</Button>
          </Card>
          
          <Card>
            <SectionTitle badge={((dojoScenariosData && dojoScenariosData.scenarios) || []).length}>Recent Dojo Results</SectionTitle>
            {(() => {
              const scenarios = (dojoScenariosData && dojoScenariosData.scenarios) || [];
              const memories = (dojoMemoriesData && dojoMemoriesData.memories) || [];
              if (scenarios.length === 0 && memories.length === 0) {
                return (
                  <div style={{ textAlign: 'center', padding: 24 }}>
                    <div style={{ fontSize: 48, marginBottom: 8 }}>🥋</div>
                    <div style={{ fontSize: 14, fontWeight: 'bold', color: colors.textSecondary }}>No sessions yet</div>
                    <div style={{ fontSize: 11, color: colors.textSecondary }}>Select a persona and start a session</div>
                  </div>
                );
              }
              return (
                <div>
                  {scenarios.slice(0, 5).map((s, i) => (
                    <div key={s.id || i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: `1px solid ${colors.border}` }}>
                      <div>
                        <div style={{ fontSize: 12, fontWeight: 'bold' }}>{s.persona || s.skill_target || 'Session'}</div>
                        <div style={{ fontSize: 10, color: colors.textSecondary }}>{s.created_at || s.date || ''}</div>
                      </div>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        {s.violation_count != null && (
                          <Badge color={s.violation_count > 0 ? colors.red : colors.green}>
                            {s.violation_count > 0 ? `${s.violation_count} violation${s.violation_count !== 1 ? 's' : ''}` : 'Clean'}
                          </Badge>
                        )}
                        <Badge color={s.status === 'completed' ? colors.green : s.status === 'active' ? colors.cyan : colors.textSecondary}>
                          {(s.status || 'queued').toUpperCase()}
                        </Badge>
                      </div>
                    </div>
                  ))}
                  {memories.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <div style={{ fontSize: 10, color: colors.purple, fontWeight: 'bold', marginBottom: 6 }}>Training Memories</div>
                      {memories.slice(0, 3).map((m, i) => (
                        <div key={i} style={{ fontSize: 10, color: colors.textSecondary, padding: '4px 0', borderBottom: `1px solid ${colors.border}` }}>
                          {m.summary || m.content || JSON.stringify(m).slice(0, 80)}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })()}
          </Card>
        </div>
      )}
      
      {activeTab === 'versions' && (
        <Card>
          <SectionTitle>Version History (Time Travel)</SectionTitle>
          <div style={{ fontFamily: 'monospace', fontSize: 11 }}>
            {versions.length === 0 && <div style={{ color: colors.textSecondary, padding: 12 }}>No versions recorded yet</div>}
            {versions.map((v, idx) => (
              <div key={v.version || idx} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: 12, borderBottom: `1px solid ${colors.border}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ color: colors.purple }}>{v.version || `v${idx + 1}`}</span>
                  <span style={{ color: colors.textSecondary }}>{v.date || v.created_at || ''}</span>
                  <span style={{ color: colors.textSecondary }}>{v.entries || v.entry_count || 0} entries</span>
                  {idx === 0 && <Badge color={colors.green}>CURRENT</Badge>}
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <Button style={{ padding: '4px 8px', fontSize: 10 }} onClick={() => { const current = versions[0] && (versions[0].version || 0); apiFetch(`/api/night-school/versions/compare?version_a=${current}&version_b=${v.version || idx}`).then(r => r && alert(JSON.stringify(r))); }}>Compare</Button>
                  {idx > 0 && <Button style={{ padding: '4px 8px', fontSize: 10 }} onClick={() => { if (window.confirm('Revert to this version?')) apiFetch(`/api/night-school/versions/${v.version || idx}/revert`, { method: 'POST' }); }}>Revert</Button>}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
};

// =============================================================================
// SC_04: THE EYE (ANALYTICS)
// =============================================================================

const TheEyeScreen = () => {
  const { data: tokenData } = useApi('/api/admin/token-economics');
  const { data: metricsData } = useApi('/api/admin/analytics/metrics-distribution');
  const { data: tierData } = useApi('/api/admin/billing/tier-config');
  const tokens = tokenData || {};
  const daily = (tokens.daily_usage || []);
  const todayTokens = daily.length > 0 ? daily[0].tokens || 0 : 0;
  const weekTokens = daily.slice(0, 7).reduce((s, d) => s + (d.tokens || 0), 0);
  const monthTokens = tokens.total_tokens_30d || 0;
  const costToday = (todayTokens * 6 / 1_000_000).toFixed(2);
  const costWeek = (weekTokens * 6 / 1_000_000).toFixed(2);
  const costMonth = tokens.estimated_cost_30d_usd || 0;
  const dist = metricsData || {};
  const tiers = (tierData && tierData.tiers) || [];

  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ color: colors.gold, fontSize: 20, margin: '0 0 24px 0' }}>👁️ The Eye - Analytics & Surveillance</h1>
      
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 24 }}>
        <div>
          <Card style={{ marginBottom: 24 }}>
            <SectionTitle>Token Economics Monitor</SectionTitle>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginBottom: 16 }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 24, fontWeight: 'bold', color: colors.cyan }}>${costToday}</div>
                <div style={{ fontSize: 10, color: colors.textSecondary }}>Today ({todayTokens.toLocaleString()} tokens)</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 24, fontWeight: 'bold', color: colors.gold }}>${costWeek}</div>
                <div style={{ fontSize: 10, color: colors.textSecondary }}>This Week</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 24, fontWeight: 'bold', color: colors.purple }}>${costMonth}</div>
                <div style={{ fontSize: 10, color: colors.textSecondary }}>This Month (30d)</div>
              </div>
            </div>
            <div style={{ fontSize: 10, color: colors.textSecondary, textAlign: 'center' }}>{tokens.pricing_note || ''}</div>
          </Card>
          
          <Card>
            <SectionTitle>Client Metrics Distribution</SectionTitle>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div style={{ textAlign: 'center', padding: 16, background: colors.cyanDim, borderRadius: 8 }}>
                <div style={{ fontSize: 11, color: colors.textSecondary }}>Avg GAP Score</div>
                <div style={{ fontSize: 24, fontWeight: 'bold', color: colors.cyan }}>{((dist.gap_scores || {}).average || 0).toFixed(3)}</div>
              </div>
              <div style={{ textAlign: 'center', padding: 16, background: colors.purpleDim, borderRadius: 8 }}>
                <div style={{ fontSize: 11, color: colors.textSecondary }}>High Anxiety Count</div>
                <div style={{ fontSize: 24, fontWeight: 'bold', color: colors.purple }}>{(dist.anxiety_levels || {}).high_count || 0}</div>
              </div>
            </div>
            {dist.risk_distribution && (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 8 }}>Risk Distribution ({dist.total_clients || 0} clients)</div>
                {Object.entries(dist.risk_distribution).map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 12 }}>
                    <span>{k}</span>
                    <Badge color={k === 'CRITICAL' ? colors.red : k === 'HIGH' ? colors.orange : colors.textSecondary}>{v}</Badge>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
        
        <div>
          <Card style={{ marginBottom: 24 }}>
            <SectionTitle badge={tiers.length || null}>Tier Feature Controls</SectionTitle>
            {tiers.length === 0 && <div style={{ color: colors.textSecondary, fontSize: 11, padding: 12 }}>Loading tier config...</div>}
            {tiers.map((t) => (
              <div key={t.key} style={{ padding: 12, borderBottom: `1px solid ${colors.border}` }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontWeight: 'bold', color: t.key === 'TOP_TIER' ? colors.gold : colors.textPrimary }}>{t.label}</span>
                  <span style={{ fontSize: 11, color: colors.textSecondary }}>
                    {t.price_display}{t.subscriber_count > 0 ? ` · ${t.subscriber_count} users` : ''}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {Object.entries(t.features || {}).map(([feat, enabled]) => (
                    <Badge key={feat} color={enabled ? colors.green : colors.textSecondary}>
                      {feat.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())} {enabled ? '✓' : '✗'}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </Card>
          
          <Card>
            <SectionTitle>Token Usage (Last 7 Days)</SectionTitle>
            {daily.slice(0, 7).map((d, i) => (
              <div key={d.date || i} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 11, borderBottom: `1px solid ${colors.border}` }}>
                <span style={{ color: colors.textSecondary }}>{d.date}</span>
                <span>{(d.tokens || 0).toLocaleString()} tkns</span>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </div>
  );
};

// =============================================================================
// SC_05: AUDIT LOG
// =============================================================================

const AuditLogScreen = () => {
  const [searchTerm, setSearchTerm] = useState('');
  const [actionFilter, setActionFilter] = useState('All Actions');
  const { data: eventsData, loading } = useApi('/api/admin/analytics/events?limit=200');
  const allEvents = (eventsData && eventsData.events) || [];

  const filteredEvents = allEvents.filter(e => {
    if (!e || typeof e !== 'object') return false;
    const matchesSearch = !searchTerm || JSON.stringify(e).toLowerCase().includes(searchTerm.toLowerCase());
    const eType = (e.event_type || e.type || '').toUpperCase();
    const matchesAction = actionFilter === 'All Actions' || eType.includes(actionFilter);
    return matchesSearch && matchesAction;
  });

  const handleExport = () => {
    const csv = ['Timestamp,Type,Data'].concat(filteredEvents.map(e => `"${e.timestamp || e.date || ''}","${e.event_type || e.type || ''}","${(e.message || JSON.stringify(e.data || {})).replace(/"/g, '""')}"`)).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = `audit_log_${new Date().toISOString().split('T')[0]}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ color: colors.gold, fontSize: 20, margin: '0 0 24px 0' }}>📜 Sovereignty Audit Log</h1>
      
      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <input type="text" placeholder="Search audit log..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} style={{ flex: 1, padding: '10px 12px', background: colors.bgElevated, border: `1px solid ${colors.border}`, borderRadius: 8, color: colors.textPrimary, fontSize: 12 }} />
          <select value={actionFilter} onChange={e => setActionFilter(e.target.value)} style={{ padding: '10px 12px', background: colors.bgElevated, border: `1px solid ${colors.border}`, borderRadius: 8, color: colors.textPrimary, fontSize: 12 }}>
            <option>All Actions</option>
            <option>ACCESS</option>
            <option>MODIFY</option>
            <option>APPROVE</option>
            <option>SECURITY</option>
            <option>SESSION</option>
          </select>
          <Button variant="primary" onClick={handleExport}>Export CSV</Button>
        </div>
      </Card>
      
      <Card>
        {loading ? <div style={{ color: colors.textSecondary, padding: 12 }}>Loading audit events...</div> : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ color: colors.textSecondary, textAlign: 'left', borderBottom: `1px solid ${colors.border}` }}>
              <th style={{ padding: 12 }}>Timestamp</th>
              <th style={{ padding: 12 }}>Type</th>
              <th style={{ padding: 12 }}>Details</th>
            </tr>
          </thead>
          <tbody>
            {filteredEvents.length === 0 && <tr><td colSpan={3} style={{ padding: 12, color: colors.textSecondary }}>No audit events found</td></tr>}
            {filteredEvents.slice(0, 100).map((entry, idx) => (
              <tr key={entry.id || idx} style={{ borderBottom: `1px solid ${colors.border}` }}>
                <td style={{ padding: 12, fontFamily: 'monospace', fontSize: 10 }}>{entry.timestamp || entry.date || ''}</td>
                <td style={{ padding: 12 }}>
                  <Badge color={
                    (entry.event_type || '').includes('approve') ? colors.green :
                    (entry.event_type || '').includes('security') ? colors.red :
                    colors.cyan
                  }>
                    {(entry.event_type || entry.type || 'UNKNOWN').toUpperCase()}
                  </Badge>
                </td>
                <td style={{ padding: 12, color: colors.textSecondary, maxWidth: 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {entry.message || JSON.stringify(entry.data || {}).slice(0, 120)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        )}
      </Card>
      
      <div style={{ marginTop: 16, padding: 12, background: colors.redDim, border: `1px solid ${colors.red}`, borderRadius: 8, fontSize: 11 }}>
        <strong style={{ color: colors.red }}>🔒 IMMUTABLE LOG:</strong>
        <span style={{ color: colors.textSecondary }}> This audit log cannot be modified or deleted. All entries are permanent. ({filteredEvents.length} events shown)</span>
      </div>
    </div>
  );
};

// =============================================================================
// SC_06: NATE FEATURES
// =============================================================================

const NateFeaturesScreen = () => {
  const { data: dashData } = useApi('/api/admin/dashboard');
  const { data: fibreData } = useApi('/api/fibres');
  const { data: meshData } = useApi('/api/mesh/health');
  const { data: crisisData } = useApi('/api/admin/crisis-watchlist');
  const { data: aiModesData } = useApi('/api/ai-modes/status');
  const { data: settingsData, refresh: refreshSettings } = useApi('/api/admin/settings');

  const [silenceThreshold, setSilenceThreshold] = useState(3);
  const [retentionPolicy, setRetentionPolicy] = useState('forever');
  const [settingsSaving, setSettingsSaving] = useState(false);

  // Sync settings from API on load
  useEffect(() => {
    if (settingsData && settingsData.settings) {
      setSilenceThreshold(settingsData.settings.deadman_silence_threshold_days || 3);
      setRetentionPolicy(settingsData.settings.memory_retention_policy || 'forever');
    }
  }, [settingsData]);

  const saveSetting = async (key, value) => {
    setSettingsSaving(true);
    await apiFetch('/api/admin/settings', { method: 'POST', body: JSON.stringify({ key, value }) });
    setSettingsSaving(false);
    refreshSettings();
  };

  const totalUsers = (dashData && dashData.users) ? dashData.users.total : 0;
  const crisisCount = (crisisData && crisisData.count) || 0;
  const fibres = (fibreData && fibreData.fibres) || [];
  const mesh = meshData || {};
  const aiModes = (aiModesData && aiModesData.modes) || ['Empathetic', 'Directive', 'Socratic', 'Crisis'];

  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ color: colors.cyan, fontSize: 20, margin: '0 0 24px 0' }}>🧠 Little Nate AI Features</h1>
      
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
        <Card>
          <SectionTitle>💀 Deadman Switch</SectionTitle>
          <div style={{ textAlign: 'center', marginBottom: 16 }}>
            <div style={{ fontSize: 48, marginBottom: 8 }}>🟢</div>
            <div style={{ fontSize: 16, fontWeight: 'bold', color: colors.green }}>ACTIVE</div>
            <div style={{ fontSize: 10, color: colors.textSecondary }}>Monitoring {totalUsers} users</div>
          </div>
          <div style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
              <span>Silence Threshold</span>
              <span>{silenceThreshold} day{silenceThreshold !== 1 ? 's' : ''}</span>
            </div>
            <input type="range" min="1" max="7" value={silenceThreshold} onChange={(e) => setSilenceThreshold(Number(e.target.value))} onMouseUp={() => saveSetting('deadman_silence_threshold_days', silenceThreshold)} style={{ width: '100%' }} />
          </div>
          {crisisCount > 0 && (
            <div style={{ padding: 12, background: colors.redDim, borderRadius: 8, marginBottom: 12 }}>
              <div style={{ fontSize: 11, color: colors.red, fontWeight: 'bold' }}>{crisisCount} users on crisis watchlist</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Guardians notified automatically</div>
            </div>
          )}
          <div style={{ fontSize: 10, color: settingsSaving ? colors.gold : colors.textSecondary, textAlign: 'center', marginTop: 4 }}>{settingsSaving ? 'Saving...' : 'Settings auto-save on change'}</div>
        </Card>
        
        <Card>
          <SectionTitle>🐝 Swarm Intelligence</SectionTitle>
          <div style={{ textAlign: 'center', marginBottom: 16 }}>
            <div style={{ fontSize: 48, marginBottom: 8 }}>👨‍👩‍👧‍👦</div>
            <div style={{ fontSize: 16, fontWeight: 'bold', color: colors.purple }}>
              {fibres.length > 0 ? 'Family Correlation Active' : 'Initializing...'}
            </div>
            <div style={{ fontSize: 10, color: colors.textSecondary }}>Analyzing cross-member patterns</div>
          </div>
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 4 }}>Active Fibres</div>
            <div style={{ fontSize: 24, fontWeight: 'bold', color: colors.purple }}>{fibres.length}</div>
            <div style={{ fontSize: 10, color: colors.textSecondary }}>Mesh messages: {mesh.total_messages || 0}</div>
          </div>
          <Button style={{ width: '100%' }} onClick={() => window.location.hash = '#swarm-ops'}>View Swarm Matrix</Button>
        </Card>
        
        <Card>
          <SectionTitle>🎭 AI Response Modes</SectionTitle>
          {(Array.isArray(aiModes) ? aiModes : ['Empathetic', 'Directive', 'Socratic', 'Crisis']).map((mode) => {
            const modeName = typeof mode === 'string' ? mode : mode.name || 'Unknown';
            return (
              <div key={modeName} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: `1px solid ${colors.border}` }}>
                <span>{modeName} Mode</span>
                <Badge color={modeName === 'Crisis' ? colors.red : colors.green}>
                  {modeName === 'Crisis' ? 'AUTO-TRIGGER' : 'ENABLED'}
                </Badge>
              </div>
            );
          })}
        </Card>
        
        <Card>
          <SectionTitle>🧬 Memory Controls</SectionTitle>
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 4 }}>System Status</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <StatusDot status="online" />
              <span style={{ color: colors.green }}>Active — {totalUsers} user records</span>
            </div>
          </div>
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 4 }}>Retention Policy</div>
            <select value={retentionPolicy} onChange={(e) => { setRetentionPolicy(e.target.value); saveSetting('memory_retention_policy', e.target.value); }} style={{ width: '100%', padding: 8, background: colors.bgElevated, border: `1px solid ${colors.border}`, borderRadius: 8, color: colors.textPrimary }}>
              <option value="forever">Forever (with consent)</option>
              <option value="1_year">1 Year</option>
              <option value="6_months">6 Months</option>
            </select>
          </div>
          <Button variant="danger" style={{ width: '100%' }} onClick={() => { if (window.confirm('EMERGENCY MEMORY PURGE: This will delete ALL session memories for ALL users. This CANNOT be undone. Are you absolutely sure?')) { apiFetch('/api/admin/emergency-purge', { method: 'POST' }).then(() => alert('Memory purge initiated.')); } }}>🗑️ Emergency Memory Purge</Button>
        </Card>
      </div>
    </div>
  );
};

// =============================================================================
// SC_07: NEVEDAL LAB
// =============================================================================

const NevedalLabScreen = () => {
  const { data: communityData } = useApi('/api/admin/community-health');
  const { data: sessionsData } = useApi('/api/admin/live-sessions');
  const { data: metricsData } = useApi('/api/admin/analytics/metrics-distribution');

  const community = communityData || {};
  const liveSessions = (sessionsData && sessionsData.sessions) || [];
  const dist = metricsData || {};
  const avgCEmo = community.avg_c_emo || 0;
  const ceeWindows = community.active_cee_windows || 0;

  const handleReport = async (type) => {
    const result = await apiFetch(`/api/nevedal-reports/generate`, { method: 'POST', body: JSON.stringify({ report_type: type }) });
    if (result) alert(`Report generated: ${result.report_id || JSON.stringify(result)}`);
    else alert(`Report request sent for: ${type}`);
  };

  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ color: colors.purple, fontSize: 20, margin: '0 0 24px 0' }}>🔬 Nevedal Research Laboratory</h1>
      
      <Card style={{ marginBottom: 24, background: colors.purpleDim, border: `1px solid ${colors.purple}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{ fontSize: 32 }}>📐</div>
          <div>
            <div style={{ fontFamily: 'serif', fontSize: 16, color: colors.purple }}>
              C<sub>emo</sub>(t) = [β · p<sub>ent</sub> · T<sub>tunnel</sub>] / [γ<sub>env</sub> + E<sub>G</sub><sup>(joint)</sup>/ℏ]
            </div>
            <div style={{ fontSize: 10, color: colors.textSecondary }}>Quantum Emotional Coherence Formula</div>
          </div>
        </div>
      </Card>
      
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 24, marginBottom: 24 }}>
        <Card style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 8 }}>Community C_emo</div>
          <div style={{ fontSize: 36, fontWeight: 'bold', color: colors.cyan }}>{avgCEmo.toFixed(3)}</div>
          <ProgressBar value={avgCEmo * 100} max={100} color={colors.cyan} />
        </Card>
        <Card style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 8 }}>Active CEE Windows</div>
          <div style={{ fontSize: 36, fontWeight: 'bold', color: colors.green }}>{ceeWindows}</div>
          <div style={{ fontSize: 10, color: colors.textSecondary }}>{community.clients_with_data || 0} clients with data</div>
        </Card>
        <Card style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 8 }}>Avg GAP Score</div>
          <div style={{ fontSize: 36, fontWeight: 'bold', color: colors.purple }}>{((dist.gap_scores || {}).average || 0).toFixed(3)}</div>
          <div style={{ fontSize: 10, color: colors.textSecondary }}>{dist.total_clients || 0} clients measured</div>
        </Card>
      </div>
      
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
        <Card>
          <SectionTitle badge={`${liveSessions.length} Active`}>Live Session Nevedal Streams</SectionTitle>
          {liveSessions.length === 0 && <div style={{ color: colors.textSecondary, fontSize: 12, padding: 12 }}>No active sessions</div>}
          {liveSessions.slice(0, 5).map((session, idx) => (
            <div key={session.session_id || idx} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 0', borderBottom: `1px solid ${colors.border}` }}>
              <div>
                <div style={{ fontWeight: 'bold' }}>{session.client_id}</div>
                <div style={{ fontSize: 10, color: colors.textSecondary }}>Type: {session.session_type || 'ai'}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 16, fontWeight: 'bold', color: colors.cyan }}>{session.mood || '--'}</div>
                <div style={{ fontSize: 9, color: colors.textSecondary }}>Mood</div>
              </div>
            </div>
          ))}
          <Button style={{ marginTop: 12, width: '100%' }} onClick={() => window.open('/nevedal_lab_live.html', '_blank')}>Open Real-time Dashboard</Button>
        </Card>
        
        <Card>
          <SectionTitle>Research Tools</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Button style={{ height: 80, flexDirection: 'column', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => handleReport('community_coherence')}>
              <span style={{ fontSize: 24 }}>📊</span>
              <span style={{ fontSize: 10, marginTop: 4 }}>Generate Report</span>
            </Button>
            <Button style={{ height: 80, flexDirection: 'column', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => handleReport('dyad_analysis')}>
              <span style={{ fontSize: 24 }}>👥</span>
              <span style={{ fontSize: 10, marginTop: 4 }}>Dyad Analysis</span>
            </Button>
            <Button style={{ height: 80, flexDirection: 'column', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => handleReport('family_matrix')}>
              <span style={{ fontSize: 24 }}>👨‍👩‍👧‍👦</span>
              <span style={{ fontSize: 10, marginTop: 4 }}>Family Matrix</span>
            </Button>
            <Button style={{ height: 80, flexDirection: 'column', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => handleReport('longitudinal')}>
              <span style={{ fontSize: 24 }}>📈</span>
              <span style={{ fontSize: 10, marginTop: 4 }}>Longitudinal</span>
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
};

// =============================================================================
// SC_08: DEPENDENCY GUARDIAN
// =============================================================================

const SEVERITY_COLORS = {
  CRITICAL: '#EF4444',
  WARNING: '#F59E0B',
  INFO: '#3B82F6',
  OK: '#22C55E',
};

const DependencyGuardianScreen = () => {
  const { data: report, loading, refresh } = useApi('/api/admin/dependency-report');
  const [running, setRunning] = useState(false);
  const [filter, setFilter] = useState('all');

  const triggerAudit = async () => {
    setRunning(true);
    await apiFetch('/api/admin/run-dependency-audit', { method: 'POST' });
    setRunning(false);
    refresh();
  };

  const summary = (report && report.summary) || {};
  const findings = (report && report.findings) || [];
  const ts = report && report.timestamp ? new Date(report.timestamp).toLocaleString() : 'Never';

  const filtered = filter === 'all'
    ? findings
    : findings.filter(f => f.severity === filter.toUpperCase());

  const categories = [...new Set(findings.map(f => f.category))];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ color: colors.gold, fontSize: 20, margin: 0 }}>Dependency Guardian</h1>
          <div style={{ fontSize: 11, color: colors.textSecondary, marginTop: 4 }}>Last audit: {ts}</div>
        </div>
        <button
          onClick={triggerAudit}
          disabled={running}
          style={{
            padding: '10px 20px', background: running ? colors.bgElevated : colors.gold,
            color: colors.bgDark, border: 'none', borderRadius: 8, cursor: running ? 'wait' : 'pointer',
            fontWeight: 'bold', fontSize: 12,
          }}
        >
          {running ? 'Auditing...' : 'Run Audit Now'}
        </button>
      </div>

      {loading ? (
        <div style={{ color: colors.textSecondary, padding: 40, textAlign: 'center' }}>Loading report...</div>
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 1fr', gap: 12, marginBottom: 24 }}>
            {[
              { label: 'Critical', count: summary.critical || 0, color: SEVERITY_COLORS.CRITICAL, key: 'CRITICAL' },
              { label: 'Warning', count: summary.warning || 0, color: SEVERITY_COLORS.WARNING, key: 'WARNING' },
              { label: 'Info', count: summary.info || 0, color: SEVERITY_COLORS.INFO, key: 'INFO' },
              { label: 'OK', count: summary.ok || 0, color: SEVERITY_COLORS.OK, key: 'OK' },
              { label: 'Total', count: summary.total || 0, color: colors.textPrimary, key: 'all' },
            ].map(s => (
              <div
                key={s.key}
                onClick={() => setFilter(s.key === filter ? 'all' : s.key)}
                style={{
                  background: filter === s.key ? colors.bgElevated : colors.bgCard,
                  border: `1px solid ${filter === s.key ? s.color : colors.border}`,
                  borderRadius: 8, padding: 16, textAlign: 'center', cursor: 'pointer',
                }}
              >
                <div style={{ fontSize: 28, fontWeight: 'bold', color: s.color }}>{s.count}</div>
                <div style={{ fontSize: 10, color: colors.textSecondary, marginTop: 4 }}>{s.label}</div>
              </div>
            ))}
          </div>

          {categories.map(cat => {
            const catFindings = filtered.filter(f => f.category === cat);
            if (catFindings.length === 0) return null;
            const catLabel = { python: 'Python Packages', node: 'Node Packages', flutter: 'Flutter Packages', docker: 'Docker Images', api_keys: 'API Keys', playwright: 'Playwright / Chromium' }[cat] || cat;
            return (
              <Card key={cat} style={{ marginBottom: 16 }}>
                <SectionTitle badge={catFindings.length}>{catLabel}</SectionTitle>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                  <thead>
                    <tr style={{ color: colors.textSecondary, textAlign: 'left', borderBottom: `1px solid ${colors.border}` }}>
                      <th style={{ padding: '8px 12px', width: 80 }}>Status</th>
                      <th style={{ padding: '8px 12px' }}>Package</th>
                      <th style={{ padding: '8px 12px' }}>Current</th>
                      <th style={{ padding: '8px 12px' }}>Latest</th>
                      <th style={{ padding: '8px 12px' }}>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {catFindings.map((f, idx) => (
                      <tr key={idx} style={{ borderBottom: `1px solid ${colors.border}` }}>
                        <td style={{ padding: '8px 12px' }}>
                          <span style={{
                            display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 9, fontWeight: 'bold',
                            background: `${SEVERITY_COLORS[f.severity]}22`, color: SEVERITY_COLORS[f.severity],
                          }}>
                            {f.severity}
                          </span>
                        </td>
                        <td style={{ padding: '8px 12px', fontFamily: 'monospace' }}>{f.package}</td>
                        <td style={{ padding: '8px 12px', fontFamily: 'monospace', color: colors.textSecondary }}>{f.current || '--'}</td>
                        <td style={{ padding: '8px 12px', fontFamily: 'monospace', color: f.severity !== 'OK' ? SEVERITY_COLORS[f.severity] : colors.textSecondary }}>{f.latest || '--'}</td>
                        <td style={{ padding: '8px 12px', color: colors.textSecondary, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            );
          })}

          {findings.length === 0 && (
            <Card style={{ textAlign: 'center', padding: 40 }}>
              <div style={{ fontSize: 14, color: colors.textSecondary }}>No audit data yet. Click "Run Audit Now" to start the first scan.</div>
            </Card>
          )}
        </>
      )}
    </div>
  );
};

// =============================================================================
// MAIN APP
// =============================================================================

export default function SovereignCommand() {
  const [activeScreen, setActiveScreen] = useState('dashboard');
  
  const renderScreen = () => {
    switch (activeScreen) {
      case 'dashboard': return <DashboardScreen />;
      case 'users': return <UserManagementScreen />;
      case 'revenue': return <RevenueDashboard />;
      case 'night-school': return <NightSchoolScreen />;
      case 'the-eye': return <TheEyeScreen />;
      case 'audit': return <AuditLogScreen />;
      case 'nate': return <NateFeaturesScreen />;
      case 'nevedal': return <NevedalLabScreen />;
      case 'the-pulse': return <ThePulse />;
      case 'strategic-memory': return <StrategicMemory />;
      case 'swarm-ops': return <SwarmOperations />;
      case 'foresight': return <ForesightDashboard />;
      case 'family-patterns': return <FamilyPatterns />;
      case 'architecture': return <SovereigntyWireframe />;
      case 'wire-diagram': return <SovereignSwarmWireDiagram />;
      case 'quakete': return <QuaketeMap />;
      case 'big-nate': return <BigNateChat />;
      case 'zefcp': return <ZEFCPMonitor />;
      case 'hive-defense': return <HiveDefenseDashboard />;
      case 'dependency-guardian': return <DependencyGuardianScreen />;
      default: return <DashboardScreen />;
    }
  };
  
  return (
    <div style={{ display: 'flex', height: '100vh', background: colors.bgDark, color: colors.textPrimary, fontFamily: "'Segoe UI', system-ui, sans-serif" }}>
      <Sidebar activeScreen={activeScreen} setActiveScreen={setActiveScreen} />
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {renderScreen()}
      </div>
    </div>
  );
}
