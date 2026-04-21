import { describe, it, expect } from 'vitest'

/**
 * F205 stream dedup regression test.
 *
 * Reproduces the exact logic from ArrayDetail.vue:
 * - _alertKey() generates dedup keys
 * - Entering stream mode seeds from recentAlerts and registers keys
 * - Subsequent refresh/reconnect delivering the same alerts produces zero duplicates
 * - Genuinely new alerts after seed are still accepted
 */

function _alertKey(a) {
  return a.id || `${a.timestamp}_${a.observer_name}_${(a.message || '').slice(0, 50)}`
}

describe('F205 stream dedup (enter stream → refresh → no duplicates)', () => {
  const SEED_ALERTS = [
    { id: 1, array_id: 'arr_001', observer_name: 'alarm_type', level: 'error', message: 'DiskEnclosure fault', timestamp: '2026-04-21T10:00:00Z', created_at: '2026-04-21T10:00:02Z' },
    { id: 2, array_id: 'arr_001', observer_name: 'disk_smart', level: 'warning', message: 'Reallocated sectors: 5', timestamp: '2026-04-21T10:00:05Z', created_at: '2026-04-21T10:00:06Z' },
    { id: 3, array_id: 'arr_001', observer_name: 'alarm_type', level: 'error', message: 'FanModule alarm', timestamp: '2026-04-21T10:00:10Z', created_at: '2026-04-21T10:00:11Z' },
  ]

  it('seed registers all keys so refresh produces zero unseen items', () => {
    const seenAlertKeys = new Set()
    const streamItems = []

    // Step 1: Enter stream mode — seed from recentAlerts
    for (const a of SEED_ALERTS) {
      streamItems.push({ ...a, _streamKey: `s${streamItems.length + 1}` })
      seenAlertKeys.add(_alertKey(a))
    }
    expect(streamItems.length).toBe(3)
    expect(seenAlertKeys.size).toBe(3)

    // Step 2: Silent refresh delivers the SAME alerts (simulates 30s poll or reconnect catch-up)
    const refreshData = [...SEED_ALERTS]
    const unseen = []
    for (const alert of refreshData) {
      const key = _alertKey(alert)
      if (!seenAlertKeys.has(key)) {
        seenAlertKeys.add(key)
        unseen.push(alert)
      }
    }

    // No duplicates should appear
    expect(unseen.length).toBe(0)
    expect(streamItems.length).toBe(3) // unchanged
  })

  it('genuinely new alerts after seed ARE accepted', () => {
    const seenAlertKeys = new Set()
    const streamItems = []

    // Seed
    for (const a of SEED_ALERTS) {
      streamItems.push({ ...a, _streamKey: `s${streamItems.length + 1}` })
      seenAlertKeys.add(_alertKey(a))
    }

    // New alert arrives via WS
    const newAlert = { id: 4, array_id: 'arr_001', observer_name: 'rebuild_status', level: 'info', message: 'Rebuilding 12%', timestamp: '2026-04-21T10:01:00Z', created_at: '2026-04-21T10:01:01Z' }
    const key = _alertKey(newAlert)
    expect(seenAlertKeys.has(key)).toBe(false)
    seenAlertKeys.add(key)
    streamItems.push({ ...newAlert, _streamKey: `s${streamItems.length + 1}` })

    expect(streamItems.length).toBe(4)
    expect(seenAlertKeys.size).toBe(4)
  })

  it('batch refill (reconnect) with mix of old+new only adds new', () => {
    const seenAlertKeys = new Set()
    const streamItems = []

    // Seed with first 2
    for (const a of SEED_ALERTS.slice(0, 2)) {
      streamItems.push({ ...a, _streamKey: `s${streamItems.length + 1}` })
      seenAlertKeys.add(_alertKey(a))
    }
    expect(streamItems.length).toBe(2)

    // Reconnect refill: old 2 + 1 new (SEED_ALERTS[2])
    const batchRefill = [...SEED_ALERTS]
    const unseen = []
    for (const alert of batchRefill) {
      const key = _alertKey(alert)
      if (!seenAlertKeys.has(key)) {
        seenAlertKeys.add(key)
        unseen.push(alert)
      }
    }

    // Only the 3rd alert is new
    expect(unseen.length).toBe(1)
    expect(unseen[0].id).toBe(3)
  })

  it('alerts without id use composite key for dedup', () => {
    const seenAlertKeys = new Set()

    const alertNoId = { observer_name: 'alarm_type', message: 'DiskEnclosure fault', timestamp: '2026-04-21T10:00:00Z' }
    const key1 = _alertKey(alertNoId)
    seenAlertKeys.add(key1)

    // Same alert again (no id) should produce the same key
    const duplicate = { ...alertNoId }
    const key2 = _alertKey(duplicate)
    expect(seenAlertKeys.has(key2)).toBe(true)

    // Different timestamp = different key
    const different = { ...alertNoId, timestamp: '2026-04-21T10:00:05Z' }
    expect(seenAlertKeys.has(_alertKey(different))).toBe(false)
  })
})
