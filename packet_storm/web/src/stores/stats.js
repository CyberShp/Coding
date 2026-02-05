import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useStatsStore = defineStore('stats', () => {
  // WebSocket connection
  const connected = ref(false)
  let ws = null

  // Real-time stats
  const stats = ref({
    tx: { packets: 0, bytes: 0, errors: 0, current_pps: 0, current_mbps: 0, avg_pps: 0, avg_mbps: 0 },
    rx: { packets: 0, bytes: 0 },
    anomalies: { total: 0, by_type: {} },
    runtime_seconds: 0,
    recent_errors: [],
  })

  // Session state
  const session = ref(null)

  // History for charts (last 60 data points = 1 minute at 1s intervals)
  const ppsHistory = ref([])
  const mbpsHistory = ref([])
  const maxHistorySize = 60

  function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/stats`

    try {
      ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        connected.value = true
        console.log('WebSocket connected')
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'stats_update' && msg.data) {
            stats.value = msg.data

            // Update history
            const now = new Date().toLocaleTimeString()
            ppsHistory.value.push({ time: now, value: msg.data.tx?.current_pps || 0 })
            mbpsHistory.value.push({ time: now, value: msg.data.tx?.current_mbps || 0 })

            if (ppsHistory.value.length > maxHistorySize) ppsHistory.value.shift()
            if (mbpsHistory.value.length > maxHistorySize) mbpsHistory.value.shift()
          }
        } catch (e) {
          console.error('WebSocket message parse error:', e)
        }
      }

      ws.onclose = () => {
        connected.value = false
        console.log('WebSocket disconnected, reconnecting in 3s...')
        setTimeout(connect, 3000)
      }

      ws.onerror = (err) => {
        console.error('WebSocket error:', err)
        connected.value = false
      }
    } catch (e) {
      console.error('WebSocket connection failed:', e)
      setTimeout(connect, 3000)
    }
  }

  function sendAction(action) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action }))
    }
  }

  function disconnect() {
    if (ws) {
      ws.close()
      ws = null
    }
  }

  return {
    connected,
    stats,
    session,
    ppsHistory,
    mbpsHistory,
    connect,
    disconnect,
    sendAction,
  }
})
