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

      <!-- Active Issues Panel -->
      <el-card class="active-issues-card">
        <template #header>
          <div class="card-header">
            <span>活跃告警与异常</span>
            <el-tag v-if="activeIssues.length > 0" type="danger" size="small">{{ activeIssues.length }} 项</el-tag>
            <el-tag v-else type="success" size="small">无异常</el-tag>
          </div>
        </template>

        <div v-if="activeIssues.length > 0" class="issues-list">
          <div
            v-for="issue in activeIssues"
            :key="issue.key"
            class="issue-item"
            :class="`issue-${issue.level}`"
            @click="openIssueDetail(issue)"
          >
            <div class="issue-header">
              <span class="issue-title">{{ issue.title }}</span>
              <el-tag :type="issue.level === 'error' || issue.level === 'critical' ? 'danger' : 'warning'" size="small">
                {{ issue.level === 'error' || issue.level === 'critical' ? '错误' : '警告' }}
              </el-tag>
              <el-button
                v-if="issue.alert_id"
                size="small"
                type="success"
                text
                class="issue-ack-btn"
                @click.stop="handleAckIssue(issue)"
              >
                <el-icon><Check /></el-icon> 确认消除
              </el-button>
            </div>
            <div class="issue-message">{{ issue.message }}</div>
            <div class="issue-meta">
              <span class="issue-observer">{{ getObserverName(issue.observer) }}</span>
              <span class="issue-since" v-if="issue.since">持续自 {{ formatRelativeTime(issue.since) }}</span>
            </div>
          </div>
        </div>

        <div v-else class="issues-empty">
          <el-icon :size="32" color="#67c23a"><CircleCheck /></el-icon>
          <p>所有监测项正常运行</p>
        </div>
      </el-card>

      <!-- Recent Alerts (Translated + Drawer + Folding) -->
      <el-card class="alerts-card">
        <template #header>
          <div class="card-header">
            <span>最近告警</span>
            <el-button size="small" @click="$router.push('/alerts')">查看全部</el-button>
          </div>
        </template>
        
        <FoldedAlertList
          :alerts="recentAlerts"
          :show-array-id="false"
          empty-text="暂无告警，请刷新以同步"
          @select="openAlertDrawer"
          @ack="handleAck"
        />
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

      <!-- 告警详情抽屉 -->
      <AlertDetailDrawer v-model="drawerVisible" :alert="selectedAlert" @ack-changed="onAckChanged" />

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
import { Refresh, ArrowRight, CircleCheck, Check } from '@element-plus/icons-vue'
import { useArrayStore } from '../stores/arrays'
import api from '../api'
import LogViewer from '../components/LogViewer.vue'
import AgentConfig from '../components/AgentConfig.vue'
import PerformanceMonitor from '../components/PerformanceMonitor.vue'
import PortTrafficChart from '../components/PortTrafficChart.vue'
import EventTimeline from '../components/EventTimeline.vue'
import SnapshotDiff from '../components/SnapshotDiff.vue'
import AlertDetailDrawer from '@/components/AlertDetailDrawer.vue'
import FoldedAlertList from '@/components/FoldedAlertList.vue'
import { translateAlert, getObserverName as getObserverLabel, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'

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

const activeIssues = computed(() => {
  return array.value?.active_issues || []
})

function getAlertTranslation(alert) {
  return translateAlert(alert)
}

async function handleAckIssue(issue) {
  if (!issue.alert_id) return
  try {
    await api.ackAlerts([issue.alert_id])
    ElMessage.success('已确认消除')
    // Remove from local active issues immediately
    if (array.value?.active_issues) {
      array.value.active_issues = array.value.active_issues.filter(
        i => i.key !== issue.key
      )
    }
  } catch (e) {
    ElMessage.error('确认失败: ' + (e.response?.data?.detail || e.message))
  }
}

function openIssueDetail(issue) {
  // Build a pseudo-alert object from the issue for the drawer
  selectedAlert.value = {
    observer_name: issue.observer,
    level: issue.level,
    message: issue.message,
    details: issue.details || {},
    timestamp: issue.latest || issue.since || '',
  }
  drawerVisible.value = true
}

function formatRelativeTime(ts) {
  if (!ts) return ''
  const now = Date.now()
  const then = new Date(ts).getTime()
  if (isNaN(then)) return ts
  const diffSec = Math.floor((now - then) / 1000)
  if (diffSec < 60) return `${diffSec} 秒前`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr} 小时前`
  const diffDay = Math.floor(diffHr / 24)
  return `${diffDay} 天前`
}

function openAlertDrawer(alert) {
  selectedAlert.value = alert
  drawerVisible.value = true
}

async function handleAck({ alertIds }) {
  try {
    await api.ackAlerts(alertIds)
    ElMessage.success('已确认')
    recentAlerts.value.forEach(a => {
      if (alertIds.includes(a.id)) a.is_acked = true
    })
    // Also remove from active issues if applicable
    if (array.value?.active_issues) {
      // Refresh to get updated active issues
      await loadArray()
    }
  } catch (e) {
    ElMessage.error('确认失败: ' + (e.response?.data?.detail || e.message))
  }
}

function onAckChanged({ alertId, acked }) {
  const a = recentAlerts.value.find(x => x.id === alertId)
  if (a) a.is_acked = acked
  // Refresh active issues when ack status changes
  if (array.value?.array_id) {
    loadArray()
  }
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
.active-issues-card,
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

/* Active Issues */
.issues-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.issue-item {
  padding: 12px 16px;
  border-radius: 8px;
  border-left: 4px solid #dcdfe6;
  background: #fafafa;
  cursor: pointer;
  transition: all 0.2s;
}

.issue-item:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  transform: translateX(2px);
}

.issue-warning { border-left-color: #e6a23c; background: #fdf6ec; }
.issue-error, .issue-critical { border-left-color: #f56c6c; background: #fef0f0; }

.issue-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.issue-title {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}

.issue-message {
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
  word-break: break-all;
  margin-bottom: 6px;
}

.issue-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: #909399;
}

.issue-observer {
  font-family: monospace;
  background: #f0f2f5;
  padding: 1px 6px;
  border-radius: 4px;
}

.issue-since {
  font-style: italic;
}

.issue-ack-btn {
  margin-left: auto;
  font-size: 12px;
}

.issues-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px 0;
  color: #67c23a;
}

.issues-empty p {
  margin-top: 8px;
  color: #909399;
  font-size: 14px;
}

/* Alert list is now in FoldedAlertList.vue component */

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
