import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'
import { isCriticalAlert } from '../utils/alertTranslator'
import { sendDesktopNotification, playAlertSound, requestNotificationPermission } from '../utils/notification'

export const useAlertStore = defineStore('alerts', () => {
  // State
  const alerts = ref([])
  const recentAlerts = ref([])
  const stats = ref(null)
  const loading = ref(false)
  const ws = ref(null)
  const wsConnected = ref(false)

  // Critical event banner state
  const criticalEvents = ref([])  // unacknowledged critical events

  // WebSocket reconnection state
  let heartbeatTimer = null
  let reconnectTimer = null
  let reconnectAttempts = 0
  const MAX_RECONNECT_ATTEMPTS = 10
  const BASE_RECONNECT_DELAY = 1000  // 1 second

  // Getters
  const recentCount = computed(() => {
    return recentAlerts.value.filter(a => 
      a.level === 'error' || a.level === 'critical'
    ).length
  })

  const hasCriticalEvents = computed(() => criticalEvents.value.length > 0)

  // Actions
  async function fetchAlerts(params = {}) {
    loading.value = true
    try {
      const response = await api.getAlerts(params)
      alerts.value = response.data
      return response.data
    } finally {
      loading.value = false
    }
  }

  async function fetchRecentAlerts() {
    try {
      const response = await api.getRecentAlerts()
      recentAlerts.value = response.data
    } catch (error) {
      console.error('Failed to fetch recent alerts:', error)
    }
  }

  async function fetchStats() {
    try {
      const response = await api.getAlertStats()
      stats.value = response.data
    } catch (error) {
      console.error('Failed to fetch stats:', error)
    }
  }

  function acknowledgeCritical(id) {
    criticalEvents.value = criticalEvents.value.filter(e => e.id !== id)
  }

  function acknowledgeAllCritical() {
    criticalEvents.value = []
  }

  function handleNewAlert(data) {
    // Add to recent list
    recentAlerts.value.unshift(data)
    if (recentAlerts.value.length > 20) {
      recentAlerts.value.pop()
    }

    // Check if critical
    if (isCriticalAlert(data)) {
      criticalEvents.value.unshift(data)
      // Keep max 50 critical events
      if (criticalEvents.value.length > 50) {
        criticalEvents.value = criticalEvents.value.slice(0, 50)
      }

      // Desktop notification
      const title = `关键事件：${data.observer_name || '未知'}`
      const body = (data.message || '').substring(0, 120)
      sendDesktopNotification(title, body, { tag: `critical-${data.id || Date.now()}` })

      // Sound
      playAlertSound()
    }
  }

  function cleanupTimers() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  function scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      console.warn('WebSocket max reconnect attempts reached, stopping reconnection')
      return
    }
    
    // Exponential backoff: 1s, 2s, 4s, 8s, 16s, max 30s
    const delay = Math.min(BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttempts), 30000)
    reconnectAttempts++
    
    console.log(`WebSocket reconnecting in ${delay}ms (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`)
    reconnectTimer = setTimeout(connectWebSocket, delay)
  }

  function connectWebSocket() {
    if (ws.value) return

    // Clean up any existing timers
    cleanupTimers()

    // Request notification permission on first connect
    requestNotificationPermission()

    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/alerts`
    
    try {
      ws.value = new WebSocket(wsUrl)
      
      ws.value.onopen = () => {
        wsConnected.value = true
        reconnectAttempts = 0  // Reset on successful connection
        console.log('WebSocket connected')
        
        // Start heartbeat
        heartbeatTimer = setInterval(() => {
          if (ws.value && ws.value.readyState === WebSocket.OPEN) {
            ws.value.send(JSON.stringify({ type: 'ping' }))
          }
        }, 30000)
      }

      ws.value.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          
          if (data.type === 'alert') {
            handleNewAlert(data.data)
          }
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e)
        }
      }

      ws.value.onclose = () => {
        wsConnected.value = false
        ws.value = null
        cleanupTimers()
        scheduleReconnect()
      }

      ws.value.onerror = (error) => {
        console.error('WebSocket error:', error)
      }

    } catch (error) {
      console.error('Failed to connect WebSocket:', error)
      scheduleReconnect()
    }
  }

  function disconnectWebSocket() {
    cleanupTimers()
    reconnectAttempts = MAX_RECONNECT_ATTEMPTS  // Prevent auto-reconnect
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
  }

  return {
    // State
    alerts,
    recentAlerts,
    stats,
    loading,
    wsConnected,
    criticalEvents,
    // Getters
    recentCount,
    hasCriticalEvents,
    // Actions
    fetchAlerts,
    fetchRecentAlerts,
    fetchStats,
    connectWebSocket,
    disconnectWebSocket,
    acknowledgeCritical,
    acknowledgeAllCritical,
  }
})
