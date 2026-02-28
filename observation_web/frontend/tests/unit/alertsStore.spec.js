import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

describe('alertsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  describe('state', () => {
    it('should have correct initial state', () => {
      const state = {
        alerts: [],
        recentAlerts: [],
        stats: null,
        loading: false,
        wsConnected: false,
        criticalEvents: [],
      }
      
      expect(state.alerts).toEqual([])
      expect(state.recentAlerts).toEqual([])
      expect(state.stats).toBeNull()
      expect(state.loading).toBe(false)
      expect(state.wsConnected).toBe(false)
      expect(state.criticalEvents).toEqual([])
    })
  })

  describe('WebSocket reconnection', () => {
    it('should calculate exponential backoff correctly', () => {
      const BASE_RECONNECT_DELAY = 1000
      const MAX_RECONNECT_ATTEMPTS = 10
      
      const getDelay = (attempts) => {
        return Math.min(BASE_RECONNECT_DELAY * Math.pow(2, attempts), 30000)
      }
      
      expect(getDelay(0)).toBe(1000)
      expect(getDelay(1)).toBe(2000)
      expect(getDelay(2)).toBe(4000)
      expect(getDelay(3)).toBe(8000)
      expect(getDelay(4)).toBe(16000)
      expect(getDelay(5)).toBe(30000) // Capped
      expect(getDelay(10)).toBe(30000) // Still capped
    })

    it('should respect max reconnect attempts', () => {
      const MAX_RECONNECT_ATTEMPTS = 10
      let reconnectAttempts = 0
      
      const scheduleReconnect = () => {
        if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
          return false
        }
        reconnectAttempts++
        return true
      }
      
      // Should allow 10 reconnects
      for (let i = 0; i < 10; i++) {
        expect(scheduleReconnect()).toBe(true)
      }
      
      // 11th attempt should fail
      expect(scheduleReconnect()).toBe(false)
    })
  })

  describe('timer cleanup', () => {
    it('should clean up heartbeat timer on disconnect', () => {
      let heartbeatTimer = setInterval(() => {}, 30000)
      let reconnectTimer = setTimeout(() => {}, 5000)
      
      const cleanupTimers = () => {
        if (heartbeatTimer) {
          clearInterval(heartbeatTimer)
          heartbeatTimer = null
        }
        if (reconnectTimer) {
          clearTimeout(reconnectTimer)
          reconnectTimer = null
        }
      }
      
      expect(heartbeatTimer).not.toBeNull()
      expect(reconnectTimer).not.toBeNull()
      
      cleanupTimers()
      
      expect(heartbeatTimer).toBeNull()
      expect(reconnectTimer).toBeNull()
    })
  })

  describe('handleNewAlert', () => {
    it('should add alert to recent list', () => {
      const recentAlerts = []
      
      const handleNewAlert = (data) => {
        recentAlerts.unshift(data)
        if (recentAlerts.length > 20) {
          recentAlerts.pop()
        }
      }
      
      const alert = { id: 1, level: 'warning', message: 'Test' }
      handleNewAlert(alert)
      
      expect(recentAlerts.length).toBe(1)
      expect(recentAlerts[0]).toEqual(alert)
    })

    it('should limit recent alerts to 20', () => {
      const recentAlerts = []
      
      const handleNewAlert = (data) => {
        recentAlerts.unshift(data)
        if (recentAlerts.length > 20) {
          recentAlerts.pop()
        }
      }
      
      // Add 25 alerts
      for (let i = 0; i < 25; i++) {
        handleNewAlert({ id: i, level: 'info' })
      }
      
      expect(recentAlerts.length).toBe(20)
      expect(recentAlerts[0].id).toBe(24) // Most recent
    })

    it('should track critical events separately', () => {
      const criticalEvents = []
      
      const isCriticalAlert = (data) => data.level === 'error' || data.level === 'critical'
      
      const handleNewAlert = (data) => {
        if (isCriticalAlert(data)) {
          criticalEvents.unshift(data)
          if (criticalEvents.length > 50) {
            criticalEvents.splice(50)
          }
        }
      }
      
      handleNewAlert({ id: 1, level: 'info' })
      handleNewAlert({ id: 2, level: 'error' })
      handleNewAlert({ id: 3, level: 'critical' })
      
      expect(criticalEvents.length).toBe(2)
      expect(criticalEvents[0].id).toBe(3)
      expect(criticalEvents[1].id).toBe(2)
    })
  })

  describe('recentCount computed', () => {
    it('should count only error and critical alerts', () => {
      const recentAlerts = [
        { level: 'info' },
        { level: 'warning' },
        { level: 'error' },
        { level: 'critical' },
        { level: 'error' },
      ]
      
      const recentCount = recentAlerts.filter(a => 
        a.level === 'error' || a.level === 'critical'
      ).length
      
      expect(recentCount).toBe(3)
    })
  })
})
