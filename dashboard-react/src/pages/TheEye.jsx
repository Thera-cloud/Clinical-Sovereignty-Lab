import { Link } from 'react-router-dom'

export default function TheEye() {
  return (
    <div style={{ padding: '24px', background: 'var(--bg-dark)', minHeight: '100vh' }}>
      <Link to="/dashboard" style={{ color: 'var(--gold)', marginBottom: '20px', display: 'inline-block' }}>← Back to Dashboard</Link>
      <h1 style={{ color: 'var(--gold)', marginTop: '20px' }}>TheEye</h1>
      <p style={{ color: 'var(--text-secondary)', marginTop: '12px' }}>Coming soon...</p>
    </div>
  )
}
