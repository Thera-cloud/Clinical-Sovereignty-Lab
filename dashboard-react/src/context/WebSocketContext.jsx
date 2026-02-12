import { createContext, useContext, useEffect, useState, useRef, useCallback } from 'react'
import { useAuth } from './AuthContext'

const WebSocketContext = createContext(null)

export function WebSocketProvider({ children }) {
  const { user, token } = useAuth()
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState(null)
  const socketRef = useRef(null)
  const listenersRef = useRef({})

  const connect = useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket('ws://localhost:8765')
    
    ws.onopen = () => {
      console.log('[WS] Connected')
      setIsConnected(true)
      
      // Auto-authenticate if we have credentials
      const password = sessionStorage.getItem('password')
      const username = sessionStorage.getItem('username')
      const role = sessionStorage.getItem('role')
      
      if (username && password) {
        ws.send(JSON.stringify({
          type: 'login_request',
          username,
          password,
          expected_role: role
        }))
      }
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      console.log('[WS] Received:', data.type)
      setLastMessage(data)
      
      // Notify all listeners for this message type
      const typeListeners = listenersRef.current[data.type] || []
      typeListeners.forEach(callback => callback(data))
      
      // Also notify 'all' listeners
      const allListeners = listenersRef.current['all'] || []
      allListeners.forEach(callback => callback(data))
    }

    ws.onclose = () => {
      console.log('[WS] Disconnected')
      setIsConnected(false)
      setTimeout(connect, 3000)
    }

    ws.onerror = (error) => {
      console.error('[WS] Error:', error)
    }

    socketRef.current = ws
  }, [])

  useEffect(() => {
    connect()
    return () => {
      if (socketRef.current) {
        socketRef.current.close()
      }
    }
  }, [connect])

  const send = useCallback((type, payload = {}) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type, ...payload }))
    } else {
      console.warn('[WS] Not connected, cannot send:', type)
    }
  }, [])

  const subscribe = useCallback((type, callback) => {
    if (!listenersRef.current[type]) {
      listenersRef.current[type] = []
    }
    listenersRef.current[type].push(callback)
    
    // Return unsubscribe function
    return () => {
      listenersRef.current[type] = listenersRef.current[type].filter(cb => cb !== callback)
    }
  }, [])

  return (
    <WebSocketContext.Provider value={{ isConnected, lastMessage, send, subscribe }}>
      {children}
    </WebSocketContext.Provider>
  )
}

export function useWebSocket() {
  const context = useContext(WebSocketContext)
  if (!context) {
    throw new Error('useWebSocket must be used within WebSocketProvider')
  }
  return context
}
