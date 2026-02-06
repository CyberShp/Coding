<template>
  <div class="dashboard">
    <!-- Stats Cards -->
    <el-row :gutter="20" class="stats-row">
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon" style="background: #409eff">
              <el-icon size="28"><Cpu /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ arrayStore.totalCount }}</div>
              <div class="stat-label">总阵列数</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon" style="background: #67c23a">
              <el-icon size="28"><CircleCheck /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ arrayStore.connectedCount }}</div>
              <div class="stat-label">在线阵列</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon" style="background: #e6a23c">
              <el-icon size="28"><Bell /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ summary.total_24h || 0 }}</div>
              <div class="stat-label">24h 告警</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon" style="background: #f56c6c">
              <el-icon size="28"><Warning /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ summary.error_count || 0 }}</div>
              <div class="stat-label">错误告警</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Main Content -->
    <el-row :gutter="20">
      <!-- Array Health Matrix + Trends -->
      <el-col :span="16">
        <!-- Health Matrix -->
        <el-card class="content-card">
          <template #header>
            <div class="card-header">
              <span>阵列健康矩阵</span>
              <el-button text @click="loadArrays">
                <el-icon><Refresh /></el-icon>
              </el-button>
            </div>
          </template>
          <div class="health-matrix" v-if="arrayStore.arrays.length > 0">
            <div
              v-for="arr in arrayStore.arrays"
              :key="arr.array_id"
              class="health-tile"
              :class="getArrayStatusClass(arr)"
              @click="$router.push(`/arrays/${arr.array_id}`)"
            >
              <div class="tile-status-bar" :class="getArrayStatusClass(arr)"></div>
              <div class="tile-content">
                <div class="tile-name">{{ arr.name }}</div>
                <div class="tile-host">{{ arr.host }}</div>
                <div class="tile-meta">
                  <el-tag :type="getStateTagType(arr.state)" size="small" effect="plain">
                    {{ arr.state === 'connected' ? '在线' : '离线' }}
                  </el-tag>
                  <span v-if="arr.agent_running" class="tile-agent-badge">
                    <el-icon color="#67c23a"><CircleCheck /></el-icon>
                    Agent
                  </span>
                </div>
                <div class="tile-observers" v-if="arr.observer_status && Object.keys(arr.observer_status).length > 0">
                  <span 
                    v-for="(obs, name) in arr.observer_status" 
                    :key="name"
                    class="obs-dot"
                    :class="`obs-${obs.status}`"
                    :title="`${name}: ${obs.status}`"
                  ></span>
                </div>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无阵列">
            <el-button type="primary" @click="$router.push('/arrays')">添加阵列</el-button>
          </el-empty>
        </el-card>

        <!-- Observer Summary -->
        <el-card class="content-card" v-if="observerSummary.length > 0">
          <template #header>
            <span>观察点概览</span>
          </template>
          <div class="observer-summary">
            <div v-for="obs in observerSummary" :key="obs.name" class="obs-summary-item">
              <span class="obs-name">{{ getObserverDisplayName(obs.name) }}</span>
              <div class="obs-bar">
                <div class="obs-bar-ok" :style="{ width: obs.okPercent + '%' }"></div>
                <div class="obs-bar-warn" :style="{ width: obs.warnPercent + '%' }"></div>
                <div class="obs-bar-error" :style="{ width: obs.errorPercent + '%' }"></div>
              </div>
              <span class="obs-count">{{ obs.ok }}/{{ obs.total }}</span>
            </div>
          </div>
        </el-card>

        <!-- Alert Trend Chart (multi-line by level) -->
        <el-card class="content-card chart-card">
          <template #header>
            <span>24小时告警趋势</span>
          </template>
          <v-chart :option="trendChartOption" autoresize style="height: 250px" />
        </el-card>
      </el-col>

      <!-- Recent Alerts Stream -->
      <el-col :span="8">
        <el-card class="content-card alerts-card">
          <template #header>
            <div class="card-header">
              <span>实时告警流</span>
              <el-badge :value="alertStore.wsConnected ? 'LIVE' : 'OFFLINE'" 
                        :type="alertStore.wsConnected ? 'success' : 'danger'"
                        class="ws-badge" />
            </div>
          </template>
          <div class="alerts-list">
            <div
              v-for="alert in alertStore.recentAlerts"
              :key="alert.id"
              class="alert-item"
              :class="`alert-${alert.level}`"
            >
              <div class="alert-level">
                <el-tag :type="getLevelType(alert.level)" size="small">
                  {{ getLevelText(alert.level) }}
                </el-tag>
              </div>
              <div class="alert-content">
                <div class="alert-message">{{ alert.message }}</div>
                <div class="alert-meta">
                  {{ alert.observer_name }} · {{ formatTime(alert.timestamp) }}
                </div>
              </div>
            </div>
            <el-empty v-if="alertStore.recentAlerts.length === 0" description="暂无告警" />
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { Cpu, CircleCheck, Bell, Warning, Refresh } from '@element-plus/icons-vue'
import { useArrayStore } from '../stores/arrays'
import { useAlertStore } from '../stores/alerts'
import api from '../api'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent])

const arrayStore = useArrayStore()
const alertStore = useAlertStore()

const summary = ref({})
const stats = ref(null)

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

const OBSERVER_DISPLAY_NAMES = {
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

function getObserverDisplayName(name) {
  return OBSERVER_DISPLAY_NAMES[name] || name
}

const observerSummary = computed(() => {
  const summaryMap = {}
  
  for (const arr of arrayStore.arrays) {
    if (!arr.observer_status) continue
    for (const [name, info] of Object.entries(arr.observer_status)) {
      if (name === '_meta') continue
      if (!summaryMap[name]) {
        summaryMap[name] = { name, ok: 0, warning: 0, error: 0, total: 0 }
      }
      summaryMap[name].total++
      if (info.status === 'ok') summaryMap[name].ok++
      else if (info.status === 'warning') summaryMap[name].warning++
      else if (info.status === 'error') summaryMap[name].error++
    }
  }
  
  return Object.values(summaryMap).map(s => ({
    ...s,
    okPercent: s.total > 0 ? (s.ok / s.total * 100) : 0,
    warnPercent: s.total > 0 ? (s.warning / s.total * 100) : 0,
    errorPercent: s.total > 0 ? (s.error / s.total * 100) : 0,
  }))
})

function getArrayStatusClass(arr) {
  if (arr.state !== 'connected') return 'status-offline'
  if (arr.observer_status) {
    const hasError = Object.values(arr.observer_status).some(s => s.status === 'error')
    if (hasError) return 'status-error'
    const hasWarning = Object.values(arr.observer_status).some(s => s.status === 'warning')
    if (hasWarning) return 'status-warning'
  }
  return 'status-ok'
}

function getStateTagType(state) {
  return state === 'connected' ? 'success' : 'info'
}

function getLevelType(level) {
  const types = {
    info: 'info',
    warning: 'warning',
    error: 'danger',
    critical: 'danger'
  }
  return types[level] || 'info'
}

function getLevelText(level) {
  const texts = {
    info: '信息',
    warning: '警告',
    error: '错误',
    critical: '严重'
  }
  return texts[level] || level
}

function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

async function loadArrays() {
  try {
    await arrayStore.fetchArrays()
  } catch (error) {
    console.error('Failed to load arrays:', error)
  }
}

async function loadData() {
  // Load data in parallel with individual error handling
  // so one failure doesn't block others
  const tasks = [
    loadArrays().catch(e => console.error('Load arrays failed:', e)),
    alertStore.fetchRecentAlerts().catch(e => console.error('Load alerts failed:', e)),
    api.getAlertSummary().then(res => summary.value = res.data).catch(e => console.error('Load summary failed:', e)),
    api.getAlertStats().then(res => stats.value = res.data).catch(e => console.error('Load stats failed:', e)),
  ]
  
  await Promise.all(tasks)
}

onMounted(loadData)
</script>

<style scoped>
.dashboard {
  padding: 20px;
}

.stats-row {
  margin-bottom: 20px;
}

.stat-card {
  border-radius: 8px;
}

.stat-content {
  display: flex;
  align-items: center;
}

.stat-icon {
  width: 60px;
  height: 60px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  margin-right: 16px;
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: #303133;
}

.stat-label {
  font-size: 14px;
  color: #909399;
}

.content-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* Health Matrix */
.health-matrix {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.health-tile {
  border-radius: 8px;
  background: #fff;
  border: 1px solid #e4e7ed;
  cursor: pointer;
  transition: all 0.2s;
  overflow: hidden;
}

.health-tile:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}

.tile-status-bar {
  height: 4px;
  width: 100%;
}

.tile-status-bar.status-ok { background: #67c23a; }
.tile-status-bar.status-warning { background: #e6a23c; }
.tile-status-bar.status-error { background: #f56c6c; }
.tile-status-bar.status-offline { background: #dcdfe6; }

.tile-content {
  padding: 12px 14px;
}

.tile-name {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 2px;
}

.tile-host {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}

.tile-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tile-agent-badge {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  color: #67c23a;
}

.tile-observers {
  display: flex;
  gap: 4px;
  margin-top: 8px;
}

.obs-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #dcdfe6;
}

.obs-ok { background: #67c23a; }
.obs-warning { background: #e6a23c; }
.obs-error { background: #f56c6c; }

/* Observer Summary */
.observer-summary {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.obs-summary-item {
  display: flex;
  align-items: center;
  gap: 12px;
}

.obs-name {
  width: 80px;
  font-size: 13px;
  color: #606266;
  flex-shrink: 0;
}

.obs-bar {
  flex: 1;
  height: 8px;
  background: #f0f0f0;
  border-radius: 4px;
  display: flex;
  overflow: hidden;
}

.obs-bar-ok { background: #67c23a; }
.obs-bar-warn { background: #e6a23c; }
.obs-bar-error { background: #f56c6c; }

.obs-count {
  width: 40px;
  font-size: 12px;
  color: #909399;
  text-align: right;
}

.alerts-card {
  height: calc(100vh - 280px);
  overflow: hidden;
}

.alerts-list {
  max-height: calc(100vh - 350px);
  overflow-y: auto;
}

.alert-item {
  padding: 12px;
  border-left: 3px solid;
  margin-bottom: 8px;
  background: #f5f7fa;
  border-radius: 0 4px 4px 0;
}

.alert-item.alert-info { border-color: #909399; }
.alert-item.alert-warning { border-color: #e6a23c; }
.alert-item.alert-error { border-color: #f56c6c; }
.alert-item.alert-critical { border-color: #f56c6c; }

.alert-level {
  margin-bottom: 4px;
}

.alert-message {
  font-size: 13px;
  color: #303133;
  word-break: break-all;
}

.alert-meta {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.ws-badge :deep(.el-badge__content) {
  font-size: 10px;
}

.chart-card {
  margin-top: 20px;
}
</style>
