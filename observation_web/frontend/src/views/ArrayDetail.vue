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

      <!-- Observer Status (Grouped Card Layout) -->
      <el-card class="observer-card">
        <template #header>
          <div class="card-header">
            <span>观察点状态</span>
            <el-tag type="info" size="small">{{ observerList.length }} 个观察点</el-tag>
          </div>
        </template>
        
        <div v-if="observerList.length > 0">
          <div v-for="group in groupedObservers" :key="group.key" class="observer-group">
            <div class="group-title">{{ group.label }}</div>
            <div class="observer-grid">
              <div 
                v-for="obs in group.items" 
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

      <!-- Port Traffic Chart (always show if array exists) -->
      <el-card class="traffic-card">
        <template #header>
          <div class="card-header">
            <span>端口流量监控</span>
            <el-tag type="success" size="small">最近2小时</el-tag>
          </div>
        </template>
        
        <PortTrafficChart :array-id="array.array_id" />
      </el-card>

      <!-- Event Timeline -->
      <el-card class="timeline-card">
        <template #header>
          <div class="card-header">
            <span>事件时间线</span>
            <el-tag type="info" size="small">跨观察点</el-tag>
          </div>
        </template>
        
        <EventTimeline :array-id="array.array_id" />
      </el-card>

      <!-- Snapshot & Diff -->
      <el-card class="snapshot-card">
        <template #header>
          <div class="card-header">
            <span>状态快照与对比</span>
            <el-tag type="info" size="small">测试前后对比</el-tag>
          </div>
        </template>
        
        <SnapshotDiff :array-id="array.array_id" />
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

      <!-- Recent Alerts (Translated + Drawer) -->
      <el-card class="alerts-card">
        <template #header>
          <div class="card-header">
            <span>最近告警</span>
            <el-button size="small" @click="$router.push('/alerts')">查看全部</el-button>
          </div>
        </template>
        
        <div class="alert-timeline" v-if="recentAlerts.length > 0">
          <div 
            v-for="(a, index) in recentAlerts" 
            :key="index" 
            class="alert-timeline-item clickable-alert"
            :class="`alert-${a.level}`"
            @click="openAlertDrawer(a)"
          >
            <div class="alert-time">{{ formatDateTime(a.timestamp) }}</div>
            <div class="alert-body">
              <div class="alert-header-row">
                <el-tag :type="getLevelType(a.level)" size="small">
                  {{ getLevelText(a.level) }}
                </el-tag>
                <span class="alert-observer">{{ getObserverLabel(a.observer_name) }}</span>
                <el-tag v-if="getAlertTranslation(a).parsed?.is_history" type="info" size="small" effect="plain">历史告警上报</el-tag>
                <el-tag v-else-if="getAlertTranslation(a).parsed?.is_resume" type="success" size="small" effect="plain">已恢复</el-tag>
              </div>
              <div class="alert-summary-text">{{ getAlertTranslation(a).summary }}</div>
            </div>
            <el-icon class="alert-arrow"><ArrowRight /></el-icon>
          </div>
        </div>
        
        <el-empty v-else description="暂无告警，请刷新以同步" />
      </el-card>

      <!-- 告警详情抽屉 -->
      <AlertDetailDrawer v-model="drawerVisible" :alert="selectedAlert" />

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
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, ArrowRight } from '@element-plus/icons-vue'
import { useArrayStore } from '../stores/arrays'
import api from '../api'
import LogViewer from '../components/LogViewer.vue'
import AgentConfig from '../components/AgentConfig.vue'
import PerformanceMonitor from '../components/PerformanceMonitor.vue'
import PortTrafficChart from '../components/PortTrafficChart.vue'
import EventTimeline from '../components/EventTimeline.vue'
import SnapshotDiff from '../components/SnapshotDiff.vue'
import AlertDetailDrawer from '@/components/AlertDetailDrawer.vue'
import { translateAlert, getObserverName as getObserverLabel, getObserverGroup, OBSERVER_GROUPS, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'

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
const drawerVisible = ref(false)
const selectedAlert = ref(null)

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

const groupedObservers = computed(() => {
  const list = observerList.value
  if (list.length === 0) return []

  const groups = {}
  for (const obs of list) {
    const { key, label } = getObserverGroup(obs.name)
    if (!groups[key]) {
      groups[key] = { key, label, items: [] }
    }
    groups[key].items.push(obs)
  }

  // Sort: port -> card -> system
  const order = ['port', 'card', 'system']
  return order.map(k => groups[k]).filter(Boolean)
})

function getAlertTranslation(alert) {
  return translateAlert(alert)
}

function openAlertDrawer(alert) {
  selectedAlert.value = alert
  drawerVisible.value = true
}

async function loadRecentAlerts() {
  if (!array.value?.array_id) return
  try {
    const res = await api.getAlerts({ array_id: array.value.array_id, limit: 20 })
    recentAlerts.value = res.data.items || res.data || []
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

// Observer name lookup delegated to alertTranslator.getObserverName
function getObserverName(name) {
  return getObserverLabel(name)
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
  return LEVEL_TAG_TYPES[level] || 'info'
}

function getLevelText(level) {
  return LEVEL_LABELS[level] || level
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

async function handleConnect() {
  // 如果有保存的密码，先尝试自动连接
  const statusData = arrayStore.statuses.find(s => s.array_id === array.value?.array_id)
  if (statusData?.has_saved_password) {
    connecting.value = true
    try {
      const result = await arrayStore.connectArray(array.value.array_id, '')
      ElMessage.success('自动连接成功')
      if (result?.agent_status === 'not_deployed') {
        ElMessage.warning(result.hint || 'Agent 未部署')
      }
      await loadArray()
      return
    } catch (error) {
      ElMessage.warning('已保存密码连接失败，请重新输入')
    } finally {
      connecting.value = false
    }
  }
  
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

// ───── Auto-refresh (30s silent) ─────
let refreshTimer = null

async function silentRefresh() {
  // Skip if page is hidden or a manual operation is in progress
  if (document.hidden) return
  if (isOperating.value || refreshing.value || connecting.value) return

  try {
    const arrayId = route.params.id
    const response = await api.getArrayStatus(arrayId)
    array.value = response.data
    await loadRecentAlerts()
  } catch {
    // Silent — don't disturb the user
  }
}

onMounted(() => {
  loadArray()
  refreshTimer = setInterval(silentRefresh, 30000) // 30 seconds
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
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

/* Observer group */
.observer-group {
  margin-bottom: 16px;
}

.observer-group:last-child {
  margin-bottom: 0;
}

.group-title {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 8px;
  padding-left: 4px;
  border-left: 3px solid #409eff;
  padding-left: 8px;
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

.alert-summary-text {
  font-size: 13px;
  color: #303133;
  line-height: 1.6;
  word-break: break-word;
}

.clickable-alert {
  cursor: pointer;
  transition: background 0.15s;
  align-items: center;
}

.clickable-alert:hover {
  background: #f5f7fa;
}

.alert-arrow {
  color: var(--el-text-color-placeholder);
  flex-shrink: 0;
}

.alert-error { }
.alert-warning { }
.alert-critical .alert-body { color: #f56c6c; }

/* Performance & Traffic card */
.perf-card,
.traffic-card {
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
