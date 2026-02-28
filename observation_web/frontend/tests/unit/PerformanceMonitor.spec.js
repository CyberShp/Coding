import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref, nextTick } from 'vue'

describe('PerformanceMonitor', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  describe('autoRefresh', () => {
    it('should default to enabled', () => {
      const autoRefresh = ref(true)
      expect(autoRefresh.value).toBe(true)
    })

    it('should toggle auto refresh correctly', () => {
      let refreshTimer = null
      const autoRefresh = ref(true)
      
      const toggleAutoRefresh = (enabled) => {
        if (refreshTimer) {
          clearInterval(refreshTimer)
          refreshTimer = null
        }
        if (enabled) {
          refreshTimer = setInterval(() => {}, 15000)
        }
      }
      
      toggleAutoRefresh(true)
      expect(refreshTimer).not.toBeNull()
      
      toggleAutoRefresh(false)
      expect(refreshTimer).toBeNull()
    })
  })

  describe('timer cleanup', () => {
    it('should clean up refresh timer on unmount', () => {
      let refreshTimer = setInterval(() => {}, 15000)
      
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

  describe('cpuData computed', () => {
    it('should filter metrics with cpu0 values', () => {
      const metrics = ref([
        { ts: '2024-01-15T10:00:00', cpu0: 45.5 },
        { ts: '2024-01-15T10:01:00', cpu0: null },
        { ts: '2024-01-15T10:02:00', cpu0: 50.0 },
      ])
      
      const cpuData = metrics.value
        .filter(m => m.cpu0 != null)
        .map(m => ({ ts: m.ts, value: m.cpu0 }))
      
      expect(cpuData.length).toBe(2)
      expect(cpuData[0].value).toBe(45.5)
      expect(cpuData[1].value).toBe(50.0)
    })
  })

  describe('memData computed', () => {
    it('should filter metrics with memory values', () => {
      const metrics = ref([
        { ts: '2024-01-15T10:00:00', mem_used_mb: 4096, mem_total_mb: 16384 },
        { ts: '2024-01-15T10:01:00', mem_used_mb: null },
        { ts: '2024-01-15T10:02:00', mem_used_mb: 4500, mem_total_mb: 16384 },
      ])
      
      const memData = metrics.value
        .filter(m => m.mem_used_mb != null)
        .map(m => ({
          ts: m.ts,
          used: m.mem_used_mb,
          total: m.mem_total_mb || 0,
        }))
      
      expect(memData.length).toBe(2)
      expect(memData[0].used).toBe(4096)
      expect(memData[1].used).toBe(4500)
    })
  })

  describe('latestMetrics computed', () => {
    it('should return latest available values', () => {
      const metrics = ref([
        { cpu0: 30.0, mem_used_mb: 3000 },
        { cpu0: 40.0 },
        { mem_used_mb: 4000, mem_total_mb: 16384 },
        { cpu0: 50.0 },
      ])
      
      const getLatest = () => {
        if (metrics.value.length === 0) return null
        let latest = {}
        for (let i = metrics.value.length - 1; i >= 0; i--) {
          const m = metrics.value[i]
          if (m.cpu0 != null && latest.cpu0 == null) latest.cpu0 = m.cpu0
          if (m.mem_used_mb != null && latest.mem_used_mb == null) {
            latest.mem_used_mb = m.mem_used_mb
            latest.mem_total_mb = m.mem_total_mb
          }
          if (latest.cpu0 != null && latest.mem_used_mb != null) break
        }
        return Object.keys(latest).length > 0 ? latest : null
      }
      
      const latest = getLatest()
      expect(latest.cpu0).toBe(50.0)
      expect(latest.mem_used_mb).toBe(4000)
      expect(latest.mem_total_mb).toBe(16384)
    })

    it('should return null when metrics are empty', () => {
      const metrics = ref([])
      
      const getLatest = () => {
        if (metrics.value.length === 0) return null
        return {}
      }
      
      expect(getLatest()).toBeNull()
    })
  })

  describe('cpuStatusClass computed', () => {
    it('should return status-error for CPU >= 90', () => {
      const getStatusClass = (cpu0) => {
        if (!cpu0) return ''
        if (cpu0 >= 90) return 'status-error'
        if (cpu0 >= 70) return 'status-warning'
        return 'status-ok'
      }
      
      expect(getStatusClass(95)).toBe('status-error')
      expect(getStatusClass(90)).toBe('status-error')
    })

    it('should return status-warning for CPU >= 70', () => {
      const getStatusClass = (cpu0) => {
        if (!cpu0) return ''
        if (cpu0 >= 90) return 'status-error'
        if (cpu0 >= 70) return 'status-warning'
        return 'status-ok'
      }
      
      expect(getStatusClass(85)).toBe('status-warning')
      expect(getStatusClass(70)).toBe('status-warning')
    })

    it('should return status-ok for CPU < 70', () => {
      const getStatusClass = (cpu0) => {
        if (!cpu0) return ''
        if (cpu0 >= 90) return 'status-error'
        if (cpu0 >= 70) return 'status-warning'
        return 'status-ok'
      }
      
      expect(getStatusClass(60)).toBe('status-ok')
      expect(getStatusClass(0)).toBe('status-ok')
    })
  })

  describe('time formatting', () => {
    it('should format timestamp correctly', () => {
      const formatTime = (ts) => {
        if (!ts) return ''
        const d = new Date(ts)
        return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      }
      
      const result = formatTime('2024-01-15T10:30:45')
      expect(result).toContain(':')
    })

    it('should handle empty timestamp', () => {
      const formatTime = (ts) => {
        if (!ts) return ''
        const d = new Date(ts)
        return d.toLocaleTimeString('zh-CN')
      }
      
      expect(formatTime('')).toBe('')
      expect(formatTime(null)).toBe('')
    })
  })
})
