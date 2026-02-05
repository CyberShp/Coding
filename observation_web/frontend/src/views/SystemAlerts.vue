<template>
  <div class="system-alerts">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>系统告警</span>
          <div class="filter-actions">
            <el-select v-model="filters.level" placeholder="告警级别" clearable style="width: 120px">
              <el-option label="调试" value="debug" />
              <el-option label="信息" value="info" />
              <el-option label="警告" value="warning" />
              <el-option label="错误" value="error" />
              <el-option label="严重" value="critical" />
            </el-select>
            <el-input 
              v-model="filters.module" 
              placeholder="模块名称" 
              clearable 
              style="width: 160px"
            />
            <el-button type="primary" @click="loadAlerts">
              <el-icon><Search /></el-icon>
              查询
            </el-button>
            <el-button type="danger" @click="clearAlerts">
              <el-icon><Delete /></el-icon>
              清空
            </el-button>
          </div>
        </div>
      </template>

      <!-- Stats -->
      <el-row :gutter="20" class="stats-row">
        <el-col :span="4">
          <div class="stat-item">
            <div class="stat-value">{{ stats?.total || 0 }}</div>
            <div class="stat-label">总数</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="stat-item">
            <div class="stat-value critical-text">{{ stats?.critical || 0 }}</div>
            <div class="stat-label">严重</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="stat-item">
            <div class="stat-value error-text">{{ stats?.error || 0 }}</div>
            <div class="stat-label">错误</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="stat-item">
            <div class="stat-value warning-text">{{ stats?.warning || 0 }}</div>
            <div class="stat-label">警告</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="stat-item">
            <div class="stat-value info-text">{{ stats?.info || 0 }}</div>
            <div class="stat-label">信息</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="stat-item">
            <div class="stat-value debug-text">{{ stats?.debug || 0 }}</div>
            <div class="stat-label">调试</div>
          </div>
        </el-col>
      </el-row>

      <!-- Alert Table -->
      <el-table :data="alerts" v-loading="loading" stripe>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="alert-detail">
              <p><strong>详细信息:</strong></p>
              <pre>{{ JSON.stringify(row.details, null, 2) }}</pre>
              <template v-if="row.traceback">
                <p><strong>堆栈跟踪:</strong></p>
                <pre class="traceback">{{ row.traceback }}</pre>
              </template>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.timestamp) }}
          </template>
        </el-table-column>
        <el-table-column label="级别" width="80">
          <template #default="{ row }">
            <el-tag :type="getLevelType(row.level)" size="small">
              {{ getLevelText(row.level) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="模块" width="150" prop="module" />
        <el-table-column label="消息" prop="message" show-overflow-tooltip />
      </el-table>

      <div class="alert-hint">
        <el-alert
          title="系统告警说明"
          type="info"
          :closable="false"
          show-icon
        >
          系统告警记录后端运行时的错误和警告信息，用于问题诊断和调试。
          告警存储在内存中，最多保留 500 条记录，服务重启后会清空。
        </el-alert>
      </div>
    </el-card>

    <!-- Debug Info Card -->
    <el-card class="debug-card">
      <template #header>
        <div class="card-header">
          <span>系统调试信息</span>
          <el-button type="primary" size="small" @click="loadDebugInfo">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <div v-loading="debugLoading">
        <el-collapse v-if="debugInfo">
          <el-collapse-item title="SSH 连接状态" name="ssh">
            <el-table :data="sshConnections" size="small" stripe>
              <el-table-column prop="array_id" label="阵列 ID" width="150" />
              <el-table-column prop="host" label="主机" width="150" />
              <el-table-column prop="state" label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="row.state === 'connected' ? 'success' : 'danger'" size="small">
                    {{ row.state }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="last_error" label="最后错误" show-overflow-tooltip />
            </el-table>
            <p v-if="!sshConnections.length" class="empty-text">暂无 SSH 连接</p>
          </el-collapse-item>

          <el-collapse-item title="阵列状态缓存" name="cache">
            <el-table :data="statusCache" size="small" stripe>
              <el-table-column prop="array_id" label="阵列 ID" width="150" />
              <el-table-column prop="name" label="名称" width="120" />
              <el-table-column prop="state" label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="row.state === 'connected' ? 'success' : 'info'" size="small">
                    {{ row.state }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="agent_running" label="Agent" width="80">
                <template #default="{ row }">
                  <el-tag :type="row.agent_running ? 'success' : 'info'" size="small">
                    {{ row.agent_running ? '运行中' : '未运行' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="last_refresh" label="最后刷新" width="180" />
            </el-table>
            <p v-if="!statusCache.length" class="empty-text">暂无状态缓存</p>
          </el-collapse-item>

          <el-collapse-item title="系统信息" name="system">
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="Python 版本">{{ debugInfo.system_info?.python_version?.split(' ')[0] }}</el-descriptions-item>
              <el-descriptions-item label="平台">{{ debugInfo.system_info?.platform }}</el-descriptions-item>
              <el-descriptions-item label="当前时间">{{ debugInfo.system_info?.current_time }}</el-descriptions-item>
              <el-descriptions-item label="告警统计">
                错误: {{ debugInfo.alert_stats?.error || 0 }}, 
                警告: {{ debugInfo.alert_stats?.warning || 0 }}
              </el-descriptions-item>
            </el-descriptions>
          </el-collapse-item>
        </el-collapse>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Search, Delete, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'

const loading = ref(false)
const alerts = ref([])
const stats = ref(null)
const filters = ref({
  level: '',
  module: '',
})

// Debug info
const debugLoading = ref(false)
const debugInfo = ref(null)

const sshConnections = computed(() => {
  if (!debugInfo.value?.ssh_connections) return []
  return Object.entries(debugInfo.value.ssh_connections).map(([id, info]) => ({
    array_id: id,
    ...info,
  }))
})

const statusCache = computed(() => {
  if (!debugInfo.value?.array_status_cache) return []
  return Object.entries(debugInfo.value.array_status_cache).map(([id, info]) => ({
    array_id: id,
    ...info,
  }))
})

const loadAlerts = async () => {
  loading.value = true
  try {
    const params = {}
    if (filters.value.level) params.level = filters.value.level
    if (filters.value.module) params.module = filters.value.module
    
    const [alertsRes, statsRes] = await Promise.all([
      api.getSystemAlerts(params),
      api.getSystemAlertStats(),
    ])
    alerts.value = alertsRes.data
    stats.value = statsRes.data
  } catch (error) {
    ElMessage.error('加载系统告警失败')
  } finally {
    loading.value = false
  }
}

const clearAlerts = async () => {
  try {
    await ElMessageBox.confirm('确定要清空所有系统告警吗？', '确认清空', {
      type: 'warning',
    })
    await api.clearSystemAlerts()
    ElMessage.success('已清空系统告警')
    loadAlerts()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('清空失败')
    }
  }
}

const formatDateTime = (isoString) => {
  if (!isoString) return '-'
  const date = new Date(isoString)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

const getLevelType = (level) => {
  const types = {
    debug: 'info',
    info: '',
    warning: 'warning',
    error: 'danger',
    critical: 'danger',
  }
  return types[level] || 'info'
}

const getLevelText = (level) => {
  const texts = {
    debug: '调试',
    info: '信息',
    warning: '警告',
    error: '错误',
    critical: '严重',
  }
  return texts[level] || level
}

const loadDebugInfo = async () => {
  debugLoading.value = true
  try {
    const res = await api.getSystemDebugInfo()
    debugInfo.value = res.data
  } catch (error) {
    ElMessage.error('加载调试信息失败')
  } finally {
    debugLoading.value = false
  }
}

onMounted(() => {
  loadAlerts()
  loadDebugInfo()
})
</script>

<style scoped>
.system-alerts {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.filter-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.stats-row {
  margin-bottom: 20px;
}

.stat-item {
  text-align: center;
  padding: 16px;
  background: #f5f7fa;
  border-radius: 4px;
}

.stat-value {
  font-size: 24px;
  font-weight: bold;
  color: #303133;
}

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-top: 4px;
}

.critical-text {
  color: #f56c6c;
}

.error-text {
  color: #f56c6c;
}

.warning-text {
  color: #e6a23c;
}

.info-text {
  color: #409eff;
}

.debug-text {
  color: #909399;
}

.alert-detail {
  padding: 12px 24px;
}

.alert-detail pre {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}

.alert-detail .traceback {
  background: #fef0f0;
  color: #f56c6c;
}

.alert-hint {
  margin-top: 20px;
}

.debug-card {
  margin-top: 20px;
}

.empty-text {
  color: #909399;
  text-align: center;
  padding: 20px;
}
</style>
