import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

export const useArrayStore = defineStore('arrays', () => {
  // State
  const arrays = ref([])
  const currentArray = ref(null)
  const loading = ref(false)

  // Getters
  const connectedCount = computed(() => 
    arrays.value.filter(a => a.state === 'connected').length
  )

  const runningCount = computed(() =>
    arrays.value.filter(a => a.agent_running).length
  )

  const totalCount = computed(() => arrays.value.length)

  // Actions
  async function fetchArrays() {
    loading.value = true
    try {
      const response = await api.getArrays()
      arrays.value = response.data
      return response.data
    } finally {
      loading.value = false
    }
  }

  async function fetchArray(arrayId) {
    loading.value = true
    try {
      const response = await api.getArray(arrayId)
      currentArray.value = response.data
      return response.data
    } finally {
      loading.value = false
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
    }
    return response.data
  }

  async function disconnectArray(arrayId) {
    await api.disconnectArray(arrayId)
    const index = arrays.value.findIndex(a => a.array_id === arrayId)
    if (index !== -1) {
      arrays.value[index].state = 'disconnected'
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
  }
})
