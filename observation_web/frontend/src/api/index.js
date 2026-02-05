import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// Request interceptor
http.interceptors.request.use(
  config => {
    // Add auth token if needed
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

// Response interceptor
http.interceptors.response.use(
  response => response,
  error => {
    console.error('API Error:', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

export default {
  // Arrays
  getArrays: () => http.get('/arrays'),
  getArrayStatuses: () => http.get('/arrays/statuses'),
  getArray: (id) => http.get(`/arrays/${id}`),
  createArray: (data) => http.post('/arrays', data),
  updateArray: (id, data) => http.put(`/arrays/${id}`, data),
  deleteArray: (id) => http.delete(`/arrays/${id}`),
  getArrayStatus: (id) => http.get(`/arrays/${id}/status`),
  connectArray: (id, password) => http.post(`/arrays/${id}/connect`, null, { params: { password } }),
  disconnectArray: (id) => http.post(`/arrays/${id}/disconnect`),
  refreshArray: (id) => http.post(`/arrays/${id}/refresh`),
  deployAgent: (id) => http.post(`/arrays/${id}/deploy-agent`),
  startAgent: (id) => http.post(`/arrays/${id}/start-agent`),
  stopAgent: (id) => http.post(`/arrays/${id}/stop-agent`),
  restartAgent: (id) => http.post(`/arrays/${id}/restart-agent`),

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
}
