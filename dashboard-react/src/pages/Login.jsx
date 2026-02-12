import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWebSocket } from '../context/WebSocketContext'
import { useAuth } from '../context/AuthContext'
import styles from '../styles/Login.module.css'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('ADMIN')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  
  const { send, subscribe, isConnected } = useWebSocket()
  const { login } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    const unsubSuccess = subscribe('login_success', (data) => {
      login(data.profile, data.token, password)
      navigate('/dashboard')
    })

    const unsubError = subscribe('login_error', (data) => {
      setError(data.message || 'Login failed')
      setIsLoading(false)
    })

    return () => {
      unsubSuccess()
      unsubError()
    }
  }, [subscribe, login, navigate, password])

  const handleSubmit = (e) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)
    
    sessionStorage.setItem('username', username)
    sessionStorage.setItem('password', password)
    sessionStorage.setItem('role', role)
    
    send('login_request', {
      username,
      password,
      expected_role: role
    })
  }

  return (
    <div className={styles.container}>
      <div className={styles.loginBox}>
        <div className={styles.logo}>
          <div className={styles.logoIcon}>👑</div>
          <h1 className={styles.logoText}>SOVEREIGN</h1>
          <p className={styles.logoSubtext}>Command Center</p>
        </div>

        <form onSubmit={handleSubmit} className={styles.form}>
          <div className={styles.field}>
            <label>Username</label>
            <input
              typ"text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Enter username"
              required
            />
          </div>

          <div className={styles.field}>
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              required
            />
          </div>

          <div className={styles.field}>
            <label>Role</label>
            <div className={styles.roleButtons}>
              <button
                type="button"
                className={`${styles.roleBtn} ${role === 'ADMIN' ? styles.active : ''}`}
                onClick={() => setRole('ADMIN')}
              >
                👑 Admin
              </button>
              <button
                type="button"
                className={`${styles.roleBtn} ${role === 'COACH' ? styles.acti : ''}`}
                onClick={() => setRole('COACH')}
              >
                👨‍⚕️ Coach
              </button>
            </div>
          </div>

          {error && <div className={styles.error}>{error}</div>}

          <button
            type="submit"
            className={styles.submitBtn}
            disabled={isLoading || !isConnected}
          >
            {isLoading ? 'Authenticating...' : !isConnected ? 'Connecting...' : 'Enter Command Center'}
          </button>
        </form>

        <div className={styles.status}>
          <span className={`${styles.statusDot} ${isConnected ? styles.online : ''}`}></span>
          {isConnected ? 'Bridge Online' : 'Connecting...'}
        </div>
      </div>
    </div>
  )
}
