/**
 * WebSocket lifecycle composable.
 * Handles connect / disconnect / reconnect with exponential backoff and heartbeat.
 *
 * @param {object} options
 * @param {function} options.onMessage  - called with parsed alert data when type === 'alert'
 * @param {function} [options.onConnect] - called each time the socket successfully opens
 */
import { ref, shallowRef } from 'vue'

export function useAlertWebSocket({ onMessage, onConnect } = {}) {
  const ws = shallowRef(null)
  const wsConnected = ref(false)

  let heartbeatTimer = null
  let reconnectTimer = null
  let reconnectAttempts = 0
  let intentionalDisconnect = false

  const MAX_RECONNECT_DELAY = 60000  // cap at 60 s
  const BASE_RECONNECT_DELAY = 1000  // start at 1 s

  function cleanupTimers() {
    if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null }
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  }

  function scheduleReconnect() {
    if (intentionalDisconnect) return
    const delay = Math.min(BASE_RECONNECT_DELAY * Math.pow(2, Math.min(reconnectAttempts, 6)), MAX_RECONNECT_DELAY)
    reconnectAttempts++
    console.log(`WebSocket reconnecting in ${delay}ms (attempt ${reconnectAttempts})`)
    reconnectTimer = setTimeout(connect, delay)
  }

  function connect() {
    if (ws.value) return
    cleanupTimers()
    intentionalDisconnect = false

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${proto}//${window.location.host}/ws/alerts`

    try {
      const socket = new WebSocket(wsUrl)
      ws.value = socket

      socket.onopen = () => {
        if (socket !== ws.value) return  // stale socket
        wsConnected.value = true
        reconnectAttempts = 0
        console.log('Alert WebSocket connected')
        if (onConnect) onConnect()
        heartbeatTimer = setInterval(() => {
          if (ws.value?.readyState === WebSocket.OPEN) {
            ws.value.send(JSON.stringify({ type: 'ping' }))
          }
        }, 30000)
      }

      socket.onmessage = (event) => {
        if (socket !== ws.value) return  // stale socket
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'alert' && onMessage) onMessage(data.data)
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e)
        }
      }

      socket.onclose = () => {
        if (socket !== ws.value) return  // stale socket — do NOT touch shared state
        wsConnected.value = false
        ws.value = null
        cleanupTimers()
        scheduleReconnect()
      }

      socket.onerror = (error) => {
        console.error('WebSocket error:', error)
      }

    } catch (error) {
      console.error('Failed to create WebSocket:', error)
      scheduleReconnect()
    }
  }

  function disconnect() {
    cleanupTimers()
    intentionalDisconnect = true
    wsConnected.value = false
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
  }

  return { ws, wsConnected, connect, disconnect }
}
