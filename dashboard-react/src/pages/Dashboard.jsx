import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useWebSocket } from '../context/WebSocketContext'
import { useAuth } from '../context/AuthContext'
import Header from '../components/Header'
import Sidebar from '../components/Sidebar'
import styles from '../styles/Dashboard.module.css'

export default function Dashboard() {
  const [stats, setStats] = useState({})
  const [clients, setClients] = useState([])
  const [crisisAlerts, setCrisisAlerts] = useState([])
  const [activeTab, setActiveTab] = useState('command')
  
  const { send, subscribe, isConnected } = useWebSocket()
  const { user, isAdmin, logout } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!user) {
      navigate('/login')
      return
    }

    // Request initial data
    send('admin_get_stats')
    send('coach_get_clients')
    send('admin_get_crisis_watchlist')

    const unsubStats = subscribe('admin_stats', (data) => {
      setStats(data.stats || {})
      setCrisisAlerts(data.crisis_watchlist || [])
    })

    const unsubClients = subscribe('coach_clients', (data) => {
      setClients(data.clients || [])
    })

    return () => {
      unsubStats()
      unsubClients()
    }
  }, [user, navigate, send, subscribe])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className={styles.container}>
      <Header user={user} onLogout={handleLogout} isConnected={isConnected} />
      
      <div className={styles.layout}>
        <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} isAdmin={isAdmin} />
        
        <main className={styles.main}>
          {activeTab === 'command' && (
            <CommandTab stats={stats} clients={clients} crisisAlerts={crisisAlerts} />
          )}
          {activeTab === 'clients' && (
            <ClientsTab clients={clients} />
          )}
          {activeTab === 'crisis' && (
            <CrisisTab alerts={crisisAlerts} />
          )}
        </main>
      </div>
    </div>
  )
}

function CommandTab({ stats, clients, crisisAlerts }) {
  return (
    <div className={styles.dashboardGrid}>
      {/* Stats Row */}
      <div className={styles.statsRow}>
        <StatCard label="Total Users" value={stats.total_users || 0} icon="👥" color="gold" />
        <StatCard label="Live Sessions" value={stats.live_sessions || 0} icon="🔴" color="red" />
        <StatCard label="Coaches Online" value={stats.coaches_count || 0} icon="👨‍⚕️" color="green" />
        <StatCard label="Crisis Alerts" value={crisisAlerts.len�" color="red" />
      </div>

      {/* Quick Actions */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <h3>⚡ Quick Actions</h3>
        </div>
        <div className={styles.quickActions}>
          <Link to="/ask-nate" className={styles.quickAction}>
            <span className={styles.quickIcon}>🤖</span>
            <span>Ask Nate</span>
          </Link>
          <Link to="/users" className={styles.quickAction}>
            <span className={styles.quickIcon}>👤</span>
            <span>User Management</span>
          </Link>
          <Link to="/night-school" className={styles.quickAction}>
            <span className={styles.quickIcon}>🎓</span>
            <span>Night School</span>
          </Link>
          <Link to="/the-eye" className={styles.quickAction}>
            <span className={styles.quickIcon}>👁️</span>
            <span>The Eye</span>
          </Link>
          <Link to="/audit-log" className={sion}>
            <span className={styles.quickIcon}>📜</span>
            <span>Audit Log</span>
          </Link>
        </div>
      </div>

      {/* My Clients */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <h3>👥 My Clients</h3>
          <span className={styles.badge}>{clients.length}</span>
        </div>
        <div className={styles.clientList}>
          {clients.length === 0 ? (
            <div className={styles.empty}>No clients assigned</div>
          ) : (
            clients.slice(0, 5).map(client => (
              <div key={client.id} className={styles.clientItem}>
                <div className={styles.clientAvatar}>
                  {(client.name || 'U')[0]}
                </div>
                <div className={styles.clientInfo}>
                  <div className={styles.clientName}>{client.name || client.username}</div>
                  <div className={styles.clientMeta}>{client.tier || 'Standard'}</div>
                </div>
            <div className={styles.clientMetrics}>
                  <span className={styles.coherence}>{client.metrics?.coherence || '0.00'}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Crisis Center */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <h3>🚨 Crisis Center</h3>
          {crisisAlerts.length > 0 && (
            <span className={`${styles.badge} ${styles.danger}`}>{crisisAlerts.length}</span>
          )}
        </div>
        <div className={styles.crisisList}>
          {crisisAlerts.length === 0 ? (
            <div className={styles.empty}>No active crisis alerts ✓</div>
          ) : (
            crisisAlerts.map((alert, i) => (
              <div key={i} className={styles.crisisItem}>
                <div className={styles.crisisSeverity}></div>
            <div className={styles.crisisInfo}>
                  <div className={styles.crisisUser}>{alert.user_name || alert.user_id}</div>
                  <div className={styles.crisisTrigger}>{alert.trigger || 'Flagged for review'}</div>
                </div>
                <button className={styles.crisisBtn}>Review</button>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

function ClientsTab({ clients }) {
  return (
    <div className={styles.clientsGrid}>
      <h2>My Clients</h2>
      <div className={styles.clientsTable}>
        {clients.map(client => (
          <div key={client.id} className={styles.clientRow}>
            <div className={styles.clientAvatar}>{(client.name || 'U')[0]}</div>
            <div className={styles.clientName}>{client.name || client.username}</div>
            <div className={styles.clientTier}>{client.tier}</div>
            <div className={styles.clientCoherence}>{client.metrics?.coherence || '0.00'}</div>
            <button className={styles.btn}>View</button>
          </div>
        ))}
      </div>
    </div>
  )
}

function CrisisTab({ alerts }) {
  return (
    <div>
      <h2>Crisis Center</h2>
      {alerts.length === 0 ? (
        <div className={styles.empty}>No active alerts</div>
      ) : (
        alerts.map((alert, i) => (
          <div key={i} className={styles.crisisCard}>
            <h4>{alert.user_name}</h4>
            <p>{alert.trigger}</p>
          </div>
        ))
      )}
    </div>
  )
}

function StatCard({ label, value, icon, color }) {
  return (
    <div className={`${styles.statCard} ${styles[color]}`}>
      <div className={styles.statIcon}>{icon}</div>
      <div className={styles.statValue}>{value}</div>
      <div className={styles.statLabel}>{label}</div>
    </div>
  )
}
