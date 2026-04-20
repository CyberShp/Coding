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

  // AI auto-translation
  const aiAvailable = ref(false)
  const aiTranslations = ref(new Map())  // alert_id → interpretation string
  let aiStatusChecked = false
  let aiFetchQueue = []
  let aiFetching = false

  async function checkAIAvailability() {
    if (aiStatusChecked) return
    aiStatusChecked = true
    try {
      const { data } = await api.checkAIStatus()
      aiAvailable.value = !!data?.available
    } catch {
      aiAvailable.value = false
    }
  }

  async function autoTranslateAlert(alert) {
    if (!aiAvailable.value) return
    if (!alert?.id) return
    if (aiTranslations.value.has(alert.id)) return
    // Only auto-translate alarm_type observer alerts
    if (alert.observer_name !== 'alarm_type') return
    aiFetchQueue.push(alert.id)
    drainAIQueue()
  }

  const AI_BATCH_SIZE = 5
  const AI_TRANSLATIONS_MAX = 500  // LRU cap

  async function drainAIQueue() {
    if (aiFetching || aiFetchQueue.length === 0) return
    aiFetching = true
    while (aiFetchQueue.length > 0) {
      // Take a batch of up to AI_BATCH_SIZE
      const batch = []
      while (batch.length < AI_BATCH_SIZE && aiFetchQueue.length > 0) {
        const id = aiFetchQueue.shift()
        if (!aiTranslations.value.has(id)) batch.push(id)
      }
      if (batch.length === 0) continue
      // Fetch in parallel
      const results = await Promise.allSettled(
        batch.map(id => api.getAIInterpretation(id).then(r => ({ id, text: r.data?.interpretation })))
      )
      const m = new Map(aiTranslations.value)
      for (const r of results) {
        if (r.status === 'fulfilled' && r.value.text) {
          m.set(r.value.id, r.value.text)
        }
      }
      // LRU eviction: drop oldest entries if over cap
      if (m.size > AI_TRANSLATIONS_MAX) {
        const excess = m.size - AI_TRANSLATIONS_MAX
        const iter = m.keys()
        for (let i = 0; i < excess; i++) m.delete(iter.next().value)
      }
      aiTranslations.value = m
    }
    aiFetching = false
  }

  function getAITranslation(alertId) {
    const val = aiTranslations.value.get(alertId)
    if (val === undefined) return null
    // LRU touch: delete + re-insert moves key to end of Map iteration order
    const m = aiTranslations.value
    m.delete(alertId)
    m.set(alertId, val)
    return val
  }

  // Critical event banner state
  const criticalEvents = ref([])  // unacknowledged critical events

  // Suppressed observers: after "acknowledge all", new alerts from these observers
  // are auto-suppressed for 24h (no banner, no notification, no sound)
  const suppressedObservers = ref(new Map())  // observer_name -> expiryTimestamp

  // WebSocket reconnection state
  let heartbeatTimer = null
  let reconnectTimer = null
  let reconnectAttempts = 0
  const MAX_RECONNECT_DELAY = 60000  // cap at 60s between attempts
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
      // Auto-translate alarm_type alerts when AI is available
      checkAIAvailability().then(() => {
        const items = Array.isArray(response.data) ? response.data : (response.data?.items || [])
        for (const a of items) autoTranslateAlert(a)
      })
      return response.data
    } finally {
      loading.value = false
    }
  }

  async function fetchRecentAlerts(options = {}) {
    try {
      const response = await api.getRecentAlerts(20, options)
      recentAlerts.value = response.data
      // Auto-translate alarm_type alerts
      checkAIAvailability().then(() => {
        for (const a of (response.data || [])) autoTranslateAlert(a)
      })
    } catch (error) {
      if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
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

  const RECENT_ALERTS_HOURS = 2
  const RECENT_ALERTS_MAX = 50

  function handleNewAlert(data) {
    // Auto-translate alarm_type alerts via AI
    autoTranslateAlert(data)

    // Add to recent list
    recentAlerts.value.unshift(data)
    // Keep only alerts within last 2 hours, cap at 50
    const cutoff = Date.now() - RECENT_ALERTS_HOURS * 60 * 60 * 1000
    recentAlerts.value = recentAlerts.value
      .filter(a => new Date(a.timestamp || 0).getTime() > cutoff)
      .slice(0, RECENT_ALERTS_MAX)

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
    if (intentionalDisconnect) return  // User/component called disconnectWebSocket
    // Infinite reconnect with exponential backoff capped at MAX_RECONNECT_DELAY
    const delay = Math.min(BASE_RECONNECT_DELAY * Math.pow(2, Math.min(reconnectAttempts, 6)), MAX_RECONNECT_DELAY)
    reconnectAttempts++

    console.log(`WebSocket reconnecting in ${delay}ms (attempt ${reconnectAttempts})`)
    reconnectTimer = setTimeout(connectWebSocket, delay)
  }

  let intentionalDisconnect = false

  function connectWebSocket() {
    if (ws.value) return

    // Clean up any existing timers
    cleanupTimers()
    intentionalDisconnect = false

    // Request notification permission on first connect
    requestNotificationPermission()

    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/alerts`

    try {
      const socket = new WebSocket(wsUrl)
      ws.value = socket

      // All handlers are closure-scoped to THIS socket instance.
      // If a stale socket fires onclose after a new one is already assigned
      // to ws.value, the guard `socket !== ws.value` prevents clobbering.

      socket.onopen = () => {
        if (socket !== ws.value) return  // stale socket, ignore
        wsConnected.value = true
        reconnectAttempts = 0
        console.log('WebSocket connected')
        fetchRecentAlerts().catch(e => console.error('Fetch recent alerts on WS open failed:', e))
        heartbeatTimer = setInterval(() => {
          if (ws.value && ws.value.readyState === WebSocket.OPEN) {
            ws.value.send(JSON.stringify({ type: 'ping' }))
          }
        }, 30000)
      }

      socket.onmessage = (event) => {
        if (socket !== ws.value) return  // stale socket, ignore
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'alert') {
            handleNewAlert(data.data)
          }
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
      console.error('Failed to connect WebSocket:', error)
      scheduleReconnect()
    }
  }

  function disconnectWebSocket() {
    cleanupTimers()
    intentionalDisconnect = true  // Prevent auto-reconnect
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
    aiAvailable,
    aiTranslations,
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
    getAITranslation,
    checkAIAvailability,
    autoTranslateAlert,
  }
})
