import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const AUTO_SYNC_SECONDS = 300

export const useCardStore = defineStore('cards', () => {
  // Timestamp and tick survive navigation — component mounts/unmounts don't reset them
  const nextAutoSyncAt = ref(Date.now() + AUTO_SYNC_SECONDS * 1000)
  const nowTs = ref(Date.now())
  let _autoSyncTimer = null
  let _secondTicker = null

  const nextAutoSyncText = computed(() => {
    const diff = Math.max(0, Math.floor((nextAutoSyncAt.value - nowTs.value) / 1000))
    const mm = String(Math.floor(diff / 60)).padStart(2, '0')
    const ss = String(diff % 60).padStart(2, '0')
    return `${mm}:${ss}`
  })

  function startTimers(syncFn) {
    if (_autoSyncTimer) return // already running, deadline is preserved
    _autoSyncTimer = setInterval(() => {
      syncFn()
      nextAutoSyncAt.value = Date.now() + AUTO_SYNC_SECONDS * 1000
    }, AUTO_SYNC_SECONDS * 1000)
    _secondTicker = setInterval(() => {
      nowTs.value = Date.now()
    }, 1000)
  }

  function stopTimers() {
    if (_autoSyncTimer) { clearInterval(_autoSyncTimer); _autoSyncTimer = null }
    if (_secondTicker) { clearInterval(_secondTicker); _secondTicker = null }
  }

  function resetTimer() {
    nextAutoSyncAt.value = Date.now() + AUTO_SYNC_SECONDS * 1000
  }

  return { nextAutoSyncAt, nowTs, nextAutoSyncText, startTimers, stopTimers, resetTimer }
})
