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
  const personalViewActive = ref(false)

  const hasPersonalView = computed(() => {
    return watchedTagIds.value.length > 0 ||
      watchedArrayIds.value.length > 0 ||
      watchedObservers.value.length > 0
  })

  async function load() {
    try {
      const res = await api.getPreferences()
      const d = res.data || {}
      defaultTagId.value = d.default_tag_id ?? null
      watchedTagIds.value = d.watched_tag_ids || []
      watchedArrayIds.value = d.watched_array_ids || []
      watchedObservers.value = d.watched_observers || []
      mutedObservers.value = d.muted_observers || []
      alertSound.value = d.alert_sound !== false
      return d
    } catch {
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
    return d
  }

  function togglePersonalView() {
    personalViewActive.value = !personalViewActive.value
  }

  return {
    defaultTagId,
    watchedTagIds,
    watchedArrayIds,
    watchedObservers,
    mutedObservers,
    alertSound,
    personalViewActive,
    hasPersonalView,
    load,
    update,
    togglePersonalView,
  }
})
