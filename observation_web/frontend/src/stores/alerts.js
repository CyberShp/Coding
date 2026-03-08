import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'
import { isCriticalAlert } from '../utils/alertTranslator'
import { sendDesktopNotification, playAlertSound, requestNotificationPermission } from '../utils/notification'
import { usePreferencesStore } from './preferences'
import { useArrayStore } from './arrays'

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

  // Suppressed observers: after "acknowledge all", new alerts from these observers
  // are auto-suppressed for 24h (no banner, no notification, no sound)
  const suppressedObservers = ref(new Map())  // observer_name -> expiryTimestamp

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

  // Suppressed list for UI: [{ observer, expiresAt }]
  const suppressedList = computed(() => {
    const now = Date.now()
    const list = []
    for (const [obs, expiry] of suppressedObservers.value.entries()) {
      if (expiry > now) {
        list.push({ observer: obs, expiresAt: expiry })
      }
    }
    return list.sort((a, b) => a.expiresAt - b.expiresAt)
  })

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
    const now = Date.now()
    const expiryMs = 24 * 60 * 60 * 1000
    const newSuppressed = new Map(suppressedObservers.value)
    for (const e of criticalEvents.value) {
      const obs = e.observer_name || 'unknown'
      newSuppressed.set(obs, now + expiryMs)
    }
    suppressedObservers.value = newSuppressed
    criticalEvents.value = []
  }

  function clearSuppression(observerName) {
    const m = new Map(suppressedObservers.value)
    m.delete(observerName)
    suppressedObservers.value = m
  }

  function clearAllSuppressions() {
    suppressedObservers.value = new Map()
  }

  function _cleanupExpiredSuppressions() {
    const now = Date.now()
    const m = suppressedObservers.value
    let changed = false
    for (const [obs, expiry] of m.entries()) {
      if (expiry <= now) {
        m.delete(obs)
        changed = true
      }
    }
    if (changed) {
      suppressedObservers.value = new Map(m)
    }
  }

  function handleNewAlert(data) {
    // Add to recent list
    recentAlerts.value.unshift(data)
    if (recentAlerts.value.length > 20) {
      recentAlerts.value.pop()
    }

    // Check if critical
    if (isCriticalAlert(data)) {
      // Personal view: skip banner/notification for alerts outside watched arrays/tags
      const prefs = usePreferencesStore()
      if (prefs.personalViewActive) {
        const watchedIds = prefs.watchedArrayIds || []
        const watchedTags = prefs.watchedTagIds || []
        const arrStore = useArrayStore()
        const allowedArrayIds = new Set([
          ...watchedIds,
          ...arrStore.arrays.filter(a => a.tag_id != null && watchedTags.includes(a.tag_id)).map(a => a.array_id)
        ])
        if (!allowedArrayIds.has(data.array_id)) {
          return
        }
      }

      _cleanupExpiredSuppressions()
      const obs = data.observer_name || 'unknown'
      const expiry = suppressedObservers.value.get(obs)
      const now = Date.now()
      if (expiry && now < expiry) {
        // Suppressed: skip banner, notification, sound
        return
      }

      criticalEvents.value.unshift(data)
      if (criticalEvents.value.length > 50) {
        criticalEvents.value = criticalEvents.value.slice(0, 50)
      }

      const title = `关键事件：${data.observer_name || '未知'}`
      const body = (data.message || '').substring(0, 120)
      sendDesktopNotification(title, body, { tag: `critical-${data.id || Date.now()}` })
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
    clearSuppression,
    clearAllSuppressions,
    suppressedObservers,
    suppressedList,
  }
})
