/**
 * monitorHelpers.js — pure logic for multi-user custom monitoring (Phase 2).
 *
 * These functions drive the visibility partitioning, owner-permission UI, and
 * health-dashboard "stale" highlighting. They are framework-free so they can be
 * unit-tested directly (tests/unit/monitor-multiuser.spec.js) without mounting.
 */

// Contract visibility values: draft | team | global.
// The legacy custom-observer studio used `private` for the personal/draft tier;
// treat it as `draft` so old rows still land in the right bucket.
export const VISIBILITY_LABELS = { draft: '草稿', team: '本组', global: '全局库' }
export const VISIBILITY_TAG_TYPE = { draft: 'info', team: 'warning', global: 'success' }

export function normalizeVisibility(visibility) {
  if (visibility === 'private') return 'draft'
  if (visibility === 'draft' || visibility === 'team' || visibility === 'global') return visibility
  // Unknown / missing → team is the contract default ownership tier.
  return 'team'
}

/**
 * Split templates into the three visibility zones.
 * @param {Array} templates
 * @returns {{draft: Array, team: Array, global: Array}}
 */
export function partitionByVisibility(templates = []) {
  const groups = { draft: [], team: [], global: [] }
  for (const t of templates || []) {
    groups[normalizeVisibility(t?.visibility)].push(t)
  }
  return groups
}

/**
 * Whether the current user may edit/delete/publish a template.
 * Owner (owner_user_id === user.id) or admin.
 */
export function canManageTemplate(template, currentUser, isAdmin = false) {
  if (isAdmin) return true
  if (!template || !currentUser) return false
  return template.owner_user_id != null && template.owner_user_id === currentUser.id
}

/**
 * Publish actions available for a template at its current visibility.
 * draft → can publish to team or global; team → can publish to global; global → none.
 * @returns {Array<{visibility: string, label: string}>}
 */
export function publishTargets(visibility) {
  const v = normalizeVisibility(visibility)
  if (v === 'draft') {
    return [
      { visibility: 'team', label: '发布到小组' },
      { visibility: 'global', label: '发布到全局' },
    ]
  }
  if (v === 'team') {
    return [{ visibility: 'global', label: '发布到全局' }]
  }
  return []
}

const DAY_MS = 24 * 60 * 60 * 1000

/**
 * A deployment is "stale" (可能可清理) when its last alert is older than `days`.
 * A deployment that never alerted (null/empty) is NOT flagged — there is no
 * timestamp to compare and it may simply be new.
 */
export function isStaleDeployment(lastAlertAt, now = Date.now(), days = 7) {
  if (!lastAlertAt) return false
  const ts = new Date(lastAlertAt).getTime()
  if (Number.isNaN(ts)) return false
  return now - ts > days * DAY_MS
}

export { DAY_MS }
