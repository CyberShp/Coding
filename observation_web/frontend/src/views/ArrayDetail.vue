<template>
  <div class="array-detail" v-loading="loading">
    <el-page-header @back="$router.back()">
      <template #content>
        <span class="page-title">{{ array?.name || '阵列详情' }}</span>
      </template>
    </el-page-header>

    <div class="content" v-if="array">
      <!-- Basic Info -->
      <el-card class="info-card">
        <template #header>
          <div class="card-header">
            <span>基本信息</span>
            <div class="actions">
              <el-button 
                v-if="array.state !== 'connected'"
                type="primary"
                size="small"
                @click="handleConnect"
              >
                连接
              </el-button>
              <el-button 
                v-else
                size="small"
                @click="handleDisconnect"
              >
                断开
              </el-button>
              <el-button size="small" @click="handleRefresh" :loading="refreshing">
                <el-icon><Refresh /></el-icon>
                刷新
              </el-button>
            </div>
          </div>
        </template>
        
        <el-descriptions :column="3" border>
          <el-descriptions-item label="名称">{{ array.name }}</el-descriptions-item>
          <el-descriptions-item label="地址">{{ array.host }}:{{ array.port }}</el-descriptions-item>
          <el-descriptions-item label="用户名">{{ array.username }}</el-descriptions-item>
          <el-descriptions-item label="连接状态">
            <el-tag :type="getStateType(array.state)">{{ getStateText(array.state) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Agent 状态">
            <el-tag v-if="array.agent_running" type="success">运行中</el-tag>
            <el-tag v-else-if="array.agent_deployed" type="warning">已部署</el-tag>
            <el-tag v-else type="info">未部署</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="最后刷新">
            {{ array.last_refresh ? formatDateTime(array.last_refresh) : '-' }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- Observer Status (Card Layout) -->
      <el-card class="observer-card">
        <template #header>
          <div class="card-header">
            <span>观察点状态</span>
            <el-tag type="info" size="small">{{ observerList.length }} 个观察点</el-tag>
          </div>
        </template>
        
        <div class="observer-grid" v-if="observerList.length > 0">
          <div 
            v-for="obs in observerList" 
            :key="obs.name" 
            class="observer-item"
            :class="`observer-${obs.status}`"
          >
            <div class="observer-header">
              <span class="observer-name">{{ getObserverName(obs.name) }}</span>
              <el-tag :type="getObserverStatusType(obs.status)" size="small">
                {{ getObserverStatusText(obs.status) }}
              </el-tag>
            </div>
            <div class="observer-message" v-if="obs.message">{{ obs.message }}</div>
            <div class="observer-id">{{ obs.name }}</div>
          </div>
        </div>
        
        <el-empty v-else description="暂无数据，请刷新" />
      </el-card>

      <!-- Performance Monitor Tab -->
      <el-card class="perf-card" v-if="array.state === 'connected'">
        <template #header>
          <div class="card-header">
            <span>性能监控</span>
            <el-tag type="success" size="small">实时</el-tag>
          </div>
        </template>
        
        <PerformanceMonitor :array-id="array.array_id" />
      </el-card>

      <!-- Agent Controls -->
      <el-card class="agent-card">
        <template #header>
          <div class="card-header">
            <span>Agent 控制</span>
            <el-tag v-if="array.agent_running" type="success">运行中</el-tag>
            <el-tag v-else-if="array.agent_deployed" type="warning">已部署</el-tag>
            <el-tag v-else type="info">未部署</el-tag>
          </div>
        </template>

        <div class="agent-actions">
          <el-progress
            v-if="isOperating"
            :percentage="100"
            :indeterminate="true"
            :duration="2"
            status="success"
          >
            <span>{{ operationText }}</span>
          </el-progress>

          <div class="agent-buttons">
            <el-button
              type="primary"
              size="small"
              :loading="deploying"
              :disabled="array.state !== 'connected'"
              @click="handleDeployAgent"
            >
              部署 Agent
            </el-button>
            <el-button
              type="success"
              size="small"
              :loading="starting"
              :disabled="array.state !== 'connected' || array.agent_running"
              @click="handleStartAgent"
            >
              启动 Agent
            </el-button>
            <el-button
              size="small"
              :loading="restarting"
              :disabled="array.state !== 'connected'"
              @click="handleRestartAgent"
            >
              重启 Agent
            </el-button>
            <el-button
              type="danger"
              size="small"
              :loading="stopping"
              :disabled="array.state !== 'connected' || !array.agent_running"
              @click="handleStopAgent"
            >
              停止 Agent
            </el-button>
          </div>
        </div>
      </el-card>

      <!-- Recent Alerts (Structured Display) -->
      <el-card class="alerts-card">
        <template #header>
          <div class="card-header">
            <span>最近告警</span>
            <el-button size="small" @click="$router.push('/alerts')">查看全部</el-button>
          </div>
        </template>
        
        <div class="alert-timeline" v-if="recentAlerts.length > 0">
          <div 
            v-for="(alert, index) in recentAlerts" 
            :key="index" 
            class="alert-timeline-item"
            :class="`alert-${alert.level}`"
          >
            <div class="alert-time">{{ formatDateTime(alert.timestamp) }}</div>
            <div class="alert-body">
              <div class="alert-header-row">
                <el-tag :type="getLevelType(alert.level)" size="small">
                  {{ getLevelText(alert.level) }}
                </el-tag>
                <span class="alert-observer">{{ getObserverName(alert.observer_name) }}</span>
                <el-tag v-if="alert.parsed?.is_history" type="info" size="small">历史告警上报</el-tag>
              </div>
              <!-- Structured alarm display -->
              <div v-if="alert.parsed?.alarm_type != null" class="alert-structured">
                <el-descriptions :column="3" size="small" border>
                  <el-descriptions-item label="告警类型">{{ alert.parsed.alarm_type }}</el-descriptions-item>
                  <el-descriptions-item label="告警名称">{{ alert.parsed.alarm_name || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="告警ID">{{ alert.parsed.alarm_id || '-' }}</el-descriptions-item>
                </el-descriptions>
              </div>
              <div v-else class="alert-message-text">{{ alert.message }}</div>
            </div>
          </div>
        </div>
        
        <el-empty v-else description="暂无告警，请刷新以同步" />
      </el-card>

      <!-- Log Viewer -->
      <el-card class="log-card" v-if="array.state === 'connected'">
        <template #header>
          <div class="card-header">
            <span>在线日志查看器</span>
            <el-tag type="success" size="small">实时</el-tag>
          </div>
        </template>
        
        <LogViewer :array-id="array.array_id" />
      </el-card>

      <!-- Agent Config -->
      <el-card class="config-card" v-if="array.state === 'connected' && array.agent_deployed">
        <template #header>
          <div class="card-header">
            <span>Agent 配置</span>
            <el-tag type="info" size="small">远程同步</el-tag>
          </div>
        </template>
        
        <AgentConfig :array-id="array.array_id" />
      </el-card>
    </div>

    <!-- Connect Dialog -->
    <el-dialog v-model="connectDialogVisible" title="连接阵列" width="400px">
      <el-form :model="connectForm">
        <el-form-item label="密码">
          <el-input 
            v-model="connectForm.password" 
            type="password" 
            show-password 
            placeholder="SSH 密码" 
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="connectDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="doConnect" :loading="connecting">连接</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useArrayStore } from '../stores/arrays'
import api from '../api'
import LogViewer from '../components/LogViewer.vue'
import AgentConfig from '../components/AgentConfig.vue'
import PerformanceMonitor from '../components/PerformanceMonitor.vue'

const route = useRoute()
const arrayStore = useArrayStore()

const loading = ref(true)
const refreshing = ref(false)
const connectDialogVisible = ref(false)
const connecting = ref(false)
const array = ref(null)
const deploying = ref(false)
const starting = ref(false)
const stopping = ref(false)
const restarting = ref(false)

const connectForm = reactive({
  password: '',
})

const recentAlerts = ref([])

const observerList = computed(() => {
  if (!array.value?.observer_status) return []
  return Object.entries(array.value.observer_status)
    .filter(([name]) => name !== '_meta')
    .map(([name, info]) => ({
      name,
      status: info.status,
      message: info.message,
    }))
})

function parseAlarmMessage(message) {
  // Parse structured alarm messages like "alarm type(5) alarm name(disk_fault) alarm id(0x1234)"
  const parsed = {}
  const typeMatch = message.match(/alarm\s*type\s*\((\d+)\)/i)
  const nameMatch = message.match(/alarm\s*name\s*\(([^)]+)\)/i)
  const idMatch = message.match(/alarm\s*id\s*\(([^)]+)\)/i)
  
  if (typeMatch) parsed.alarm_type = typeMatch[1]
  if (nameMatch) parsed.alarm_name = nameMatch[1]
  if (idMatch) parsed.alarm_id = idMatch[1]
  
  if (message.includes('历史告警') || message.includes('history')) {
    parsed.is_history = true
  }
  
  return Object.keys(parsed).length > 0 ? parsed : null
}

async function loadRecentAlerts() {
  if (!array.value?.array_id) return
  try {
    const res = await api.getAlerts({ array_id: array.value.array_id, limit: 20 })
    const alerts = res.data.items || res.data || []
    recentAlerts.value = alerts.map(a => ({
      ...a,
      parsed: parseAlarmMessage(a.message || ''),
    }))
  } catch (error) {
    console.error('Failed to load alerts:', error)
  }
}

const isOperating = computed(() => deploying.value || starting.value || stopping.value || restarting.value)

const operationText = computed(() => {
  if (deploying.value) return '部署中...'
  if (starting.value) return '启动中...'
  if (restarting.value) return '重启中...'
  if (stopping.value) return '停止中...'
  return ''
})

const OBSERVER_NAMES = {
  error_code: '误码监测',
  link_status: '链路状态',
  card_recovery: '卡修复',
  alarm_type: 'AlarmType',
  memory_leak: '内存泄漏',
  cpu_usage: 'CPU利用率',
  cmd_response: '命令响应',
  sig_monitor: 'sig信号',
  sensitive_info: '敏感信息',
}

function getObserverName(name) {
  return OBSERVER_NAMES[name] || name
}

function getStateType(state) {
  const types = {
    connected: 'success',
    connecting: 'warning',
    disconnected: 'info',
    error: 'danger',
  }
  return types[state] || 'info'
}

function getStateText(state) {
  const texts = {
    connected: '已连接',
    connecting: '连接中',
    disconnected: '未连接',
    error: '错误',
  }
  return texts[state] || state
}

function getObserverStatusType(status) {
  const types = {
    ok: 'success',
    warning: 'warning',
    error: 'danger',
    unknown: 'info',
  }
  return types[status] || 'info'
}

function getObserverStatusText(status) {
  const texts = {
    ok: '正常',
    warning: '警告',
    error: '错误',
    unknown: '未知',
  }
  return texts[status] || status
}

function getLevelType(level) {
  const types = {
    info: 'info',
    warning: 'warning',
    error: 'danger',
    critical: 'danger',
  }
  return types[level] || 'info'
}

function getLevelText(level) {
  const texts = {
    info: '信息',
    warning: '警告',
    error: '错误',
    critical: '严重',
  }
  return texts[level] || level
}

function formatDateTime(timestamp) {
  if (!timestamp) return '-'
  return new Date(timestamp).toLocaleString('zh-CN')
}

async function loadArray() {
  loading.value = true
  try {
    const arrayId = route.params.id
    const response = await api.getArrayStatus(arrayId)
    array.value = response.data
    // Load alerts from database instead of embedded in status
    await loadRecentAlerts()
  } catch (error) {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

function handleConnect() {
  connectForm.password = ''
  connectDialogVisible.value = true
}

async function doConnect() {
  connecting.value = true
  try {
    const result = await arrayStore.connectArray(array.value.array_id, connectForm.password)
    ElMessage.success('连接成功')
    connectDialogVisible.value = false
    if (result?.agent_status === 'not_deployed') {
      ElMessage.warning(result.hint || 'Agent 未部署')
    }
    await loadArray()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '连接失败')
  } finally {
    connecting.value = false
  }
}

async function handleDisconnect() {
  try {
    await arrayStore.disconnectArray(array.value.array_id)
    ElMessage.success('已断开连接')
    await loadArray()
  } catch (error) {
    ElMessage.error('断开连接失败')
  }
}

async function handleRefresh() {
  refreshing.value = true
  try {
    await arrayStore.refreshArray(array.value.array_id)
    await loadArray()
    ElMessage.success('刷新成功')
  } catch (error) {
    ElMessage.error('刷新失败')
  } finally {
    refreshing.value = false
  }
}

async function handleDeployAgent() {
  deploying.value = true
  try {
    await api.deployAgent(array.value.array_id)
    ElMessage.success('部署成功')
    await loadArray()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '部署失败')
  } finally {
    deploying.value = false
  }
}

async function handleStartAgent() {
  starting.value = true
  try {
    await api.startAgent(array.value.array_id)
    ElMessage.success('启动成功')
    await loadArray()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '启动失败')
  } finally {
    starting.value = false
  }
}

async function handleRestartAgent() {
  restarting.value = true
  try {
    await api.restartAgent(array.value.array_id)
    ElMessage.success('重启成功')
    await loadArray()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '重启失败')
  } finally {
    restarting.value = false
  }
}

async function handleStopAgent() {
  stopping.value = true
  try {
    await api.stopAgent(array.value.array_id)
    ElMessage.success('停止成功')
    await loadArray()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '停止失败')
  } finally {
    stopping.value = false
  }
}

onMounted(loadArray)
</script>

<style scoped>
.array-detail {
  padding: 20px;
}

.page-title {
  font-size: 18px;
  font-weight: 500;
}

.content {
  margin-top: 20px;
}

.info-card,
.observer-card,
.agent-card,
.alerts-card,
.perf-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.actions {
  display: flex;
  gap: 8px;
}

.agent-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.agent-buttons {
  display: flex;
  gap: 8px;
}

/* Observer card grid */
.observer-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.observer-item {
  padding: 12px 16px;
  border-radius: 8px;
  border-left: 4px solid #dcdfe6;
  background: #fafafa;
  transition: all 0.2s;
}

.observer-item:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.observer-ok { border-left-color: #67c23a; background: #f0f9eb; }
.observer-warning { border-left-color: #e6a23c; background: #fdf6ec; }
.observer-error { border-left-color: #f56c6c; background: #fef0f0; }

.observer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.observer-name {
  font-weight: 600;
  font-size: 14px;
}

.observer-message {
  font-size: 12px;
  color: #606266;
  line-height: 1.4;
  word-break: break-all;
}

.observer-id {
  font-size: 11px;
  color: #c0c4cc;
  margin-top: 4px;
  font-family: monospace;
}

/* Alert timeline */
.alert-timeline {
  max-height: 500px;
  overflow-y: auto;
}

.alert-timeline-item {
  display: flex;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid #f0f0f0;
}

.alert-timeline-item:last-child {
  border-bottom: none;
}

.alert-time {
  flex-shrink: 0;
  width: 140px;
  font-size: 12px;
  color: #909399;
  padding-top: 2px;
}

.alert-body {
  flex: 1;
  min-width: 0;
}

.alert-header-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.alert-observer {
  font-size: 13px;
  font-weight: 500;
  color: #606266;
}

.alert-structured {
  margin-top: 4px;
}

.alert-message-text {
  font-size: 13px;
  color: #303133;
  word-break: break-all;
  line-height: 1.5;
}

.alert-error { }
.alert-warning { }
.alert-critical .alert-body { color: #f56c6c; }

/* Performance card */
.perf-card {
  margin-bottom: 20px;
}

.log-card {
  margin-bottom: 20px;
}

.log-card :deep(.el-card__body) {
  height: 500px;
  padding: 0;
}

.config-card {
  margin-bottom: 20px;
}

.config-card :deep(.el-card__body) {
  padding: 0;
}
</style>
