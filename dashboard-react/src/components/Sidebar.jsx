import { Link } from 'react-router-dom'
import styles from '../styles/Sidebar.module.css'

const navItems = [
  { id: 'command', label: 'Command', icon: '📊' },
  { id: 'clients', label: 'My Clients', icon: '👥' },
  { id: 'calendar', label: 'Calendar', icon: '📅' },
  { id: 'crisis', label: 'Crisis Center', icon: '🚨' },
]

const adminItems = [
  { id: 'users', label: 'Users', icon: '👤', path: '/users' },
  { id: 'night-school', label: 'Night School', icon: '🎓', path: '/night-school' },
  { id: 'the-eye', label: 'The Eye', icon: '👁️', path: '/the-eye' },
  { id: 'audit-log', label: 'Audit Log', icon: '📜', path: '/audit-log' },
]

export default function Sidebar({ activeTab, setActiveTab, isAdmin }) {
  return (
    <aside className={styles.sidebar}>
      <nav classN        {navItems.map(item => (
          <button
            key={item.id}
            className={`${styles.navItem} ${activeTab === item.id ? styles.active : ''}`}
            onClick={() => setActiveTab(item.id)}
          >
            <span className={styles.icon}>{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
        
        {isAdmin && (
          <>
            <div className={styles.divider}></div>
            <div className={styles.sectionLabel}>Admin</div>
            {adminItems.map(item => (
              <Link
                key={item.id}
                to={item.path}
                className={styles.navItem}
              >
                <span className={styles.icon}>{item.icon}</span>
                <span>{item.label}</span>
              </Link>
            ))}
          </>
        )}
      </nav>
    </aside>
  )
}
