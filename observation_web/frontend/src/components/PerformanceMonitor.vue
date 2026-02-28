<template>
  <div class="performance-monitor">
    <!-- Time Range Selector -->
    <div class="toolbar">
      <el-radio-group v-model="timeRange" size="small" @change="loadMetrics">
        <el-radio-button :label="30">30分钟</el-radio-button>
        <el-radio-button :label="60">1小时</el-radio-button>
        <el-radio-button :label="360">6小时</el-radio-button>
        <el-radio-button :label="1440">24小时</el-radio-button>
      </el-radio-group>
      <el-button size="small" @click="loadMetrics" :loading="loading">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
      <el-switch
        v-model="autoRefresh"
        active-text="自动刷新"
        inactive-text=""
        size="small"
        @change="toggleAutoRefresh"
      />
    </div>

    <!-- CPU Chart -->
    <div class="chart-section">
      <h4>CPU0 利用率</h4>
      <v-chart v-if="cpuData.length > 0" :option="cpuChartOption" autoresize style="height: 220px" />
      <div v-else class="empty-hint">
        <el-empty description="暂无 CPU 数据" :image-size="60">
          <template #description>
            <p>暂无 CPU 数据</p>
            <p class="hint-text">请确保 Agent 已部署并正在运行，数据将自动刷新</p>
          </template>
        </el-empty>
      </div>
    </div>

    <!-- Memory Chart -->
    <div class="chart-section">
      <h4>内存使用量</h4>
      <v-chart v-if="memData.length > 0" :option="memChartOption" autoresize style="height: 220px" />
      <div v-else class="empty-hint">
        <el-empty description="暂无内存数据" :image-size="60">
          <template #description>
            <p>暂无内存数据</p>
            <p class="hint-text">请确保 Agent 已部署并正在运行，数据将自动刷新</p>
          </template>
        </el-empty>
      </div>
    </div>

    <!-- Current Stats -->
    <div class="stats-bar" v-if="latestMetrics">
      <div class="stat-item">
        <span class="stat-label">CPU0 当前</span>
        <span class="stat-value" :class="cpuStatusClass">{{ latestMetrics.cpu0 != null ? latestMetrics.cpu0.toFixed(1) + '%' : '-' }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">内存使用</span>
        <span class="stat-value">{{ latestMetrics.mem_used_mb ? (latestMetrics.mem_used_mb / 1024).toFixed(1) + 'GB' : '-' }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">内存总量</span>
        <span class="stat-value">{{ latestMetrics.mem_total_mb ? (latestMetrics.mem_total_mb / 1024).toFixed(1) + 'GB' : '-' }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">数据点数</span>
        <span class="stat-value">{{ totalDataPoints }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  ToolboxComponent,
  DataZoomComponent,
  MarkLineComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
import { Refresh } from '@element-plus/icons-vue'
import api from '../api'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, ToolboxComponent, DataZoomComponent, MarkLineComponent])

const props = defineProps({
  arrayId: { type: String, required: true },
})

const timeRange = ref(60)
const loading = ref(false)
const autoRefresh = ref(true)  // Default to auto-refresh enabled
const metrics = ref([])
let refreshTimer = null

const cpuData = computed(() => {
  return metrics.value
    .filter(m => m.cpu0 != null)
    .map(m => ({
      ts: formatTime(m.ts),
      value: m.cpu0,
    }))
})

const memData = computed(() => {
  return metrics.value
    .filter(m => m.mem_used_mb != null)
    .map(m => ({
      ts: formatTime(m.ts),
      used: m.mem_used_mb,
      total: m.mem_total_mb || 0,
    }))
})

const latestMetrics = computed(() => {
  if (metrics.value.length === 0) return null
  // Find latest CPU and memory values
  let latest = {}
  for (let i = metrics.value.length - 1; i >= 0; i--) {
    const m = metrics.value[i]
    if (m.cpu0 != null && latest.cpu0 == null) latest.cpu0 = m.cpu0
    if (m.mem_used_mb != null && latest.mem_used_mb == null) {
      latest.mem_used_mb = m.mem_used_mb
      latest.mem_total_mb = m.mem_total_mb
    }
    if (latest.cpu0 != null && latest.mem_used_mb != null) break
  }
  return Object.keys(latest).length > 0 ? latest : null
})

const totalDataPoints = computed(() => metrics.value.length)

const cpuStatusClass = computed(() => {
  if (!latestMetrics.value?.cpu0) return ''
  if (latestMetrics.value.cpu0 >= 90) return 'status-error'
  if (latestMetrics.value.cpu0 >= 70) return 'status-warning'
  return 'status-ok'
})

const cpuChartOption = computed(() => ({
  tooltip: {
    trigger: 'axis',
    formatter: (params) => {
      const p = params[0]
      return `${p.axisValue}<br/>${p.marker} CPU0: <b>${p.value}%</b>`
    },
  },
  grid: { left: '3%', right: '4%', bottom: '15%', top: '10%', containLabel: true },
  xAxis: {
    type: 'category',
    data: cpuData.value.map(d => d.ts),
    axisLabel: { fontSize: 10, rotate: 30 },
  },
  yAxis: {
    type: 'value',
    min: 0,
    max: 100,
    axisLabel: { formatter: '{value}%' },
  },
  dataZoom: [{ type: 'inside' }],
  series: [{
    name: 'CPU0',
    type: 'line',
    smooth: true,
    symbol: 'none',
    lineStyle: { width: 2 },
    areaStyle: {
      opacity: 0.2,
      color: {
        type: 'linear',
        x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [
          { offset: 0, color: '#409eff' },
          { offset: 1, color: 'rgba(64,158,255,0.05)' },
        ],
      },
    },
    data: cpuData.value.map(d => d.value),
    markLine: {
      silent: true,
      data: [{ yAxis: 90, lineStyle: { color: '#f56c6c', type: 'dashed' }, label: { formatter: '告警线 90%' } }],
    },
  }],
}))

const memChartOption = computed(() => ({
  tooltip: {
    trigger: 'axis',
    formatter: (params) => {
      const p = params[0]
      return `${p.axisValue}<br/>${p.marker} 内存: <b>${(p.value / 1024).toFixed(2)}GB</b>`
    },
  },
  grid: { left: '3%', right: '4%', bottom: '15%', top: '10%', containLabel: true },
  xAxis: {
    type: 'category',
    data: memData.value.map(d => d.ts),
    axisLabel: { fontSize: 10, rotate: 30 },
  },
  yAxis: {
    type: 'value',
    axisLabel: { formatter: (v) => (v / 1024).toFixed(1) + 'GB' },
  },
  dataZoom: [{ type: 'inside' }],
  series: [{
    name: '已用内存',
    type: 'line',
    smooth: true,
    symbol: 'none',
    lineStyle: { width: 2, color: '#67c23a' },
    areaStyle: {
      opacity: 0.2,
      color: {
        type: 'linear',
        x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [
          { offset: 0, color: '#67c23a' },
          { offset: 1, color: 'rgba(103,194,58,0.05)' },
        ],
      },
    },
    data: memData.value.map(d => d.used),
  }],
}))

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

async function loadMetrics() {
  loading.value = true
  try {
    const res = await api.getArrayMetrics(props.arrayId, timeRange.value)
    metrics.value = res.data.metrics || []
  } catch (error) {
    console.error('Failed to load metrics:', error)
  } finally {
    loading.value = false
  }
}

function toggleAutoRefresh(enabled) {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  if (enabled) {
    refreshTimer = setInterval(loadMetrics, 15000) // Refresh every 15s
  }
}

onMounted(() => {
  loadMetrics()
  // Start auto-refresh if enabled by default
  if (autoRefresh.value) {
    toggleAutoRefresh(true)
  }
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style scoped>
.performance-monitor {
  padding: 16px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.chart-section {
  margin-bottom: 20px;
}

.chart-section h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: #606266;
}

.stats-bar {
  display: flex;
  gap: 24px;
  padding: 12px 16px;
  background: #f5f7fa;
  border-radius: 6px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-label {
  font-size: 12px;
  color: #909399;
}

.stat-value {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.stat-value.status-ok { color: #67c23a; }
.stat-value.status-warning { color: #e6a23c; }
.stat-value.status-error { color: #f56c6c; }

.empty-hint {
  padding: 20px;
  text-align: center;
}

.empty-hint p {
  margin: 4px 0;
}

.hint-text {
  font-size: 12px;
  color: #909399;
}
</style>
