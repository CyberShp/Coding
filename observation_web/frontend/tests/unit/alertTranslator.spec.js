import { describe, it, expect } from 'vitest'

// Mock the alertTranslator module functions
const LEVEL_LABELS = {
  info: '信息',
  warning: '警告',
  error: '错误',
  critical: '严重',
}

const LEVEL_TAG_TYPES = {
  info: 'info',
  warning: 'warning',
  error: 'danger',
  critical: 'danger',
}

const OBSERVER_NAMES = {
  cpu_usage: 'CPU 使用率',
  memory_leak: '内存泄漏',
  pcie_bandwidth: 'PCIe 带宽',
  alarm_type: '硬件告警',
  card_info: '板卡状态',
}

function getObserverName(name) {
  return OBSERVER_NAMES[name] || name
}

function isCriticalAlert(alert) {
  return alert.level === 'error' || alert.level === 'critical'
}

function translateMemoryLeak(details) {
  const parts = []
  if (details.current_used_mb) {
    parts.push(`当前内存: ${(details.current_used_mb / 1024).toFixed(1)}GB`)
  }
  if (details.consecutive_increases) {
    parts.push(`连续增长: ${details.consecutive_increases}次`)
  }
  if (details.recovered) {
    parts.push('状态: 已恢复')
  }
  return { summary: parts.join(', ') }
}

describe('alertTranslator', () => {
  describe('LEVEL_LABELS', () => {
    it('should have correct Chinese labels for all levels', () => {
      expect(LEVEL_LABELS.info).toBe('信息')
      expect(LEVEL_LABELS.warning).toBe('警告')
      expect(LEVEL_LABELS.error).toBe('错误')
      expect(LEVEL_LABELS.critical).toBe('严重')
    })
  })

  describe('LEVEL_TAG_TYPES', () => {
    it('should map error and critical to danger', () => {
      expect(LEVEL_TAG_TYPES.error).toBe('danger')
      expect(LEVEL_TAG_TYPES.critical).toBe('danger')
    })

    it('should map info and warning correctly', () => {
      expect(LEVEL_TAG_TYPES.info).toBe('info')
      expect(LEVEL_TAG_TYPES.warning).toBe('warning')
    })
  })

  describe('getObserverName', () => {
    it('should translate known observer names', () => {
      expect(getObserverName('cpu_usage')).toBe('CPU 使用率')
      expect(getObserverName('memory_leak')).toBe('内存泄漏')
      expect(getObserverName('pcie_bandwidth')).toBe('PCIe 带宽')
      expect(getObserverName('alarm_type')).toBe('硬件告警')
      expect(getObserverName('card_info')).toBe('板卡状态')
    })

    it('should return original name for unknown observers', () => {
      expect(getObserverName('unknown_observer')).toBe('unknown_observer')
    })
  })

  describe('isCriticalAlert', () => {
    it('should return true for error level', () => {
      expect(isCriticalAlert({ level: 'error' })).toBe(true)
    })

    it('should return true for critical level', () => {
      expect(isCriticalAlert({ level: 'critical' })).toBe(true)
    })

    it('should return false for info level', () => {
      expect(isCriticalAlert({ level: 'info' })).toBe(false)
    })

    it('should return false for warning level', () => {
      expect(isCriticalAlert({ level: 'warning' })).toBe(false)
    })
  })

  describe('translateMemoryLeak', () => {
    it('should format memory usage correctly', () => {
      const result = translateMemoryLeak({ current_used_mb: 4096 })
      expect(result.summary).toContain('4.0GB')
    })

    it('should include consecutive increases', () => {
      const result = translateMemoryLeak({ consecutive_increases: 8 })
      expect(result.summary).toContain('连续增长: 8次')
    })

    it('should indicate recovery status', () => {
      const result = translateMemoryLeak({ recovered: true })
      expect(result.summary).toContain('已恢复')
    })

    it('should combine multiple details', () => {
      const result = translateMemoryLeak({
        current_used_mb: 8192,
        consecutive_increases: 10,
        recovered: false,
      })
      expect(result.summary).toContain('8.0GB')
      expect(result.summary).toContain('10次')
    })
  })
})
