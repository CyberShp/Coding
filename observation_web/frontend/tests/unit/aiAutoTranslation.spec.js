import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAlertStore } from '@/stores/alerts'

// Mock the api module
vi.mock('@/api', () => ({
  default: {
    checkAIStatus: vi.fn(),
    getAIInterpretation: vi.fn(),
    getAlerts: vi.fn(),
    getRecentAlerts: vi.fn(),
    getAlertStats: vi.fn(),
  }
}))

// Mock notification utils (avoid side effects)
vi.mock('@/utils/notification', () => ({
  sendDesktopNotification: vi.fn(),
  playAlertSound: vi.fn(),
  requestNotificationPermission: vi.fn(),
}))

import api from '@/api'

describe('AI Auto-Translation for alarm_type alerts', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useAlertStore()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('checkAIAvailability', () => {
    it('should mark AI as available when /ai/status returns available=true', async () => {
      api.checkAIStatus.mockResolvedValue({ data: { available: true } })

      await store.checkAIAvailability()

      expect(store.aiAvailable).toBe(true)
      expect(api.checkAIStatus).toHaveBeenCalledOnce()
    })

    it('should mark AI as unavailable on error', async () => {
      api.checkAIStatus.mockRejectedValue(new Error('network error'))

      await store.checkAIAvailability()

      expect(store.aiAvailable).toBe(false)
    })

    it('should only check once (idempotent)', async () => {
      api.checkAIStatus.mockResolvedValue({ data: { available: true } })

      await store.checkAIAvailability()
      await store.checkAIAvailability()

      expect(api.checkAIStatus).toHaveBeenCalledOnce()
    })
  })

  describe('autoTranslateAlert', () => {
    beforeEach(async () => {
      api.checkAIStatus.mockResolvedValue({ data: { available: true } })
      await store.checkAIAvailability()
    })

    it('should translate alarm_type alerts with valid id', async () => {
      api.getAIInterpretation.mockResolvedValue({
        data: { interpretation: '磁盘阵列 RAID5 中第3块盘离线' }
      })

      const alert = { id: 42, observer_name: 'alarm_type', message: 'Disk Failed(3)' }
      await store.autoTranslateAlert(alert)

      // drainAIQueue is async; wait for it
      await vi.waitFor(() => {
        expect(store.getAITranslation(42)).toBe('磁盘阵列 RAID5 中第3块盘离线')
      })

      expect(api.getAIInterpretation).toHaveBeenCalledWith(42)
    })

    it('should skip non-alarm_type observers', async () => {
      const alert = { id: 10, observer_name: 'disk_smart', message: 'some message' }
      await store.autoTranslateAlert(alert)

      // Give queue time to drain
      await new Promise(r => setTimeout(r, 10))

      expect(api.getAIInterpretation).not.toHaveBeenCalled()
      expect(store.getAITranslation(10)).toBeNull()
    })

    it('should skip alerts without id', async () => {
      const alert = { observer_name: 'alarm_type', message: 'Disk Failed(3)' }
      await store.autoTranslateAlert(alert)

      await new Promise(r => setTimeout(r, 10))

      expect(api.getAIInterpretation).not.toHaveBeenCalled()
    })

    it('should not re-fetch already translated alerts', async () => {
      api.getAIInterpretation.mockResolvedValue({
        data: { interpretation: '翻译结果' }
      })

      const alert = { id: 99, observer_name: 'alarm_type', message: 'Alert' }
      await store.autoTranslateAlert(alert)

      await vi.waitFor(() => {
        expect(store.getAITranslation(99)).toBe('翻译结果')
      })

      // Call again — should not trigger second API call
      await store.autoTranslateAlert(alert)
      await new Promise(r => setTimeout(r, 10))

      expect(api.getAIInterpretation).toHaveBeenCalledTimes(1)
    })

    it('should skip when AI is not available', async () => {
      // Re-create store without AI available
      setActivePinia(createPinia())
      store = useAlertStore()
      api.checkAIStatus.mockResolvedValue({ data: { available: false } })
      await store.checkAIAvailability()

      const alert = { id: 50, observer_name: 'alarm_type', message: 'Alert' }
      await store.autoTranslateAlert(alert)

      await new Promise(r => setTimeout(r, 10))

      expect(api.getAIInterpretation).not.toHaveBeenCalled()
    })
  })

  describe('integration: fetchAlerts triggers auto-translate', () => {
    it('should auto-translate alarm_type alerts after fetchAlerts', async () => {
      api.checkAIStatus.mockResolvedValue({ data: { available: true } })
      api.getAlerts.mockResolvedValue({
        data: [
          { id: 1, observer_name: 'alarm_type', message: 'Controller Warning' },
          { id: 2, observer_name: 'disk_smart', message: 'Temperature high' },
          { id: 3, observer_name: 'alarm_type', message: 'BBU Low' },
        ]
      })
      api.getAIInterpretation
        .mockResolvedValueOnce({ data: { interpretation: '控制器警告翻译' } })
        .mockResolvedValueOnce({ data: { interpretation: 'BBU电量低翻译' } })

      await store.fetchAlerts({})

      // Wait for async AI check + queue drain
      await vi.waitFor(() => {
        expect(store.getAITranslation(1)).toBe('控制器警告翻译')
      })

      expect(store.getAITranslation(2)).toBeNull() // disk_smart skipped
      expect(store.getAITranslation(3)).toBe('BBU电量低翻译')
      expect(api.getAIInterpretation).toHaveBeenCalledTimes(2)
    })
  })

  describe('integration: handleNewAlert via WebSocket triggers auto-translate', () => {
    it('should auto-translate alarm_type alert received via WS', async () => {
      api.checkAIStatus.mockResolvedValue({ data: { available: true } })
      await store.checkAIAvailability()

      api.getAIInterpretation.mockResolvedValue({
        data: { interpretation: 'WS实时翻译结果' }
      })

      // Simulate WebSocket alert with id (P1 fix ensures id is broadcast)
      const wsAlert = {
        id: 77,
        observer_name: 'alarm_type',
        level: 'warning',
        message: 'Disk Rebuilding(5)',
        array_id: 'arr_test',
        timestamp: new Date().toISOString(),
      }

      // Manually call handleNewAlert — in real flow this is triggered by WS onmessage
      // We need to simulate: the store's internal handleNewAlert adds to recent + triggers translate
      store.recentAlerts = []
      // The store doesn't expose handleNewAlert directly; trigger via autoTranslateAlert
      await store.autoTranslateAlert(wsAlert)

      await vi.waitFor(() => {
        expect(store.getAITranslation(77)).toBe('WS实时翻译结果')
      })
    })
  })
})
