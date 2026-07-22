/**
 * monitor-multiuser.spec.js — multi-user custom monitoring Phase 2 (frontend).
 *
 * Covers the three pieces of logic the feature hinges on:
 *   1. visibility partitioning (我的草稿 / 本组 / 全局库)
 *   2. owner-permission button show/hide (edit/delete/publish vs read-only)
 *   3. health-dashboard "stale" (最后告警过久) highlighting
 *
 * The pure helpers in src/views/monitorHelpers.js drive every v-if in
 * AdminMonitors.vue (edit/delete/publish gating, visibility zones) and
 * MonitorHealth.vue (stale highlighting), so exercising them directly is both
 * faithful to the rendered behaviour and free of element-stub flakiness.
 */

import { describe, it, expect } from 'vitest'

import {
  normalizeVisibility,
  partitionByVisibility,
  canManageTemplate,
  publishTargets,
  isStaleDeployment,
} from '@/views/monitorHelpers'

// ---------------------------------------------------------------------------
// 1. Visibility partitioning
// ---------------------------------------------------------------------------
describe('partitionByVisibility', () => {
  const templates = [
    { id: 1, visibility: 'draft' },
    { id: 2, visibility: 'team' },
    { id: 3, visibility: 'global' },
    { id: 4, visibility: 'team' },
    { id: 5, visibility: 'private' }, // legacy alias → draft
    { id: 6 },                        // missing → team (contract default tier)
  ]

  it('groups templates into the three zones', () => {
    const groups = partitionByVisibility(templates)
    expect(groups.draft.map(t => t.id)).toEqual([1, 5])
    expect(groups.team.map(t => t.id)).toEqual([2, 4, 6])
    expect(groups.global.map(t => t.id)).toEqual([3])
  })

  it('normalizes legacy/unknown visibility values', () => {
    expect(normalizeVisibility('private')).toBe('draft')
    expect(normalizeVisibility('draft')).toBe('draft')
    expect(normalizeVisibility('global')).toBe('global')
    expect(normalizeVisibility(undefined)).toBe('team')
    expect(normalizeVisibility('bogus')).toBe('team')
  })

  it('returns empty zones for empty input', () => {
    expect(partitionByVisibility([])).toEqual({ draft: [], team: [], global: [] })
    expect(partitionByVisibility()).toEqual({ draft: [], team: [], global: [] })
  })
})

// ---------------------------------------------------------------------------
// 2. Owner-permission button show/hide
// ---------------------------------------------------------------------------
describe('canManageTemplate', () => {
  const template = { id: 10, owner_user_id: 42, created_by: 'alice' }

  it('lets the owner manage their own template', () => {
    expect(canManageTemplate(template, { id: 42 }, false)).toBe(true)
  })

  it('hides management from a non-owner', () => {
    expect(canManageTemplate(template, { id: 7 }, false)).toBe(false)
  })

  it('lets an admin manage any template', () => {
    expect(canManageTemplate(template, { id: 7 }, true)).toBe(true)
  })

  it('denies anonymous (no current user)', () => {
    expect(canManageTemplate(template, null, false)).toBe(false)
  })

  it('does not match when owner_user_id is missing', () => {
    expect(canManageTemplate({ id: 11 }, { id: 42 }, false)).toBe(false)
  })
})

describe('publishTargets', () => {
  it('offers team + global for a draft', () => {
    expect(publishTargets('draft').map(a => a.visibility)).toEqual(['team', 'global'])
  })
  it('offers only global for a team template', () => {
    expect(publishTargets('team').map(a => a.visibility)).toEqual(['global'])
  })
  it('offers nothing for a global template', () => {
    expect(publishTargets('global')).toEqual([])
  })
  it('treats legacy private as draft', () => {
    expect(publishTargets('private').map(a => a.visibility)).toEqual(['team', 'global'])
  })
})

// ---------------------------------------------------------------------------
// 3. Health dashboard "stale" highlighting
// ---------------------------------------------------------------------------
describe('isStaleDeployment', () => {
  const now = new Date('2026-07-22T12:00:00Z').getTime()
  const daysAgo = d => new Date(now - d * 24 * 60 * 60 * 1000).toISOString()

  it('flags a deployment whose last alert is older than 7 days', () => {
    expect(isStaleDeployment(daysAgo(8), now)).toBe(true)
    expect(isStaleDeployment(daysAgo(30), now)).toBe(true)
  })

  it('does not flag a recent alert', () => {
    expect(isStaleDeployment(daysAgo(2), now)).toBe(false)
    expect(isStaleDeployment(daysAgo(6.9), now)).toBe(false)
  })

  it('does not flag a deployment that never alerted', () => {
    expect(isStaleDeployment(null, now)).toBe(false)
    expect(isStaleDeployment('', now)).toBe(false)
    expect(isStaleDeployment(undefined, now)).toBe(false)
  })

  it('ignores unparseable timestamps', () => {
    expect(isStaleDeployment('not-a-date', now)).toBe(false)
  })

  it('honours a custom day threshold', () => {
    expect(isStaleDeployment(daysAgo(4), now, 3)).toBe(true)
    expect(isStaleDeployment(daysAgo(2), now, 3)).toBe(false)
  })
})
