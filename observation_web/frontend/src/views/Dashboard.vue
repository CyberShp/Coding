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
    <ActiveTaskBanner :task="activeTask" :duration="taskDuration" />

    <!-- Layer 1: Global Health Summary -->
    <div class="layer">
      <DashboardSummary
        :initial-loaded="initialLoaded"
        :freshness="freshness"
        :active-anomaly-count="activeAnomalyCount"
        :needs-manual-count="needsManualCount"
        :online-agent-count="onlineAgentCount"
        :filtered-total-count="filteredTotalCount"
      />
    </div>

    <!-- Layer 2: Problem Focus -->
    <div class="layer">
      <DashboardFocusCards
        :real-anomaly-pending="realAnomalyPending"
        :active-task="activeTask"
        :collection-failure-count="collectionFailureCount"
        :recent-recovery-count="recentRecoveryCount"
      />
    </div>

    <!-- Layer 3: Status Heatmap + Alert Stream -->
    <el-row :gutter="20" class="layer">
      <DashboardHeatmap
        :initial-loaded="initialLoaded"
        :filtered-arrays="filteredArrays"
        :filtered-alerts="filteredAlerts"
        :ws-connected="alertStore.wsConnected"
        :personal-view-active="preferencesStore.personalViewActive"
        @refresh="loadArrays"
        @select="openAlertDrawer"
        @ack="handleAck"
        @undo-ack="handleUndoAck"
        @modify-ack="handleModifyAck"
      />
    </el-row>

    <!-- Layer 4: Trend Area -->
    <el-row :gutter="20" class="layer">
      <DashboardCharts
        :trend-chart-option="trendChartOption"
        :health-pie-option="healthPieOption"
      />
    </el-row>

    <!-- Alert Detail Drawer -->
    <AlertDetailDrawer v-model="drawerVisible" :alert="selectedAlert" @ack-changed="onAckChanged" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useArrayStore } from '../stores/arrays'
import { useAlertStore } from '../stores/alerts'
import { usePreferencesStore } from '../stores/preferences'
import api from '../api'
import AlertDetailDrawer from '@/components/AlertDetailDrawer.vue'
import ActiveTaskBanner from '@/components/ActiveTaskBanner.vue'
import DashboardSummary from '@/components/DashboardSummary.vue'
import DashboardFocusCards from '@/components/DashboardFocusCards.vue'
import DashboardHeatmap from '@/components/DashboardHeatmap.vue'
import DashboardCharts from '@/components/DashboardCharts.vue'
import { getArrayFreshness, getArrayStatusClass } from '@/utils/arrayStatus'

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

const RECENT_ALERTS_CUTOFF_MS = 2 * 60 * 60 * 1000

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

// Layer 1 computed stats
const filteredTotalCount = computed(() => filteredArrays.value.length)

const onlineAgentCount = computed(() =>
  filteredArrays.value.filter(a => a.agent_healthy).length,
)

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
    return msg.includes('recover') || msg.includes('resume') || msg.includes('恢复')
  }).length
})

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
    splitLine: { lineStyle: { color: '#d9d9d9' } },
  },
  series: [{
    name: '异常数',
    type: 'line',
    smooth: true,
    symbol: 'circle',
    symbolSize: 4,
    lineStyle: { width: 2, color: '#ff4d4f' },
    itemStyle: { color: '#ff4d4f' },
    areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
      { offset: 0, color: 'rgba(255,77,79,0.3)' },
      { offset: 1, color: 'rgba(255,77,79,0.03)' },
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
        { value: ok, name: '健康', itemStyle: { color: '#52c41a' } },
        { value: warn, name: '告警', itemStyle: { color: '#faad14' } },
        { value: err, name: '异常', itemStyle: { color: '#ff4d4f' } },
        { value: offline, name: '离线', itemStyle: { color: '#8c8c8c' } },
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
</style>
