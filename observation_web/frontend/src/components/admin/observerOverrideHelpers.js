/**
 * observerOverrideHelpers.js — pure helpers for the built-in observer config
 * override UI (design §四: observer_config_overrides — 全局一份降级为默认值，
 * 新增按 L1 标签/按阵列覆盖层，小组各管各的).
 */

/** Built-in observer points that can carry config overrides. */
export const BUILTIN_OBSERVERS = [
  'alarm_type',
  'card_info',
  'card_recovery',
  'disk_error',
  'eth_link',
  'fc_link',
  'log_watcher',
  'port_error',
  'process_monitor',
]

/** Scope types an override may target (global default is the base config). */
export const SCOPE_TYPES = ['tag', 'array']

/**
 * Split a flat override list into scope groups for display.
 *
 * The API returns [{ scope_type: 'tag'|'array', scope_id, params, enabled,
 * updated_by }]; the UI shows a tag-override list and an array-override list.
 * A defensively-handled 'global' scope is captured separately if present.
 *
 * @param {Array} overrides
 * @returns {{ global: object|null, tag: Array, array: Array }}
 */
export function groupOverridesByScope(overrides) {
  const groups = { global: null, tag: [], array: [] }
  for (const o of overrides || []) {
    if (o.scope_type === 'global') groups.global = o
    else if (o.scope_type === 'tag') groups.tag.push(o)
    else if (o.scope_type === 'array') groups.array.push(o)
  }
  return groups
}
