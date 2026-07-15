import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

export const useArrayStore = defineStore('arrays', () => {
  // State
  const arrays = ref([])
  const currentArray = ref(null)
  const loading = ref(false)
  const statusWsConnected = ref(false)
  const inFlightFetchArrays = new Map()
  let pendingRequests = 0
  let statusWs = null
  let statusHeartbeatTimer = null
  let statusReconnectTimer = null
  let statusReconnectAttempts = 0
  let statusWsStopped = true

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

  const totalCount = computed(() => arrays.value.length)

  function observedAt(value) {
    const timestamp = value ? new Date(value).getTime() : 0
    return Number.isFinite(timestamp) ? timestamp : 0
  }

  function mergeStatus(current, incoming) {
    if (!current) return { ...incoming }
    const merged = { ...current, ...incoming }

    if (observedAt(incoming.connection_observed_at) < observedAt(current.connection_observed_at)) {
      merged.state = current.state
      merged.last_error = current.last_error
      merged.connection_observed_at = current.connection_observed_at
      merged.connection_status_source = current.connection_status_source
    }
    if (observedAt(incoming.agent_observed_at) < observedAt(current.agent_observed_at)) {
      const agentKeys = [
        'agent_deployed', 'agent_running', 'agent_state', 'agent_status_message',
        'agent_status_source', 'agent_observed_at', 'agent_heartbeat_at',
        'observer_health', 'observer_status',
      ]
      agentKeys.forEach(key => { merged[key] = current[key] })
    }
    if (observedAt(incoming.deployment_updated_at) < observedAt(current.deployment_updated_at)) {
      merged.deployment_state = current.deployment_state
      merged.deployment_message = current.deployment_message
      merged.deployment_updated_at = current.deployment_updated_at
    }
    return merged
  }

  function applyStatusUpdate(arrayId, data) {
    if (!arrayId || !data || typeof data !== 'object') return
    const index = arrays.value.findIndex(item => item.array_id === arrayId)
    if (index !== -1) {
      arrays.value[index] = mergeStatus(arrays.value[index], data)
    } else if (data.name || data.host) {
      arrays.value.push({ ...data, array_id: arrayId })
    }
    if (currentArray.value?.array_id === arrayId) {
      currentArray.value = mergeStatus(currentArray.value, data)
    }
  }

  function handleStatusMessage(message) {
    if (!message || typeof message !== 'object') return
    if (message.type === 'status_update') {
      applyStatusUpdate(message.array_id, message.data)
      return
    }
    if (message.type === 'batch' && Array.isArray(message.messages)) {
      message.messages.forEach(handleStatusMessage)
    }
  }

  function clearStatusTimers() {
    if (statusHeartbeatTimer) clearInterval(statusHeartbeatTimer)
    if (statusReconnectTimer) clearTimeout(statusReconnectTimer)
    statusHeartbeatTimer = null
    statusReconnectTimer = null
  }

  function scheduleStatusReconnect() {
    if (statusWsStopped || statusReconnectTimer) return
    const delay = Math.min(1000 * Math.pow(2, statusReconnectAttempts), 30000)
    statusReconnectAttempts += 1
    statusReconnectTimer = setTimeout(() => {
      statusReconnectTimer = null
      connectStatusWebSocket()
    }, delay)
  }

  function connectStatusWebSocket() {
    if (statusWs && statusWs.readyState <= WebSocket.OPEN) return
    statusWsStopped = false
    clearStatusTimers()
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'

    try {
      statusWs = new WebSocket(`${protocol}//${window.location.host}/ws/status`)
      statusWs.onopen = () => {
        statusWsConnected.value = true
        statusReconnectAttempts = 0
        statusHeartbeatTimer = setInterval(() => {
          if (statusWs?.readyState === WebSocket.OPEN) {
            statusWs.send(JSON.stringify({ type: 'ping' }))
          }
        }, 30000)
        if (arrays.value.length > 0) {
          fetchArrays().catch(error => console.debug('Status reconciliation failed:', error))
        }
      }
      statusWs.onmessage = event => {
        try {
          handleStatusMessage(JSON.parse(event.data))
        } catch (error) {
          console.debug('Invalid status WebSocket message:', error)
        }
      }
      statusWs.onclose = () => {
        statusWsConnected.value = false
        statusWs = null
        if (statusHeartbeatTimer) clearInterval(statusHeartbeatTimer)
        statusHeartbeatTimer = null
        scheduleStatusReconnect()
      }
      statusWs.onerror = () => {
        statusWsConnected.value = false
      }
    } catch (error) {
      statusWs = null
      scheduleStatusReconnect()
    }
  }

  function disconnectStatusWebSocket() {
    statusWsStopped = true
    clearStatusTimers()
    statusWsConnected.value = false
    if (statusWs) statusWs.close()
    statusWs = null
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
        const incoming = response.data || []
        arrays.value = incoming.map(item => {
          const current = arrays.value.find(existing => existing.array_id === item.array_id)
          return mergeStatus(current, item)
        })
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
      currentArray.value = mergeStatus(currentArray.value, response.data)
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
      arrays.value[index] = mergeStatus(arrays.value[index], response.data)
    }
    return response.data
  }

  async function deleteArray(arrayId) {
    await api.deleteArray(arrayId)
    arrays.value = arrays.value.filter(a => a.array_id !== arrayId)
  }

  async function connectArray(arrayId, password) {
    const response = await api.connectArray(arrayId, password)
    applyStatusUpdate(arrayId, response.data.status_snapshot || {
      state: 'connected',
      agent_deployed: response.data.agent_deployed,
      agent_running: response.data.agent_running,
    })
    return response.data
  }

  async function disconnectArray(arrayId) {
    const response = await api.disconnectArray(arrayId)
    applyStatusUpdate(arrayId, response.data.status_snapshot || { state: 'disconnected' })
  }

  async function refreshArray(arrayId) {
    const response = await api.refreshArray(arrayId)
    const index = arrays.value.findIndex(a => a.array_id === arrayId)
    if (index !== -1) {
      arrays.value[index] = mergeStatus(arrays.value[index], response.data)
    }
    if (currentArray.value?.array_id === arrayId) {
      currentArray.value = mergeStatus(currentArray.value, response.data)
    }
    return response.data
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
    applyStatusUpdate,
    handleStatusMessage,
    connectStatusWebSocket,
    disconnectStatusWebSocket,
  }
})
