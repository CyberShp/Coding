import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

export const usePreferencesStore = defineStore('preferences', () => {
  const defaultTagId = ref(null)
  const watchedTagIds = ref([])
  const watchedArrayIds = ref([])
  const watchedObservers = ref([])
  const mutedObservers = ref([])
  const alertSound = ref(true)
  const dashboardL1TagId = ref(null)
  let savedPV = false
  try { savedPV = localStorage.getItem('personalViewActive') === 'true' } catch { /* storage unavailable */ }
  const personalViewActive = ref(savedPV)

  const hasPersonalView = computed(() => {
    return watchedTagIds.value.length > 0 ||
      watchedArrayIds.value.length > 0 ||
      watchedObservers.value.length > 0
  })

  async function load(options = {}) {
    try {
      const res = await api.getPreferences(options)
      const d = res.data || {}
      defaultTagId.value = d.default_tag_id ?? null
      watchedTagIds.value = d.watched_tag_ids || []
      watchedArrayIds.value = d.watched_array_ids || []
      watchedObservers.value = d.watched_observers || []
      mutedObservers.value = d.muted_observers || []
      alertSound.value = d.alert_sound !== false
      dashboardL1TagId.value = d.dashboard_l1_tag_id ?? null
      return d
    } catch (error) {
      if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') {
        return {}
      }
      defaultTagId.value = null
      return {}
    }
  }

  async function update(data) {
    const res = await api.updatePreferences(data)
    const d = res.data || {}
    defaultTagId.value = d.default_tag_id ?? null
    watchedTagIds.value = d.watched_tag_ids || []
    watchedArrayIds.value = d.watched_array_ids || []
    watchedObservers.value = d.watched_observers || []
    mutedObservers.value = d.muted_observers || []
    alertSound.value = d.alert_sound !== false
    dashboardL1TagId.value = d.dashboard_l1_tag_id ?? null
    return d
  }

  function togglePersonalView() {
    personalViewActive.value = !personalViewActive.value
    try { localStorage.setItem('personalViewActive', String(personalViewActive.value)) } catch { /* storage unavailable */ }
  }

  return {
    defaultTagId,
    watchedTagIds,
    watchedArrayIds,
    watchedObservers,
    mutedObservers,
    alertSound,
    dashboardL1TagId,
    personalViewActive,
    hasPersonalView,
    load,
    update,
    togglePersonalView,
  }
})
