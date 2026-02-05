<template>
  <div class="dashboard">
    <h2 class="page-title">Dashboard</h2>

    <!-- Stats Cards -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="6">
        <el-card class="stat-card" shadow="never">
          <div class="stat-value">{{ formatNumber(stats.tx.packets) }}</div>
          <div class="stat-label">TX Packets</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card" shadow="never">
          <div class="stat-value">{{ formatPps(stats.tx.current_pps) }}</div>
          <div class="stat-label">Current Rate</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card" shadow="never">
          <div class="stat-value">{{ formatMbps(stats.tx.current_mbps) }}</div>
          <div class="stat-label">Throughput</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card error" shadow="never">
          <div class="stat-value">{{ formatNumber(stats.tx.errors) }}</div>
          <div class="stat-label">TX Errors</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Charts -->
    <el-row :gutter="16" class="chart-row">
      <el-col :span="12">
        <el-card class="chart-card" shadow="never">
          <template #header>
            <span>Send Rate (pps)</span>
          </template>
          <v-chart :option="ppsChartOption" autoresize style="height: 300px;" />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card class="chart-card" shadow="never">
          <template #header>
            <span>Throughput (Mbps)</span>
          </template>
          <v-chart :option="mbpsChartOption" autoresize style="height: 300px;" />
        </el-card>
      </el-col>
    </el-row>

    <!-- Details -->
    <el-row :gutter="16" class="detail-row">
      <el-col :span="12">
        <el-card class="detail-card" shadow="never">
          <template #header>
            <span>Anomaly Breakdown</span>
          </template>
          <el-table :data="anomalyTableData" size="small" style="width: 100%">
            <el-table-column prop="type" label="Type" />
            <el-table-column prop="count" label="Count" width="100" align="right" />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card class="detail-card" shadow="never">
          <template #header>
            <span>Recent Errors</span>
          </template>
          <div v-if="stats.recent_errors.length === 0" class="no-data">
            No errors
          </div>
          <div v-else class="error-list">
            <div v-for="(err, idx) in stats.recent_errors" :key="idx" class="error-item">
              {{ err.error }}
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { useStatsStore } from '@/stores/stats'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent])

const statsStore = useStatsStore()
const stats = computed(() => statsStore.stats)

onMounted(() => {
  statsStore.connect()
})

onUnmounted(() => {
  statsStore.disconnect()
})

const anomalyTableData = computed(() => {
  const byType = stats.value.anomalies?.by_type || {}
  return Object.entries(byType).map(([type, count]) => ({ type, count }))
})

const ppsChartOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: { trigger: 'axis' },
  grid: { left: 60, right: 20, top: 20, bottom: 30 },
  xAxis: {
    type: 'category',
    data: statsStore.ppsHistory.map(p => p.time),
    axisLabel: { color: '#888', fontSize: 10 },
    axisLine: { lineStyle: { color: '#333' } },
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: '#888' },
    splitLine: { lineStyle: { color: '#222' } },
  },
  series: [{
    type: 'line',
    data: statsStore.ppsHistory.map(p => p.value),
    smooth: true,
    lineStyle: { color: '#409EFF', width: 2 },
    areaStyle: { color: 'rgba(64, 158, 255, 0.1)' },
    showSymbol: false,
  }],
}))

const mbpsChartOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: { trigger: 'axis' },
  grid: { left: 60, right: 20, top: 20, bottom: 30 },
  xAxis: {
    type: 'category',
    data: statsStore.mbpsHistory.map(p => p.time),
    axisLabel: { color: '#888', fontSize: 10 },
    axisLine: { lineStyle: { color: '#333' } },
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: '#888' },
    splitLine: { lineStyle: { color: '#222' } },
  },
  series: [{
    type: 'line',
    data: statsStore.mbpsHistory.map(p => p.value),
    smooth: true,
    lineStyle: { color: '#67C23A', width: 2 },
    areaStyle: { color: 'rgba(103, 194, 58, 0.1)' },
    showSymbol: false,
  }],
}))

function formatNumber(n) { return (n || 0).toLocaleString() }
function formatPps(n) { return `${(n || 0).toLocaleString(undefined, {maximumFractionDigits: 0})} pps` }
function formatMbps(n) { return `${(n || 0).toFixed(4)} Mbps` }
</script>

<style scoped>
.page-title { margin-bottom: 20px; color: #e0e0e0; }
.stats-row { margin-bottom: 16px; }
.chart-row { margin-bottom: 16px; }
.stat-card { background: #16213e; border: 1px solid #2a2a3e; border-radius: 8px; text-align: center; padding: 12px; }
.stat-card.error .stat-value { color: #F56C6C; }
.stat-value { font-size: 28px; font-weight: 700; color: #409EFF; }
.stat-label { font-size: 13px; color: #888; margin-top: 4px; }
.chart-card, .detail-card { background: #16213e; border: 1px solid #2a2a3e; border-radius: 8px; }
.no-data { color: #666; text-align: center; padding: 20px; }
.error-list { max-height: 200px; overflow-y: auto; }
.error-item { padding: 6px 0; color: #F56C6C; font-size: 13px; border-bottom: 1px solid #222; }
</style>
