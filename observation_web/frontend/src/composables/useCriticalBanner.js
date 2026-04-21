/**
 * Critical alert banner composable.
 * Tracks unacknowledged critical events, suppression rules per observer,
 * desktop notification + sound triggers.
 */
import { ref, computed } from 'vue'
import { isCriticalAlert } from '../utils/alertTranslator'
import { sendDesktopNotification, playAlertSound } from '../utils/notification'
import { usePreferencesStore } from '../stores/preferences'
import { useArrayStore } from '../stores/arrays'

export function useCriticalBanner() {
  const criticalEvents = ref([])
  // observer_name → expiry timestamp (ms); active suppression = expiry > Date.now()
  const suppressedObservers = ref(new Map())

  const hasCriticalEvents = computed(() => criticalEvents.value.length > 0)

  const suppressedList = computed(() => {
    const now = Date.now()
    const list = []
    for (const [observer, expiresAt] of suppressedObservers.value.entries()) {
      if (expiresAt > now) list.push({ observer, expiresAt })
    }
    return list.sort((a, b) => a.expiresAt - b.expiresAt)
  })

  function _cleanupExpiredSuppressions() {
    const now = Date.now()
    const m = suppressedObservers.value
    let changed = false
    for (const [obs, expiry] of m.entries()) {
      if (expiry <= now) { m.delete(obs); changed = true }
    }
    if (changed) suppressedObservers.value = new Map(m)
  }

  function handleCriticalAlert(data) {
    if (!isCriticalAlert(data)) return

    // Personal view: skip alerts outside watched arrays/tags
    const prefs = usePreferencesStore()
    if (prefs.personalViewActive) {
      const watchedIds = prefs.watchedArrayIds || []
      const watchedTags = prefs.watchedTagIds || []
      const arrStore = useArrayStore()
      const allowedIds = new Set([
        ...watchedIds,
        ...arrStore.arrays
          .filter(a => a.tag_id != null && watchedTags.includes(a.tag_id))
          .map(a => a.array_id),
      ])
      if (!allowedIds.has(data.array_id)) return
    }

    _cleanupExpiredSuppressions()
    const obs = data.observer_name || 'unknown'
    const expiry = suppressedObservers.value.get(obs)
    if (expiry && Date.now() < expiry) return  // suppressed

    criticalEvents.value.unshift(data)
    if (criticalEvents.value.length > 50) {
      criticalEvents.value = criticalEvents.value.slice(0, 50)
    }

    sendDesktopNotification(
      `关键事件：${data.observer_name || '未知'}`,
      (data.message || '').substring(0, 120),
      { tag: `critical-${data.id || Date.now()}` }
    )
    playAlertSound()
  }

  function acknowledgeCritical(id) {
    criticalEvents.value = criticalEvents.value.filter(e => e.id !== id)
  }

  function acknowledgeAllCritical() {
    const expiryMs = 24 * 60 * 60 * 1000
    const now = Date.now()
    const newSuppressed = new Map(suppressedObservers.value)
    for (const e of criticalEvents.value) {
      newSuppressed.set(e.observer_name || 'unknown', now + expiryMs)
    }
    suppressedObservers.value = newSuppressed
    criticalEvents.value = []
  }

  function clearSuppression(observerName) {
    const m = new Map(suppressedObservers.value)
    m.delete(observerName)
    suppressedObservers.value = m
  }

  function clearAllSuppressions() {
    suppressedObservers.value = new Map()
  }

  return {
    criticalEvents,
    suppressedObservers,
    suppressedList,
    hasCriticalEvents,
    handleCriticalAlert,
    acknowledgeCritical,
    acknowledgeAllCritical,
    clearSuppression,
    clearAllSuppressions,
  }
}
