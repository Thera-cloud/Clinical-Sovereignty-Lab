import { Routes, Route, Navigate } from 'react-router-dom'
import { WebSocketProvider } from './context/WebSocketContext'
import { AuthProvider } from './context/AuthContext'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Users from './pages/Users'
import AskNate from './pages/AskNate'
import NightSchool from './pages/NightSchool'
import TheEye from './pages/TheEye'
import AuditLog from './pages/AuditLog'

function App() {
  return (
    <AuthProvider>
      <WebSocketProvider>
        <Routes>
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/login" element={<Login />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/users" element={<Users />} />
          <Route path="/ask-nate" element={<AskNate />} />
          <Route path="/night-school" element={<NightSchool />} />
          <Route path="/the-eye" element={<TheEye />} />
          <Route path="/audit-log" element={<AuditLog />} />
        </Routes>
      </WebSocketProvider>
    </AuthProvider>
  )
}

export default App
