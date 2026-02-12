import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useWebSocket } from '../context/WebSocketContext'
import styles from '../styles/Users.module.css'

export default function Users() {
  const [users, setUsers] = useState([])
  const [selectedUser, setSelectedUser] = useState(null)
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  
  const { send, subscribe } = useWebSocket()

  useEffect(() => {
    send('admin_get_users')
    
    const unsub = subscribe('admin_users', (data) => {
      setUsers(data.users || [])
    })
    
    return unsub
  }, [send, subscribe])

  const filteredUsers = users.filter(u => {
    const matchesSearch = (u.name || '').toLowerCase().includes(search.toLowerCase()) ||
                         (u.username || '').toLowerCase().includes(search.toLowerCase())
    const role = (u.role || '').toLowerCase()
    const matchesFilter = filter === 'all' || 
                         role === filter ||
                         (filter === 'client' && (role === 'user' || role === 'client'))
    return matchesSearch && matchesFilter
  })

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <Link to="/dashboard" className={styles.backBtn}>← Back</Link>
          <h1>User Management</h1>
        </div>
      </header>
      
      <div className={styles.layout}>
        <aside className={styles.sidebar}>
          <input
            type="text"
            placeholder="🔍 Search users..."
            className={styles.searchInput}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          
          <div className={styles.filters}>
            {['all', 'client', 'coach', 'a'].map(f => (
              <button
                key={f}
                className={`${styles.filterBtn} ${filter === f ? styles.active : ''}`}
                onClick={() => setFilter(f)}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
          
          <div className={styles.userList}>
            {filteredUsers.map(user => (
              <div
                key={user.id}
                className={`${styles.userItem} ${selectedUser?.id === user.id ? styles.selected : ''}`}
                onClick={() => setSelectedUser(user)}
              >
                <div className={styles.userAvatar}>
                  {(user.name || user.username || '?')[0].toUpperCase()}
                </div>
                <div className={styles.userInfo}>
                  <div className={styles.userName}>{user.name || user.username}</div>
                  <div className={styles.userMeta}>{user.role} • {user.family_id || 'No Family'/div>
                </div>
              </div>
            ))}
          </div>
        </aside>
        
        <main className={styles.main}>
          {selectedUser ? (
            <UserDetail user={selectedUser} />
          ) : (
            <div className={styles.empty}>
              <span className={styles.emptyIcon}>👤</span>
              <p>Select a user to view details</p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

function UserDetail({ user }) {
  return (
    <div className={styles.detail}>
      <div className={styles.detailHeader}>
        <h2>{user.name || user.username}</h2>
        <p>{user.id}</p>
      </div>
      
      <div className={styles.cards}>
        <div className={styles.card}>
          <h3>📋 Basic Info</h3>
          <div className={styles.field}>
            <span>Username</span>
            <span>{user.username || user.id}</span>
          </div>
          <div className={styles.field}>
            <>Email</span>
            <span>{user.email || 'Not set'}</span>
          </div>
          <div className={styles.field}>
            <span>Role</span>
            <span className={styles.gold}>{user.role}</span>
          </div>
          <div className={styles.field}>
            <span>Subscription</span>
            <span className={styles.green}>{user.subscription_tier || user.subscription_plan || 'TRIAL'}</span>
          </div>
          <div className={styles.field}>
            <span>Coach</span>
            <span>{user.assigned_coach_id || 'None'}</span>
          </div>
        </div>
        
        <div className={`${styles.card} ${styles.nevedal}`}>
          <h3>🧠 Nevedal State</h3>
          <div className={styles.metrics}>
            <div className={styles.metric}>
              <div className={styles.metricValue}>{user.metrics?.coherence || '0.00'}</div>
              <div className={styles.metricLabel}>Coherence</div>
            </div>
            <div className={styles.metric}>
            <div className={styles.metricValue}>{user.metrics?.growth || '0.00'}</div>
              <div className={styles.metricLabel}>Growth</div>
            </div>
            <div className={styles.metric}>
              <div className={styles.metricValue}>{user.metrics?.risk || 'LOW'}</div>
              <div className={styles.metricLabel}>Risk</div>
            </div>
          </div>
        </div>
        
        <div className={`${styles.card} ${styles.full}`}>
          <h3>🔐 Identity Actions</h3>
          <div className={styles.actions}>
            <button className={styles.actionBtn}>🔑 Reset Password</button>
            <button className={styles.actionBtn}>👆 Reset Biometrics</button>
            <button className={styles.actionBtn}>📱 Force Logout</button>
            <button className={`${styles.actionBtn} ${styles.danger}`}>🧹 Wipe Memory</button>
            <button className={`${styles.actionBtn} ${styles.danger}`}>🚫 Ban Account</button>
          </div>
        </div>
     </div>
  )
}
