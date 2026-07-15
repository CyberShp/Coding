import { onMounted, onBeforeUnmount } from 'vue'

export function useVisibleRefresh(callback, interval = 30000) {
  let timer = null
  let running = false
  let lastRunAt = Date.now()

  const run = async () => {
    if (document.hidden || running) return
    running = true
    try {
      await callback()
      lastRunAt = Date.now()
    } finally {
      running = false
    }
  }

  const handleVisibilityChange = () => {
    if (!document.hidden && Date.now() - lastRunAt >= interval) run()
  }

  onMounted(() => {
    timer = window.setInterval(run, interval)
    document.addEventListener('visibilitychange', handleVisibilityChange)
  })

  onBeforeUnmount(() => {
    if (timer) window.clearInterval(timer)
    document.removeEventListener('visibilitychange', handleVisibilityChange)
  })

  return { refreshWhenVisible: run }
}
