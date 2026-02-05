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

  // Alerts
  getAlerts: (params) => http.get('/alerts', { params }),
  getRecentAlerts: (limit = 20) => http.get('/alerts/recent', { params: { limit } }),
  getAlertStats: (hours = 24) => http.get('/alerts/stats', { params: { hours } }),
  getAlertSummary: () => http.get('/alerts/summary'),

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
}
