<template>
  <div class="dashboard">
    <div class="dashboard-header">
      <div>
        <span class="page-kicker">OPERATIONS OVERVIEW</span>
        <h1>运行态势</h1>
        <p>优先展示需要处置的阵列和告警</p>
      </div>
      <div class="header-actions">
        <el-select
          v-model="dashboardL1Filter"
          placeholder="全部一级标签"
          clearable
          style="width: 180px"
          @change="onL1FilterChange"
        >
          <el-option
            v-for="t in l1Tags"
            :key="t.id"
            :label="t.name"
            :value="t.id"
          />
        </el-select>
        <el-button circle aria-label="刷新仪表盘" @click="manualRefresh" :loading="loading">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
    </div>

    <div class="status-ribbon">
      <button class="status-cell danger" type="button" @click="$router.push({ path: '/alerts', query: { level: 'error' } })">
        <span>高优告警</span><strong>{{ filteredAlertErrorCount }}</strong><small>最近 2 小时</small>
      </button>
      <button class="status-cell warning" type="button" @click="$router.push('/arrays')">
        <span>需关注阵列</span><strong>{{ attentionArrays.length }}</strong><small>{{ activeIssueCount }} 项活跃异常</small>
      </button>
      <button class="status-cell" type="button" @click="$router.push('/arrays')">
        <span>离线阵列</span><strong>{{ offlineCount }}</strong><small>{{ filteredConnectedCount }}/{{ filteredTotalCount }} 在线</small>
      </button>
      <button class="status-cell task" type="button" @click="$router.push('/test-tasks')">
        <span>运行任务</span><strong class="task-value">{{ activeTask ? activeTask.name : '无' }}</strong><small>{{ activeTask ? `已运行 ${taskDuration}` : '当前无测试任务' }}</small>
      </button>
    </div>

    <main class="dashboard-grid">
      <section class="panel attention-panel">
        <div class="panel-header">
          <div><span class="panel-kicker">ACTION QUEUE</span><h2>需要处理</h2></div>
          <span class="panel-meta">按严重程度排序</span>
        </div>

        <div v-if="attentionArrays.length" class="attention-list">
          <button v-for="arr in attentionArrays" :key="arr.array_id" class="attention-row" type="button" @click="$router.push(`/arrays/${arr.array_id}`)">
            <span class="severity-rail" :class="getArrayStatusClass(arr)" />
            <span class="array-cell"><strong>{{ arr.name }}</strong><small>{{ arr.host }}</small></span>
            <span class="issue-cell"><strong>{{ getPrimaryIssue(arr) }}</strong><small>{{ getArrayStatusText(arr) }}</small></span>
            <span class="count-cell">{{ (arr.active_issues || []).length || '!' }}</span>
            <span class="row-arrow">›</span>
          </button>
        </div>
        <div v-else-if="filteredArrays.length" class="all-clear">
          <el-icon :size="34"><CircleCheck /></el-icon>
          <div><strong>当前没有待处理阵列</strong><span>所有在线阵列均未发现活跃异常</span></div>
        </div>
        <el-empty v-else-if="preferencesStore.personalViewActive" description="个人视图尚未配置阵列">
          <el-button type="primary" @click="$router.push('/settings')">配置个人视图</el-button>
        </el-empty>
        <el-empty v-else description="暂无阵列"><el-button type="primary" @click="$router.push('/arrays')">添加阵列</el-button></el-empty>
      </section>

      <section class="panel stream-panel">
        <div class="panel-header">
          <div><span class="panel-kicker">LIVE SIGNALS</span><h2>实时告警</h2></div>
          <span class="live-state" :class="{ connected: alertStore.wsConnected }"><i />{{ alertStore.wsConnected ? '实时' : '已断开' }}</span>
        </div>
        <div class="alerts-list">
          <FoldedAlertList :alerts="filteredAlerts" :show-array-id="true" :compact="true" @select="openAlertDrawer" @ack="handleAck" @undo-ack="handleUndoAck" @modify-ack="handleModifyAck" />
        </div>
        <el-button class="stream-more" text type="primary" @click="$router.push('/alerts')">进入告警中心</el-button>
      </section>

      <section class="panel fleet-panel">
        <div class="panel-header">
          <div><span class="panel-kicker">FLEET STATUS</span><h2>全部阵列</h2></div>
          <span class="panel-meta">{{ healthyArrays.length }} 个健康</span>
        </div>
        <div class="fleet-grid">
          <button v-for="arr in filteredArrays" :key="arr.array_id" class="fleet-tile" :class="getArrayStatusClass(arr)" type="button" @click="$router.push(`/arrays/${arr.array_id}`)">
            <span class="fleet-dot" /><span class="fleet-name">{{ arr.name }}</span><span class="fleet-host">{{ arr.host }}</span>
            <span class="fleet-state">{{ getArrayStatusText(arr) }}</span>
          </button>
        </div>
      </section>

      <section class="panel trend-panel">
        <div class="panel-header"><div><span class="panel-kicker">2H TREND</span><h2>告警趋势</h2></div><span class="panel-meta">共 {{ filteredAlertTotal }} 条</span></div>
        <v-chart :option="trendChartOption" autoresize class="trend-chart" />
      </section>
    </main>

    <AlertDetailDrawer v-model="drawerVisible" :alert="selectedAlert" @ack-changed="onAckChanged" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { ElMessage } from 'element-plus'
import { CircleCheck, Refresh } from '@element-plus/icons-vue'
import { useArrayStore } from '../stores/arrays'
import { useAlertStore } from '../stores/alerts'
import { usePreferencesStore } from '../stores/preferences'
import api from '../api'
import AlertDetailDrawer from '@/components/AlertDetailDrawer.vue'
import FoldedAlertList from '@/components/FoldedAlertList.vue'
import { translateAlert, getObserverName, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent])

const arrayStore = useArrayStore()
const alertStore = useAlertStore()
const preferencesStore = usePreferencesStore()

const summary = ref({})
const stats = ref(null)
const activeTask = ref(null)
const taskDuration = ref('')
const drawerVisible = ref(false)
const selectedAlert = ref(null)
const loading = ref(false)
const l1Tags = ref([])
const dashboardL1Filter = ref(null)
let pageAbortController = null

const trendChartOption = computed(() => ({
  tooltip: {
    trigger: 'axis'
  },
  grid: {
    left: '3%',
    right: '4%',
    bottom: '3%',
    containLabel: true
  },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: stats.value?.trend_24h?.map(t => t.hour) || []
  },
  yAxis: {
    type: 'value'
  },
  series: [{
    name: '告警数',
    type: 'line',
    smooth: true,
    areaStyle: {
      opacity: 0.3
    },
    data: stats.value?.trend_24h?.map(t => t.count) || []
  }]
}))

// Build allowed array ID set for personal view (shared by arrays & alerts filtering)
const allowedArrayIds = computed(() => {
  if (!preferencesStore.personalViewActive) return null
  const watchedIds = preferencesStore.watchedArrayIds || []
  const watchedTags = new Set(preferencesStore.watchedTagIds || [])
  return new Set([
    ...watchedIds,
    ...arrayStore.arrays.filter(a => a.tag_id != null && watchedTags.has(a.tag_id)).map(a => a.array_id)
  ])
})

const filteredArrays = computed(() => {
  let result = arrayStore.arrays

  // L1 tag filter (independent of personal view)
  if (dashboardL1Filter.value) {
    const l1Id = dashboardL1Filter.value
    const childTagIds = new Set()
    l1Tags.value.forEach(t => { if (t.id === l1Id) childTagIds.add(t.id) })
    // Also include L2 tags that are children of this L1
    arrayStore.arrays.forEach(a => {
      if (a.tag_l1_name) {
        const matchingL1 = l1Tags.value.find(t => t.id === l1Id)
        if (matchingL1 && a.tag_l1_name === matchingL1.name && a.tag_id) {
          childTagIds.add(a.tag_id)
        }
      }
    })
    result = result.filter(arr => arr.tag_id && childTagIds.has(arr.tag_id))
  }

  // Personal view filter
  const allowed = allowedArrayIds.value
  if (allowed) {
    if (allowed.size === 0) return []
    result = result.filter(arr => allowed.has(arr.array_id))
  }

  return result
})

const filteredTotalCount = computed(() => filteredArrays.value.length)
const filteredConnectedCount = computed(() =>
  filteredArrays.value.filter(a => a.state === 'connected').length
)

const statusWeight = {
  'status-error': 0,
  'status-offline': 1,
  'status-warning': 2,
  'status-attention': 3,
  'status-ok': 4,
}

const attentionArrays = computed(() => filteredArrays.value
  .filter(arr => getArrayStatusClass(arr) !== 'status-ok')
  .slice()
  .sort((a, b) => statusWeight[getArrayStatusClass(a)] - statusWeight[getArrayStatusClass(b)]))

const healthyArrays = computed(() => filteredArrays.value.filter(arr => getArrayStatusClass(arr) === 'status-ok'))
const offlineCount = computed(() => filteredArrays.value.filter(arr => arr.state !== 'connected').length)
const activeIssueCount = computed(() => filteredArrays.value.reduce((sum, arr) => sum + (arr.active_issues || []).length, 0))

const RECENT_ALERTS_CUTOFF_MS = 2 * 60 * 60 * 1000

const filteredAlerts = computed(() => {
  const cutoff = Date.now() - RECENT_ALERTS_CUTOFF_MS
  const within2h = alertStore.recentAlerts.filter(
    a => new Date(a.timestamp || 0).getTime() > cutoff
  )
  const allowed = allowedArrayIds.value
  if (!allowed) return within2h
  if (allowed.size === 0) return []
  return within2h.filter(a => allowed.has(a.array_id))
})

const filteredAlertTotal = computed(() => {
  if (!preferencesStore.personalViewActive) return summary.value.total || summary.value.total_24h || 0
  return filteredAlerts.value.length
})

const filteredAlertErrorCount = computed(() => {
  if (!preferencesStore.personalViewActive) return summary.value.error_count || 0
  return filteredAlerts.value.filter(a => a.level === 'error' || a.level === 'critical').length
})

function getObserverLabel(name) {
  return getObserverName(name)
}

function getAlertSummary(alert) {
  const result = translateAlert(alert)
  return result.summary || alert.message
}

function openAlertDrawer(alert) {
  selectedAlert.value = alert
  drawerVisible.value = true
}

async function handleAck({ alertIds, ackType = 'dismiss' }) {
  try {
    await api.ackAlerts(alertIds, '', { ack_type: ackType })
    ElMessage.success('已确认')
    alertStore.recentAlerts.forEach(a => {
      if (alertIds.includes(a.id)) a.is_acked = true
    })
  } catch (e) {
    ElMessage.error('确认失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function handleUndoAck({ alertIds }) {
  try {
    await api.batchUndoAck(alertIds)
    ElMessage.success('已撤销确认')
    alertStore.recentAlerts.forEach(a => {
      if (alertIds.includes(a.id)) a.is_acked = false
    })
  } catch (e) {
    ElMessage.error('撤销失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function handleModifyAck({ alertIds, ackType }) {
  try {
    await api.batchModifyAck(alertIds, ackType)
    ElMessage.success('已更改确认类型')
  } catch (e) {
    ElMessage.error('更改失败: ' + (e.response?.data?.detail || e.message))
  }
}

function onAckChanged({ alertId, acked }) {
  const a = alertStore.recentAlerts.find(x => x.id === alertId)
  if (a) a.is_acked = acked
}

function getArrayStatusClass(arr) {
  if (arr.state !== 'connected') return 'status-offline'
  // Use active_issues as the primary health indicator
  const issues = arr.active_issues || []
  if (issues.length > 0) {
    const hasError = issues.some(i => i.level === 'error' || i.level === 'critical')
    if (hasError) return 'status-error'
    return 'status-warning'
  }
  // Secondary: check recent alerts in last 2 hours for errors/warnings
  const summary = arr.recent_alert_summary || {}
  const recentErrors = (summary.error || 0) + (summary.critical || 0)
  if (recentErrors > 0) return 'status-attention'
  const recentWarnings = summary.warning || 0
  if (recentWarnings > 0) return 'status-warning'
  return 'status-ok'
}

function getPrimaryIssue(arr) {
  if (arr.state !== 'connected') return '阵列连接中断'
  const issue = (arr.active_issues || [])[0]
  if (issue) return issue.title || issue.message || '发现活跃异常'
  return '近期告警仍需复核'
}

function getArrayStatusText(arr) {
  const labels = {
    'status-error': '严重异常',
    'status-offline': '离线',
    'status-warning': '警告',
    'status-attention': '需复核',
    'status-ok': '正常',
  }
  return labels[getArrayStatusClass(arr)]
}

function getStateTagType(state) {
  return state === 'connected' ? 'success' : 'info'
}

function getLevelType(level) {
  return LEVEL_TAG_TYPES[level] || 'info'
}

function getLevelText(level) {
  return LEVEL_LABELS[level] || level
}

function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

async function loadL1Tags() {
  try {
    const signal = pageAbortController?.signal
    const res = await api.getTags({ signal })
    l1Tags.value = (res.data || []).filter(t => t.level === 1)
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    l1Tags.value = []
  }
}

function onL1FilterChange() {
  loadData()
}

async function loadArrays() {
  try {
    // Load all arrays so we can filter client-side by L1 tag
    const signal = pageAbortController?.signal
    await arrayStore.fetchArrays(null, { signal })
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    console.error('Failed to load arrays:', error)
  }
}

async function loadActiveTask() {
  try {
    const signal = pageAbortController?.signal
    const res = await api.getTestTasks({ status: 'running', limit: 1 }, { signal })
    const running = (res.data || [])[0]
    activeTask.value = running || null
    if (running && running.started_at) {
      const sec = (Date.now() - new Date(running.started_at).getTime()) / 1000
      if (sec < 60) taskDuration.value = `${Math.round(sec)}s`
      else if (sec < 3600) taskDuration.value = `${Math.floor(sec / 60)}m`
      else taskDuration.value = `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
    }
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
  }
}

async function loadData() {
  if (pageAbortController) pageAbortController.abort()
  pageAbortController = new AbortController()
  const { signal } = pageAbortController

  await preferencesStore.load({ signal })
  // Initialize L1 filter from preference if not set manually
  if (dashboardL1Filter.value === null && preferencesStore.dashboardL1TagId) {
    dashboardL1Filter.value = preferencesStore.dashboardL1TagId
  }
  const tasks = [
    loadArrays().catch(e => console.error('Load arrays failed:', e)),
    loadL1Tags().catch(e => console.error('Load tags failed:', e)),
    alertStore.fetchRecentAlerts({ signal }).catch(e => console.error('Load alerts failed:', e)),
    api.getAlertSummary(2, { signal }).then(res => summary.value = res.data).catch(e => console.error('Load summary failed:', e)),
    api.getAlertStats(2, { signal }).then(res => stats.value = res.data).catch(e => console.error('Load stats failed:', e)),
    loadActiveTask(),
  ]

  await Promise.all(tasks)
}

async function manualRefresh() {
  loading.value = true
  try {
    await loadData()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
})

onUnmounted(() => {
  if (pageAbortController) {
    pageAbortController.abort()
    pageAbortController = null
  }
})
</script>

<style scoped>
.dashboard {
  min-height: 100%;
  padding: 22px 24px 36px;
  background: #f4f6f8;
  color: #1f2a37;
}

.dashboard-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  max-width: 1500px;
  margin: 0 auto 18px;
}

.page-kicker,
.panel-kicker {
  color: #8993a1;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 9px;
  letter-spacing: 0;
}

.dashboard-header h1 {
  margin: 3px 0 0;
  color: #182330;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 0;
}

.dashboard-header p {
  margin: 4px 0 0;
  color: #7d8897;
  font-size: 12px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-ribbon {
  display: grid;
  grid-template-columns: repeat(3, minmax(140px, 0.8fr)) minmax(220px, 1.6fr);
  max-width: 1500px;
  margin: 0 auto 12px;
  border: 1px solid #dde2e8;
  border-radius: 6px;
  background: #fff;
  overflow: hidden;
}

.status-cell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px 12px;
  min-height: 70px;
  padding: 13px 16px;
  border: 0;
  border-right: 1px solid #e6e9ed;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.status-cell:last-child {
  border-right: 0;
}

.status-cell:hover {
  background: #f8fafb;
}

.status-cell > span {
  color: #465263;
  font-size: 12px;
  font-weight: 650;
}

.status-cell strong {
  grid-column: 2;
  grid-row: 1 / span 2;
  align-self: center;
  color: #263342;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 26px;
  line-height: 1;
}

.status-cell small {
  color: #8a94a2;
  font-size: 10px;
}

.status-cell.danger strong {
  color: #bd3737;
}

.status-cell.warning strong {
  color: #b47620;
}

.status-cell .task-value {
  max-width: 180px;
  overflow: hidden;
  font-family: inherit;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.75fr) minmax(320px, 0.85fr);
  gap: 12px;
  max-width: 1500px;
  margin: 0 auto;
}

.panel {
  min-width: 0;
  padding: 17px;
  border: 1px solid #dde2e8;
  border-radius: 6px;
  background: #fff;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 32px;
  margin-bottom: 13px;
}

.panel-header h2 {
  margin: 2px 0 0;
  color: #263342;
  font-size: 15px;
  font-weight: 680;
}

.panel-meta {
  color: #8a94a2;
  font-size: 11px;
}

.attention-list {
  border-top: 1px solid #e6e9ed;
}

.attention-row {
  display: grid;
  grid-template-columns: 4px minmax(140px, 0.7fr) minmax(180px, 1.4fr) 34px 14px;
  align-items: stretch;
  width: 100%;
  min-height: 64px;
  padding: 0;
  border: 0;
  border-bottom: 1px solid #e9ecf0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.attention-row:hover {
  background: #f8fafb;
}

.severity-rail {
  width: 3px;
  margin: 11px 0;
  border-radius: 2px;
  background: #9da7b4;
}

.severity-rail.status-error { background: #bd3737; }
.severity-rail.status-warning,
.severity-rail.status-attention { background: #c0842e; }
.severity-rail.status-offline { background: #6f7a88; }

.array-cell,
.issue-cell {
  display: flex;
  min-width: 0;
  flex-direction: column;
  justify-content: center;
  padding: 10px 12px;
}

.array-cell strong,
.issue-cell strong {
  overflow: hidden;
  color: #2c3745;
  font-size: 12px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.array-cell small,
.issue-cell small {
  overflow: hidden;
  margin-top: 4px;
  color: #8993a1;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.array-cell small {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.count-cell,
.row-arrow {
  align-self: center;
  color: #697586;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 15px;
  text-align: center;
}

.row-arrow {
  color: #a0a9b5;
  font-family: inherit;
  font-size: 21px;
}

.all-clear {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 120px;
  padding: 18px;
  color: #187c5a;
  background: #f4faf7;
}

.all-clear strong,
.all-clear span {
  display: block;
}

.all-clear strong {
  margin-bottom: 4px;
  color: #2b5044;
  font-size: 14px;
}

.all-clear span {
  color: #74867f;
  font-size: 11px;
}

.stream-panel {
  grid-column: 2;
  grid-row: 1 / span 2;
  min-height: 520px;
  overflow: hidden;
}

.alerts-list {
  max-height: 570px;
  overflow-y: auto;
}

.live-state {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #9099a6;
  font-size: 10px;
}

.live-state i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #a5adb7;
}

.live-state.connected {
  color: #187c5a;
}

.live-state.connected i {
  background: #1a8a63;
  box-shadow: 0 0 0 3px #dff1e9;
}

.stream-more {
  width: 100%;
  margin-top: 10px;
  border-top: 1px solid #edf0f3;
}

.fleet-panel {
  grid-column: 1;
}

.fleet-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 7px;
}

.fleet-tile {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  min-width: 0;
  padding: 10px;
  border: 1px solid #e3e7ec;
  border-radius: 4px;
  background: #fff;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 150ms ease, background-color 150ms ease;
}

.fleet-tile:hover {
  border-color: #aeb8c4;
  background: #fafbfc;
}

.fleet-dot {
  grid-row: 1 / span 2;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #17835d;
}

.fleet-tile.status-error .fleet-dot { background: #bd3737; }
.fleet-tile.status-warning .fleet-dot,
.fleet-tile.status-attention .fleet-dot { background: #c0842e; }
.fleet-tile.status-offline .fleet-dot { background: #929ba7; }

.fleet-name,
.fleet-host {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fleet-name {
  color: #344050;
  font-size: 11px;
  font-weight: 650;
}

.fleet-host {
  grid-column: 2;
  color: #9099a5;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 9px;
}

.fleet-state {
  grid-column: 3;
  grid-row: 1 / span 2;
  color: #7c8795;
  font-size: 9px;
}

.trend-panel {
  grid-column: 1;
}

.trend-chart {
  height: 220px;
}

@media (max-width: 1100px) {
  .status-ribbon {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .status-cell:nth-child(2) {
    border-right: 0;
  }

  .status-cell:nth-child(-n + 2) {
    border-bottom: 1px solid #e6e9ed;
  }

  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .stream-panel,
  .fleet-panel,
  .trend-panel {
    grid-column: 1;
    grid-row: auto;
  }

  .stream-panel {
    min-height: 0;
  }
}

@media (max-width: 680px) {
  .dashboard {
    padding: 16px 12px 30px;
  }

  .dashboard-header {
    align-items: flex-start;
    gap: 14px;
  }

  .dashboard-header p {
    display: none;
  }

  .header-actions :deep(.el-select) {
    width: 140px !important;
  }

  .status-cell {
    min-height: 62px;
    padding: 10px 12px;
  }

  .status-cell strong {
    font-size: 21px;
  }

  .attention-row {
    grid-template-columns: 4px minmax(110px, 0.8fr) minmax(120px, 1fr) 26px;
  }

  .row-arrow {
    display: none;
  }

  .panel {
    padding: 13px;
  }
}
</style>
