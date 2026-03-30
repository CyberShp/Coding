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

  // Status WebSocket
  let _statusWs = null
  let _statusWsReconnectTimer = null

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
    arrays.value.filter(a => a.state === 'connected').length
  )

  const runningCount = computed(() =>
    arrays.value.filter(a => a.agent_running).length
  )

  const healthyCount = computed(() =>
    arrays.value.filter(a => a.agent_healthy).length
  )

  const totalCount = computed(() => arrays.value.length)

  // --- Status WebSocket ---

  function _applyStatusUpdate(arrayId, data) {
    // Update arrays list
    const index = arrays.value.findIndex(a => a.array_id === arrayId)
    if (index !== -1) {
      arrays.value[index] = { ...arrays.value[index], ...data }
    }
    // Update currentArray if viewing this array
    if (currentArray.value?.array_id === arrayId) {
      currentArray.value = { ...currentArray.value, ...data }
    }
  }

  function connectStatusWebSocket() {
    if (_statusWs && _statusWs.readyState <= 1) return // already open/connecting

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/status`

    try {
      _statusWs = new WebSocket(wsUrl)
    } catch {
      return
    }

    _statusWs.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'status_update' && msg.array_id && msg.data) {
          _applyStatusUpdate(msg.array_id, msg.data)
        }
        // Handle batched messages
        if (msg.type === 'batch' && Array.isArray(msg.messages)) {
          for (const m of msg.messages) {
            if (m.type === 'status_update' && m.array_id && m.data) {
              _applyStatusUpdate(m.array_id, m.data)
            }
          }
        }
      } catch { /* ignore parse errors */ }
    }

    _statusWs.onclose = () => {
      _statusWs = null
      // Auto-reconnect after 5 seconds
      if (!_statusWsReconnectTimer) {
        _statusWsReconnectTimer = setTimeout(() => {
          _statusWsReconnectTimer = null
          connectStatusWebSocket()
        }, 5000)
      }
    }

    _statusWs.onerror = () => {
      // onclose will fire after onerror
    }

    // Heartbeat ping every 25 seconds
    const pingInterval = setInterval(() => {
      if (_statusWs && _statusWs.readyState === WebSocket.OPEN) {
        _statusWs.send(JSON.stringify({ type: 'ping' }))
      } else {
        clearInterval(pingInterval)
      }
    }, 25000)
  }

  function disconnectStatusWebSocket() {
    if (_statusWsReconnectTimer) {
      clearTimeout(_statusWsReconnectTimer)
      _statusWsReconnectTimer = null
    }
    if (_statusWs) {
      _statusWs.onclose = null  // prevent auto-reconnect
      _statusWs.close()
      _statusWs = null
    }
  }

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
      arrays.value[index].agent_deployed = response.data.agent_deployed
      arrays.value[index].agent_running = response.data.agent_running
      arrays.value[index].agent_healthy = response.data.agent_healthy ?? false
    }
    if (currentArray.value?.array_id === arrayId) {
      currentArray.value = {
        ...currentArray.value,
        state: 'connected',
        agent_deployed: response.data.agent_deployed,
        agent_running: response.data.agent_running,
        agent_healthy: response.data.agent_healthy ?? false,
      }
    }
    return response.data
  }

  async function disconnectArray(arrayId) {
    await api.disconnectArray(arrayId)
    const index = arrays.value.findIndex(a => a.array_id === arrayId)
    if (index !== -1) {
      arrays.value[index].state = 'disconnected'
    }
    if (currentArray.value?.array_id === arrayId) {
      currentArray.value = { ...currentArray.value, state: 'disconnected' }
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

  return {
    // State
    arrays,
    currentArray,
    loading,
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
    // Status WebSocket
    connectStatusWebSocket,
    disconnectStatusWebSocket,
    // Internal (exposed for testing)
    _applyStatusUpdate,
  }
})
