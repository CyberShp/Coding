/**
 * Composable: alert folding logic.
 *
 * Groups alerts whose messages are "nearly identical" (same observer, array,
 * and message skeleton after stripping numbers/timestamps) into collapsible
 * groups, shared across AlertCenter, ArrayDetail and Dashboard.
 */
import { computed, reactive } from 'vue'
import { translateAlert } from '@/utils/alertTranslator'

export const LEVEL_RANK = { critical: 4, error: 3, warning: 2, info: 1 }

function getTranslatedSummary(row) {
  const result = translateAlert(row)
  return result.summary || row.message
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
      // Generate folding key: observer + array + message skeleton (strip numbers/timestamps)
      const skeleton = (alert.message || '')
        .replace(/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}[:\d.]*/g, '#TIME#')  // timestamps
        .replace(/\d+/g, '#N#')  // numbers
        .replace(/\s+/g, ' ')
        .trim()
        .substring(0, 80)  // first 80 chars as key

      const key = `${alert.observer_name}|${alert.array_id}|${skeleton}`

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
