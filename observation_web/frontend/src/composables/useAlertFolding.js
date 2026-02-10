/**
 * Composable: alert folding logic.
 *
 * Groups alerts that represent the SAME recurring issue into collapsible
 * groups. The folding key is observer-aware:
 * - alarm_type: fold by objType + action (同类告警反复上报才折叠)
 * - card_info: fold by slot + board_id (同一张卡反复上报才折叠)
 * - error_code: fold by port (同端口误码才折叠)
 * - link_status: fold by port (同端口链路变化才折叠)
 * - Others: fold by message skeleton (通用兜底)
 */
import { computed, reactive } from 'vue'
import { translateAlert } from '@/utils/alertTranslator'

export const LEVEL_RANK = { critical: 4, error: 3, warning: 2, info: 1 }

function getTranslatedSummary(row) {
  const result = translateAlert(row)
  return result.summary || row.message
}

/**
 * Extract a semantic identity from alert details for smarter folding.
 * Returns a string that distinguishes different "subjects" within the same observer.
 * Alerts with the same identity represent the SAME recurring issue.
 */
function getAlertIdentity(alert) {
  const d = alert.details || {}
  const obs = alert.observer_name

  if (obs === 'alarm_type') {
    // Fold by objType + action so same-type faults group together,
    // but DiskEnclosure faults don't mix with FanModule faults
    const first = (d.new_send_alarms || [])[0] || (d.new_resume_alarms || [])[0] || (d.new_events || [])[0]
    if (first) {
      return `${first.obj_type || first.alarm_name || '?'}|${first.action || (first.is_resume ? 'resume' : first.is_event ? 'event' : 'fault')}`
    }
  }

  if (obs === 'card_info') {
    // Fold by slot + board_id so same-card issues group together
    const items = d.alerts || []
    if (items.length > 0) {
      const a = items[0]
      return `${a.card || '?'}|${a.board_id || '?'}|${a.field || '?'}`
    }
  }

  if (obs === 'error_code') {
    // Fold by port — same port's repeated errors group together
    const ports = Object.keys(d.port_counters || {})
    if (ports.length > 0) return ports[0]
  }

  if (obs === 'link_status') {
    // Fold by port
    const changes = d.changes || []
    if (changes.length > 0) return changes[0].port || '?'
  }

  if (obs === 'port_speed') {
    const changes = d.changes || []
    if (changes.length > 0) return changes[0].port || '?'
  }

  if (obs === 'port_fec') {
    const changes = d.changes || []
    if (changes.length > 0) return changes[0].port || '?'
  }

  if (obs === 'controller_state') {
    const changes = d.changes || []
    if (changes.length > 0) return changes[0].id || '?'
  }

  if (obs === 'disk_state') {
    const changes = d.changes || []
    if (changes.length > 0) return changes[0].id || '?'
  }

  // Fallback: use message skeleton (strip numbers/timestamps)
  return null
}

/**
 * @param {import('vue').Ref<Array>} alerts  – reactive alert array
 * @returns {{ foldedAlerts: import('vue').ComputedRef<Array>, toggleExpand: (key: string) => void }}
 */
export function useAlertFolding(alerts) {
  // Expanded state lives OUTSIDE computed in a reactive Map so that:
  // 1) Mutations trigger Vue re-renders (unlike plain objects in computed)
  // 2) State survives computed re-evaluations (e.g. after silent refresh)
  const expandedKeys = reactive(new Set())

  function toggleExpand(key) {
    if (expandedKeys.has(key)) {
      expandedKeys.delete(key)
    } else {
      expandedKeys.add(key)
    }
  }

  const foldedAlerts = computed(() => {
    const groups = []
    const map = new Map()

    for (const alert of alerts.value) {
      // Try observer-aware identity first; fall back to message skeleton
      let identity = getAlertIdentity(alert)
      if (!identity) {
        identity = (alert.message || '')
          .replace(/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}[:\d.]*/g, '#TIME#')
          .replace(/\d+/g, '#N#')
          .replace(/\s+/g, ' ')
          .trim()
          .substring(0, 80)
      }

      const key = `${alert.observer_name}|${alert.array_id}|${identity}`

      if (map.has(key)) {
        const g = map.get(key)
        g.items.push(alert)
        g.count++
        // Track latest time and worst level
        if (alert.timestamp > g.latestTime) g.latestTime = alert.timestamp
        if ((LEVEL_RANK[alert.level] || 0) > (LEVEL_RANK[g.worstLevel] || 0)) g.worstLevel = alert.level
      } else {
        const group = {
          key,
          observer: alert.observer_name,
          arrayId: alert.array_id,
          summaryMsg: getTranslatedSummary(alert),
          latestTime: alert.timestamp,
          worstLevel: alert.level,
          count: 1,
          items: [alert],
        }
        map.set(key, group)
        groups.push(group)
      }
    }

    // Attach reactive expanded flag derived from the Set
    // (reading expandedKeys.has() inside computed creates a reactive dependency)
    for (const g of groups) {
      g.expanded = expandedKeys.has(g.key)
    }

    return groups
  })

  return { foldedAlerts, toggleExpand }
}
