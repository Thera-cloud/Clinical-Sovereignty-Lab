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
// MOCK DATA
// =============================================================================

const mockData = {
  systemStatus: {
    bridge: 'online',
    azure: 'online',
    nightSchool: 'training',
  },
  metrics: {
    activeUsers: 847,
    liveSessions: 23,
    coachesOnline: 12,
    criticalAlerts: 2,
  },
  crisisWatchlist: [
    { id: '1', name: 'Alex M.', severity: 'critical', trigger: 'Keyword: "end it"', duration: '3 days silent', userId: 'CLI_089' },
    { id: '2', name: 'Jordan K.', severity: 'warning', trigger: '988 mentioned', duration: '1 day silent', userId: 'CLI_156' },
    { id: '3', name: 'Sam R.', severity: 'monitoring', trigger: 'Coach flagged', duration: 'Active today', userId: 'CLI_203' },
  ],
  liveSessions: [
    { id: '1', name: 'Emma T.', type: 'AI', duration: '12:34', coach: null, tier: 'TOP', tokensUsed: 2340 },
    { id: '2', name: 'Michael C.', type: 'COACH', duration: '45:12', coach: 'Dr. Hope', tier: 'STANDARD', tokensUsed: 890 },
    { id: '3', name: 'Sarah L.', type: 'FAMILY', duration: '23:45', coach: 'Dr. Smith', tier: 'STANDARD', tokensUsed: 1560 },
  ],
  pendingApprovals: [
    { id: '1', name: 'Dr. James Wilson', specialty: 'Anxiety', submitted: '2 days ago' },
    { id: '2', name: 'Dr. Maria Santos', specialty: 'Family', submitted: '5 days ago' },
  ],
  communityHealth: {
    anxiety: 67,
    stability: 82,
    engagement: 91,
  },
  tokenEconomics: {
    dailySpend: 1247,
    dailyBudget: 2000,
  },
  activityFeed: [
    { time: '2m ago', event: 'Crisis alert triggered', type: 'alert' },
    { time: '5m ago', event: 'New coach Dr. Wilson pending approval', type: 'info' },
    { time: '12m ago', event: 'Night School completed training cycle', type: 'success' },
    { time: '1h ago', event: 'Token budget 60% consumed', type: 'warning' },
  ],
  users: [
    { id: 'CLI_001', name: 'Emma Thompson', role: 'CLIENT', tier: 'TOP', familyId: 'FAM_001', status: 'active' },
    { id: 'CLI_002', name: 'Michael Chen', role: 'CLIENT', tier: 'STANDARD', familyId: null, status: 'active' },
    { id: 'COA_001', name: 'Dr. Sarah Hope', role: 'COACH', tier: 'MASTER', familyId: null, status: 'active' },
    { id: 'ADM_001', name: 'Admin User', role: 'ADMIN', tier: 'MASTER', familyId: null, status: 'active' },
  ],
  wisdomEntries: [
    { id: '1', category: 'crisis_intervention', content: 'Always provide 988 for crisis...', approved: true, confidence: 0.95 },
    { id: '2', category: 'cbt_techniques', content: 'Use cognitive reframing when...', approved: true, confidence: 0.87 },
    { id: '3', category: 'general', content: 'Validate feelings before solutions...', approved: false, confidence: 0.72 },
  ],
  pendingNotes: [
    { id: '1', coachName: 'Dr. Hope', clientName: 'Emma T.', piiDetected: true, content: 'Client discussed work stress...' },
    { id: '2', coachName: 'Dr. Smith', clientName: 'Michael C.', piiDetected: false, content: 'Good progress on anxiety...' },
  ],
  auditLog: [
    { id: '1', timestamp: '2026-01-21 14:32:15', admin: 'admin_LN', action: 'APPROVE', target: 'coach_note_123', description: 'Approved coach note for wisdom' },
    { id: '2', timestamp: '2026-01-21 14:28:03', admin: 'admin_LN', action: 'ACCESS', target: 'user_CLI_001', description: 'Viewed user profile' },
    { id: '3', timestamp: '2026-01-21 14:15:42', admin: 'admin_LN', action: 'MODIFY', target: 'wisdom_v16', description: 'Created wisdom snapshot' },
  ],
};

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
  { id: 'night-school', icon: '🎓', label: 'Night School' },
  { id: 'the-eye', icon: '👁️', label: 'The Eye' },
  { id: 'audit', icon: '📜', label: 'Audit Log' },
  { id: 'nate', icon: '🧠', label: 'Nate Features' },
  { id: 'nevedal', icon: '🔬', label: 'Nevedal Lab' },
  { id: 'the-pulse', icon: '💓', label: 'The Pulse' },
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
  const { systemStatus, metrics, crisisWatchlist, liveSessions, communityHealth, tokenEconomics, activityFeed, pendingApprovals } = mockData;
  
  return (
    <div style={{ padding: 24 }}>
      {/* System Status Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ color: colors.gold, fontSize: 20, margin: 0 }}>System Dashboard</h1>
        <div style={{ display: 'flex', gap: 16 }}>
          <span><StatusDot status={systemStatus.bridge} />Bridge</span>
          <span><StatusDot status={systemStatus.azure} />Azure</span>
          <span><StatusDot status={systemStatus.nightSchool} />Night School</span>
        </div>
      </div>
      
      {/* Metrics */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 24 }}>
        <MetricCard icon="👥" label="Active Users" value={metrics.activeUsers} />
        <MetricCard icon="🎥" label="Live Sessions" value={metrics.liveSessions} color={colors.green} />
        <MetricCard icon="👨‍⚕️" label="Coaches Online" value={metrics.coachesOnline} color={colors.gold} />
        <MetricCard icon="⚠️" label="Critical Alerts" value={metrics.criticalAlerts} color={colors.red} />
      </div>
      
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 24 }}>
        <div>
          {/* Crisis Watchlist */}
          <SectionTitle badge={`${crisisWatchlist.length} Active`}>Crisis Watchlist</SectionTitle>
          <Card style={{ marginBottom: 24 }}>
            {crisisWatchlist.map((item) => (
              <div
                key={item.id}
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
                      width: 40,
                      height: 40,
                      borderRadius: '50%',
                      background: item.severity === 'critical' ? colors.redDim : item.severity === 'warning' ? colors.orangeDim : colors.cyanDim,
                      border: `2px solid ${item.severity === 'critical' ? colors.red : item.severity === 'warning' ? colors.orange : colors.cyan}`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    {item.severity === 'critical' ? '🚨' : item.severity === 'warning' ? '⚠️' : '👁️'}
                  </div>
                  <div>
                    <div style={{ fontWeight: 'bold', fontSize: 13 }}>{item.name}</div>
                    <div style={{ fontSize: 10, color: colors.textSecondary }}>{item.trigger}</div>
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <Badge color={item.severity === 'critical' ? colors.red : item.severity === 'warning' ? colors.orange : colors.cyan}>
                    {item.severity.toUpperCase()}
                  </Badge>
                  <div style={{ fontSize: 9, color: colors.textSecondary, marginTop: 4 }}>{item.duration}</div>
                </div>
              </div>
            ))}
          </Card>
          
          {/* Live Sessions */}
          <SectionTitle badge={`${liveSessions.length} Active`}>Live Sessions</SectionTitle>
          <Card>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ color: colors.textSecondary, textAlign: 'left' }}>
                  <th style={{ padding: 8 }}>User</th>
                  <th style={{ padding: 8 }}>Type</th>
                  <th style={{ padding: 8 }}>Duration</th>
                  <th style={{ padding: 8 }}>Tier</th>
                  <th style={{ padding: 8 }}>Tokens</th>
                </tr>
              </thead>
              <tbody>
                {liveSessions.map((session) => (
                  <tr key={session.id} style={{ borderTop: `1px solid ${colors.border}` }}>
                    <td style={{ padding: 8 }}>{session.name}</td>
                    <td style={{ padding: 8 }}>
                      <Badge color={session.type === 'AI' ? colors.cyan : colors.gold}>{session.type}</Badge>
                    </td>
                    <td style={{ padding: 8, fontFamily: 'monospace' }}>{session.duration}</td>
                    <td style={{ padding: 8 }}>
                      <Badge color={session.tier === 'TOP' ? colors.gold : colors.textSecondary}>{session.tier}</Badge>
                    </td>
                    <td style={{ padding: 8 }}>{session.tokensUsed.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
        
        <div>
          {/* Community Health */}
          <SectionTitle>Community Nevedal State</SectionTitle>
          <Card style={{ marginBottom: 24 }}>
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                <span>Anxiety Level</span>
                <span style={{ color: communityHealth.anxiety > 70 ? colors.orange : colors.green }}>{communityHealth.anxiety}%</span>
              </div>
              <ProgressBar value={communityHealth.anxiety} max={100} color={communityHealth.anxiety > 70 ? colors.orange : colors.green} />
            </div>
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                <span>Emotional Stability</span>
                <span style={{ color: colors.cyan }}>{communityHealth.stability}%</span>
              </div>
              <ProgressBar value={communityHealth.stability} max={100} color={colors.cyan} />
            </div>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                <span>Platform Engagement</span>
                <span style={{ color: colors.green }}>{communityHealth.engagement}%</span>
              </div>
              <ProgressBar value={communityHealth.engagement} max={100} color={colors.green} />
            </div>
          </Card>
          
          {/* Token Economics */}
          <SectionTitle>Token Economics</SectionTitle>
          <Card style={{ marginBottom: 24 }}>
            <div style={{ textAlign: 'center', marginBottom: 12 }}>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: colors.gold }}>${tokenEconomics.dailySpend}</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>of ${tokenEconomics.dailyBudget} daily budget</div>
            </div>
            <ProgressBar 
              value={tokenEconomics.dailySpend} 
              max={tokenEconomics.dailyBudget} 
              color={tokenEconomics.dailySpend / tokenEconomics.dailyBudget > 0.8 ? colors.orange : colors.gold} 
            />
          </Card>
          
          {/* Pending Approvals */}
          <SectionTitle badge={pendingApprovals.length}>Pending Approvals</SectionTitle>
          <Card style={{ marginBottom: 24 }}>
            {pendingApprovals.map((item) => (
              <div key={item.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0' }}>
                <div>
                  <div style={{ fontSize: 12 }}>{item.name}</div>
                  <div style={{ fontSize: 10, color: colors.textSecondary }}>{item.specialty} • {item.submitted}</div>
                </div>
                <Button variant="primary" style={{ padding: '6px 12px', fontSize: 10 }}>Review</Button>
              </div>
            ))}
          </Card>
          
          {/* Activity Feed */}
          <SectionTitle>Activity Feed</SectionTitle>
          <Card>
            {activityFeed.map((item, i) => (
              <div key={i} style={{ display: 'flex', gap: 12, padding: '8px 0', borderBottom: i < activityFeed.length - 1 ? `1px solid ${colors.border}` : 'none' }}>
                <div style={{ fontSize: 9, color: colors.textSecondary, width: 50 }}>{item.time}</div>
                <div style={{ fontSize: 11, color: item.type === 'alert' ? colors.red : item.type === 'warning' ? colors.orange : colors.textPrimary }}>
                  {item.event}
                </div>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </div>
  );
};

// =============================================================================
// SC_02: USER MANAGEMENT
// =============================================================================

const UserManagementScreen = () => {
  const [selectedUser, setSelectedUser] = useState(mockData.users[0]);
  const [searchTerm, setSearchTerm] = useState('');
  const [roleFilter, setRoleFilter] = useState('ALL');
  
  const filteredUsers = mockData.users.filter((user) => {
    const matchesSearch = user.name.toLowerCase().includes(searchTerm.toLowerCase()) || user.id.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesRole = roleFilter === 'ALL' || user.role === roleFilter;
    return matchesSearch && matchesRole;
  });
  
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
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
              <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
                <div
                  style={{
                    width: 64,
                    height: 64,
                    borderRadius: '50%',
                    background: selectedUser.role === 'ADMIN' ? colors.gold : selectedUser.role === 'COACH' ? colors.gold : colors.cyan,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 28,
                  }}
                >
                  {selectedUser.role === 'ADMIN' ? '👑' : selectedUser.role === 'COACH' ? '👨‍⚕️' : '👤'}
                </div>
                <div>
                  <h2 style={{ margin: 0, fontSize: 20 }}>{selectedUser.name}</h2>
                  <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                    <Badge color={selectedUser.role === 'ADMIN' ? colors.gold : selectedUser.role === 'COACH' ? colors.gold : colors.cyan}>
                      {selectedUser.role}
                    </Badge>
                    <Badge color={selectedUser.tier === 'TOP' || selectedUser.tier === 'MASTER' ? colors.gold : colors.textSecondary}>
                      {selectedUser.tier}
                    </Badge>
                    <Badge color={colors.green}>ACTIVE</Badge>
                  </div>
                </div>
              </div>
            </div>
            
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
              {/* Basic Info */}
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
                    <span>{selectedUser.tier}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0' }}>
                    <span style={{ color: colors.textSecondary }}>Family</span>
                    <span>{selectedUser.familyId || 'None'}</span>
                  </div>
                </div>
              </Card>
              
              {/* Nevedal State */}
              <Card>
                <SectionTitle>Nevedal State</SectionTitle>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                    <span>C_emo (Coherence)</span>
                    <span style={{ color: colors.cyan }}>0.72</span>
                  </div>
                  <ProgressBar value={72} max={100} color={colors.cyan} />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                    <span>p_ent (Entanglement)</span>
                    <span style={{ color: colors.purple }}>0.65</span>
                  </div>
                  <ProgressBar value={65} max={100} color={colors.purple} />
                </div>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                    <span>γ_env (Decoherence)</span>
                    <span style={{ color: colors.orange }}>0.28</span>
                  </div>
                  <ProgressBar value={28} max={100} color={colors.orange} />
                </div>
              </Card>
              
              {/* Matchmaker Protocol */}
              <Card>
                <SectionTitle>Matchmaker Protocol</SectionTitle>
                <div style={{ textAlign: 'center', marginBottom: 16 }}>
                  <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 8 }}>Best Coach Match</div>
                  <div style={{ fontSize: 16, fontWeight: 'bold', color: colors.gold }}>Dr. Sarah Hope</div>
                  <div style={{ fontSize: 28, fontWeight: 'bold', color: colors.green, margin: '8px 0' }}>94%</div>
                  <div style={{ fontSize: 10, color: colors.textSecondary }}>Compatibility Score</div>
                </div>
                <Button variant="primary" style={{ width: '100%' }}>Run Matchmaker Analysis</Button>
              </Card>
              
              {/* Identity Resolution */}
              <Card>
                <SectionTitle>Identity Resolution</SectionTitle>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <Button>🔑 Reset Password</Button>
                  <Button>🔐 Reset Biometrics</Button>
                  <Button variant="danger">🚫 Ban User</Button>
                  <Button variant="danger">🗑️ Wipe Memory</Button>
                </div>
              </Card>
            </div>
          </>
        ) : (
          <div style={{ textAlign: 'center', color: colors.textSecondary, marginTop: 100 }}>
            Select a user to view details
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
  
  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ color: colors.purple, fontSize: 20, margin: '0 0 24px 0' }}>🎓 Night School Director</h1>
      
      {/* Tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
        {['wisdom', 'notes', 'dojo', 'versions'].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: '10px 20px',
              background: activeTab === tab ? colors.purpleDim : colors.bgCard,
              border: `1px solid ${activeTab === tab ? colors.purple : colors.border}`,
              color: activeTab === tab ? colors.purple : colors.textSecondary,
              borderRadius: 8,
              fontSize: 12,
              cursor: 'pointer',
              textTransform: 'capitalize',
            }}
          >
            {tab === 'wisdom' ? '📚 Wisdom' : tab === 'notes' ? '📝 Notes Queue' : tab === 'dojo' ? '🥋 The Dojo' : '⏱️ Versions'}
          </button>
        ))}
      </div>
      
      {activeTab === 'wisdom' && (
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 24 }}>
          <Card>
            <SectionTitle badge={mockData.wisdomEntries.length}>Wisdom Entries</SectionTitle>
            {mockData.wisdomEntries.map((entry) => (
              <div key={entry.id} style={{ padding: 12, borderBottom: `1px solid ${colors.border}` }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <Badge color={colors.purple}>{entry.category}</Badge>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 10, color: colors.textSecondary }}>Confidence: {(entry.confidence * 100).toFixed(0)}%</span>
                    <Badge color={entry.approved ? colors.green : colors.orange}>{entry.approved ? 'APPROVED' : 'PENDING'}</Badge>
                  </div>
                </div>
                <div style={{ fontSize: 12, color: colors.textSecondary }}>{entry.content}</div>
              </div>
            ))}
            <Button variant="primary" style={{ marginTop: 16, width: '100%' }}>+ Add Wisdom Entry</Button>
          </Card>
          
          <Card>
            <SectionTitle>Quick Stats</SectionTitle>
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: colors.purple }}>{mockData.wisdomEntries.length}</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Total Entries</div>
            </div>
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: colors.green }}>{mockData.wisdomEntries.filter(e => e.approved).length}</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Approved</div>
            </div>
            <div>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: colors.orange }}>{mockData.wisdomEntries.filter(e => !e.approved).length}</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Pending Review</div>
            </div>
            <Button style={{ marginTop: 16, width: '100%' }}>📸 Create Snapshot</Button>
          </Card>
        </div>
      )}
      
      {activeTab === 'notes' && (
        <Card>
          <SectionTitle badge={mockData.pendingNotes.length}>Pending Coach Notes</SectionTitle>
          {mockData.pendingNotes.map((note) => (
            <div key={note.id} style={{ padding: 16, borderBottom: `1px solid ${colors.border}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div>
                  <span style={{ fontWeight: 'bold' }}>{note.coachName}</span>
                  <span style={{ color: colors.textSecondary }}> → {note.clientName}</span>
                </div>
                {note.piiDetected && <Badge color={colors.orange}>⚠️ PII DETECTED</Badge>}
              </div>
              <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 12, padding: 12, background: colors.bgElevated, borderRadius: 8 }}>
                {note.content}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Button variant="success" style={{ flex: 1 }}>✓ Approve</Button>
                <Button variant="danger" style={{ flex: 1 }}>✗ Reject</Button>
                <Button style={{ flex: 1 }}>✏️ Redact</Button>
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
                  <Button key={persona} style={{ fontSize: 10 }}>{persona}</Button>
                ))}
              </div>
            </div>
            <Button variant="primary" style={{ width: '100%' }}>Start Dojo Session</Button>
          </Card>
          
          <Card>
            <SectionTitle>Recent Dojo Results</SectionTitle>
            <div style={{ textAlign: 'center', padding: 24 }}>
              <div style={{ fontSize: 48, marginBottom: 8 }}>✅</div>
              <div style={{ fontSize: 16, fontWeight: 'bold', color: colors.green }}>All Tests Passed</div>
              <div style={{ fontSize: 11, color: colors.textSecondary }}>Last run: 2 hours ago</div>
            </div>
          </Card>
        </div>
      )}
      
      {activeTab === 'versions' && (
        <Card>
          <SectionTitle>Version History (Time Travel)</SectionTitle>
          <div style={{ fontFamily: 'monospace', fontSize: 11 }}>
            {[
              { version: 'v16.4', date: '2026-01-21', entries: 847, current: true },
              { version: 'v16.3', date: '2026-01-20', entries: 842, current: false },
              { version: 'v16.2', date: '2026-01-18', entries: 835, current: false },
            ].map((v) => (
              <div key={v.version} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: 12, borderBottom: `1px solid ${colors.border}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ color: colors.purple }}>{v.version}</span>
                  <span style={{ color: colors.textSecondary }}>{v.date}</span>
                  <span style={{ color: colors.textSecondary }}>{v.entries} entries</span>
                  {v.current && <Badge color={colors.green}>CURRENT</Badge>}
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <Button style={{ padding: '4px 8px', fontSize: 10 }}>Compare</Button>
                  {!v.current && <Button style={{ padding: '4px 8px', fontSize: 10 }}>Revert</Button>}
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

const TheEyeScreen = () => (
  <div style={{ padding: 24 }}>
    <h1 style={{ color: colors.gold, fontSize: 20, margin: '0 0 24px 0' }}>👁️ The Eye - Analytics & Surveillance</h1>
    
    <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 24 }}>
      <div>
        {/* Token Economics */}
        <Card style={{ marginBottom: 24 }}>
          <SectionTitle>Token Economics Monitor</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginBottom: 16 }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 'bold', color: colors.cyan }}>$1,247</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Today's Spend</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 'bold', color: colors.gold }}>$8,432</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>This Week</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 'bold', color: colors.purple }}>$32,156</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>This Month</div>
            </div>
          </div>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
              <span>Daily Budget</span>
              <span>$1,247 / $2,000 (62%)</span>
            </div>
            <ProgressBar value={1247} max={2000} color={colors.gold} />
          </div>
        </Card>
        
        {/* Usage Breakdown */}
        <Card>
          <SectionTitle>Usage Breakdown by Modality</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
            <div style={{ textAlign: 'center', padding: 16, background: colors.cyanDim, borderRadius: 8 }}>
              <div style={{ fontSize: 24 }}>💬</div>
              <div style={{ fontSize: 20, fontWeight: 'bold', color: colors.cyan }}>$567</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Text</div>
            </div>
            <div style={{ textAlign: 'center', padding: 16, background: colors.purpleDim, borderRadius: 8 }}>
              <div style={{ fontSize: 24 }}>🎤</div>
              <div style={{ fontSize: 20, fontWeight: 'bold', color: colors.purple }}>$423</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Voice</div>
            </div>
            <div style={{ textAlign: 'center', padding: 16, background: colors.goldDim, borderRadius: 8 }}>
              <div style={{ fontSize: 24 }}>👁️</div>
              <div style={{ fontSize: 20, fontWeight: 'bold', color: colors.gold }}>$257</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Vision</div>
            </div>
          </div>
        </Card>
      </div>
      
      <div>
        {/* Tier Feature Controls */}
        <Card style={{ marginBottom: 24 }}>
          <SectionTitle>Tier Feature Controls</SectionTitle>
          {['TOP', 'STANDARD', 'TRIAL'].map((tier) => (
            <div key={tier} style={{ padding: 12, borderBottom: `1px solid ${colors.border}` }}>
              <div style={{ fontWeight: 'bold', marginBottom: 8, color: tier === 'TOP' ? colors.gold : colors.textPrimary }}>{tier} Tier</div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Badge color={colors.green}>Voice ✓</Badge>
                <Badge color={tier === 'TRIAL' ? colors.textSecondary : colors.green}>{tier === 'TRIAL' ? 'Vision ✗' : 'Vision ✓'}</Badge>
              </div>
            </div>
          ))}
        </Card>
        
        {/* Throttle Control */}
        <Card>
          <SectionTitle>Global Throttle</SectionTitle>
          <div style={{ textAlign: 'center', marginBottom: 16 }}>
            <div style={{ fontSize: 36, fontWeight: 'bold', color: colors.green }}>100%</div>
            <div style={{ fontSize: 10, color: colors.textSecondary }}>Current Throughput</div>
          </div>
          <input
            type="range"
            min="0"
            max="100"
            defaultValue="100"
            style={{ width: '100%' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: colors.textSecondary }}>
            <span>0%</span>
            <span>100%</span>
          </div>
        </Card>
      </div>
    </div>
  </div>
);

// =============================================================================
// SC_05: AUDIT LOG
// =============================================================================

const AuditLogScreen = () => (
  <div style={{ padding: 24 }}>
    <h1 style={{ color: colors.gold, fontSize: 20, margin: '0 0 24px 0' }}>📜 Sovereignty Audit Log</h1>
    
    <Card style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
        <input
          type="text"
          placeholder="Search audit log..."
          style={{
            flex: 1,
            padding: '10px 12px',
            background: colors.bgElevated,
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            color: colors.textPrimary,
            fontSize: 12,
          }}
        />
        <select style={{ padding: '10px 12px', background: colors.bgElevated, border: `1px solid ${colors.border}`, borderRadius: 8, color: colors.textPrimary, fontSize: 12 }}>
          <option>All Actions</option>
          <option>ACCESS</option>
          <option>MODIFY</option>
          <option>APPROVE</option>
          <option>SECURITY</option>
        </select>
        <Button variant="primary">Export</Button>
      </div>
    </Card>
    
    <Card>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ color: colors.textSecondary, textAlign: 'left', borderBottom: `1px solid ${colors.border}` }}>
            <th style={{ padding: 12 }}>Timestamp</th>
            <th style={{ padding: 12 }}>Admin</th>
            <th style={{ padding: 12 }}>Action</th>
            <th style={{ padding: 12 }}>Target</th>
            <th style={{ padding: 12 }}>Description</th>
          </tr>
        </thead>
        <tbody>
          {mockData.auditLog.map((entry) => (
            <tr key={entry.id} style={{ borderBottom: `1px solid ${colors.border}` }}>
              <td style={{ padding: 12, fontFamily: 'monospace', fontSize: 10 }}>{entry.timestamp}</td>
              <td style={{ padding: 12 }}>{entry.admin}</td>
              <td style={{ padding: 12 }}>
                <Badge color={entry.action === 'APPROVE' ? colors.green : entry.action === 'MODIFY' ? colors.orange : colors.cyan}>
                  {entry.action}
                </Badge>
              </td>
              <td style={{ padding: 12, fontFamily: 'monospace', fontSize: 10 }}>{entry.target}</td>
              <td style={{ padding: 12, color: colors.textSecondary }}>{entry.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
    
    <div style={{ marginTop: 16, padding: 12, background: colors.redDim, border: `1px solid ${colors.red}`, borderRadius: 8, fontSize: 11 }}>
      <strong style={{ color: colors.red }}>🔒 IMMUTABLE LOG:</strong>
      <span style={{ color: colors.textSecondary }}> This audit log cannot be modified or deleted. All entries are permanent.</span>
    </div>
  </div>
);

// =============================================================================
// SC_06: NATE FEATURES
// =============================================================================

const NateFeaturesScreen = () => (
  <div style={{ padding: 24 }}>
    <h1 style={{ color: colors.cyan, fontSize: 20, margin: '0 0 24px 0' }}>🧠 Little Nate AI Features</h1>
    
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
      {/* Deadman Switch */}
      <Card>
        <SectionTitle>💀 Deadman Switch</SectionTitle>
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
          <div style={{ fontSize: 48, marginBottom: 8 }}>🟢</div>
          <div style={{ fontSize: 16, fontWeight: 'bold', color: colors.green }}>ACTIVE</div>
          <div style={{ fontSize: 10, color: colors.textSecondary }}>Monitoring 847 users</div>
        </div>
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
            <span>Silence Threshold</span>
            <span>3 days</span>
          </div>
          <input type="range" min="1" max="7" defaultValue="3" style={{ width: '100%' }} />
        </div>
        <div style={{ padding: 12, background: colors.redDim, borderRadius: 8, marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: colors.red, fontWeight: 'bold' }}>2 users triggered</div>
          <div style={{ fontSize: 10, color: colors.textSecondary }}>Guardians notified automatically</div>
        </div>
        <Button variant="primary" style={{ width: '100%' }}>Configure Deadman</Button>
      </Card>
      
      {/* Swarm Intelligence */}
      <Card>
        <SectionTitle>🐝 Swarm Intelligence</SectionTitle>
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
          <div style={{ fontSize: 48, marginBottom: 8 }}>👨‍👩‍👧‍👦</div>
          <div style={{ fontSize: 16, fontWeight: 'bold', color: colors.purple }}>Family Correlation Active</div>
          <div style={{ fontSize: 10, color: colors.textSecondary }}>Analyzing cross-member patterns</div>
        </div>
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 4 }}>Active Swarms</div>
          <div style={{ fontSize: 24, fontWeight: 'bold', color: colors.purple }}>23</div>
          <div style={{ fontSize: 10, color: colors.textSecondary }}>family groups being analyzed</div>
        </div>
        <Button style={{ width: '100%' }}>View Swarm Matrix</Button>
      </Card>
      
      {/* AI Modes */}
      <Card>
        <SectionTitle>🎭 AI Response Modes</SectionTitle>
        {['Empathetic', 'Directive', 'Socratic', 'Crisis'].map((mode) => (
          <div key={mode} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: `1px solid ${colors.border}` }}>
            <span>{mode} Mode</span>
            <Badge color={mode === 'Crisis' ? colors.red : colors.green}>
              {mode === 'Crisis' ? 'AUTO-TRIGGER' : 'ENABLED'}
            </Badge>
          </div>
        ))}
      </Card>
      
      {/* Memory Controls */}
      <Card>
        <SectionTitle>🧬 Memory Controls</SectionTitle>
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 4 }}>Hippocampus Status</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <StatusDot status="online" />
            <span style={{ color: colors.green }}>Active - 2.3TB stored</span>
          </div>
        </div>
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 4 }}>Retention Policy</div>
          <select style={{ width: '100%', padding: 8, background: colors.bgElevated, border: `1px solid ${colors.border}`, borderRadius: 8, color: colors.textPrimary }}>
            <option>Forever (with consent)</option>
            <option>1 Year</option>
            <option>6 Months</option>
          </select>
        </div>
        <Button variant="danger" style={{ width: '100%' }}>🗑️ Emergency Memory Purge</Button>
      </Card>
    </div>
  </div>
);

// =============================================================================
// SC_07: NEVEDAL LAB
// =============================================================================

const NevedalLabScreen = () => (
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
        <div style={{ fontSize: 36, fontWeight: 'bold', color: colors.cyan }}>0.72</div>
        <ProgressBar value={72} max={100} color={colors.cyan} />
      </Card>
      <Card style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 8 }}>CEE Events Today</div>
        <div style={{ fontSize: 36, fontWeight: 'bold', color: colors.green }}>47</div>
        <div style={{ fontSize: 10, color: colors.green }}>↑ 12% from yesterday</div>
      </Card>
      <Card style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 8 }}>Avg Session τ_emo</div>
        <div style={{ fontSize: 36, fontWeight: 'bold', color: colors.purple }}>2.3s</div>
        <div style={{ fontSize: 10, color: colors.textSecondary }}>Coherence lifetime</div>
      </Card>
    </div>
    
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
      <Card>
        <SectionTitle>Live Session Nevedal Streams</SectionTitle>
        {mockData.liveSessions.slice(0, 3).map((session) => (
          <div key={session.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 0', borderBottom: `1px solid ${colors.border}` }}>
            <div>
              <div style={{ fontWeight: 'bold' }}>{session.name}</div>
              <div style={{ fontSize: 10, color: colors.textSecondary }}>Session: {session.duration}</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 16, fontWeight: 'bold', color: colors.cyan }}>{(0.5 + Math.random() * 0.4).toFixed(2)}</div>
              <div style={{ fontSize: 9, color: colors.textSecondary }}>C_emo</div>
            </div>
          </div>
        ))}
        <Button style={{ marginTop: 12, width: '100%' }}>Open Real-time Dashboard</Button>
      </Card>
      
      <Card>
        <SectionTitle>Research Tools</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Button style={{ height: 80, flexDirection: 'column', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ fontSize: 24 }}>📊</span>
            <span style={{ fontSize: 10, marginTop: 4 }}>Generate Report</span>
          </Button>
          <Button style={{ height: 80, flexDirection: 'column', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ fontSize: 24 }}>👥</span>
            <span style={{ fontSize: 10, marginTop: 4 }}>Dyad Analysis</span>
          </Button>
          <Button style={{ height: 80, flexDirection: 'column', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ fontSize: 24 }}>👨‍👩‍👧‍👦</span>
            <span style={{ fontSize: 10, marginTop: 4 }}>Family Matrix</span>
          </Button>
          <Button style={{ height: 80, flexDirection: 'column', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ fontSize: 24 }}>📈</span>
            <span style={{ fontSize: 10, marginTop: 4 }}>Longitudinal</span>
          </Button>
        </div>
      </Card>
    </div>
  </div>
);

// =============================================================================
// MAIN APP
// =============================================================================

export default function SovereignCommand() {
  const [activeScreen, setActiveScreen] = useState('dashboard');
  
  const renderScreen = () => {
    switch (activeScreen) {
      case 'dashboard': return <DashboardScreen />;
      case 'users': return <UserManagementScreen />;
      case 'night-school': return <NightSchoolScreen />;
      case 'the-eye': return <TheEyeScreen />;
      case 'audit': return <AuditLogScreen />;
      case 'nate': return <NateFeaturesScreen />;
      case 'nevedal': return <NevedalLabScreen />;
      case 'the-pulse': return <ThePulse />;
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
