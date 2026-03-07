import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'

export const usePreferencesStore = defineStore('preferences', () => {
  const defaultTagId = ref(null)

  async function load() {
    try {
      const res = await api.getPreferences()
      defaultTagId.value = res.data?.default_tag_id ?? null
      return res.data
    } catch {
      defaultTagId.value = null
      return { default_tag_id: null }
    }
  }

  async function update(data) {
    const res = await api.updatePreferences(data)
    defaultTagId.value = res.data?.default_tag_id ?? null
    return res.data
  }

  return {
    defaultTagId,
    load,
    update,
  }
})
