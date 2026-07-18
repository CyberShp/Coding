import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'

// Mock the api module the component depends on so mounting never hits the network.
vi.mock('@/api', () => ({
  default: {
    getArrayMetrics: vi.fn().mockResolvedValue({ data: { metrics: [] } }),
  },
}))

// Import the REAL component and its REAL exported helpers — the tests below
// exercise the component's own logic, not a re-implemented copy.
import PerformanceMonitor, {
  getStatusClass,
  formatTime,
  buildCpuData,
  buildMemData,
  computeLatestMetrics,
} from '@/components/PerformanceMonitor.vue'

describe('PerformanceMonitor', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('getStatusClass (real component logic)', () => {
    it('returns status-error for CPU >= 90', () => {
      expect(getStatusClass(95)).toBe('status-error')
      expect(getStatusClass(90)).toBe('status-error')
    })

    it('returns status-warning for 70 <= CPU < 90', () => {
      expect(getStatusClass(85)).toBe('status-warning')
      expect(getStatusClass(70)).toBe('status-warning')
    })

    it('returns status-ok for CPU < 70', () => {
      expect(getStatusClass(60)).toBe('status-ok')
    })

    it('treats 0% CPU as a valid value (status-ok), not empty', () => {
      // Regression: `!cpu0` incorrectly returned '' for 0. 0% is a real reading.
      expect(getStatusClass(0)).toBe('status-ok')
    })

    it('returns empty string only when value is null/undefined', () => {
      expect(getStatusClass(null)).toBe('')
      expect(getStatusClass(undefined)).toBe('')
    })
  })

  describe('buildCpuData (real component logic)', () => {
    it('filters out entries without a cpu0 value and keeps 0', () => {
      const cpuData = buildCpuData([
        { ts: '2024-01-15T10:00:00', cpu0: 45.5 },
        { ts: '2024-01-15T10:01:00', cpu0: null },
        { ts: '2024-01-15T10:02:00', cpu0: 0 },
      ])

      expect(cpuData.length).toBe(2)
      expect(cpuData[0].value).toBe(45.5)
      expect(cpuData[1].value).toBe(0)
    })

    it('handles empty / missing input', () => {
      expect(buildCpuData([])).toEqual([])
      expect(buildCpuData(undefined)).toEqual([])
    })
  })

  describe('buildMemData (real component logic)', () => {
    it('filters entries with memory values and defaults total to 0', () => {
      const memData = buildMemData([
        { ts: '2024-01-15T10:00:00', mem_used_mb: 4096, mem_total_mb: 16384 },
        { ts: '2024-01-15T10:01:00', mem_used_mb: null },
        { ts: '2024-01-15T10:02:00', mem_used_mb: 4500 },
      ])

      expect(memData.length).toBe(2)
      expect(memData[0].used).toBe(4096)
      expect(memData[0].total).toBe(16384)
      expect(memData[1].used).toBe(4500)
      expect(memData[1].total).toBe(0)
    })
  })

  describe('computeLatestMetrics (real component logic)', () => {
    it('returns the latest available cpu and memory values', () => {
      const latest = computeLatestMetrics([
        { cpu0: 30.0, mem_used_mb: 3000 },
        { cpu0: 40.0 },
        { mem_used_mb: 4000, mem_total_mb: 16384 },
        { cpu0: 50.0 },
      ])

      expect(latest.cpu0).toBe(50.0)
      expect(latest.mem_used_mb).toBe(4000)
      expect(latest.mem_total_mb).toBe(16384)
    })

    it('returns null when metrics are empty', () => {
      expect(computeLatestMetrics([])).toBeNull()
      expect(computeLatestMetrics(undefined)).toBeNull()
    })
  })

  describe('formatTime (real component logic)', () => {
    it('formats a timestamp into a time string', () => {
      expect(formatTime('2024-01-15T10:30:45')).toContain(':')
    })

    it('returns empty string for empty/null timestamp', () => {
      expect(formatTime('')).toBe('')
      expect(formatTime(null)).toBe('')
    })
  })

  describe('auto-refresh timer lifecycle (mounted component)', () => {
    let setIntervalSpy
    let clearIntervalSpy

    beforeEach(() => {
      setIntervalSpy = vi.spyOn(globalThis, 'setInterval')
      clearIntervalSpy = vi.spyOn(globalThis, 'clearInterval')
    })

    afterEach(() => {
      setIntervalSpy.mockRestore()
      clearIntervalSpy.mockRestore()
    })

    it('starts a 15s refresh interval on mount (autoRefresh defaults to on)', () => {
      const wrapper = mount(PerformanceMonitor, { props: { arrayId: 'arr-001' } })

      expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 15000)

      wrapper.unmount()
    })

    it('clears the refresh interval on unmount', () => {
      const wrapper = mount(PerformanceMonitor, { props: { arrayId: 'arr-001' } })
      clearIntervalSpy.mockClear()

      wrapper.unmount()

      expect(clearIntervalSpy).toHaveBeenCalled()
    })
  })
})
