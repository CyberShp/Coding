import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/api', () => ({
  default: {
    getRecentAlerts: vi.fn().mockResolvedValue({ data: [] }),
  },
}))

vi.mock('../../src/utils/notification', () => ({
  sendDesktopNotification: vi.fn(),
  playAlertSound: vi.fn(),
  requestNotificationPermission: vi.fn(),
}))

import { useAlertStore } from '../../src/stores/alerts'
import { usePreferencesStore } from '../../src/stores/preferences'


describe('alerts realtime payloads', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('consumes every alert in a websocket batch', () => {
    const store = useAlertStore()

    store.handleWebSocketMessage({
      type: 'batch',
      messages: [
        { type: 'alert', data: { id: 1, level: 'info', timestamp: new Date().toISOString() } },
        { type: 'alert', data: { id: 2, level: 'warning', timestamp: new Date().toISOString() } },
      ],
    })

    expect(store.recentAlerts.map(alert => alert.id)).toEqual([2, 1])
  })

  it('ignores a repeated realtime event id', () => {
    const store = useAlertStore()
    const message = {
      type: 'alert',
      data: { id: 7, level: 'info', timestamp: new Date().toISOString() },
    }

    store.handleWebSocketMessage(message)
    store.handleWebSocketMessage(message)

    expect(store.recentAlerts).toHaveLength(1)
  })

  it('applies watched observers in personal view', () => {
    const store = useAlertStore()
    const preferences = usePreferencesStore()
    preferences.personalViewActive = true
    preferences.watchedObservers = ['cpu_usage']

    store.handleWebSocketMessage({
      type: 'batch',
      messages: [
        { type: 'alert', data: { id: 11, observer_name: 'link_status', level: 'warning', timestamp: new Date().toISOString() } },
        { type: 'alert', data: { id: 12, observer_name: 'cpu_usage', level: 'warning', timestamp: new Date().toISOString() } },
      ],
    })

    expect(store.recentAlerts.map(alert => alert.id)).toEqual([12])
  })
})
