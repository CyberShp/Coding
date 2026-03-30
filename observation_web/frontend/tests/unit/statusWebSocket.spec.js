/**
 * Tests for status WebSocket integration and unified status display.
 *
 * Covers:
 * 8.  Status WebSocket updates array list in real time
 * 9.  Detail page syncs when viewing that array
 * 10. Reconnect → detail page auto-switches from disconnected to connected
 * 11. Dashboard stats use agent_healthy, not loose agent_running
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useArrayStore } from '../../src/stores/arrays'

describe('Arrays Store - Status WebSocket', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useArrayStore()
  })

  // ── Test 8: status_update updates list ──────────────────────────────
  it('applies status_update to array list', () => {
    // Seed with initial data
    store.arrays = [
      { array_id: 'arr1', name: 'Array1', state: 'disconnected', agent_running: false, agent_healthy: false },
      { array_id: 'arr2', name: 'Array2', state: 'connected', agent_running: true, agent_healthy: true },
    ]

    // Simulate status_update message
    store._applyStatusUpdate({
      array_id: 'arr1',
      state: 'connected',
      transport_connected: true,
      agent_running: true,
      agent_healthy: true,
    })

    const updated = store.arrays.find(a => a.array_id === 'arr1')
    expect(updated.state).toBe('connected')
    expect(updated.agent_running).toBe(true)
    expect(updated.agent_healthy).toBe(true)
    expect(updated.transport_connected).toBe(true)
  })

  // ── Test 9: detail page syncs on status_update ──────────────────────
  it('updates currentArray when viewing that array', () => {
    store.currentArray = {
      array_id: 'arr1',
      name: 'Array1',
      state: 'disconnected',
      agent_running: false,
      agent_healthy: false,
    }

    store._applyStatusUpdate({
      array_id: 'arr1',
      state: 'connected',
      agent_running: true,
      agent_healthy: true,
    })

    expect(store.currentArray.state).toBe('connected')
    expect(store.currentArray.agent_running).toBe(true)
    expect(store.currentArray.agent_healthy).toBe(true)
  })

  it('does NOT update currentArray for a different array_id', () => {
    store.currentArray = {
      array_id: 'arr1',
      name: 'Array1',
      state: 'disconnected',
    }

    store._applyStatusUpdate({
      array_id: 'arr2',
      state: 'connected',
    })

    // arr1 should remain unchanged
    expect(store.currentArray.state).toBe('disconnected')
  })

  // ── Test 10: reconnect updates detail page ──────────────────────────
  it('auto-switches detail page from disconnected to connected on reconnect', () => {
    store.arrays = [
      { array_id: 'arr1', state: 'disconnected', agent_running: false, agent_healthy: false },
    ]
    store.currentArray = {
      array_id: 'arr1',
      state: 'disconnected',
      agent_running: false,
      agent_healthy: false,
    }

    // Simulate reconnect event via status_update
    store._applyStatusUpdate({
      array_id: 'arr1',
      state: 'connected',
      transport_connected: true,
      agent_running: true,
      agent_healthy: true,
      event: 'connect',
    })

    expect(store.currentArray.state).toBe('connected')
    expect(store.arrays[0].state).toBe('connected')
    // No manual refresh needed
  })

  // ── Test 11: Dashboard stats use agent_healthy ──────────────────────
  it('healthyCount counts only agent_healthy arrays', () => {
    store.arrays = [
      { array_id: 'a1', agent_running: true, agent_healthy: true },
      { array_id: 'a2', agent_running: true, agent_healthy: false },  // running but not healthy
      { array_id: 'a3', agent_running: false, agent_healthy: false },
    ]

    expect(store.healthyCount).toBe(1)
    expect(store.runningCount).toBe(2)
  })

  it('connectedCount includes degraded state', () => {
    store.arrays = [
      { array_id: 'a1', state: 'connected' },
      { array_id: 'a2', state: 'degraded' },
      { array_id: 'a3', state: 'disconnected' },
    ]

    expect(store.connectedCount).toBe(2)
  })
})
