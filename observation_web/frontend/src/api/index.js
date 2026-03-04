import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  timeout: 15000,  // 15s default timeout
})

// Create a separate instance for long operations
const httpLong = axios.create({
  baseURL: '/api',
  timeout: 60000,  // 60s for long operations
})

// Request interceptor - add auth token when present
http.interceptors.request.use(
  config => {
    const token = localStorage.getItem('admin_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

httpLong.interceptors.request.use(
  config => {
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

// Response interceptor with better error handling
const handleError = (error) => {
  if (error.code === 'ECONNABORTED') {
    console.error('API Timeout:', error.config?.url)
    error.message = '请求超时，请重试'
  } else if (error.code === 'ERR_NETWORK') {
    console.error('Network Error:', error.config?.url)
    error.message = '网络错误，请检查连接'
  } else {
    console.error('API Error:', error.response?.data || error.message)
  }
  return Promise.reject(error)
}

http.interceptors.response.use(response => response, handleError)
httpLong.interceptors.response.use(response => response, handleError)

export default {
  // Arrays
  getArrays: (tagId = null) => http.get('/arrays', { params: tagId ? { tag_id: tagId } : {} }),
  getArrayStatuses: (tagId = null) => http.get('/arrays/statuses', { params: tagId ? { tag_id: tagId } : {} }),
  getArray: (id) => http.get(`/arrays/${id}`),
  createArray: (data) => http.post('/arrays', data),
  updateArray: (id, data) => http.put(`/arrays/${id}`, data),
  deleteArray: (id) => http.delete(`/arrays/${id}`),
  getArrayStatus: (id) => http.get(`/arrays/${id}/status`),
  searchArrays: (ip) => http.get('/arrays/search', { params: { ip } }),

  // Tags
  getTags: () => http.get('/tags'),
  createTag: (data) => http.post('/tags', data),
  getTag: (id) => http.get(`/tags/${id}`),
  updateTag: (id, data) => http.put(`/tags/${id}`, data),
  deleteTag: (id) => http.delete(`/tags/${id}`),
  getTagArrays: (id, searchIp = null) => http.get(`/tags/${id}/arrays`, { params: searchIp ? { search_ip: searchIp } : {} }),
  migrateFoldersToTags: () => http.post('/tags/migrate-folders'),

  // Auth (admin)
  login: (username, password) => http.post('/auth/login', { username, password }),
  getAuthMe: () => http.get('/auth/me'),
  logout: () => http.post('/auth/logout'),

  // Issues (feedback)
  getIssues: (status = null) => http.get('/issues', { params: status ? { status_filter: status } : {} }),
  createIssue: (data) => http.post('/issues', data),
  getIssue: (id) => http.get(`/issues/${id}`),
  updateIssueStatus: (id, status, resolutionNote = '') =>
    http.put(`/issues/${id}/status`, { status, resolution_note: resolutionNote }),

  // Users
  getOnlineUsers: () => http.get('/users/online'),
  getCurrentUser: () => http.get('/users/me'),
  setNickname: (nickname) => http.post('/users/me/nickname', { nickname }),
  claimNickname: (nickname) => http.post('/users/claim', { nickname }),
  getUserCount: () => http.get('/users/count'),
  // Long operations use httpLong with 60s timeout
  connectArray: (id, password) => httpLong.post(`/arrays/${id}/connect`, null, { params: { password } }),
  disconnectArray: (id) => http.post(`/arrays/${id}/disconnect`),
  refreshArray: (id) => httpLong.post(`/arrays/${id}/refresh`),
  deployAgent: (id) => httpLong.post(`/arrays/${id}/deploy-agent`),
  startAgent: (id) => httpLong.post(`/arrays/${id}/start-agent`),
  stopAgent: (id) => httpLong.post(`/arrays/${id}/stop-agent`),
  restartAgent: (id) => httpLong.post(`/arrays/${id}/restart-agent`),
  // Log Viewer
  getArrayLogs: (id, params) => http.get(`/arrays/${id}/logs`, { params }),
  listLogFiles: (id, directory = '/var/log') => http.get(`/arrays/${id}/log-files`, { params: { directory } }),
  // Batch Operations
  batchAction: (action, arrayIds, password = null) => httpLong.post(`/arrays/batch/${action}`, { array_ids: arrayIds, password }),
  // Agent Config
  getAgentConfig: (id) => http.get(`/arrays/${id}/agent-config`),
  updateAgentConfig: (id, config, restartAgent = false, configHash = null) =>
    httpLong.put(`/arrays/${id}/agent-config`, {
      ...config,
      restart_agent: restartAgent,
      config_hash: configHash,
    }),
  restoreAgentConfig: (id) => http.post(`/arrays/${id}/agent-config/restore`),
  // Metrics
  getArrayMetrics: (id, minutes = 60) => http.get(`/arrays/${id}/metrics`, { params: { minutes } }),

  // Port Traffic
  getTrafficPorts: (arrayId) => http.get(`/traffic/${arrayId}/ports`),
  getTrafficData: (arrayId, port, minutes = 30) => http.get(`/traffic/${arrayId}/data`, { params: { port, minutes } }),
  syncTraffic: (arrayId) => httpLong.post(`/traffic/${arrayId}/sync`),
  getTrafficDiagnostic: (arrayId) => http.get(`/traffic/${arrayId}/diagnostic`),
  getTrafficModeInfo: (arrayId) => http.get(`/traffic/${arrayId}/mode-info`),

  // Alerts
  getAlerts: (params) => http.get('/alerts', { params }),
  getRecentAlerts: (limit = 20) => http.get('/alerts/recent', { params: { limit } }),
  getAlertStats: (hours = 24) => http.get('/alerts/stats', { params: { hours } }),
  getAlertSummary: (hours = 2) => http.get('/alerts/summary', { params: { hours } }),
  getAggregatedAlerts: (params) => http.get('/alerts/aggregated', { params }),
  exportAlerts: (params) => http.get('/alerts/export', { params, responseType: 'blob' }),

  // Alert Acknowledgement
  ackAlerts: (alertIds, comment = '', opts = {}) => http.post('/alerts/ack', {
    alert_ids: alertIds,
    comment,
    ack_type: opts.ack_type || 'dismiss',
    ...(opts.expires_hours ? { expires_hours: opts.expires_hours } : {}),
  }),
  ackAllVisible: (hours = 2, ackType = 'dismiss') =>
    http.post('/alerts/ack-all-visible', null, { params: { hours, ack_type: ackType } }),
  unackAlert: (alertId) => http.delete(`/alerts/ack/${alertId}`),
  getAlertAckDetails: (alertId) => http.get(`/alerts/${alertId}/ack`),

  // Test Tasks
  getTestTasks: (params) => http.get('/test-tasks', { params }),
  createTestTask: (data) => http.post('/test-tasks', data),
  getTestTask: (id) => http.get(`/test-tasks/${id}`),
  startTestTask: (id) => http.post(`/test-tasks/${id}/start`),
  stopTestTask: (id) => http.post(`/test-tasks/${id}/stop`),
  deleteTestTask: (id) => http.delete(`/test-tasks/${id}`),
  getTestTaskSummary: (id) => http.get(`/test-tasks/${id}/summary`),

  // Test Task Locks
  getAllLocks: () => http.get('/test-tasks/locks/all'),
  checkLocks: (arrayIds) => http.get('/test-tasks/locks/check', { params: { array_ids: arrayIds.join(',') } }),
  getArrayLock: (arrayId) => http.get(`/test-tasks/locks/array/${arrayId}`),
  forceUnlock: (arrayId) => http.delete(`/test-tasks/locks/force/${arrayId}`),

  // Alert Expectation Rules
  getAlertRules: () => http.get('/alert-rules'),
  createAlertRule: (data) => http.post('/alert-rules', data),
  getAlertRule: (id) => http.get(`/alert-rules/${id}`),
  updateAlertRule: (id, data) => http.put(`/alert-rules/${id}`, data),
  deleteAlertRule: (id) => http.delete(`/alert-rules/${id}`),
  toggleAlertRule: (id) => http.post(`/alert-rules/${id}/toggle`),
  initBuiltinRules: () => http.post('/alert-rules/init-builtin'),
  resetBuiltinRules: () => http.post('/alert-rules/reset-builtin'),

  // Snapshots
  createSnapshot: (arrayId) => httpLong.post(`/snapshots/${arrayId}`),
  getSnapshots: (arrayId) => http.get(`/snapshots/${arrayId}`),
  diffSnapshots: (id1, id2) => httpLong.get(`/snapshots/diff`, { params: { id1, id2 } }),

  // Timeline
  getTimeline: (arrayId, params) => http.get(`/timeline/${arrayId}`, { params }),

  // Query
  executeQuery: (task) => http.post('/query/execute', task),
  testPattern: (data) => http.post('/query/test-pattern', data),
  validatePattern: (pattern) => http.post('/query/validate-pattern', { pattern }),
  getQueryTemplates: () => http.get('/query/templates'),
  createQueryTemplate: (data) => http.post('/query/templates', data),
  deleteQueryTemplate: (id) => http.delete(`/query/templates/${id}`),

  // System Alerts
  getSystemAlerts: (params) => http.get('/system-alerts', { params }),
  getSystemAlertStats: () => http.get('/system-alerts/stats'),
  clearSystemAlerts: () => http.delete('/system-alerts'),
  getSystemDebugInfo: () => http.get('/system-alerts/debug'),

  // Data Lifecycle
  getSyncState: (arrayId) => http.get(`/data/sync-state/${arrayId}`),
  getLogFiles: (arrayId) => http.get(`/data/log-files/${arrayId}`),
  importHistory: (arrayId, data) => httpLong.post(`/data/import/${arrayId}`, data),
  getArchiveConfig: () => http.get('/data/archive/config'),
  updateArchiveConfig: (config) => http.put('/data/archive/config', config),
  runArchive: () => httpLong.post('/data/archive/run'),
  getArchiveStats: () => http.get('/data/archive/stats'),
  queryArchive: (params) => http.get('/data/archive/query', { params }),

  // Scheduled Tasks
  getTasks: (enabledOnly = false) => http.get('/tasks', { params: { enabled_only: enabledOnly } }),
  createTask: (data) => http.post('/tasks', data),
  getTask: (id) => http.get(`/tasks/${id}`),
  updateTask: (id, data) => http.put(`/tasks/${id}`, data),
  deleteTask: (id) => http.delete(`/tasks/${id}`),
  runTask: (id) => httpLong.post(`/tasks/${id}/run`),
  getTaskResults: (id, limit = 20) => http.get(`/tasks/${id}/results`, { params: { limit } }),
  getRecentTaskResults: (limit = 50) => http.get('/tasks/results/recent', { params: { limit } }),

  // Audit Logs
  getAuditLogs: (params) => http.get('/audit', { params }),
  getAuditStats: () => http.get('/audit/stats'),
  cleanupAuditLogs: (retentionDays = 30) => http.delete('/audit/cleanup', { params: { retention_days: retentionDays } }),
}
