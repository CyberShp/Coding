import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

export const useAlertStore = defineStore('alerts', () => {
  // State
  const alerts = ref([])
  const recentAlerts = ref([])
  const stats = ref(null)
  const loading = ref(false)
  const ws = ref(null)
  const wsConnected = ref(false)

  // Getters
  const recentCount = computed(() => {
    return recentAlerts.value.filter(a => 
      a.level === 'error' || a.level === 'critical'
    ).length
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

  function connectWebSocket() {
    if (ws.value) return

    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/alerts`
    
    try {
      ws.value = new WebSocket(wsUrl)
      
      ws.value.onopen = () => {
        wsConnected.value = true
        console.log('WebSocket connected')
      }

      ws.value.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          
          if (data.type === 'alert') {
            // Add new alert to recent list
            recentAlerts.value.unshift(data.data)
            // Keep only last 20
            if (recentAlerts.value.length > 20) {
              recentAlerts.value.pop()
            }
          }
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e)
        }
      }

      ws.value.onclose = () => {
        wsConnected.value = false
        ws.value = null
        // Reconnect after 5 seconds
        setTimeout(connectWebSocket, 5000)
      }

      ws.value.onerror = (error) => {
        console.error('WebSocket error:', error)
      }

      // Send heartbeat every 30 seconds
      setInterval(() => {
        if (ws.value && ws.value.readyState === WebSocket.OPEN) {
          ws.value.send(JSON.stringify({ type: 'ping' }))
        }
      }, 30000)

    } catch (error) {
      console.error('Failed to connect WebSocket:', error)
    }
  }

  function disconnectWebSocket() {
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
    // Getters
    recentCount,
    // Actions
    fetchAlerts,
    fetchRecentAlerts,
    fetchStats,
    connectWebSocket,
    disconnectWebSocket,
  }
})
