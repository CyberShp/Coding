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

// Request interceptor
http.interceptors.request.use(
  config => {
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
  getArrays: () => http.get('/arrays'),
  getArrayStatuses: () => http.get('/arrays/statuses'),
  getArray: (id) => http.get(`/arrays/${id}`),
  createArray: (data) => http.post('/arrays', data),
  updateArray: (id, data) => http.put(`/arrays/${id}`, data),
  deleteArray: (id) => http.delete(`/arrays/${id}`),
  getArrayStatus: (id) => http.get(`/arrays/${id}/status`),
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
  updateAgentConfig: (id, config, restartAgent = false) => http.put(`/arrays/${id}/agent-config`, { ...config, restart_agent: restartAgent }),
  restoreAgentConfig: (id) => http.post(`/arrays/${id}/agent-config/restore`),
  // Metrics
  getArrayMetrics: (id, minutes = 60) => http.get(`/arrays/${id}/metrics`, { params: { minutes } }),

  // Port Traffic
  getTrafficPorts: (arrayId) => http.get(`/traffic/${arrayId}/ports`),
  getTrafficData: (arrayId, port, minutes = 30) => http.get(`/traffic/${arrayId}/data`, { params: { port, minutes } }),
  syncTraffic: (arrayId) => httpLong.post(`/traffic/${arrayId}/sync`),

  // Alerts
  getAlerts: (params) => http.get('/alerts', { params }),
  getRecentAlerts: (limit = 20) => http.get('/alerts/recent', { params: { limit } }),
  getAlertStats: (hours = 24) => http.get('/alerts/stats', { params: { hours } }),
  getAlertSummary: () => http.get('/alerts/summary'),
  getAggregatedAlerts: (params) => http.get('/alerts/aggregated', { params }),
  exportAlerts: (params) => http.get('/alerts/export', { params, responseType: 'blob' }),

  // Test Tasks
  getTestTasks: (params) => http.get('/test-tasks', { params }),
  createTestTask: (data) => http.post('/test-tasks', data),
  getTestTask: (id) => http.get(`/test-tasks/${id}`),
  startTestTask: (id) => http.post(`/test-tasks/${id}/start`),
  stopTestTask: (id) => http.post(`/test-tasks/${id}/stop`),
  deleteTestTask: (id) => http.delete(`/test-tasks/${id}`),
  getTestTaskSummary: (id) => http.get(`/test-tasks/${id}/summary`),

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
}
