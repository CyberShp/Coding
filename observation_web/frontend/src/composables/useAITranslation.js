/**
 * AI alert translation composable.
 * Maintains an LRU-capped Map of alert_id → interpretation string.
 * Only translates alarm_type observer alerts. Batches requests to avoid flooding.
 */
import { ref } from 'vue'
import api from '../api'

export function useAITranslation() {
  const aiAvailable = ref(false)
  const aiTranslations = ref(new Map())

  let aiStatusChecked = false
  let aiFetchQueue = []
  let aiFetching = false

  const AI_BATCH_SIZE = 5
  const AI_TRANSLATIONS_MAX = 500  // LRU cap

  async function checkAIAvailability() {
    if (aiStatusChecked) return
    aiStatusChecked = true
    try {
      const { data } = await api.checkAIStatus()
      aiAvailable.value = !!data?.available
    } catch {
      aiAvailable.value = false
    }
  }

  async function _drainQueue() {
    if (aiFetching || aiFetchQueue.length === 0) return
    aiFetching = true
    while (aiFetchQueue.length > 0) {
      const batch = []
      while (batch.length < AI_BATCH_SIZE && aiFetchQueue.length > 0) {
        const id = aiFetchQueue.shift()
        if (!aiTranslations.value.has(id)) batch.push(id)
      }
      if (batch.length === 0) continue
      const results = await Promise.allSettled(
        batch.map(id => api.getAIInterpretation(id).then(r => ({ id, text: r.data?.interpretation })))
      )
      const m = new Map(aiTranslations.value)
      for (const r of results) {
        if (r.status === 'fulfilled' && r.value.text) m.set(r.value.id, r.value.text)
      }
      // LRU eviction: oldest keys are at the front of Map iteration order
      if (m.size > AI_TRANSLATIONS_MAX) {
        const excess = m.size - AI_TRANSLATIONS_MAX
        const iter = m.keys()
        for (let i = 0; i < excess; i++) m.delete(iter.next().value)
      }
      aiTranslations.value = m
    }
    aiFetching = false
  }

  function autoTranslateAlert(alert) {
    if (!aiAvailable.value || !alert?.id) return
    if (aiTranslations.value.has(alert.id)) return
    if (alert.observer_name !== 'alarm_type') return
    aiFetchQueue.push(alert.id)
    _drainQueue()
  }

  function getAITranslation(alertId) {
    const val = aiTranslations.value.get(alertId)
    if (val === undefined) return null
    // LRU touch: delete + re-insert moves key to end of Map iteration order
    const m = aiTranslations.value
    m.delete(alertId)
    m.set(alertId, val)
    return val
  }

  return { aiAvailable, aiTranslations, checkAIAvailability, autoTranslateAlert, getAITranslation }
}
