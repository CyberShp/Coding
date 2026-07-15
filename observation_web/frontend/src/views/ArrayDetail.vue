<template>
  <div class="array-detail" v-loading="loading">
    <template v-if="array">
      <header class="array-command-header">
        <el-button class="back-button" text circle aria-label="返回" @click="$router.back()">
          <el-icon><ArrowLeft /></el-icon>
        </el-button>
        <div class="array-identity">
          <div class="identity-line">
            <span class="status-dot" :class="array.state === 'connected' ? 'is-online' : 'is-offline'" />
            <h1>{{ array.name }}</h1>
            <span class="array-address">{{ arrayEndpoint }}</span>
          </div>
          <div class="identity-meta">
            <span>{{ getStateText(array.state) }}</span>
            <span>Agent {{ getAgentStateText(array.agent_state) }}</span>
            <span>{{ activeIssues.length ? `${activeIssues.length} 项活跃异常` : '监测正常' }}</span>
          </div>
        </div>
        <div class="header-actions">
          <el-button v-if="array.state !== 'connected'" type="primary" @click="handleConnect">连接</el-button>
          <el-button v-else @click="handleDisconnect">断开</el-button>
          <el-button circle aria-label="刷新阵列" :loading="refreshing" @click="handleRefresh">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
      </header>

      <div class="signal-strip">
        <button class="signal-item signal-danger" type="button" @click="activeSection = 'overview'">
          <span class="signal-label">活跃异常</span>
          <strong>{{ activeIssues.length }}</strong>
          <span>{{ activeIssues.length ? '需要处置' : '当前正常' }}</span>
        </button>
        <button class="signal-item" type="button" @click="activeSection = 'overview'">
          <span class="signal-label">未确认告警</span>
          <strong>{{ unackedCount }}</strong>
          <span>最近 20 条</span>
        </button>
        <button class="signal-item" type="button" @click="activeSection = 'agent'">
          <span class="signal-label">Agent</span>
          <strong class="signal-state">{{ getAgentStateText(array.agent_state) }}</strong>
          <span>{{ agentEvidenceText }}</span>
        </button>
        <div class="signal-item signal-static">
          <span class="signal-label">最后同步</span>
          <strong class="signal-time">{{ array.last_refresh ? formatDateTime(array.last_refresh) : '--' }}</strong>
          <span v-if="watchers.length">{{ watchers.length }} 人正在关注</span>
          <span v-else>无人协同查看</span>
        </div>
      </div>

      <el-tabs v-model="activeSection" class="workspace-tabs">
        <el-tab-pane label="概览" name="overview">
          <div class="overview-grid">
            <section class="surface issues-surface">
              <div class="surface-header">
                <div>
                  <span class="surface-kicker">DIAGNOSIS QUEUE</span>
                  <h2>当前需处理</h2>
                </div>
                <span class="surface-count" :class="{ 'has-danger': activeIssues.length }">{{ activeIssues.length }}</span>
              </div>
              <div v-if="activeIssues.length" class="issues-list">
                <article
                  v-for="issue in activeIssues"
                  :key="issue.key"
                  class="issue-item"
                  :class="[`issue-${issue.level}`, { 'issue-suppressed': issue.suppressed }]"
                  @click="openIssueDetail(issue)"
                >
                  <div class="issue-row">
                    <span class="issue-title">{{ issue.title }}</span>
                    <span class="issue-observer">{{ getObserverName(issue.observer) }}</span>
                    <span v-if="issue.since && !issue.suppressed" class="issue-since">持续 {{ formatRelativeTime(issue.since) }}</span>
                    <el-button v-if="issue.alert_id && !issue.suppressed" text type="success" class="issue-ack-btn" @click.stop="handleAckIssue(issue)">
                      <el-icon><Check /></el-icon> 忽略
                    </el-button>
                  </div>
                  <div class="issue-message">{{ issue.message }}</div>
                </article>
              </div>
              <div v-else class="issues-empty">
                <el-icon :size="30"><CircleCheck /></el-icon>
                <div><strong>暂无活跃异常</strong><span>所有系统级观察点状态正常</span></div>
              </div>
            </section>

            <aside class="surface context-surface">
              <div class="surface-header compact"><h2>阵列信息</h2></div>
              <dl class="context-list">
                <div><dt>地址</dt><dd>{{ arrayEndpoint }}</dd></div>
                <div><dt>用户</dt><dd>{{ array.username }}</dd></div>
                <div><dt>标签</dt><dd>
                  <el-select v-model="array.tag_id" placeholder="未分类" size="small" clearable @change="handleTagChange">
                    <el-option v-for="tag in tags" :key="tag.id" :label="tag.parent_name ? `${tag.parent_name} / ${tag.name}` : tag.name" :value="tag.id" />
                  </el-select>
                </dd></div>
              </dl>
              <div v-if="watchers.length" class="watchers-block">
                <span class="context-label"><el-icon><User /></el-icon> 协同查看</span>
                <div class="watchers-list">
                  <el-tag v-for="w in watchers" :key="w.ip" :style="{ borderColor: w.color, color: w.color }" effect="plain" size="small">
                    {{ w.nickname || w.ip }}
                  </el-tag>
                </div>
              </div>
            </aside>

            <section v-if="activeIssues.length" class="surface ai-surface">
              <div class="surface-header compact">
                <h2><el-icon><MagicStick /></el-icon> AI 综合解读</h2>
                <el-button v-if="!aiSummaryLoading" text type="primary" @click="fetchAISummary">{{ aiSummaryText ? '重新解读' : '开始解读' }}</el-button>
              </div>
              <div v-if="aiSummaryLoading" class="ai-state"><el-icon class="is-loading"><Loading /></el-icon> 正在分析当前异常...</div>
              <el-alert v-else-if="aiSummaryError" type="warning" :title="aiSummaryError" show-icon />
              <div v-else-if="aiSummaryText" class="ai-summary-text">{{ aiSummaryText }}</div>
              <p v-else class="ai-placeholder">汇总当前异常的关联、影响与建议检查顺序。</p>
            </section>

            <section class="surface alerts-surface">
              <div class="surface-header compact">
                <div><span class="surface-kicker">RECENT SIGNALS</span><h2>最近告警</h2></div>
                <el-button text type="primary" @click="$router.push({ path: '/alerts', query: { array_id: array.array_id } })">打开告警中心</el-button>
              </div>
              <FoldedAlertList :alerts="recentAlerts" :show-array-id="false" empty-text="暂无告警" @select="openAlertDrawer" @ack="handleAck" @undo-ack="handleUndoAck" @modify-ack="handleModifyAck" />
            </section>
          </div>
        </el-tab-pane>

        <el-tab-pane label="性能与事件" name="performance">
          <div class="workspace-stack">
            <section v-if="array.state === 'connected'" class="surface"><div class="surface-header"><h2>实时性能</h2><el-tag type="success" effect="plain">15s</el-tag></div><PerformanceMonitor :array-id="array.array_id" /></section>
            <section v-else class="surface disconnected-state"><el-empty description="连接阵列后可查看实时性能" /></section>
            <section class="surface"><div class="surface-header"><h2>端口流量</h2><span class="surface-note">按端口查看收发带宽</span></div><PortTrafficChart :array-id="array.array_id" /></section>
            <section class="surface"><div class="surface-header"><h2>事件时间线</h2><span class="surface-note">跨观察点关联</span></div><EventTimeline :array-id="array.array_id" /></section>
          </div>
        </el-tab-pane>

        <el-tab-pane label="在线日志" name="logs">
          <section class="surface log-surface" v-if="array.state === 'connected'"><LogViewer :array-id="array.array_id" /></section>
          <section class="surface disconnected-state" v-else><el-empty description="连接阵列后可查看在线日志" /></section>
        </el-tab-pane>

        <el-tab-pane label="Agent" name="agent">
          <section class="surface agent-surface">
            <el-alert
              v-if="array.deployment_state && array.deployment_state !== 'idle'"
              :type="deploymentNoticeType"
              :title="array.deployment_message || getDeploymentStateText(array.deployment_state)"
              :closable="false"
              show-icon
              class="deployment-notice"
            />
            <div class="agent-state-panel">
              <span class="agent-state-mark" :class="{ running: ['running', 'degraded'].includes(array.agent_state) }" />
              <div>
                <span>当前状态 · {{ agentEvidenceText }}</span>
                <strong>{{ array.agent_status_message || `Agent ${getAgentStateText(array.agent_state)}` }}</strong>
              </div>
            </div>
            <el-progress v-if="isOperating" :percentage="100" :indeterminate="true" :duration="2" status="success"><span>{{ operationText }}</span></el-progress>
            <div class="agent-flow">
              <el-button type="primary" :loading="deploying" :disabled="array.state !== 'connected'" @click="handleDeployAgent">1. 部署</el-button>
              <el-button type="success" :loading="starting" :disabled="array.state !== 'connected' || array.agent_running" @click="handleStartAgent">2. 启动</el-button>
              <el-button :loading="restarting" :disabled="array.state !== 'connected'" @click="handleRestartAgent">重启</el-button>
              <el-button type="danger" plain :loading="stopping" :disabled="array.state !== 'connected' || !array.agent_running" @click="handleStopAgent">停止</el-button>
            </div>
          </section>
        </el-tab-pane>

        <el-tab-pane label="快照对比" name="snapshots">
          <section class="surface"><div class="surface-header"><h2>状态快照与对比</h2><span class="surface-note">记录测试前后差异</span></div><SnapshotDiff :array-id="array.array_id" /></section>
        </el-tab-pane>
      </el-tabs>

      <AlertDetailDrawer v-model="drawerVisible" :alert="selectedAlert" @ack-changed="onAckChanged" />
    </template>

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
import { ref, reactive, computed, watch, onMounted, onUnmounted, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, ArrowLeft, CircleCheck, Check, User, MagicStick, Loading } from '@element-plus/icons-vue'
import { useArrayStore } from '../stores/arrays'
import { useAlertStore } from '../stores/alerts'
import api from '../api'
import AlertDetailDrawer from '@/components/AlertDetailDrawer.vue'
import FoldedAlertList from '@/components/FoldedAlertList.vue'
import { translateAlert, getObserverName as getObserverLabel, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'

const route = useRoute()
const router = useRouter()
const arrayStore = useArrayStore()
const alertStore = useAlertStore()

const LogViewer = defineAsyncComponent(() => import('../components/LogViewer.vue'))
const PerformanceMonitor = defineAsyncComponent(() => import('../components/PerformanceMonitor.vue'))
const PortTrafficChart = defineAsyncComponent(() => import('../components/PortTrafficChart.vue'))
const EventTimeline = defineAsyncComponent(() => import('../components/EventTimeline.vue'))
const SnapshotDiff = defineAsyncComponent(() => import('../components/SnapshotDiff.vue'))

const loading = ref(true)
const refreshing = ref(false)
const connectDialogVisible = ref(false)
const connecting = ref(false)
const array = ref(null)
const deploying = ref(false)
const starting = ref(false)
const stopping = ref(false)
const restarting = ref(false)
const validSections = new Set(['overview', 'performance', 'logs', 'agent', 'snapshots'])
const activeSection = ref(validSections.has(route.query.tab) ? route.query.tab : 'overview')

const connectForm = reactive({
  password: '',
})

const recentAlerts = ref([])
const drawerVisible = ref(false)
const selectedAlert = ref(null)
const tags = ref([])
const watchers = ref([])
let pageAbortController = null

const aiSummaryLoading = ref(false)
const aiSummaryError = ref('')
const aiSummaryText = ref('')

watch(activeSection, (tab) => {
  const query = { ...route.query }
  if (tab === 'overview') delete query.tab
  else query.tab = tab
  router.replace({ query })
})

const activeIssues = computed(() => {
  return array.value?.active_issues || []
})

const arrayEndpoint = computed(() => {
  if (!array.value) return '--'
  return array.value.port ? `${array.value.host}:${array.value.port}` : array.value.host
})

const unackedCount = computed(() => {
  return recentAlerts.value.filter(a => !a.is_acked).length
})

const agentEvidenceText = computed(() => {
  const timestamp = array.value?.agent_heartbeat_at || array.value?.agent_observed_at
  if (!timestamp) return '尚未核验'
  const source = array.value?.agent_status_source === 'agent_heartbeat' ? '心跳' : '平台探测'
  return `${source} ${formatRelativeTime(timestamp)}`
})

const deploymentNoticeType = computed(() => {
  const state = array.value?.deployment_state
  if (state === 'failed') return 'error'
  if (state === 'partial') return 'warning'
  if (state === 'succeeded') return 'success'
  return 'info'
})

function getAgentStateText(state) {
  return ({
    unknown: '待确认',
    not_deployed: '未部署',
    stopped: '已停止',
    starting: '启动中',
    running: '运行中',
    degraded: '部分异常',
    error: '异常',
  })[state] || '待确认'
}

function getDeploymentStateText(state) {
  return ({
    deploying: '正在安装 Agent',
    configuring: '正在应用配置',
    verifying: '正在核验部署结果',
    succeeded: '部署完成',
    partial: '部署部分完成',
    failed: '部署失败',
  })[state] || '部署状态待确认'
}

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
    ElMessage.error('确认失败: ' + errMsg(e, '未知错误'))
  }
}

function openIssueDetail(issue) {
  // Build a pseudo-alert object from the issue for the drawer (id/array_id required for ack)
  selectedAlert.value = {
    id: issue.alert_id,
    array_id: array.value?.array_id,
    observer_name: issue.observer,
    level: issue.level,
    message: issue.message,
    details: issue.details || {},
    timestamp: issue.latest || issue.since || '',
  }
  drawerVisible.value = true
}

async function fetchAISummary() {
  aiSummaryLoading.value = true
  aiSummaryError.value = ''
  aiSummaryText.value = ''
  try {
    const { data: statusData } = await api.checkAIStatus()
    if (!statusData?.available) {
      aiSummaryError.value = 'AI 解读服务暂不可用'
      return
    }
    const firstWithAlertId = activeIssues.value.find(i => i.alert_id)
    if (!firstWithAlertId) {
      aiSummaryError.value = '当前异常暂无关联告警 ID，请点击上方单项在侧栏查看详情'
      return
    }
    const { data } = await api.getAIInterpretation(firstWithAlertId.alert_id)
    aiSummaryText.value = data.interpretation || '暂无解读内容'
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || 'AI 解读请求失败'
    aiSummaryError.value = typeof msg === 'string' ? msg : JSON.stringify(msg)
  } finally {
    aiSummaryLoading.value = false
  }
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

async function handleAck({ alertIds, ackType = 'dismiss' }) {
  try {
    await api.ackAlerts(alertIds, '', { ack_type: ackType })
    ElMessage.success('已确认')
    recentAlerts.value.forEach(a => {
      if (alertIds.includes(a.id)) a.is_acked = true
    })
    if (array.value?.active_issues) await loadArray()
  } catch (e) {
    ElMessage.error('确认失败: ' + errMsg(e, '未知错误'))
  }
}

async function handleUndoAck({ alertIds }) {
  try {
    await api.batchUndoAck(alertIds)
    ElMessage.success('已撤销确认')
    recentAlerts.value.forEach(a => {
      if (alertIds.includes(a.id)) a.is_acked = false
    })
    if (array.value?.active_issues) await loadArray()
  } catch (e) {
    ElMessage.error('撤销失败: ' + errMsg(e, '未知错误'))
  }
}

async function handleModifyAck({ alertIds, ackType }) {
  try {
    await api.batchModifyAck(alertIds, ackType)
    ElMessage.success('已更改确认类型')
  } catch (e) {
    ElMessage.error('更改失败: ' + errMsg(e, '未知错误'))
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

async function loadRecentAlerts(signal = undefined) {
  if (!array.value?.array_id) return
  try {
    const res = await api.getAlerts({ array_id: array.value.array_id, limit: 20 }, { signal })
    recentAlerts.value = res.data.items || res.data || []
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    console.error('Failed to load alerts:', error)
  }
}

async function loadTags() {
  try {
    const signal = pageAbortController?.signal
    const res = await api.getTags({ signal })
    tags.value = res.data || []
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    console.error('Failed to load tags:', error)
  }
}

async function handleTagChange(tagId) {
  if (!array.value?.array_id) return
  try {
    await api.updateArray(array.value.array_id, { tag_id: tagId || null })
    ElMessage.success('标签已更新')
    await loadArray()
  } catch (e) {
    ElMessage.error('更新失败: ' + errMsg(e, '未知错误'))
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

/** Safely extract error message string for ElMessage */
function errMsg(error, fallback) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (typeof error?.message === 'string') return error.message
  return fallback
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

async function loadWatchers() {
  if (!array.value?.array_id) return
  try {
    const signal = pageAbortController?.signal
    const res = await api.getArrayWatchers(array.value.array_id, { signal })
    watchers.value = res.data || []
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    watchers.value = []
  }
}

async function loadArray() {
  if (pageAbortController) pageAbortController.abort()
  pageAbortController = new AbortController()
  const { signal } = pageAbortController
  loading.value = true
  try {
    const arrayId = route.params.id
    const response = await api.getArrayStatus(arrayId, { signal })
    array.value = response.data
    arrayStore.currentArray = response.data
    await Promise.all([loadRecentAlerts(signal), loadWatchers()])
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

async function handleConnect() {
  // 如果有保存的密码，先尝试自动连接
  const statusData = arrayStore.arrays.find(s => s.array_id === array.value?.array_id)
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
    ElMessage.error(errMsg(error, '连接失败'))
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

// Mutex flag to prevent overlapping refreshes (manual + silent)
let refreshInFlight = false

async function handleRefresh() {
  if (refreshInFlight) return
  refreshInFlight = true
  refreshing.value = true
  try {
    await arrayStore.refreshArray(array.value.array_id)
    await loadArray()
    ElMessage.success('刷新成功')
  } catch (error) {
    const msg = error.response?.data?.detail || error.message || '刷新失败'
    ElMessage.error(typeof msg === 'string' ? msg : '刷新失败')
  } finally {
    refreshing.value = false
    refreshInFlight = false
  }
}

async function handleDeployAgent() {
  deploying.value = true
  try {
    const { data } = await api.deployAgent(array.value.array_id)
    if (data.status) arrayStore.applyStatusUpdate(array.value.array_id, data.status)
    if (data.outcome === 'partial') ElMessage.warning(data.message || '部署部分完成')
    else if (data.outcome === 'pending') ElMessage.info(data.message || '部署结果正在确认')
    else ElMessage.success(data.message || '部署成功')
    await reconcileArrayStatus()
  } catch (error) {
    ElMessage.error(errMsg(error, '部署失败'))
  } finally {
    deploying.value = false
  }
}

async function handleStartAgent() {
  starting.value = true
  try {
    const { data } = await api.startAgent(array.value.array_id)
    if (data.outcome === 'pending') ElMessage.info(data.message || '启动结果正在确认')
    else ElMessage.success(data.message || '启动成功')
    await reconcileArrayStatus()
  } catch (error) {
    ElMessage.error(errMsg(error, '启动失败'))
  } finally {
    starting.value = false
  }
}

async function handleRestartAgent() {
  restarting.value = true
  try {
    const { data } = await api.restartAgent(array.value.array_id)
    if (data.outcome === 'pending') ElMessage.info(data.message || '重启结果正在确认')
    else ElMessage.success(data.message || '重启成功')
    await reconcileArrayStatus()
  } catch (error) {
    ElMessage.error(errMsg(error, '重启失败'))
  } finally {
    restarting.value = false
  }
}

async function handleStopAgent() {
  stopping.value = true
  try {
    const { data } = await api.stopAgent(array.value.array_id)
    if (data.outcome === 'pending') ElMessage.info(data.message || '停止结果正在确认')
    else ElMessage.success(data.message || '停止成功')
    await reconcileArrayStatus()
  } catch (error) {
    ElMessage.error(errMsg(error, '停止失败'))
  } finally {
    stopping.value = false
  }
}

async function reconcileArrayStatus() {
  try {
    const { data } = await api.getArrayStatus(array.value.array_id)
    arrayStore.applyStatusUpdate(array.value.array_id, data)
    array.value = arrayStore.currentArray || data
  } catch (error) {
    console.debug('Agent operation status reconciliation failed:', error)
  }
}

// When WebSocket delivers a new alert for this array, prepend to recentAlerts
const seenAlertKeys = new Set()
watch(
  () => alertStore.recentAlerts,
  (newList) => {
    const latest = newList[0]
    if (!latest || !array.value?.array_id) return
    if (latest.array_id !== array.value.array_id) return
    const key = latest.id || `${latest.timestamp}_${latest.observer_name}_${(latest.message || '').slice(0, 50)}`
    if (seenAlertKeys.has(key)) return
    seenAlertKeys.add(key)
    recentAlerts.value.unshift(latest)
    if (recentAlerts.value.length > 20) recentAlerts.value.pop()
  },
  { deep: true }
)

watch(
  () => arrayStore.currentArray,
  (next) => {
    if (next?.array_id === route.params.id) array.value = next
  },
  { deep: true },
)

onMounted(() => {
  loadTags()
  loadArray()
})

onUnmounted(() => {
  if (pageAbortController) {
    pageAbortController.abort()
    pageAbortController = null
  }
})
</script>

<style scoped>
.array-detail {
  min-height: 100%;
  padding: 18px 24px 36px;
  background: #f4f6f8;
  color: #17202a;
}

.array-command-header {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  max-width: 1500px;
  margin: 0 auto 16px;
}

.back-button {
  width: 34px;
  height: 34px;
  border: 1px solid #d9dee5;
  background: #fff;
}

.array-identity {
  min-width: 0;
}

.identity-line,
.identity-meta,
.header-actions,
.surface-header,
.surface-header h2,
.watchers-list,
.agent-flow,
.agent-state-panel {
  display: flex;
  align-items: center;
}

.identity-line {
  gap: 10px;
}

.identity-line h1 {
  overflow: hidden;
  margin: 0;
  font-size: 21px;
  font-weight: 680;
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-dot {
  flex: 0 0 auto;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #9aa4b2;
  box-shadow: 0 0 0 4px #e5e9ee;
}

.status-dot.is-online {
  background: #16825d;
  box-shadow: 0 0 0 4px #dcefe8;
}

.array-address {
  padding: 2px 7px;
  border: 1px solid #d9dee5;
  border-radius: 3px;
  color: #566271;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
}

.identity-meta {
  gap: 14px;
  margin-top: 4px;
  color: #748091;
  font-size: 12px;
}

.identity-meta span + span::before {
  content: '';
  display: inline-block;
  width: 3px;
  height: 3px;
  margin: 0 8px 2px 0;
  border-radius: 50%;
  background: #aeb6c1;
}

.header-actions {
  gap: 8px;
}

.signal-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  max-width: 1500px;
  margin: 0 auto 12px;
  border: 1px solid #dfe3e8;
  border-radius: 6px;
  background: #fff;
  overflow: hidden;
}

.signal-item {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 2px 12px;
  padding: 13px 16px;
  border: 0;
  border-right: 1px solid #e7eaee;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.signal-item:last-child {
  border-right: 0;
}

.signal-item:not(.signal-static):hover {
  background: #f8fafb;
}

.signal-item strong {
  grid-row: 1 / span 2;
  grid-column: 2;
  align-self: center;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 24px;
  line-height: 1;
}

.signal-item .signal-state,
.signal-item .signal-time {
  font-family: inherit;
  font-size: 15px;
}

.signal-label {
  color: #344050;
  font-size: 12px;
  font-weight: 650;
}

.signal-item > span:last-child {
  color: #8993a1;
  font-size: 11px;
}

.signal-danger strong {
  color: #c43c3c;
}

.workspace-tabs {
  max-width: 1500px;
  margin: 0 auto;
}

.workspace-tabs :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 12px;
  border: 1px solid #dfe3e8;
  border-radius: 6px 6px 0 0;
  background: #fff;
}

.workspace-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.workspace-tabs :deep(.el-tabs__item) {
  height: 46px;
  padding: 0 18px;
  color: #596575;
  font-size: 13px;
}

.workspace-tabs :deep(.el-tabs__item.is-active) {
  color: #185c88;
  font-weight: 650;
}

.workspace-tabs :deep(.el-tabs__active-bar) {
  height: 3px;
  background: #1677a7;
}

.workspace-tabs :deep(.el-tabs__content) {
  padding-top: 12px;
}

.overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(280px, 0.8fr);
  gap: 12px;
}

.surface {
  min-width: 0;
  padding: 18px;
  border: 1px solid #dfe3e8;
  border-radius: 6px;
  background: #fff;
}

.surface-header {
  justify-content: space-between;
  gap: 12px;
  min-height: 32px;
  margin-bottom: 14px;
}

.surface-header.compact {
  min-height: 28px;
}

.surface-header h2 {
  gap: 7px;
  margin: 0;
  color: #24303e;
  font-size: 15px;
  font-weight: 680;
}

.surface-kicker {
  display: block;
  margin-bottom: 3px;
  color: #8b95a3;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 9px;
}

.surface-count {
  min-width: 30px;
  color: #697586;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 25px;
  text-align: right;
}

.surface-count.has-danger {
  color: #c43c3c;
}

.surface-note {
  color: #8792a0;
  font-size: 12px;
}

.issues-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  max-height: 340px;
  overflow-y: auto;
}

.issue-item {
  padding: 11px 12px;
  border: 1px solid #e4e8ed;
  border-left: 3px solid #c78a2f;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
  transition: border-color 160ms ease, background-color 160ms ease;
}

.issue-item:hover {
  border-color: #bdc6d1;
  background: #fafbfc;
}

.issue-error,
.issue-critical {
  border-left-color: #c43c3c;
}

.issue-suppressed {
  opacity: 0.65;
  border-left-color: #8b95a3;
}

.issue-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  gap: 8px;
  margin-bottom: 5px;
}

.issue-title {
  color: #25313f;
  font-size: 13px;
  font-weight: 680;
}

.issue-message {
  overflow: hidden;
  color: #657181;
  font-size: 12px;
  line-height: 1.5;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.issue-observer {
  padding: 1px 5px;
  border-radius: 3px;
  background: #f0f2f5;
  color: #737e8c;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
}

.issue-since {
  color: #8993a1;
  font-size: 11px;
}

.issue-ack-btn {
  margin-left: auto;
  font-size: 11px;
}

.issues-empty {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 120px;
  padding: 20px;
  color: #16825d;
  background: #f5faf8;
}

.issues-empty strong,
.issues-empty span {
  display: block;
}

.issues-empty strong {
  margin-bottom: 4px;
  color: #275044;
  font-size: 14px;
}

.issues-empty span {
  color: #71847e;
  font-size: 12px;
}

.context-surface {
  grid-column: 2;
  grid-row: 1;
}

.context-list {
  margin: 0;
}

.context-list > div {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  align-items: center;
  min-height: 38px;
  border-bottom: 1px solid #edf0f3;
}

.context-list dt,
.context-label {
  color: #8792a0;
  font-size: 11px;
}

.context-list dd {
  min-width: 0;
  margin: 0;
  color: #344050;
  font-size: 12px;
}

.context-list :deep(.el-select) {
  width: 100%;
}

.watchers-block {
  margin-top: 18px;
}

.context-label {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 8px;
}

.watchers-list {
  flex-wrap: wrap;
  gap: 6px;
}

.ai-surface,
.alerts-surface {
  grid-column: 1 / -1;
}

.ai-surface {
  border-left: 3px solid #567c96;
}

.ai-state,
.ai-placeholder {
  color: #6f7b89;
  font-size: 13px;
}

.ai-state {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ai-placeholder {
  margin: 0;
}

.ai-summary-text {
  color: #394657;
  font-size: 13px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.workspace-stack {
  display: grid;
  gap: 12px;
}

.log-surface {
  min-height: 560px;
  padding: 0;
  overflow: hidden;
}

.log-surface :deep(.log-viewer) {
  height: 560px;
}

.disconnected-state {
  min-height: 220px;
}

.agent-surface {
  max-width: 760px;
}

.deployment-notice {
  margin-bottom: 18px;
}

.agent-state-panel {
  gap: 14px;
  margin-bottom: 22px;
  padding-bottom: 18px;
  border-bottom: 1px solid #e5e8ec;
}

.agent-state-panel span,
.agent-state-panel strong {
  display: block;
}

.agent-state-panel span {
  color: #84909f;
  font-size: 11px;
}

.agent-state-panel strong {
  margin-top: 3px;
  color: #2e3947;
  font-size: 15px;
}

.agent-state-mark {
  width: 12px;
  height: 40px;
  border-radius: 2px;
  background: #aeb6c1;
}

.agent-state-mark.running {
  background: #16825d;
}

.agent-flow {
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

@media (max-width: 980px) {
  .array-detail {
    padding: 14px;
  }

  .signal-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .signal-item:nth-child(2) {
    border-right: 0;
  }

  .signal-item:nth-child(-n + 2) {
    border-bottom: 1px solid #e7eaee;
  }

  .overview-grid {
    grid-template-columns: 1fr;
  }

  .context-surface,
  .ai-surface,
  .alerts-surface {
    grid-column: 1;
    grid-row: auto;
  }
}

@media (max-width: 640px) {
  .array-command-header {
    grid-template-columns: 34px minmax(0, 1fr);
  }

  .header-actions {
    grid-column: 1 / -1;
    justify-content: flex-end;
  }

  .array-address {
    display: none;
  }

  .identity-meta {
    overflow: hidden;
    white-space: nowrap;
  }

  .workspace-tabs :deep(.el-tabs__item) {
    padding: 0 11px;
    font-size: 12px;
  }

  .signal-item {
    padding: 11px 12px;
  }

  .signal-item strong {
    font-size: 20px;
  }

  .surface {
    padding: 14px;
  }
}
</style>
