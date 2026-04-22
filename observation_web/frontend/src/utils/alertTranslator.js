/**
 * 告警消息可读性翻译工具 v2
 *
 * 每条告警翻译为三段式结构：事件 → 影响 → 建议
 * 同时保留结构化解析结果和原始文本，供详情面板使用。
 *
 * 静态字符串（observerNames、levelLabels、impact/suggestion）
 * 均从 alertTranslations.json 加载，便于非代码方式维护。
 */
import TRANSLATIONS from './alertTranslations.json'

// 观察点中文名称映射（从 JSON 加载）
export const OBSERVER_NAMES = TRANSLATIONS.observerNames

// 告警级别中文映射（从 JSON 加载）
export const LEVEL_LABELS = TRANSLATIONS.levelLabels

export const LEVEL_TAG_TYPES = TRANSLATIONS.levelTagTypes

// 快捷访问：每个观察点的 impact / suggestion 字符串
const T = TRANSLATIONS.observerStrings

// 观察点分组（端口级 / 卡件级 / 系统级）
export const OBSERVER_GROUPS = {
  port: {
    label: '端口级检查',
    observers: ['error_code', 'link_status', 'port_fec', 'port_speed', 'port_traffic'],
  },
  card: {
    label: '卡件级检查',
    observers: ['card_recovery', 'card_info', 'pcie_bandwidth', 'controller_state', 'disk_state'],
  },
  system: {
    label: '系统级检查',
    observers: ['alarm_type', 'memory_leak', 'cpu_usage', 'cmd_response', 'sig_monitor', 'sensitive_info', 'process_crash', 'io_timeout'],
  },
}

// 关键事件观察点 — 任何场景下都需立即关注
export const CRITICAL_OBSERVERS = new Set([
  'process_crash', 'io_timeout', 'sig_monitor', 'controller_state', 'disk_state',
])

// 关键事件级别
export function isCriticalAlert(alert) {
  if (!alert) return false
  if (CRITICAL_OBSERVERS.has(alert.observer_name)) return true
  if (alert.level === 'critical') return true
  if (alert.level === 'error' && ['process_crash', 'io_timeout', 'controller_state', 'disk_state'].includes(alert.observer_name)) return true
  return false
}

/**
 * 根据观察点名返回所属分组
 */
export function getObserverGroup(observerName) {
  for (const [groupKey, group] of Object.entries(OBSERVER_GROUPS)) {
    if (group.observers.includes(observerName)) {
      return { key: groupKey, label: group.label }
    }
  }
  return { key: 'system', label: '系统级检查' }
}

// 告警级别中文映射
export const LEVEL_LABELS = {
  info: '信息',
  warning: '警告',
  error: '错误',
  critical: '严重',
}

export const LEVEL_TAG_TYPES = {
  info: 'info',
  warning: 'warning',
  error: 'danger',
  critical: 'danger',
}

/**
 * 翻译告警消息（v2: 三段式）
 * @param {Object} alert - { observer_name, message, details, level, ... }
 * @returns {Object} { summary, event, impact, suggestion, parsed, original, events, log_path }
 */
export function translateAlert(alert) {
  if (!alert) return { summary: '', event: '', impact: '', suggestion: '', parsed: null, original: '', events: [], log_path: '' }

  const translator = TRANSLATORS[alert.observer_name]
  if (translator) {
    return translator(alert)
  }
  return defaultTranslator(alert)
}

/**
 * 获取观察点中文名
 */
export function getObserverName(key) {
  return OBSERVER_NAMES[key] || key
}

// ============ 各观察点翻译器 ============

const TRANSLATORS = {
  alarm_type: translateAlarmType,
  error_code: translateErrorCode,
  link_status: translateLinkStatus,
  memory_leak: translateMemoryLeak,
  cpu_usage: translateCpuUsage,
  card_recovery: translateCardRecovery,
  port_fec: translatePortFec,
  port_speed: translatePortSpeed,
  pcie_bandwidth: translatePcieBandwidth,
  card_info: translateCardInfo,
  cmd_response: translateCmdResponse,
  sig_monitor: translateSigMonitor,
  sensitive_info: translateSensitiveInfo,
  controller_state: translateControllerState,
  disk_state: translateDiskState,
  process_crash: translateProcessCrash,
  io_timeout: translateIoTimeout,
}

// ===== Helper to build standard 3-part result =====
function makeResult({ event, impact, suggestion, parsed = null, original = '', events = [], log_path = '' }) {
  const summary = event || original
  return { summary, event, impact, suggestion, parsed, original, events, log_path }
}

// ============ alarm_type ============
function translateAlarmType(alert) {
  const { message, details } = alert
  const original = message || ''
  const log_path = details?.log_path || ''

  const newEvts = details?.new_events || []         // AlarmType:0 event
  const newSends = details?.new_send_alarms || []   // AlarmType:1 fault
  const newResumes = details?.new_resume_alarms || [] // AlarmType:2 resume
  const activeAlarms = details?.active_alarms || []

  const events = []
  for (const e of newEvts) events.push(normalizeEvent(e, 'event'))
  for (const e of newSends) events.push(normalizeEvent(e, 'fault'))
  for (const e of newResumes) events.push(normalizeEvent(e, 'resume'))

  let event = '', impact = '', suggestion = ''
  const parts = []

  if (newEvts.length > 0) {
    if (newEvts.length === 1) {
      const e = newEvts[0]
      parts.push(`事件上报：AlarmId:${e.alarm_id || '?'} objType:${e.obj_type || e.alarm_name || '?'}`)
    } else {
      parts.push(`${newEvts.length} 条事件上报`)
    }
  }

  if (newSends.length > 0) {
    if (newSends.length === 1) {
      const e = newSends[0]
      parts.push(`故障告警：AlarmId:${e.alarm_id || '?'} objType:${e.obj_type || e.alarm_name || '?'}`)
    } else {
      parts.push(`${newSends.length} 条故障告警`)
    }
  }

  if (newResumes.length > 0) {
    if (newResumes.length === 1) {
      const e = newResumes[0]
      parts.push(`告警恢复：AlarmId:${e.alarm_id || '?'} objType:${e.obj_type || e.alarm_name || '?'}`)
    } else {
      parts.push(`${newResumes.length} 条告警恢复`)
    }
  }

  event = parts.join(' | ')
  if (activeAlarms.length > 0) {
    event += event ? ` | 当前 ${activeAlarms.length} 个活跃告警` : `当前 ${activeAlarms.length} 个活跃告警`
  }
  if (!event) event = fallbackParseAlarmMessage(original)

  impact = activeAlarms.length > 0 ? `${activeAlarms.length} ${T.alarm_type.impactActive}` : T.alarm_type.impactDefault
  suggestion = T.alarm_type.suggestion

  const firstEvent = newSends[0] || newResumes[0] || newEvts[0] || null
  const parsed = firstEvent ? {
    alarm_type: firstEvent.alarm_type,
    action: firstEvent.action || (firstEvent.alarm_type === 0 ? 'event' : firstEvent.alarm_type === 1 ? 'fault' : 'resume'),
    alarm_id: firstEvent.alarm_id,
    obj_type: firstEvent.obj_type || firstEvent.alarm_name,
    alarm_name: firstEvent.alarm_name || firstEvent.obj_type,
    is_send: firstEvent.is_send ?? false,
    is_resume: firstEvent.is_resume ?? false,
    is_event: firstEvent.is_event ?? firstEvent.alarm_type === 0,
    is_history: firstEvent.alarm_type === 0 || firstEvent.is_event_report === true,
    recovered: firstEvent.recovered ?? false,
  } : parseAlarmFromText(original)

  return { summary: event, event, impact, suggestion, parsed, original, events, log_path }
}

function normalizeEvent(e, action) {
  return {
    alarm_type: e.alarm_type,
    action: e.action || action,
    alarm_name: e.alarm_name || e.obj_type || '未知',
    alarm_id: e.alarm_id || '?',
    obj_type: e.obj_type || '未知',
    timestamp: e.timestamp || '',
    is_send: action === 'fault' || e.alarm_type === 1,
    is_resume: action === 'resume' || e.alarm_type === 2,
    is_event: action === 'event' || e.alarm_type === 0,
    is_history: e.alarm_type === 0 || e.is_event_report === true,
    recovered: e.recovered ?? (action === 'resume'),
    line: e.line || '',
  }
}

function parseAlarmFromText(text) {
  if (!text) return null
  // New format: AlarmType:X action
  const newTypeMatch = text.match(/AlarmType:(\d+)\s+(event|fault|resume)/i)
  if (newTypeMatch) {
    const alarmType = parseInt(newTypeMatch[1])
    const action = newTypeMatch[2].toLowerCase()
    const idMatch = text.match(/AlarmId:(\S+)/i)
    const objMatch = text.match(/objType:(\S+)/i)
    return {
      alarm_type: alarmType, action,
      alarm_name: objMatch ? objMatch[1].trim() : '未知',
      alarm_id: idMatch ? idMatch[1].trim() : null,
      obj_type: objMatch ? objMatch[1].trim() : '未知',
      is_send: alarmType === 1, is_resume: alarmType === 2, is_event: alarmType === 0,
      is_history: alarmType === 0, recovered: alarmType === 2,
    }
  }
  // Fallback: old format
  const typeMatch = text.match(/alarm\s*type\s*\((\d+)\)/i)
  const nameMatch = text.match(/alarm\s*name\s*\(([^)]+)\)/i)
  const idMatch = text.match(/alarm\s*id\s*\(([^)]+)\)/i)
  const isSend = /send\s+alarm/i.test(text)
  const isResume = /resume\s+alarm/i.test(text)
  if (!typeMatch && !nameMatch) return null
  const alarmType = typeMatch ? parseInt(typeMatch[1]) : null
  return {
    alarm_type: alarmType, alarm_name: nameMatch ? nameMatch[1].trim() : '未知',
    alarm_id: idMatch ? idMatch[1].trim() : null,
    is_send: isSend, is_resume: isResume, is_event: false,
    is_history: alarmType === 0, recovered: isResume,
  }
}

function fallbackParseAlarmMessage(text) {
  if (!text) return '告警事件'
  // New format markers
  const eventMatch = text.match(/事件\s*(\d+)\s*条/)
  const faultMatch = text.match(/故障\s*(\d+)\s*条/)
  const resumeMatch = text.match(/恢复\s*(\d+)\s*条/)
  if (eventMatch || faultMatch || resumeMatch) {
    const p = []
    if (eventMatch) p.push(`${eventMatch[1]} 条事件上报`)
    if (faultMatch) p.push(`${faultMatch[1]} 条故障告警`)
    if (resumeMatch) p.push(`${resumeMatch[1]} 条告警恢复`)
    return p.join(' | ')
  }
  // Old format fallback
  const sendMatch = text.match(/新上报\s*(\d+)\s*条/)
  if (sendMatch) return `新上报 ${sendMatch[1]} 条告警`
  const parsed = parseAlarmFromText(text)
  if (parsed) {
    const name = parsed.alarm_name
    const id = parsed.alarm_id ? ` (${parsed.alarm_id})` : ''
    if (parsed.is_event) return `[事件] ${name}${id}`
    if (parsed.is_history) return `[历史] ${name}${id}`
    if (parsed.is_resume) return `告警恢复：${name}${id} 已消除`
    if (parsed.is_send) return `故障告警：${name}${id}`
  }
  return text.length > 80 ? text.substring(0, 80) + '...' : text
}

// ============ error_code ============
function translateErrorCode(alert) {
  const details = alert.details || {}
  const counters = details.port_counters || {}
  const ports = Object.keys(counters)
  let event = '', impact = '', suggestion = ''

  if (ports.length > 0) {
    const items = []
    for (const port of ports.slice(0, 3)) {
      const errs = Object.entries(counters[port] || {})
      const errStrs = errs.map(([k, v]) => `${k}+${v}`).join(', ')
      items.push(`${port}: ${errStrs}`)
    }
    event = `检测到误码增长：${items.join('；')}`
    impact = T.error_code.impact
    suggestion = T.error_code.suggestion
  } else {
    event = alert.message || '误码监测事件'
    impact = T.error_code.fallbackImpact
    suggestion = T.error_code.fallbackSuggestion
  }
  return makeResult({ event, impact, suggestion, original: alert.message || '', log_path: details.log_path || '' })
}

// ============ link_status ============
function translateLinkStatus(alert) {
  const details = alert.details || {}
  const changes = details.changes || []
  let event = '', impact = '', suggestion = ''

  if (changes.length > 0) {
    const msgs = changes.slice(0, 3).map(c => `${c.port} ${c.change || 'link 变化'}`)
    event = `链路状态变化：${msgs.join('；')}`
    const hasDown = changes.some(c => /down/i.test(c.change || ''))
    if (hasDown) {
      impact = T.link_status.impactDown
      suggestion = T.link_status.suggestionDown
    } else {
      impact = T.link_status.impact
      suggestion = T.link_status.suggestion
    }
  } else {
    event = alert.message || '链路状态变化'
    impact = T.link_status.fallbackImpact
    suggestion = T.link_status.fallbackSuggestion
  }
  return makeResult({ event, impact, suggestion, original: alert.message || '', log_path: details.log_path || '' })
}

// ============ memory_leak ============
function translateMemoryLeak(alert) {
  const details = alert.details || {}
  const process = details.process || ''
  const rssMb = details.current_rss_mb
  const growthRate = details.rss_growth_mb_per_hour
  const hours = details.duration_hours
  const pct = details.current_percent

  let event = ''
  if (rssMb != null) {
    event = `内存泄漏检测：${process ? process + ' ' : ''}当前 RSS ${rssMb} MB`
    if (growthRate != null) event += `，增长速率 ${growthRate} MB/h`
    if (hours != null) event += `，持续 ${hours} 小时`
  } else if (pct != null) {
    const thresh = details.threshold || '?'
    event = `内存使用率持续上升，当前 ${pct}%（阈值 ${thresh}%）`
  } else {
    event = alert.message || '内存泄漏检测告警'
  }

  return makeResult({
    event,
    impact: T.memory_leak.impact,
    suggestion: T.memory_leak.suggestion,
    original: alert.message || '',
  })
}

// ============ cpu_usage ============
function translateCpuUsage(alert) {
  const details = alert.details || {}
  // Support both field names: cpu_usage (from observer) and current_percent (legacy)
  const pct = details.cpu_usage ?? details.current_percent
  const thresh = details.threshold
  const isNormal = alert.level === 'info'
  const topProcs = details.top_processes || []

  if (isNormal) {
    return makeResult({
      event: pct != null ? `CPU 使用率恢复正常：${pct}%` : 'CPU 使用率正常',
      impact: T.cpu_usage.impactNormal,
      suggestion: T.cpu_usage.suggestionNormal,
      original: alert.message || '',
    })
  }

  let event = pct != null ? `CPU 使用率达到 ${pct}%` : 'CPU 使用率过高'
  if (thresh != null) event += `（阈值 ${thresh}%）`
  if (topProcs.length > 0) event += `，高占用：${topProcs.slice(0, 3).join('、')}`

  return makeResult({
    event,
    impact: T.cpu_usage.impact,
    suggestion: T.cpu_usage.suggestion,
    original: alert.message || '',
  })
}

// ============ card_recovery ============
function translateCardRecovery(alert) {
  const details = alert.details || {}
  const total = details.total_count || '?'
  const newCount = details.new_count || '?'
  const events = (details.recent_events || []).slice(0, 3)
  let evtDesc = ''
  if (events.length > 0) {
    evtDesc = events.map(e => `${e.slot || '?'} @ ${e.timestamp || '?'}`).join('；')
  }
  return makeResult({
    event: `卡修复事件：总计 ${total} 次，本次新增 ${newCount} 次${evtDesc ? '（' + evtDesc + '）' : ''}`,
    impact: T.card_recovery.impact,
    suggestion: T.card_recovery.suggestion,
    original: alert.message || '',
    log_path: details.log_path || '',
  })
}

// ============ port_fec ============
function translatePortFec(alert) {
  const details = alert.details || {}
  const changes = details.changes || []
  if (changes.length > 0) {
    const msgs = changes.slice(0, 3).map(c => `${c.port}: ${c.old_fec} → ${c.new_fec}`)
    return makeResult({
      event: `FEC 模式变化：${msgs.join('；')}`,
      impact: T.port_fec.impact,
      suggestion: T.port_fec.suggestion,
      parsed: { changes },
      original: alert.message || '',
    })
  }
  return makeResult({ event: alert.message || 'FEC 模式检查正常', impact: '', suggestion: '', original: alert.message || '' })
}

// ============ port_speed ============
function translatePortSpeed(alert) {
  const details = alert.details || {}
  const changes = details.changes || []
  if (changes.length > 0) {
    const msgs = changes.slice(0, 3).map(c => `${c.port}: ${c.old_speed} → ${c.new_speed}`)
    const hasDegrade = changes.some(c => {
      const oldNum = parseInt((c.old_speed || '0').replace(/[^0-9]/g, ''))
      const newNum = parseInt((c.new_speed || '0').replace(/[^0-9]/g, ''))
      return newNum < oldNum
    })
    return makeResult({
      event: `端口速率变化：${msgs.join('；')}`,
      impact: hasDegrade ? T.port_speed.impactDegrade : T.port_speed.impact,
      suggestion: hasDegrade ? T.port_speed.suggestionDegrade : T.port_speed.suggestion,
      parsed: { changes },
      original: alert.message || '',
    })
  }
  return makeResult({ event: alert.message || '端口速率检查正常', impact: '', suggestion: '', original: alert.message || '' })
}

// ============ pcie_bandwidth ============
function translatePcieBandwidth(alert) {
  const details = alert.details || {}
  const downgrades = details.downgrades || []
  if (downgrades.length > 0) {
    return makeResult({
      event: `PCIe 带宽降级：${downgrades.slice(0, 2).join('；')}`,
      impact: T.pcie_bandwidth.impact,
      suggestion: T.pcie_bandwidth.suggestion,
      parsed: { downgrades },
      original: alert.message || '',
    })
  }
  return makeResult({ event: alert.message || 'PCIe 带宽检查正常', impact: '', suggestion: '', original: alert.message || '' })
}

// ============ card_info ============
function translateCardInfo(alert) {
  const details = alert.details || {}
  const alerts = details.alerts || []
  const total = details.total_cards || '?'
  if (alerts.length > 0) {
    const msgs = alerts.slice(0, 3).map(a => {
      const bid = a.board_id ? ` [BoardId:${a.board_id}]` : ''
      const fieldSummary = formatCardInfoFields(a)
      return `${a.card || '?'} ${fieldSummary}${bid}`.trim()
    })
    return makeResult({
      event: `${total} 张卡检查，${alerts.length} 项异常：${msgs.join('；')}`,
      impact: T.card_info.impact,
      suggestion: T.card_info.suggestion,
      parsed: { alerts, total_cards: total },
      original: alert.message || '',
    })
  }
  return makeResult({ event: alert.message || `卡件信息正常 (${total} 张卡)`, impact: '', suggestion: '', original: alert.message || '' })
}

function formatCardInfoFields(alertItem) {
  const nestedFields = Array.isArray(alertItem?.fields) ? alertItem.fields : []
  if (nestedFields.length > 0) {
    return nestedFields
      .map(field => `${field?.field || '?'}=${field?.value ?? ''}`)
      .join(', ')
  }

  if (alertItem?.field) {
    return `${alertItem.field}=${alertItem.value ?? ''}`
  }

  return '字段异常'
}

// ============ cmd_response ============
function translateCmdResponse(alert) {
  const details = alert.details || {}
  return makeResult({
    event: alert.message || '命令响应超时',
    impact: T.cmd_response.impact,
    suggestion: T.cmd_response.suggestion,
    original: alert.message || '',
  })
}

// ============ sig_monitor ============
function translateSigMonitor(alert) {
  const details = alert.details || {}
  const signals = details.new_signals || []
  let desc = alert.message || '检测到异常信号'
  if (signals.length > 0) {
    desc = `检测到 ${signals.length} 个异常信号：` + signals.slice(0, 5).map(s => `sig ${s.signal_num} (${s.process || '?'})`).join('，')
  }
  return makeResult({
    event: desc,
    impact: T.sig_monitor.impact,
    suggestion: T.sig_monitor.suggestion,
    original: alert.message || '',
    log_path: details.log_path || '',
  })
}

// ============ sensitive_info ============
function translateSensitiveInfo(alert) {
  return makeResult({
    event: alert.message || '检测到敏感信息泄露',
    impact: T.sensitive_info.impact,
    suggestion: T.sensitive_info.suggestion,
    original: alert.message || '',
    log_path: alert.details?.log_path || '',
  })
}

// ============ 新增观察点翻译器 ============

function translateControllerState(alert) {
  const details = alert.details || {}
  const changes = details.changes || []
  let desc = alert.message || '控制器状态变化'
  if (changes.length > 0) {
    desc = changes.slice(0, 3).map(c => `控制器 ${c.id || '?'}: ${c.old_state || '?'} → ${c.new_state || '?'}`).join('；')
  }
  return makeResult({
    event: desc,
    impact: T.controller_state.impact,
    suggestion: T.controller_state.suggestion,
    original: alert.message || '',
  })
}

function translateDiskState(alert) {
  const details = alert.details || {}
  const changes = details.changes || []
  let desc = alert.message || '磁盘状态变化'
  if (changes.length > 0) {
    desc = changes.slice(0, 3).map(c => `磁盘 ${c.id || '?'}: ${c.old_state || '?'} → ${c.new_state || '?'}`).join('；')
  }
  return makeResult({
    event: desc,
    impact: T.disk_state.impact,
    suggestion: T.disk_state.suggestion,
    original: alert.message || '',
  })
}

function translateProcessCrash(alert) {
  const details = alert.details || {}
  const crashes = details.crashes || []
  let desc = alert.message || '检测到进程崩溃'
  if (crashes.length > 0) {
    desc = crashes.slice(0, 3).map(c => `${c.process || '?'}: ${c.signal || c.type || 'crash'}`).join('；')
  }
  return makeResult({
    event: desc,
    impact: T.process_crash.impact,
    suggestion: T.process_crash.suggestion,
    original: alert.message || '',
    log_path: details.log_path || '',
  })
}

function translateIoTimeout(alert) {
  const details = alert.details || {}
  const events = details.events || []
  let desc = alert.message || '检测到 IO 超时'
  if (events.length > 0) {
    desc = `检测到 ${events.length} 个 IO 超时事件：` + events.slice(0, 3).map(e => e.summary || e.line || '?').join('；')
  }
  return makeResult({
    event: desc,
    impact: T.io_timeout.impact,
    suggestion: T.io_timeout.suggestion,
    original: alert.message || '',
    log_path: details.log_path || '',
  })
}

// ============ default ============
function defaultTranslator(alert) {
  const msg = alert.message || ''
  return makeResult({
    event: msg.length > 100 ? msg.substring(0, 100) + '...' : msg,
    impact: '',
    suggestion: '',
    original: msg,
    log_path: alert.details?.log_path || '',
  })
}
