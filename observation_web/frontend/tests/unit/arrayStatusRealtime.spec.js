import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/api', () => ({ default: {} }))

import { useArrayStore } from '../../src/stores/arrays'


describe('array status realtime updates', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('applies every status in a websocket batch without reloading the list', () => {
    const store = useArrayStore()
    store.arrays = [
      { array_id: 'a1', name: 'A1', state: 'disconnected' },
      { array_id: 'a2', name: 'A2', state: 'disconnected' },
    ]

    store.handleStatusMessage({
      type: 'batch',
      messages: [
        { type: 'status_update', array_id: 'a1', data: { state: 'connected' } },
        { type: 'status_update', array_id: 'a2', data: { agent_state: 'running' } },
      ],
    })

    expect(store.arrays[0].state).toBe('connected')
    expect(store.arrays[1].agent_state).toBe('running')
  })

  it('does not let an older probe replace a newer agent heartbeat', () => {
    const store = useArrayStore()
    store.arrays = [{
      array_id: 'a1',
      name: 'A1',
      agent_state: 'running',
      agent_running: true,
      agent_observed_at: '2026-07-16T10:00:10',
      agent_status_source: 'agent_heartbeat',
    }]

    store.applyStatusUpdate('a1', {
      agent_state: 'stopped',
      agent_running: false,
      agent_observed_at: '2026-07-16T10:00:09',
      agent_status_source: 'health_probe',
    })

    expect(store.arrays[0].agent_state).toBe('running')
    expect(store.arrays[0].agent_running).toBe(true)
    expect(store.arrays[0].agent_status_source).toBe('agent_heartbeat')
  })
})
