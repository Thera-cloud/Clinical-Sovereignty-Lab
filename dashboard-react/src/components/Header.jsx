import styles from '../styles/Header.module.css'

export default function Header({ user, onLogout, isConnected }) {
  return (
    <header className={styles.header}>
      <div className={styles.logo}>
        <div className={styles.logoIcon}>👑</div>
        <div className={styles.logoText}>SOVEREIGN</div>
      </div>
      
      <div className={styles.status}>
        <div className={styles.statusPill}>
          <span className={`${styles.statusD} ${isConnected ? styles.online : ''}`}></span>
          {isConnected ? 'Bridge Online' : 'Connecting...'}
        </div>
      </div>
      
      <div className={styles.userArea}>
        <div className={styles.userInfo}>
          <div className={styles.userName}>{user?.name || 'User'}</div>
          <div className={styles.userRole}>{user?.role || 'ADMIN'}</div>
        </div>
        <button onClick={onLogout} className={styles.logoutBtn}>Logout</button>
      </div>
    </header>
  )
}
