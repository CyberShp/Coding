/**
 * phase3.spec.js — multi-user collision rules, Phase 3 (frontend).
 *
 * Covers the three pieces of logic the feature hinges on:
 *   1. canUndoAck — ack undo permission (本人 / admin / system / 他人)
 *   2. is_expected === 1 renders the "预期内(测试期)" tag in the alert list
 *   3. groupOverridesByScope — observer config overrides grouped by scope_type
 *
 * jsdom in this project runs on an opaque origin, so window.localStorage is a
 * method-less stub. Install a functional in-memory implementation before any
 * store module touches it (mirrors auth.spec.js).
 */
const memoryStorage = (() => {
  let store = {}
  return {
    getItem: k => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v) },
    removeItem: k => { delete store[k] },
    clear: () => { store = {} },
  }
})()
Object.defineProperty(window, 'localStorage', { value: memoryStorage, writable: true })

import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { shallowMount } from '@vue/test-utils'

import {
  canUndoAck,
  hasHumanAcker,
  ackUndoErrorMessage,
  isExpectedTestAlert,
  UNDO_FORBIDDEN_HINT,
} from '@/utils/alertHelpers'
import { groupOverridesByScope, BUILTIN_OBSERVERS } from '@/components/admin/observerOverrideHelpers'
import FoldedAlertList from '@/components/FoldedAlertList.vue'

// ---------------------------------------------------------------------------
// 1. canUndoAck — undo permission
// ---------------------------------------------------------------------------
describe('canUndoAck', () => {
  const humanAck = { acked_by_nickname: 'alice', ack_type: 'confirmed_ok' }
  const systemAck = { ack_type: 'confirmed_ok' } // no human acknowledger

  it('lets the original acknowledger undo their own ack (本人)', () => {
    expect(canUndoAck(humanAck, { nickname: 'alice', is_admin: false })).toBe(true)
  })

  it('lets an admin undo anyone\'s ack (admin)', () => {
    expect(canUndoAck(humanAck, { nickname: 'bob', is_admin: true })).toBe(true)
  })

  it('lets any logged-in user undo a system ack (system)', () => {
    expect(canUndoAck(systemAck, { nickname: 'carol', is_admin: false })).toBe(true)
  })

  it('forbids a different non-admin user from undoing another\'s ack (他人)', () => {
    expect(canUndoAck(humanAck, { nickname: 'bob', is_admin: false })).toBe(false)
  })

  it('forbids anonymous (not logged in) from undoing anything', () => {
    expect(canUndoAck(humanAck, null)).toBe(false)
    expect(canUndoAck(systemAck, null)).toBe(false)
    expect(canUndoAck(humanAck, {})).toBe(false)
  })

  it('hasHumanAcker reflects presence of a nickname', () => {
    expect(hasHumanAcker(humanAck)).toBe(true)
    expect(hasHumanAcker(systemAck)).toBe(false)
    expect(hasHumanAcker(null)).toBe(false)
  })
})

describe('ackUndoErrorMessage', () => {
  it('maps a 403 to the localized permission hint', () => {
    const e = { response: { status: 403, data: { detail: 'only the acknowledger or an admin can undo' } } }
    expect(ackUndoErrorMessage(e)).toBe(UNDO_FORBIDDEN_HINT)
  })

  it('falls back to detail/message for non-403 errors', () => {
    const e = { response: { status: 500, data: { detail: 'boom' } } }
    expect(ackUndoErrorMessage(e)).toBe('撤销失败: boom')
    expect(ackUndoErrorMessage({ message: 'net' })).toBe('撤销失败: net')
  })
})

// ---------------------------------------------------------------------------
// 2. is_expected === 1 renders the "预期内(测试期)" tag
// ---------------------------------------------------------------------------
describe('isExpectedTestAlert', () => {
  it('is true only for is_expected === 1', () => {
    expect(isExpectedTestAlert({ is_expected: 1 })).toBe(true)
    expect(isExpectedTestAlert({ is_expected: 0 })).toBe(false)
    expect(isExpectedTestAlert({ is_expected: -1 })).toBe(false)
    expect(isExpectedTestAlert({})).toBe(false)
    expect(isExpectedTestAlert(null)).toBe(false)
  })
})

describe('FoldedAlertList — expected tag rendering', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  function mountWith(alert) {
    return shallowMount(FoldedAlertList, {
      props: { alerts: [alert] },
    })
  }

  it('renders the 预期内(测试期) tag for a test-period expected alert', () => {
    const wrapper = mountWith({
      id: 1, level: 'warning', observer_name: 'cpu_usage',
      message: 'cpu high', timestamp: '2026-07-22T00:00:00Z', is_expected: 1,
    })
    expect(wrapper.find('.expected-tag').exists()).toBe(true)
  })

  it('does not render the tag for a non-expected alert', () => {
    const wrapper = mountWith({
      id: 2, level: 'warning', observer_name: 'cpu_usage',
      message: 'cpu high', timestamp: '2026-07-22T00:00:00Z', is_expected: 0,
    })
    expect(wrapper.find('.expected-tag').exists()).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// 3. groupOverridesByScope — observer config overrides grouped by scope_type
// ---------------------------------------------------------------------------
describe('groupOverridesByScope', () => {
  it('splits overrides into tag and array groups by scope_type', () => {
    const overrides = [
      { scope_type: 'tag', scope_id: 10, params: { threshold: 90 }, enabled: true },
      { scope_type: 'array', scope_id: 'arr-1', params: { threshold: 80 }, enabled: false },
      { scope_type: 'tag', scope_id: 11, params: {}, enabled: true },
      { scope_type: 'global', scope_id: null, params: { threshold: 70 }, enabled: true },
    ]
    const groups = groupOverridesByScope(overrides)
    expect(groups.tag.map(o => o.scope_id)).toEqual([10, 11])
    expect(groups.array.map(o => o.scope_id)).toEqual(['arr-1'])
    expect(groups.global.params).toEqual({ threshold: 70 })
  })

  it('returns empty groups for empty / missing input', () => {
    expect(groupOverridesByScope([])).toEqual({ global: null, tag: [], array: [] })
    expect(groupOverridesByScope()).toEqual({ global: null, tag: [], array: [] })
  })

  it('exposes the built-in observer list', () => {
    expect(BUILTIN_OBSERVERS).toContain('alarm_type')
    expect(BUILTIN_OBSERVERS.length).toBeGreaterThan(0)
  })
})
