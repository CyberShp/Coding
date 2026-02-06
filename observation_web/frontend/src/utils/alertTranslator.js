/**
 * 告警消息可读性翻译工具
 *
 * 将各观察点的原始告警消息翻译为人类可读的中文摘要，
 * 同时保留结构化解析结果和原始文本，供详情面板使用。
 */

// 观察点中文名称映射
export const OBSERVER_NAMES = {
  error_code: '误码监测',
  link_status: '链路状态',
  card_recovery: '卡修复',
  alarm_type: '告警事件',
  memory_leak: '内存监测',
  cpu_usage: 'CPU 监测',
  cmd_response: '命令响应',
  sig_monitor: 'SIG 信号',
  sensitive_info: '敏感信息',
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
 * 翻译告警消息
 * @param {Object} alert - 告警对象 { observer_name, message, details, level, ... }
 * @returns {Object} { summary, parsed, original, events, log_path }
 */
export function translateAlert(alert) {
  if (!alert) return { summary: '', parsed: null, original: '', events: [], log_path: '' }

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
}

/**
 * alarm_type 翻译器（核心）
 *
 * alarm_type 仅有 0 和 1：
 * - type(0) = 历史告警上报，仅通知，不加入活跃告警，不会 resume
 * - type(1) = 事件生成（正常告警）
 *
 * 上报/恢复由 send alarm / resume alarm 关键字决定：
 * - send alarm = 告警上报
 * - resume alarm = 告警恢复
 */
function translateAlarmType(alert) {
  const { message, details } = alert
  const original = message || ''
  const log_path = details?.log_path || ''

  // 从 details 中提取事件
  const newSends = details?.new_send_alarms || []
  const newResumes = details?.new_resume_alarms || []
  const activeAlarms = details?.active_alarms || []
  const recentEvents = details?.recent_events || []

  // 收集所有可展示的事件
  const events = []
  for (const e of newSends) {
    events.push(normalizeEvent(e, 'send'))
  }
  for (const e of newResumes) {
    events.push(normalizeEvent(e, 'resume'))
  }

  // 生成可读摘要
  let summary = ''
  const parts = []

  if (newSends.length > 0) {
    // 区分历史上报和正常上报
    const historySends = newSends.filter(e => e.alarm_type === 0 || e.is_history_report)
    const normalSends = newSends.filter(e => e.alarm_type !== 0 && !e.is_history_report)

    if (normalSends.length === 1) {
      const e = normalSends[0]
      parts.push(`告警上报：${e.alarm_name || '未知'} (${e.alarm_id || '?'})`)
    } else if (normalSends.length > 1) {
      parts.push(`新上报 ${normalSends.length} 条告警`)
    }

    if (historySends.length === 1) {
      const e = historySends[0]
      parts.push(`[历史] ${e.alarm_name || '未知'} (${e.alarm_id || '?'}) 历史告警上报`)
    } else if (historySends.length > 1) {
      parts.push(`${historySends.length} 条历史告警上报`)
    }
  }

  if (newResumes.length === 1) {
    const e = newResumes[0]
    parts.push(`告警恢复：${e.alarm_name || '未知'} (${e.alarm_id || '?'}) 已消除`)
  } else if (newResumes.length > 1) {
    parts.push(`${newResumes.length} 条告警已恢复`)
  }

  summary = parts.join(' | ')

  if (activeAlarms.length > 0) {
    summary += summary ? ` | 当前 ${activeAlarms.length} 个活跃告警` : `当前 ${activeAlarms.length} 个活跃告警`
  }

  // 如果 details 不可用，从 message 文本回退解析
  if (!summary) {
    summary = fallbackParseAlarmMessage(original)
  }

  // 构造首个事件的 parsed 信息
  const firstEvent = newSends[0] || newResumes[0] || recentEvents[0] || null
  const parsed = firstEvent ? {
    alarm_type: firstEvent.alarm_type,
    alarm_name: firstEvent.alarm_name,
    alarm_id: firstEvent.alarm_id,
    is_send: firstEvent.is_send ?? false,
    is_resume: firstEvent.is_resume ?? false,
    is_history: firstEvent.alarm_type === 0 || firstEvent.is_history_report === true,
    recovered: firstEvent.recovered ?? false,
  } : parseAlarmFromText(original)

  return { summary, parsed, original, events, log_path }
}

/**
 * 标准化事件对象
 */
function normalizeEvent(e, action) {
  return {
    alarm_type: e.alarm_type,
    alarm_name: e.alarm_name || '未知',
    alarm_id: e.alarm_id || '?',
    timestamp: e.timestamp || '',
    is_send: action === 'send',
    is_resume: action === 'resume',
    is_history: e.alarm_type === 0 || e.is_history_report === true,
    recovered: e.recovered ?? (action === 'resume'),
    line: e.line || '',
  }
}

/**
 * 从 message 文本回退解析 alarm 信息
 */
function parseAlarmFromText(text) {
  if (!text) return null
  const typeMatch = text.match(/alarm\s*type\s*\((\d+)\)/i)
  const nameMatch = text.match(/alarm\s*name\s*\(([^)]+)\)/i)
  const idMatch = text.match(/alarm\s*id\s*\(([^)]+)\)/i)
  const isSend = /send\s+alarm/i.test(text)
  const isResume = /resume\s+alarm/i.test(text)

  if (!typeMatch && !nameMatch) return null

  const alarmType = typeMatch ? parseInt(typeMatch[1]) : null
  return {
    alarm_type: alarmType,
    alarm_name: nameMatch ? nameMatch[1].trim() : '未知',
    alarm_id: idMatch ? idMatch[1].trim() : null,
    is_send: isSend,
    is_resume: isResume,
    is_history: alarmType === 0,
    recovered: isResume,
  }
}

/**
 * 从 message 回退生成可读摘要
 */
function fallbackParseAlarmMessage(text) {
  if (!text) return '告警事件'

  // 尝试从聚合消息中提取
  const sendMatch = text.match(/新上报\s*(\d+)\s*条/)
  const resumeMatch = text.match(/恢复\s*(\d+)\s*条/)
  const activeMatch = text.match(/当前活跃\s*(\d+)\s*个/)

  if (sendMatch || resumeMatch) {
    const parts = []
    if (sendMatch) parts.push(`新上报 ${sendMatch[1]} 条告警`)
    if (resumeMatch) parts.push(`${resumeMatch[1]} 条告警已恢复`)
    if (activeMatch) parts.push(`当前 ${activeMatch[1]} 个活跃`)
    return parts.join(' | ')
  }

  // 尝试从单条告警格式解析
  const parsed = parseAlarmFromText(text)
  if (parsed) {
    const name = parsed.alarm_name
    const id = parsed.alarm_id ? ` (${parsed.alarm_id})` : ''
    if (parsed.is_history) return `[历史] ${name}${id} 历史告警上报`
    if (parsed.is_resume) return `告警恢复：${name}${id} 已消除`
    if (parsed.is_send) return `告警上报：${name}${id}`
    return `告警事件：${name}${id}`
  }

  // 兜底：截断过长消息
  return text.length > 80 ? text.substring(0, 80) + '...' : text
}

// ============ 其他观察点翻译器（保持原有可读性，微调格式）============

function translateErrorCode(alert) {
  return {
    summary: alert.message || '误码监测事件',
    parsed: null,
    original: alert.message || '',
    events: [],
    log_path: alert.details?.log_path || '',
  }
}

function translateLinkStatus(alert) {
  return {
    summary: alert.message || '链路状态变化',
    parsed: null,
    original: alert.message || '',
    events: [],
    log_path: alert.details?.log_path || '',
  }
}

function translateMemoryLeak(alert) {
  return {
    summary: alert.message || '内存监测事件',
    parsed: null,
    original: alert.message || '',
    events: [],
    log_path: alert.details?.log_path || '',
  }
}

function translateCpuUsage(alert) {
  return {
    summary: alert.message || 'CPU 监测事件',
    parsed: null,
    original: alert.message || '',
    events: [],
    log_path: alert.details?.log_path || '',
  }
}

function translateCardRecovery(alert) {
  return {
    summary: alert.message || '卡修复事件',
    parsed: null,
    original: alert.message || '',
    events: [],
    log_path: alert.details?.log_path || '',
  }
}

function defaultTranslator(alert) {
  const msg = alert.message || ''
  return {
    summary: msg.length > 100 ? msg.substring(0, 100) + '...' : msg,
    parsed: null,
    original: msg,
    events: [],
    log_path: alert.details?.log_path || '',
  }
}
