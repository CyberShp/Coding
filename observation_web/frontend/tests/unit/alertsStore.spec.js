import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAlertStore } from '@/stores/alerts'

// Mock api module
vi.mock('@/api', () => ({
  default: {
    checkAIStatus: vi.fn().mockResolvedValue({ data: { available: false } }),
    getAIInterpretation: vi.fn(),
    getAlerts: vi.fn(),
    getRecentAlerts: vi.fn().mockResolvedValue({ data: [] }),
    getAlertStats: vi.fn(),
  }
}))

// Mock notification utils
vi.mock('@/utils/notification', () => ({
  sendDesktopNotification: vi.fn(),
  playAlertSound: vi.fn(),
  requestNotificationPermission: vi.fn(),
}))

// Mock isCriticalAlert
vi.mock('@/utils/alertTranslator', () => ({
  isCriticalAlert: vi.fn(() => false),
}))

// ── WebSocket mock infrastructure ────────────────────────────
class MockWebSocket {
  static OPEN = 1
  static CLOSED = 3
  static instances = []

  constructor(url) {
    this.url = url
    this.readyState = MockWebSocket.OPEN
    this.onopen = null
    this.onclose = null
    this.onmessage = null
    this.onerror = null
    this._closed = false
    MockWebSocket.instances.push(this)
  }

  send(data) {}

  close() {
    if (this._closed) return
    this._closed = true
    this.readyState = MockWebSocket.CLOSED
    // Simulate async onclose (browser behavior)
    if (this.onclose) {
      setTimeout(() => this.onclose(), 0)
    }
  }

  // Test helpers
  simulateOpen() {
    this.readyState = MockWebSocket.OPEN
    if (this.onopen) this.onopen()
  }

  simulateClose() {
    this.readyState = MockWebSocket.CLOSED
    if (this.onclose) this.onclose()
  }

  simulateMessage(data) {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(data) })
  }
}

describe('alertsStore (real store)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    MockWebSocket.instances = []
    globalThis.WebSocket = MockWebSocket
    store = useAlertStore()
  })

  afterEach(() => {
    store.disconnectWebSocket()
    vi.useRealTimers()
    vi.clearAllMocks()
    delete globalThis.WebSocket
  })

  describe('initial state', () => {
    it('should have correct initial state', () => {
      expect(store.alerts).toEqual([])
      expect(store.recentAlerts).toEqual([])
      expect(store.stats).toBeNull()
      expect(store.loading).toBe(false)
      expect(store.wsConnected).toBe(false)
      expect(store.criticalEvents).toEqual([])
    })
  })

  describe('WebSocket lifecycle (real store)', () => {
    it('connectWebSocket creates a WebSocket and sets wsConnected on open', () => {
      store.connectWebSocket()

      expect(MockWebSocket.instances.length).toBe(1)
      const socket = MockWebSocket.instances[0]
      expect(socket.url).toContain('/ws/alerts')

      // Not connected yet until onopen
      expect(store.wsConnected).toBe(false)

      // Simulate server accepting connection
      socket.simulateOpen()
      expect(store.wsConnected).toBe(true)
    })

    it('disconnectWebSocket stops reconnection', () => {
      store.connectWebSocket()
      const socket = MockWebSocket.instances[0]
      socket.simulateOpen()
      expect(store.wsConnected).toBe(true)

      store.disconnectWebSocket()
      // wsConnected must be false immediately after disconnect (sync, not waiting for onclose)
      expect(store.wsConnected).toBe(false)
      // Advance timers — no new WebSocket should be created
      vi.advanceTimersByTime(120000)
      // Only the original socket was created, no reconnect
      expect(MockWebSocket.instances.length).toBe(1)
    })

    it('reconnects with exponential backoff on close (infinite, capped at 60s)', () => {
      store.connectWebSocket()
      const socket1 = MockWebSocket.instances[0]
      socket1.simulateOpen()
      expect(store.wsConnected).toBe(true)

      // Simulate unexpected close
      socket1.simulateClose()
      expect(store.wsConnected).toBe(false)

      // First reconnect at 1s
      vi.advanceTimersByTime(1000)
      expect(MockWebSocket.instances.length).toBe(2)

      // Simulate that one also closes
      MockWebSocket.instances[1].simulateClose()

      // Second reconnect at 2s
      vi.advanceTimersByTime(2000)
      expect(MockWebSocket.instances.length).toBe(3)

      // Third closes
      MockWebSocket.instances[2].simulateClose()

      // Third reconnect at 4s
      vi.advanceTimersByTime(4000)
      expect(MockWebSocket.instances.length).toBe(4)
    })

    it('keeps reconnecting beyond 10 attempts (infinite reconnect)', () => {
      store.connectWebSocket()
      MockWebSocket.instances[0].simulateOpen()
      MockWebSocket.instances[0].simulateClose()

      // Simulate 15 failed reconnections
      for (let i = 0; i < 15; i++) {
        vi.advanceTimersByTime(60000) // max delay
        const latest = MockWebSocket.instances[MockWebSocket.instances.length - 1]
        latest.simulateClose()
      }

      // Should have 1 (original) + 15 (reconnects) = 16 instances
      expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(16)
    })

    it('stale socket onclose does NOT clobber new socket', () => {
      store.connectWebSocket()
      const socket1 = MockWebSocket.instances[0]
      socket1.simulateOpen()

      // Simulate close — triggers reconnect timer
      socket1.simulateClose()
      expect(store.wsConnected).toBe(false)

      // Reconnect timer fires — creates socket2
      vi.advanceTimersByTime(1000)
      expect(MockWebSocket.instances.length).toBe(2)
      const socket2 = MockWebSocket.instances[1]
      socket2.simulateOpen()
      expect(store.wsConnected).toBe(true)

      // Now socket1's onclose fires AGAIN (delayed, stale)
      // This should be a no-op due to the closure guard
      socket1.simulateClose()

      // socket2 should still be the active connection
      expect(store.wsConnected).toBe(true)
      // No additional reconnect triggered
      vi.advanceTimersByTime(60000)
      expect(MockWebSocket.instances.length).toBe(2)
    })

    it('resets reconnect counter on successful connection', () => {
      store.connectWebSocket()
      MockWebSocket.instances[0].simulateOpen()
      MockWebSocket.instances[0].simulateClose()

      // After a few failed reconnects, delays should grow
      vi.advanceTimersByTime(1000) // attempt 1
      MockWebSocket.instances[1].simulateClose()
      vi.advanceTimersByTime(2000) // attempt 2
      MockWebSocket.instances[2].simulateClose()
      vi.advanceTimersByTime(4000) // attempt 3
      // This one succeeds
      MockWebSocket.instances[3].simulateOpen()

      // Now close again — delay should reset to 1s, not continue from 8s
      MockWebSocket.instances[3].simulateClose()
      vi.advanceTimersByTime(1000)
      expect(MockWebSocket.instances.length).toBe(5) // reconnected at 1s, not 8s
    })
  })

  describe('recentCount computed', () => {
    it('should count only error and critical alerts', () => {
      store.recentAlerts = [
        { level: 'info' },
        { level: 'warning' },
        { level: 'error' },
        { level: 'critical' },
        { level: 'error' },
      ]
      expect(store.recentCount).toBe(3)
    })
  })
})
