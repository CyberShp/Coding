/**
 * 告警消息可读性翻译工具 v2
 *
 * 每条告警翻译为三段式结构：事件 → 影响 → 建议
 * 同时保留结构化解析结果和原始文本，供详情面板使用。
 */

// 观察点中文名称映射
export const OBSERVER_NAMES = {
  // 端口级
  error_code: '误码监测',
  link_status: '链路状态',
  port_fec: 'FEC 模式',
  port_speed: '端口速率',
  port_traffic: '端口流量',
  // 卡件级
  card_recovery: '卡修复',
  card_info: '卡件信息',
  pcie_bandwidth: 'PCIe 带宽',
  // 系统级
  alarm_type: '告警事件',
  memory_leak: '内存监测',
  cpu_usage: 'CPU 监测',
  cmd_response: '命令响应',
  sig_monitor: 'SIG 信号',
  sensitive_info: '敏感信息',
  // 新增观察点
  controller_state: '控制器状态',
  disk_state: '磁盘状态',
  process_crash: '进程崩溃',
  io_timeout: 'IO 超时',
}

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

  impact = activeAlarms.length > 0 ? `${activeAlarms.length} 个活跃告警未恢复，可能影响业务` : '请关注告警内容'
  suggestion = '检查阵列告警日志，确认是否需要人工介入处理'

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
    impact = '端口传输质量下降，可能导致 IO 错误或性能波动'
    suggestion = '检查光模块、线缆质量和对端设备状态'
  } else {
    event = alert.message || '误码监测事件'
    impact = '端口可能存在传输异常'
    suggestion = '检查端口物理连接'
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
      impact = '端口业务中断，依赖该端口的 IO 将受到影响'
      suggestion = '检查线缆连接，确认是否为计划操作（拔线/下电测试）'
    } else {
      impact = '端口状态发生变化，业务可能短暂波动'
      suggestion = '观察业务是否恢复正常'
    }
  } else {
    event = alert.message || '链路状态变化'
    impact = '端口状态变化可能影响业务'
    suggestion = '检查端口物理连接'
  }
  return makeResult({ event, impact, suggestion, original: alert.message || '', log_path: details.log_path || '' })
}

// ============ memory_leak ============
function translateMemoryLeak(alert) {
  const details = alert.details || {}
  const pct = details.current_percent || '?'
  const thresh = details.threshold || '?'
  return makeResult({
    event: `内存使用率持续上升，当前 ${pct}%（阈值 ${thresh}%）`,
    impact: '系统可用内存减少，可能导致 OOM 或进程被杀',
    suggestion: '检查是否有内存泄漏进程，使用 top/htop 排查',
    original: alert.message || '',
  })
}

// ============ cpu_usage ============
function translateCpuUsage(alert) {
  const details = alert.details || {}
  const pct = details.current_percent || '?'
  const thresh = details.threshold || '?'
  const isNormal = alert.level === 'info'
  if (isNormal) {
    return makeResult({
      event: `CPU 使用率正常：${pct}%`,
      impact: '系统运行正常',
      suggestion: '',
      original: alert.message || '',
    })
  }
  return makeResult({
    event: `CPU0 使用率达到 ${pct}%（阈值 ${thresh}%）`,
    impact: '系统响应变慢，IO 延迟可能增大',
    suggestion: '使用 top 检查高占用进程，确认是否为测试预期',
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
    impact: '卡件发生过错误并自动修复，频繁修复可能预示硬件问题',
    suggestion: '关注修复频率，若持续增长需排查硬件健康',
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
      impact: 'FEC 模式变化可能影响纠错能力和传输可靠性',
      suggestion: '确认是否为配置变更或对端设备协商导致',
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
      impact: hasDegrade ? '端口降速，业务带宽减半或更低，IO 性能下降' : '端口速率发生变化',
      suggestion: hasDegrade ? '检查线缆/光模块质量，或确认是否为对端协商降速' : '确认速率变化是否符合预期',
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
      impact: 'PCIe 通道宽度或速率下降，设备 IO 性能受限',
      suggestion: '检查卡件是否插紧、slot 是否有硬件问题，或重启后观察',
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
      return `${a.card} ${a.field}=${a.value}${bid}`
    })
    return makeResult({
      event: `${total} 张卡检查，${alerts.length} 项异常：${msgs.join('；')}`,
      impact: '卡件状态异常，可能导致关联端口和业务不可用',
      suggestion: '检查卡件是否被下电、是否需要更换',
      parsed: { alerts, total_cards: total },
      original: alert.message || '',
    })
  }
  return makeResult({ event: alert.message || `卡件信息正常 (${total} 张卡)`, impact: '', suggestion: '', original: alert.message || '' })
}

// ============ cmd_response ============
function translateCmdResponse(alert) {
  const details = alert.details || {}
  return makeResult({
    event: alert.message || '命令响应超时',
    impact: '阵列命令处理延迟增大，可能系统负载过高或服务异常',
    suggestion: '检查阵列系统负载和服务进程状态',
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
    impact: '进程收到非预期信号，可能发生异常退出或 coredump',
    suggestion: '检查 /var/log/messages 和 coredump 文件，确认进程状态',
    original: alert.message || '',
    log_path: details.log_path || '',
  })
}

// ============ sensitive_info ============
function translateSensitiveInfo(alert) {
  return makeResult({
    event: alert.message || '检测到敏感信息泄露',
    impact: '日志中包含密码、密钥等敏感内容，可能造成安全风险',
    suggestion: '检查日志来源，修复相关代码或配置的敏感信息输出',
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
    impact: '控制器状态变化可能导致存储服务中断或降级',
    suggestion: '检查控制器状态，确认是否为升级/下电测试的预期行为',
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
    impact: '磁盘状态变化可能导致数据冗余降低或 RAID 降级',
    suggestion: '检查磁盘健康，若为离线/故障状态需尽快更换',
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
    impact: '关键进程崩溃可能导致服务中断，需要立即关注',
    suggestion: '检查 coredump 文件和系统日志，必要时重启服务',
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
    impact: 'IO 超时意味着存储访问中断，业务可能挂起',
    suggestion: '检查磁盘、控制器状态和链路连通性',
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
