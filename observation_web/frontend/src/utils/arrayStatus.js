// Pure array-status helpers shared across Dashboard sub-components.

export const FRESH_THRESHOLD_MIN = 5
export const STALE_THRESHOLD_MIN = 30

export function getArrayFreshness(arr) {
  const ts = arr.last_heartbeat_at || arr.last_refresh
  if (!ts) return 'unknown'
  const age = (Date.now() - new Date(ts).getTime()) / 60000
  if (age <= FRESH_THRESHOLD_MIN) return 'fresh'
  if (age <= STALE_THRESHOLD_MIN) return 'stale'
  return 'unknown'
}

export function getArrayStatusClass(arr) {
  if (arr.state !== 'connected') return 'status-offline'
  const issues = arr.active_issues || []
  if (issues.length > 0) {
    const hasError = issues.some(i => i.level === 'error' || i.level === 'critical')
    return hasError ? 'status-error' : 'status-warning'
  }
  const s = arr.recent_alert_summary || {}
  if ((s.error || 0) + (s.critical || 0) > 0) return 'status-attention'
  if ((s.warning || 0) > 0) return 'status-warning'
  return 'status-ok'
}

export function getStatusDotClass(arr) {
  if (arr.state !== 'connected') return 'dot-offline'
  const issues = arr.active_issues || []
  if (issues.length > 0) {
    return issues.some(i => i.level === 'error' || i.level === 'critical')
      ? 'dot-error' : 'dot-warning'
  }
  const s = arr.recent_alert_summary || {}
  if ((s.error || 0) + (s.critical || 0) > 0) return 'dot-warning'
  return 'dot-ok'
}

export function getHeatmapDotClass(arr) {
  if (arr.state !== 'connected') return 'heatmap-offline'
  const issues = arr.active_issues || []
  if (issues.length > 0) {
    return issues.some(i => i.level === 'error' || i.level === 'critical')
      ? 'heatmap-error' : 'heatmap-warning'
  }
  const s = arr.recent_alert_summary || {}
  if ((s.error || 0) + (s.critical || 0) > 0) return 'heatmap-warning'
  return 'heatmap-healthy'
}

export function getHeatmapTooltip(arr) {
  const name = arr.display_name || arr.name || '未命名'
  const ip = arr.host || '-'
  const issues = arr.active_issues || []
  const lastIssue = issues.length > 0
    ? (issues[0].message || issues[0].type || '有异常')
    : '无异常'
  return `${name} | ${ip} | ${lastIssue}`
}

export function getFreshnessClass(arr) {
  return 'freshness-' + getArrayFreshness(arr)
}

export function getFreshnessLabel(arr) {
  const f = getArrayFreshness(arr)
  if (f === 'fresh') return '实时'
  if (f === 'stale') return '延迟'
  return '未知'
}

export function formatRelativeTime(timestamp) {
  if (!timestamp) return ''
  const sec = (Date.now() - new Date(timestamp).getTime()) / 1000
  if (sec < 0) return '刚刚'
  if (sec < 60) return `${Math.round(sec)}s 前`
  if (sec < 3600) return `${Math.floor(sec / 60)}m 前`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h 前`
  return `${Math.floor(sec / 86400)}d 前`
}
