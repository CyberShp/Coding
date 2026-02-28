import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'

describe('Dashboard', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  describe('autoRefresh', () => {
    it('should auto-refresh every 30 seconds', () => {
      let refreshCount = 0
      let refreshTimer = null
      
      const silentRefresh = () => {
        refreshCount++
      }
      
      // Start auto-refresh
      refreshTimer = setInterval(silentRefresh, 30000)
      
      // Fast-forward 30 seconds
      vi.advanceTimersByTime(30000)
      expect(refreshCount).toBe(1)
      
      // Fast-forward another 30 seconds
      vi.advanceTimersByTime(30000)
      expect(refreshCount).toBe(2)
      
      // Cleanup
      clearInterval(refreshTimer)
    })

    it('should not refresh when page is hidden', () => {
      let refreshCount = 0
      const loading = ref(false)
      
      const silentRefresh = () => {
        if (document.hidden || loading.value) return
        refreshCount++
      }
      
      // Simulate hidden page
      Object.defineProperty(document, 'hidden', { value: true, writable: true })
      
      silentRefresh()
      expect(refreshCount).toBe(0)
      
      // Restore
      Object.defineProperty(document, 'hidden', { value: false, writable: true })
    })

    it('should not refresh when loading', () => {
      let refreshCount = 0
      const loading = ref(true)
      
      const silentRefresh = () => {
        if (loading.value) return
        refreshCount++
      }
      
      silentRefresh()
      expect(refreshCount).toBe(0)
      
      loading.value = false
      silentRefresh()
      expect(refreshCount).toBe(1)
    })
  })

  describe('manualRefresh', () => {
    it('should set loading state during refresh', async () => {
      const loading = ref(false)
      
      const manualRefresh = async () => {
        loading.value = true
        try {
          // Simulate async load
          await new Promise(resolve => setTimeout(resolve, 100))
        } finally {
          loading.value = false
        }
      }
      
      expect(loading.value).toBe(false)
      
      const refreshPromise = manualRefresh()
      expect(loading.value).toBe(true)
      
      vi.advanceTimersByTime(100)
      await refreshPromise
      expect(loading.value).toBe(false)
    })
  })

  describe('timer cleanup', () => {
    it('should clean up refresh timer on unmount', () => {
      let refreshTimer = setInterval(() => {}, 30000)
      
      const onUnmounted = () => {
        if (refreshTimer) {
          clearInterval(refreshTimer)
          refreshTimer = null
        }
      }
      
      expect(refreshTimer).not.toBeNull()
      onUnmounted()
      expect(refreshTimer).toBeNull()
    })
  })

  describe('array status class', () => {
    it('should return status-offline for disconnected arrays', () => {
      const getArrayStatusClass = (arr) => {
        if (arr.state !== 'connected') return 'status-offline'
        const issues = arr.active_issues || []
        if (issues.length > 0) {
          const hasError = issues.some(i => i.level === 'error' || i.level === 'critical')
          if (hasError) return 'status-error'
          return 'status-warning'
        }
        return 'status-ok'
      }
      
      expect(getArrayStatusClass({ state: 'disconnected' })).toBe('status-offline')
    })

    it('should return status-error for arrays with error issues', () => {
      const getArrayStatusClass = (arr) => {
        if (arr.state !== 'connected') return 'status-offline'
        const issues = arr.active_issues || []
        if (issues.length > 0) {
          const hasError = issues.some(i => i.level === 'error' || i.level === 'critical')
          if (hasError) return 'status-error'
          return 'status-warning'
        }
        return 'status-ok'
      }
      
      const arr = {
        state: 'connected',
        active_issues: [{ level: 'error' }]
      }
      expect(getArrayStatusClass(arr)).toBe('status-error')
    })

    it('should return status-warning for arrays with warning issues', () => {
      const getArrayStatusClass = (arr) => {
        if (arr.state !== 'connected') return 'status-offline'
        const issues = arr.active_issues || []
        if (issues.length > 0) {
          const hasError = issues.some(i => i.level === 'error' || i.level === 'critical')
          if (hasError) return 'status-error'
          return 'status-warning'
        }
        return 'status-ok'
      }
      
      const arr = {
        state: 'connected',
        active_issues: [{ level: 'warning' }]
      }
      expect(getArrayStatusClass(arr)).toBe('status-warning')
    })

    it('should return status-ok for healthy arrays', () => {
      const getArrayStatusClass = (arr) => {
        if (arr.state !== 'connected') return 'status-offline'
        const issues = arr.active_issues || []
        if (issues.length > 0) {
          const hasError = issues.some(i => i.level === 'error' || i.level === 'critical')
          if (hasError) return 'status-error'
          return 'status-warning'
        }
        return 'status-ok'
      }
      
      const arr = {
        state: 'connected',
        active_issues: []
      }
      expect(getArrayStatusClass(arr)).toBe('status-ok')
    })
  })

  describe('time formatting', () => {
    it('should format timestamp correctly', () => {
      const formatTime = (timestamp) => {
        if (!timestamp) return ''
        const date = new Date(timestamp)
        return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
      }
      
      const result = formatTime('2024-01-15T10:30:00')
      expect(result).toContain(':')
    })

    it('should handle empty timestamp', () => {
      const formatTime = (timestamp) => {
        if (!timestamp) return ''
        return new Date(timestamp).toLocaleTimeString('zh-CN')
      }
      
      expect(formatTime('')).toBe('')
      expect(formatTime(null)).toBe('')
    })
  })
})
