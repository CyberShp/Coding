import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

export const useArrayStore = defineStore('arrays', () => {
  // State
  const arrays = ref([])
  const currentArray = ref(null)
  const loading = ref(false)
  const inFlightFetchArrays = new Map()
  let pendingRequests = 0

  // Status WebSocket state
  const statusWs = ref(null)
  const statusWsConnected = ref(false)
  let statusHeartbeatTimer = null
  let statusReconnectTimer = null
  let statusReconnectAttempts = 0
  const MAX_STATUS_RECONNECT_ATTEMPTS = 10
  const BASE_STATUS_RECONNECT_DELAY = 1000

  function beginLoading() {
    pendingRequests += 1
    loading.value = true
  }

  function endLoading() {
    pendingRequests = Math.max(0, pendingRequests - 1)
    loading.value = pendingRequests > 0
  }

  // Getters
  const connectedCount = computed(() => 
    arrays.value.filter(a => a.state === 'connected' || a.state === 'degraded').length
  )

  const runningCount = computed(() =>
    arrays.value.filter(a => a.agent_running).length
  )

  const healthyCount = computed(() =>
    arrays.value.filter(a => a.agent_healthy).length
  )

  const totalCount = computed(() => arrays.value.length)

  // Actions
  async function fetchArrays(tagId = null, options = {}) {
    const hasSignal = Boolean(options && options.signal)
    const key = String(tagId ?? 'all')
    if (!hasSignal && inFlightFetchArrays.has(key)) {
      return inFlightFetchArrays.get(key)
    }

    const promise = (async () => {
      beginLoading()
      try {
        const response = await api.getArrayStatuses(tagId, options)
        arrays.value = response.data
        return response.data
      } finally {
        inFlightFetchArrays.delete(key)
        endLoading()
      }
    })()

    if (!hasSignal) {
      inFlightFetchArrays.set(key, promise)
    }
    return promise
  }

  async function fetchArray(arrayId) {
    beginLoading()
    try {
      const response = await api.getArray(arrayId)
      currentArray.value = response.data
      return response.data
    } finally {
      endLoading()
    }
  }

  async function createArray(data) {
    const response = await api.createArray(data)
    arrays.value.push(response.data)
    return response.data
  }

  async function updateArray(arrayId, data) {
    const response = await api.updateArray(arrayId, data)
    const index = arrays.value.findIndex(a => a.array_id === arrayId)
    if (index !== -1) {
      arrays.value[index] = { ...arrays.value[index], ...response.data }
    }
    return response.data
  }

  async function deleteArray(arrayId) {
    await api.deleteArray(arrayId)
    arrays.value = arrays.value.filter(a => a.array_id !== arrayId)
  }

  async function connectArray(arrayId, password) {
    const response = await api.connectArray(arrayId, password)
    const index = arrays.value.findIndex(a => a.array_id === arrayId)
    if (index !== -1) {
      arrays.value[index].state = 'connected'
      arrays.value[index].transport_connected = true
      arrays.value[index].agent_deployed = response.data.agent_deployed
      arrays.value[index].agent_running = response.data.agent_running
      arrays.value[index].agent_healthy = response.data.agent_healthy || false
    }
    if (currentArray.value?.array_id === arrayId) {
      currentArray.value = {
        ...currentArray.value,
        state: 'connected',
        transport_connected: true,
        agent_deployed: response.data.agent_deployed,
        agent_running: response.data.agent_running,
        agent_healthy: response.data.agent_healthy || false,
      }
    }
    return response.data
  }

  async function disconnectArray(arrayId) {
    await api.disconnectArray(arrayId)
    const index = arrays.value.findIndex(a => a.array_id === arrayId)
    if (index !== -1) {
      arrays.value[index].state = 'disconnected'
      arrays.value[index].transport_connected = false
    }
    if (currentArray.value?.array_id === arrayId) {
      currentArray.value = {
        ...currentArray.value,
        state: 'disconnected',
        transport_connected: false,
      }
    }
  }

  async function refreshArray(arrayId) {
    const response = await api.refreshArray(arrayId)
    const index = arrays.value.findIndex(a => a.array_id === arrayId)
    if (index !== -1) {
      arrays.value[index] = { ...arrays.value[index], ...response.data }
    }
    if (currentArray.value?.array_id === arrayId) {
      currentArray.value = { ...currentArray.value, ...response.data }
    }
    return response.data
  }

  // ─── Status WebSocket ───────────────────────────────────────────────
  function _applyStatusUpdate(data) {
    const arrayId = data.array_id
    if (!arrayId) return

    // Update array in list
    const index = arrays.value.findIndex(a => a.array_id === arrayId)
    if (index !== -1) {
      const updates = { ...data }
      delete updates.type
      delete updates.timestamp
      arrays.value[index] = { ...arrays.value[index], ...updates }
    }

    // Update detail page if viewing this array
    if (currentArray.value?.array_id === arrayId) {
      const updates = { ...data }
      delete updates.type
      delete updates.timestamp
      currentArray.value = { ...currentArray.value, ...updates }
    }
  }

  function _cleanupStatusTimers() {
    if (statusHeartbeatTimer) {
      clearInterval(statusHeartbeatTimer)
      statusHeartbeatTimer = null
    }
    if (statusReconnectTimer) {
      clearTimeout(statusReconnectTimer)
      statusReconnectTimer = null
    }
  }

  function _scheduleStatusReconnect() {
    if (statusReconnectAttempts >= MAX_STATUS_RECONNECT_ATTEMPTS) {
      console.warn('Status WebSocket max reconnect attempts reached')
      return
    }
    const delay = Math.min(BASE_STATUS_RECONNECT_DELAY * (2 ** statusReconnectAttempts), 30000)
    statusReconnectAttempts++
    statusReconnectTimer = setTimeout(connectStatusWebSocket, delay)
  }

  function connectStatusWebSocket() {
    if (statusWs.value) return
    _cleanupStatusTimers()

    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/status`

    try {
      statusWs.value = new WebSocket(wsUrl)

      statusWs.value.onopen = () => {
        statusWsConnected.value = true
        statusReconnectAttempts = 0
        console.log('Status WebSocket connected')
        statusHeartbeatTimer = setInterval(() => {
          if (statusWs.value && statusWs.value.readyState === WebSocket.OPEN) {
            statusWs.value.send(JSON.stringify({ type: 'ping' }))
          }
        }, 30000)
      }

      statusWs.value.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'status_update') {
            _applyStatusUpdate(msg.data || msg)
          } else if (msg.type === 'batch') {
            (msg.messages || []).forEach(m => {
              if (m.type === 'status_update') {
                _applyStatusUpdate(m.data || m)
              }
            })
          }
          // Ignore heartbeat/pong/connected messages
        } catch (e) {
          console.error('Failed to parse status WebSocket message:', e)
        }
      }

      statusWs.value.onclose = () => {
        statusWsConnected.value = false
        statusWs.value = null
        _cleanupStatusTimers()
        _scheduleStatusReconnect()
      }

      statusWs.value.onerror = (error) => {
        console.error('Status WebSocket error:', error)
      }
    } catch (error) {
      console.error('Failed to connect status WebSocket:', error)
      _scheduleStatusReconnect()
    }
  }

  function disconnectStatusWebSocket() {
    _cleanupStatusTimers()
    statusReconnectAttempts = MAX_STATUS_RECONNECT_ATTEMPTS
    if (statusWs.value) {
      statusWs.value.close()
      statusWs.value = null
    }
  }

  return {
    // State
    arrays,
    currentArray,
    loading,
    statusWsConnected,
    // Getters
    connectedCount,
    runningCount,
    healthyCount,
    totalCount,
    // Actions
    fetchArrays,
    fetchArray,
    createArray,
    updateArray,
    deleteArray,
    connectArray,
    disconnectArray,
    refreshArray,
    connectStatusWebSocket,
    disconnectStatusWebSocket,
    // Internal (exposed for testing)
    _applyStatusUpdate,
  }
})
