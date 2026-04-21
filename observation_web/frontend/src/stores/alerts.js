import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'
import { useAlertWebSocket } from '../composables/useAlertWebSocket'
import { useAITranslation } from '../composables/useAITranslation'
import { useCriticalBanner } from '../composables/useCriticalBanner'
import { requestNotificationPermission } from '../utils/notification'

export const useAlertStore = defineStore('alerts', () => {
  // ───── Core state ─────
  const alerts = ref([])
  const recentAlerts = ref([])
  const stats = ref(null)
  const loading = ref(false)

  // ───── Composables ─────
  const {
    aiAvailable, aiTranslations,
    checkAIAvailability, autoTranslateAlert, getAITranslation,
  } = useAITranslation()

  const {
    criticalEvents, suppressedObservers, suppressedList, hasCriticalEvents,
    handleCriticalAlert, acknowledgeCritical, acknowledgeAllCritical,
    clearSuppression, clearAllSuppressions,
  } = useCriticalBanner()

  // ───── Alert intake ─────
  const RECENT_ALERTS_HOURS = 2
  const RECENT_ALERTS_MAX = 50

  function handleNewAlert(data) {
    autoTranslateAlert(data)
    recentAlerts.value.unshift(data)
    const cutoff = Date.now() - RECENT_ALERTS_HOURS * 60 * 60 * 1000
    recentAlerts.value = recentAlerts.value
      .filter(a => new Date(a.timestamp || 0).getTime() > cutoff)
      .slice(0, RECENT_ALERTS_MAX)
    handleCriticalAlert(data)
  }

  const { ws, wsConnected, connect: _wsConnect, disconnect: _wsDisconnect } = useAlertWebSocket({
    onMessage: handleNewAlert,
    onConnect: () => fetchRecentAlerts().catch(e => console.error('Fetch recent alerts on WS open failed:', e)),
  })

  // ───── Getters ─────
  const recentCount = computed(() =>
    recentAlerts.value.filter(a => a.level === 'error' || a.level === 'critical').length
  )

  // ───── Data fetching ─────
  async function fetchAlerts(params = {}) {
    loading.value = true
    try {
      const response = await api.getAlerts(params)
      alerts.value = response.data
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

  // ───── WebSocket ─────
  function connectWebSocket() {
    requestNotificationPermission()
    _wsConnect()
  }

  function disconnectWebSocket() {
    _wsDisconnect()
  }

  return {
    // State
    alerts, recentAlerts, stats, loading, wsConnected, ws,
    criticalEvents, aiAvailable, aiTranslations,
    // Getters
    recentCount, hasCriticalEvents, suppressedList, suppressedObservers,
    // Actions
    fetchAlerts, fetchRecentAlerts, fetchStats,
    connectWebSocket, disconnectWebSocket,
    acknowledgeCritical, acknowledgeAllCritical,
    clearSuppression, clearAllSuppressions,
    getAITranslation, checkAIAvailability, autoTranslateAlert,
  }
})
