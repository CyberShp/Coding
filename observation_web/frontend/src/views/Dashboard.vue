<template>
  <div class="dashboard">
    <!-- Page Header -->
    <div class="dashboard-header">
      <h2>仪表盘</h2>
      <div class="header-actions">
        <el-select
          v-model="dashboardL1Filter"
          placeholder="全部一级标签"
          clearable
          size="small"
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
        <el-button size="small" @click="manualRefresh" :loading="loading">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
    </div>

    <!-- Active Test Task Banner -->
    <el-card v-if="activeTask" class="active-task-banner">
      <div class="task-banner-content">
        <el-tag type="success" effect="dark" size="small">进行中</el-tag>
        <span class="task-name">{{ activeTask.name }}</span>
        <el-tag size="small" effect="plain">{{ activeTask.task_type_label || activeTask.task_type }}</el-tag>
        <span class="task-duration">已运行 {{ taskDuration }}</span>
        <el-button size="small" type="warning" plain @click="$router.push('/test-tasks')">管理</el-button>
      </div>
    </el-card>

    <!-- ===================== Layer 1: Global Health Summary ===================== -->
    <div class="layer layer-summary">
      <div class="summary-cards">
        <div class="summary-card clickable" @click="$router.push('/arrays')">
          <div class="summary-icon icon-primary">
            <el-icon size="22"><Cpu /></el-icon>
          </div>
          <div class="summary-body">
            <template v-if="!initialLoaded">
              <div class="skeleton-value" />
            </template>
            <template v-else>
              <div class="summary-value">{{ filteredTotalCount }}</div>
            </template>
            <div class="summary-label">纳管阵列总数</div>
          </div>
        </div>

        <div class="summary-card clickable" @click="$router.push('/arrays')">
          <div class="summary-icon icon-success">
            <el-icon size="22"><Monitor /></el-icon>
          </div>
          <div class="summary-body">
            <template v-if="!initialLoaded">
              <div class="skeleton-value" />
            </template>
            <template v-else>
              <div class="summary-value">{{ onlineAgentCount }}</div>
            </template>
            <div class="summary-label">在线 Agent 数</div>
          </div>
        </div>

        <div class="summary-card">
          <div class="summary-icon icon-info">
            <el-icon size="22"><Clock /></el-icon>
          </div>
          <div class="summary-body">
            <template v-if="!initialLoaded">
              <div class="skeleton-value" />
            </template>
            <template v-else>
              <div class="freshness-row">
                <span class="freshness-dot dot-fresh" />
                <span class="freshness-num">{{ freshness.fresh }}</span>
                <span class="freshness-dot dot-stale" />
                <span class="freshness-num">{{ freshness.stale }}</span>
                <span class="freshness-dot dot-unknown" />
                <span class="freshness-num">{{ freshness.unknown }}</span>
              </div>
            </template>
            <div class="summary-label">数据新鲜度</div>
          </div>
        </div>

        <div class="summary-card clickable" @click="$router.push({ path: '/alerts', query: { level: 'error' } })">
          <div class="summary-icon icon-danger">
            <el-icon size="22"><Warning /></el-icon>
          </div>
          <div class="summary-body">
            <template v-if="!initialLoaded">
              <div class="skeleton-value" />
            </template>
            <template v-else>
              <div class="summary-value">{{ activeAnomalyCount }}</div>
            </template>
            <div class="summary-label">活跃异常数</div>
          </div>
        </div>

        <div class="summary-card clickable" @click="$router.push('/alerts')">
          <div class="summary-icon icon-warning">
            <el-icon size="22"><Bell /></el-icon>
          </div>
          <div class="summary-body">
            <template v-if="!initialLoaded">
              <div class="skeleton-value" />
            </template>
            <template v-else>
              <div class="summary-value">{{ needsManualCount }}</div>
            </template>
            <div class="summary-label">需要人工处理</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===================== Layer 2: Problem Focus ===================== -->
    <div class="layer layer-focus">
      <div class="focus-cards">
        <div
          class="focus-card focus-anomaly"
          :class="{ 'has-items': realAnomalyPending > 0 }"
          @click="$router.push({ path: '/alerts', query: { level: 'error' } })"
        >
          <div class="focus-count">{{ realAnomalyPending }}</div>
          <div class="focus-label">真异常待处理</div>
        </div>
        <div
          class="focus-card focus-expected"
          :class="{ 'has-items': !!activeTask }"
          @click="$router.push('/test-tasks')"
        >
          <div class="focus-count">{{ activeTask ? 1 : 0 }}</div>
          <div class="focus-label">当前测试预期</div>
        </div>
        <div
          class="focus-card focus-collection"
          :class="{ 'has-items': collectionFailureCount > 0 }"
          @click="$router.push('/arrays')"
        >
          <div class="focus-count">{{ collectionFailureCount }}</div>
          <div class="focus-label">采集失败</div>
        </div>
        <div
          class="focus-card focus-recovered"
          :class="{ 'has-items': recentRecoveryCount > 0 }"
        >
          <div class="focus-count">{{ recentRecoveryCount }}</div>
          <div class="focus-label">最近恢复</div>
        </div>
      </div>
    </div>

    <!-- ===================== Layer 3: Array Grid + Alert Stream ===================== -->
    <el-row :gutter="20" class="layer layer-grid">
      <el-col :span="16">
        <el-card class="content-card">
          <template #header>
            <div class="card-header">
              <span>阵列概览</span>
              <el-button text size="small" @click="loadArrays">
                <el-icon><Refresh /></el-icon>
              </el-button>
            </div>
          </template>

          <!-- Skeleton loading -->
          <div v-if="!initialLoaded" class="array-grid">
            <div v-for="n in 6" :key="n" class="array-card skeleton-card">
              <div class="skeleton-bar" style="width: 60%; height: 14px;" />
              <div class="skeleton-bar" style="width: 40%; height: 12px; margin-top: 6px;" />
              <div class="skeleton-bar" style="width: 80%; height: 12px; margin-top: 10px;" />
            </div>
          </div>

          <!-- Array cards -->
          <div v-else-if="filteredArrays.length > 0" class="array-grid">
            <div
              v-for="arr in filteredArrays"
              :key="arr.array_id"
              class="array-card"
              @click="$router.push(`/arrays/${arr.array_id}`)"
            >
              <div class="array-card-top">
                <div class="array-name-row">
                  <span class="status-dot" :class="getStatusDotClass(arr)" />
                  <span class="array-display-name">{{ arr.display_name || arr.name }}</span>
                  <el-badge
                    v-if="getActiveIssueCount(arr) > 0"
                    :value="getActiveIssueCount(arr)"
                    type="danger"
                    class="issue-badge"
                  />
                </div>
                <div class="array-ip">{{ arr.host }}</div>
              </div>
              <div class="array-card-tags">
                <el-tag
                  v-if="arr.tag_l1_name"
                  size="small"
                  effect="plain"
                  :color="arr.tag_color || undefined"
                  class="dim-tag"
                >{{ arr.tag_l1_name }}</el-tag>
                <el-tag
                  v-if="arr.tag_l2_name"
                  size="small"
                  effect="plain"
                  class="dim-tag"
                >{{ arr.tag_l2_name }}</el-tag>
                <el-tag
                  v-if="arr.env_type"
                  size="small"
                  type="info"
                  effect="plain"
                  class="dim-tag"
                >{{ arr.env_type }}</el-tag>
                <el-tag
                  v-if="arr.site"
                  size="small"
                  type="info"
                  effect="plain"
                  class="dim-tag"
                >{{ arr.site }}</el-tag>
              </div>
              <div class="array-card-bottom">
                <span class="agent-indicator" :class="{ online: arr.agent_healthy, degraded: arr.agent_running && !arr.agent_healthy }">
                  <span class="agent-dot" />
                  Agent
                </span>
                <span class="freshness-indicator" :class="getFreshnessClass(arr)">
                  {{ getFreshnessLabel(arr) }}
                </span>
                <span class="last-report" v-if="arr.last_heartbeat_at || arr.last_refresh">
                  {{ formatRelativeTime(arr.last_heartbeat_at || arr.last_refresh) }}
                </span>
              </div>
            </div>
          </div>

          <el-empty v-else-if="preferencesStore.personalViewActive" description="未配置关注的阵列或标签">
            <el-button type="primary" @click="$router.push('/settings')">配置个人视图</el-button>
          </el-empty>
          <el-empty v-else description="暂无阵列">
            <el-button type="primary" @click="$router.push('/arrays')">添加阵列</el-button>
          </el-empty>
        </el-card>
      </el-col>

      <!-- Alert Stream -->
      <el-col :span="8">
        <el-card class="content-card alerts-card">
          <template #header>
            <div class="card-header">
              <span>实时告警流</span>
              <el-badge
                :value="alertStore.wsConnected ? 'LIVE' : 'OFFLINE'"
                :type="alertStore.wsConnected ? 'success' : 'danger'"
                class="ws-badge"
              />
            </div>
          </template>
          <div class="alerts-list">
            <FoldedAlertList
              :alerts="filteredAlerts"
              :show-array-id="true"
              :compact="true"
              @select="openAlertDrawer"
              @ack="handleAck"
              @undo-ack="handleUndoAck"
              @modify-ack="handleModifyAck"
            />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- ===================== Layer 4: Trend Area ===================== -->
    <el-row :gutter="20" class="layer layer-trends">
      <el-col :span="16">
        <el-card class="content-card chart-card">
          <template #header>
            <span>24h 异常趋势</span>
          </template>
          <v-chart :option="trendChartOption" autoresize style="height: 260px" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card class="content-card chart-card">
          <template #header>
            <span>阵列健康分布</span>
          </template>
          <v-chart :option="healthPieOption" autoresize style="height: 260px" />
        </el-card>
      </el-col>
    </el-row>

    <!-- Alert Detail Drawer -->
    <AlertDetailDrawer v-model="drawerVisible" :alert="selectedAlert" @ack-changed="onAckChanged" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
import { ElMessage } from 'element-plus'
import { Cpu, Bell, Warning, Refresh, Monitor, Clock } from '@element-plus/icons-vue'
import { useArrayStore } from '../stores/arrays'
import { useAlertStore } from '../stores/alerts'
import { usePreferencesStore } from '../stores/preferences'
import api from '../api'
import AlertDetailDrawer from '@/components/AlertDetailDrawer.vue'
import FoldedAlertList from '@/components/FoldedAlertList.vue'
import { translateAlert, getObserverName, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'

use([CanvasRenderer, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent])

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
const initialLoaded = ref(false)
const l1Tags = ref([])
const dashboardL1Filter = ref(null)
let refreshTimer = null
let pageAbortController = null

// Freshness thresholds (minutes)
const FRESH_THRESHOLD_MIN = 5
const STALE_THRESHOLD_MIN = 30

// Allowed array IDs (personal view)
const allowedArrayIds = computed(() => {
  if (!preferencesStore.personalViewActive) return null
  const watchedIds = preferencesStore.watchedArrayIds || []
  const watchedTags = new Set(preferencesStore.watchedTagIds || [])
  return new Set([
    ...watchedIds,
    ...arrayStore.arrays
      .filter(a => a.tag_id != null && watchedTags.has(a.tag_id))
      .map(a => a.array_id),
  ])
})

// Filtered arrays (L1 tag + personal view)
const filteredArrays = computed(() => {
  let result = arrayStore.arrays

  if (dashboardL1Filter.value) {
    const l1Id = dashboardL1Filter.value
    const childTagIds = new Set()
    l1Tags.value.forEach(t => { if (t.id === l1Id) childTagIds.add(t.id) })
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

  const allowed = allowedArrayIds.value
  if (allowed) {
    if (allowed.size === 0) return []
    result = result.filter(arr => allowed.has(arr.array_id))
  }

  return result
})

// Alert filters
const RECENT_ALERTS_CUTOFF_MS = 2 * 60 * 60 * 1000

const filteredAlerts = computed(() => {
  const cutoff = Date.now() - RECENT_ALERTS_CUTOFF_MS
  const within2h = alertStore.recentAlerts.filter(
    a => new Date(a.timestamp || 0).getTime() > cutoff,
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

// Layer 1 computed stats
const filteredTotalCount = computed(() => filteredArrays.value.length)

const onlineAgentCount = computed(() =>
  filteredArrays.value.filter(a => a.agent_healthy).length,
)

const filteredConnectedCount = computed(() =>
  filteredArrays.value.filter(a => a.state === 'connected').length,
)

function getArrayFreshness(arr) {
  const ts = arr.last_heartbeat_at || arr.last_refresh
  if (!ts) return 'unknown'
  const age = (Date.now() - new Date(ts).getTime()) / 60000
  if (age <= FRESH_THRESHOLD_MIN) return 'fresh'
  if (age <= STALE_THRESHOLD_MIN) return 'stale'
  return 'unknown'
}

const freshness = computed(() => {
  const counts = { fresh: 0, stale: 0, unknown: 0 }
  filteredArrays.value.forEach(a => { counts[getArrayFreshness(a)]++ })
  return counts
})

const activeAnomalyCount = computed(() =>
  filteredArrays.value.reduce((n, a) => n + (a.active_issues || []).length, 0),
)

const needsManualCount = computed(() =>
  filteredAlerts.value.filter(a => !a.is_acked && (a.level === 'error' || a.level === 'critical')).length,
)

// Layer 2 computed stats
const realAnomalyPending = computed(() =>
  filteredAlerts.value.filter(a => !a.is_acked && (a.level === 'error' || a.level === 'critical')).length,
)

const collectionFailureCount = computed(() =>
  filteredArrays.value.filter(a =>
    (a.agent_deployed && !a.agent_healthy && a.state === 'connected') ||
    (a.state !== 'connected' && a.state !== 'degraded'),
  ).length,
)

const recentRecoveryCount = computed(() => {
  const cutoff = Date.now() - 2 * 60 * 60 * 1000
  return filteredAlerts.value.filter(a => {
    if (!a.timestamp) return false
    const ts = new Date(a.timestamp).getTime()
    if (ts < cutoff) return false
    const msg = (a.message || '').toLowerCase()
    return msg.includes('recover') || msg.includes('resume') || msg.includes('\u6062\u590d')
  }).length
})

// Layer 3 helpers
function getActiveIssueCount(arr) {
  return (arr.active_issues || []).length
}

function getStatusDotClass(arr) {
  if (arr.state !== 'connected') return 'dot-offline'
  const issues = arr.active_issues || []
  if (issues.length > 0) {
    return issues.some(i => i.level === 'error' || i.level === 'critical')
      ? 'dot-error' : 'dot-warning'
  }
  const s = arr.recent_alert_summary || {}
  if ((s.error || 0) + (s.critical || 0) > 0) return 'dot-warning'
  return 'dot-ok'
}

function getFreshnessClass(arr) {
  return 'freshness-' + getArrayFreshness(arr)
}

function getFreshnessLabel(arr) {
  const f = getArrayFreshness(arr)
  if (f === 'fresh') return '\u5b9e\u65f6'
  if (f === 'stale') return '\u5ef6\u8fdf'
  return '\u672a\u77e5'
}

function formatRelativeTime(timestamp) {
  if (!timestamp) return ''
  const sec = (Date.now() - new Date(timestamp).getTime()) / 1000
  if (sec < 0) return '\u521a\u521a'
  if (sec < 60) return `${Math.round(sec)}s \u524d`
  if (sec < 3600) return `${Math.floor(sec / 60)}m \u524d`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h \u524d`
  return `${Math.floor(sec / 86400)}d \u524d`
}

// Existing status helpers (kept for compatibility)
function getArrayStatusClass(arr) {
  if (arr.state !== 'connected') return 'status-offline'
  const issues = arr.active_issues || []
  if (issues.length > 0) {
    const hasError = issues.some(i => i.level === 'error' || i.level === 'critical')
    if (hasError) return 'status-error'
    return 'status-warning'
  }
  const s = arr.recent_alert_summary || {}
  const recentErrors = (s.error || 0) + (s.critical || 0)
  if (recentErrors > 0) return 'status-attention'
  const recentWarnings = s.warning || 0
  if (recentWarnings > 0) return 'status-warning'
  return 'status-ok'
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

function getObserverLabel(name) {
  return getObserverName(name)
}

function getAlertSummary(alert) {
  const result = translateAlert(alert)
  return result.summary || alert.message
}

function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

// Layer 4: chart options
const trendChartOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: stats.value?.trend_24h?.map(t => t.hour) || [],
    axisLabel: { fontSize: 11, color: '#909399' },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    axisLabel: { fontSize: 11, color: '#909399' },
    splitLine: { lineStyle: { color: '#f0f0f0' } },
  },
  series: [{
    name: '\u5f02\u5e38\u6570',
    type: 'line',
    smooth: true,
    symbol: 'circle',
    symbolSize: 4,
    lineStyle: { width: 2, color: '#f56c6c' },
    itemStyle: { color: '#f56c6c' },
    areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
      { offset: 0, color: 'rgba(245,108,108,0.25)' },
      { offset: 1, color: 'rgba(245,108,108,0.02)' },
    ]}},
    data: stats.value?.trend_24h?.map(t => t.count) || [],
  }],
}))

const healthPieOption = computed(() => {
  const ok = filteredArrays.value.filter(a => getArrayStatusClass(a) === 'status-ok').length
  const warn = filteredArrays.value.filter(a =>
    ['status-warning', 'status-attention'].includes(getArrayStatusClass(a)),
  ).length
  const err = filteredArrays.value.filter(a => getArrayStatusClass(a) === 'status-error').length
  const offline = filteredArrays.value.filter(a => getArrayStatusClass(a) === 'status-offline').length

  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: {
      bottom: 0,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { fontSize: 12, color: '#606266' },
    },
    series: [{
      type: 'pie',
      radius: ['40%', '65%'],
      center: ['50%', '45%'],
      avoidLabelOverlap: true,
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 13, fontWeight: 'bold' } },
      data: [
        { value: ok, name: '\u5065\u5eb7', itemStyle: { color: '#67c23a' } },
        { value: warn, name: '\u544a\u8b66', itemStyle: { color: '#e6a23c' } },
        { value: err, name: '\u5f02\u5e38', itemStyle: { color: '#f56c6c' } },
        { value: offline, name: '\u79bb\u7ebf', itemStyle: { color: '#c0c4cc' } },
      ].filter(d => d.value > 0),
    }],
  }
})

// Alert actions
function openAlertDrawer(alert) {
  selectedAlert.value = alert
  drawerVisible.value = true
}

async function handleAck({ alertIds, ackType = 'dismiss' }) {
  try {
    await api.ackAlerts(alertIds, '', { ack_type: ackType })
    ElMessage.success('\u5df2\u786e\u8ba4')
    alertStore.recentAlerts.forEach(a => {
      if (alertIds.includes(a.id)) a.is_acked = true
    })
  } catch (e) {
    ElMessage.error('\u786e\u8ba4\u5931\u8d25: ' + (e.response?.data?.detail || e.message))
  }
}

async function handleUndoAck({ alertIds }) {
  try {
    await api.batchUndoAck(alertIds)
    ElMessage.success('\u5df2\u64a4\u9500\u786e\u8ba4')
    alertStore.recentAlerts.forEach(a => {
      if (alertIds.includes(a.id)) a.is_acked = false
    })
  } catch (e) {
    ElMessage.error('\u64a4\u9500\u5931\u8d25: ' + (e.response?.data?.detail || e.message))
  }
}

async function handleModifyAck({ alertIds, ackType }) {
  try {
    await api.batchModifyAck(alertIds, ackType)
    ElMessage.success('\u5df2\u66f4\u6539\u786e\u8ba4\u7c7b\u578b')
  } catch (e) {
    ElMessage.error('\u66f4\u6539\u5931\u8d25: ' + (e.response?.data?.detail || e.message))
  }
}

function onAckChanged({ alertId, acked }) {
  const a = alertStore.recentAlerts.find(x => x.id === alertId)
  if (a) a.is_acked = acked
}

// Data loading
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
  initialLoaded.value = true
}

async function silentRefresh() {
  if (document.hidden || loading.value) return
  loading.value = true
  try {
    await loadData()
  } catch {
    // Silent fail
  } finally {
    loading.value = false
  }
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
  refreshTimer = setInterval(silentRefresh, 30000)
  // Connect status WebSocket for real-time updates
  arrayStore.connectStatusWebSocket()
})

onUnmounted(() => {
  if (pageAbortController) {
    pageAbortController.abort()
    pageAbortController = null
  }
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  arrayStore.disconnectStatusWebSocket()
})
</script>

<style scoped>
/* Base */
.dashboard {
  padding: 20px 24px;
  max-width: 1600px;
  margin: 0 auto;
}

.dashboard-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.dashboard-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.layer {
  margin-bottom: 20px;
}

/* Active task banner */
.active-task-banner {
  margin-bottom: 16px;
  border-left: 3px solid #67c23a;
}

.task-banner-content {
  display: flex;
  align-items: center;
  gap: 10px;
}

.task-name {
  font-weight: 600;
  font-size: 15px;
}

.task-duration {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-left: auto;
}

/* Layer 1: Summary cards */
.summary-cards {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}

.summary-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px 18px;
  display: flex;
  align-items: center;
  gap: 14px;
  transition: all 0.2s ease;
}

.summary-card.clickable {
  cursor: pointer;
}

.summary-card.clickable:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.summary-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.icon-primary { background: #409eff; }
.icon-success { background: #67c23a; }
.icon-info    { background: #909399; }
.icon-danger  { background: #f56c6c; }
.icon-warning { background: #e6a23c; }

.summary-body {
  min-width: 0;
}

.summary-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}

.summary-label {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
  white-space: nowrap;
}

.skeleton-value {
  width: 48px;
  height: 24px;
  border-radius: 4px;
  background: linear-gradient(90deg, #f0f0f0 25%, #e8e8e8 50%, #f0f0f0 75%);
  background-size: 200% 100%;
  animation: skeleton-pulse 1.5s ease infinite;
}

@keyframes skeleton-pulse {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Freshness dots */
.freshness-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.freshness-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.freshness-num {
  font-size: 16px;
  font-weight: 700;
  color: #303133;
  margin-right: 6px;
}

.dot-fresh   { background: #67c23a; }
.dot-stale   { background: #e6a23c; }
.dot-unknown { background: #c0c4cc; }

/* Layer 2: Focus cards */
.focus-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.focus-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
  border-left: 3px solid transparent;
}

.focus-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.focus-card.has-items.focus-anomaly    { border-left-color: #f56c6c; background: #fef0f0; }
.focus-card.has-items.focus-expected   { border-left-color: #409eff; background: #ecf5ff; }
.focus-card.has-items.focus-collection { border-left-color: #e6a23c; background: #fdf6ec; }
.focus-card.has-items.focus-recovered  { border-left-color: #67c23a; background: #f0f9eb; }

.focus-count {
  font-size: 22px;
  font-weight: 700;
  color: #303133;
  min-width: 28px;
}

.focus-label {
  font-size: 13px;
  color: #606266;
  white-space: nowrap;
}

/* Layer 3: Array grid */
.content-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.array-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.array-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.array-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border-color: #d0d3d9;
}

.skeleton-card {
  cursor: default;
  pointer-events: none;
}

.skeleton-bar {
  border-radius: 4px;
  background: linear-gradient(90deg, #f0f0f0 25%, #e8e8e8 50%, #f0f0f0 75%);
  background-size: 200% 100%;
  animation: skeleton-pulse 1.5s ease infinite;
}

.array-card-top {
  margin-bottom: 8px;
}

.array-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.dot-ok      { background: #67c23a; }
.status-dot.dot-warning  { background: #e6a23c; }
.status-dot.dot-error    { background: #f56c6c; }
.status-dot.dot-offline  { background: #c0c4cc; }

.array-display-name {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.issue-badge {
  flex-shrink: 0;
}

.issue-badge :deep(.el-badge__content) {
  font-size: 10px;
}

.array-ip {
  font-size: 12px;
  color: #909399;
  margin-left: 16px;
  margin-top: 2px;
}

.array-card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
  min-height: 22px;
}

.dim-tag {
  font-size: 11px;
  height: 20px;
  line-height: 18px;
  border-color: #e4e7ed;
}

.array-card-bottom {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  color: #909399;
  border-top: 1px solid #f5f5f5;
  padding-top: 8px;
}

.agent-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #c0c4cc;
}

.agent-indicator.online {
  color: #67c23a;
}

.agent-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.freshness-indicator {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 3px;
}

.freshness-fresh   { color: #67c23a; background: #f0f9eb; }
.freshness-stale   { color: #e6a23c; background: #fdf6ec; }
.freshness-unknown  { color: #909399; background: #f4f4f5; }

.last-report {
  margin-left: auto;
  white-space: nowrap;
}

/* Alert stream */
.alerts-card {
  height: calc(100vh - 280px);
  min-height: 400px;
  overflow: hidden;
}

.alerts-list {
  height: calc(100vh - 360px);
  min-height: 320px;
  overflow-y: auto;
}

.ws-badge {
  margin-left: 8px;
}

.ws-badge :deep(.el-badge__content) {
  font-size: 10px;
}

/* Layer 4: Charts */
.chart-card :deep(.el-card__body) {
  padding: 12px;
}

/* Responsive */
@media (max-width: 1200px) {
  .summary-cards {
    grid-template-columns: repeat(3, 1fr);
  }
  .focus-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .summary-cards {
    grid-template-columns: repeat(2, 1fr);
  }
  .focus-cards {
    grid-template-columns: 1fr;
  }
  .array-grid {
    grid-template-columns: 1fr;
  }
}
</style>