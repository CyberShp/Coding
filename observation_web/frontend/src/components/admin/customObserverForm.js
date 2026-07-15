const DEFAULT_FORM = {
  name: '',
  description: '',
  category: 'custom',
  command: '',
  command_type: 'shell',
  interval: 60,
  timeout: 30,
  strategy: 'lines',
  strategy_config: { pattern: '', mode: 'count' },
  match_condition: 'found',
  match_threshold: '',
  alert_level: 'warning',
  alert_message_template: '{value}',
  cooldown: 300,
  consecutive_threshold: 1,
  visibility: 'team',
  team_scope: '',
  is_enabled: true,
}
const V2_STRATEGIES = new Set(['pipe', 'kv', 'json', 'table', 'lines', 'diff', 'exit_code'])

function normalizeStrategy(source) {
  if (!source.strategy && !source.match_type && !source.match_expression && !source.strategy_config) {
    return { strategy: DEFAULT_FORM.strategy, config: { ...DEFAULT_FORM.strategy_config } }
  }
  const strategy = source.strategy || source.match_type || DEFAULT_FORM.strategy
  if (source.strategy_config && typeof source.strategy_config === 'object') {
    return { strategy, config: source.strategy_config }
  }
  if (V2_STRATEGIES.has(strategy)) {
    try {
      const config = JSON.parse(source.match_expression || '{}')
      return { strategy, config: config && typeof config === 'object' ? config : {} }
    } catch {
      return { strategy, config: {} }
    }
  }
  const expression = source.match_expression || ''
  if (strategy === 'regex') return { strategy: 'lines', config: { pattern: expression || '.', mode: 'first' } }
  if (strategy === 'jsonpath') return { strategy: 'json', config: { path: expression } }
  if (strategy === 'contains') return { strategy: 'lines', config: { pattern: expression, mode: 'count' } }
  return { strategy: 'lines', config: { pattern: expression || '.', mode: 'first' } }
}

export function createObserverForm(source = {}) {
  const normalized = normalizeStrategy(source)
  return {
    ...DEFAULT_FORM,
    ...source,
    strategy: normalized.strategy,
    strategy_config: normalized.config,
    match_threshold: source.match_threshold ?? '',
    is_enabled: source.is_enabled !== false,
  }
}

export function generatedTemplateToForm(template, description = '') {
  return createObserverForm({
    ...template,
    description: template.description || description,
  })
}

export function formToTemplatePayload(form) {
  return {
    name: form.name.trim(),
    description: form.description || '',
    category: form.category || 'custom',
    command: form.command.trim(),
    command_type: form.command_type || 'shell',
    interval: Number(form.interval) || 60,
    timeout: Number(form.timeout) || 30,
    match_type: form.strategy || 'lines',
    match_expression: JSON.stringify(form.strategy_config || {}),
    match_condition: form.match_condition || 'found',
    match_threshold: form.match_threshold === '' ? null : String(form.match_threshold),
    alert_level: form.alert_level || 'warning',
    alert_message_template: form.alert_message_template || '',
    cooldown: Number(form.cooldown) || 0,
    consecutive_threshold: Number(form.consecutive_threshold) || 1,
    visibility: form.visibility || 'team',
    team_scope: form.team_scope || '',
    is_enabled: form.is_enabled !== false,
  }
}

const DEPLOYMENT_STATES = {
  active: { label: '已加载', type: 'success' },
  removed: { label: '已移除', type: 'success' },
  degraded: { label: '未确认', type: 'warning' },
  failed: { label: '失败', type: 'danger' },
  deploying: { label: '下发中', type: 'primary' },
  pending: { label: '待下发', type: 'info' },
}

export function deploymentState(item) {
  return DEPLOYMENT_STATES[item?.status] || DEPLOYMENT_STATES.pending
}
