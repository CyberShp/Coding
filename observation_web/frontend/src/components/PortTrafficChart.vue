<template>
  <div class="port-traffic">
    <div class="traffic-toolbar">
      <el-select
        v-model="selectedPort"
        placeholder="选择端口"
        style="width: 200px"
        :loading="loadingPorts"
        @change="fetchTrafficData"
      >
        <el-option
          v-for="p in ports"
          :key="p"
          :label="p"
          :value="p"
        />
      </el-select>
      <el-radio-group v-model="timeRange" size="small" @change="fetchTrafficData">
        <el-radio-button :value="5">5分钟</el-radio-button>
        <el-radio-button :value="10">10分钟</el-radio-button>
        <el-radio-button :value="30">30分钟</el-radio-button>
        <el-radio-button :value="60">1小时</el-radio-button>
        <el-radio-button :value="120">2小时</el-radio-button>
      </el-radio-group>
      <el-button size="small" @click="syncAndRefresh" :loading="syncing">
        <el-icon><Refresh /></el-icon>
        同步数据
      </el-button>
      <div class="auto-refresh-toggle">
        <el-switch v-model="autoRefresh" size="small" />
        <span class="auto-label">自动刷新</span>
        <el-tag v-if="autoRefresh" type="success" size="small" effect="plain">30s</el-tag>
      </div>
    </div>

    <!-- Real-time bandwidth summary bar -->
    <div v-if="selectedPort && latestBandwidth" class="bandwidth-bar">
      <div class="bw-item">
        <span class="bw-label">TX 发送</span>
        <span class="bw-value tx">{{ formatBandwidth(latestBandwidth.tx) }}</span>
      </div>
      <div class="bw-item">
        <span class="bw-label">RX 接收</span>
        <span class="bw-value rx">{{ formatBandwidth(latestBandwidth.rx) }}</span>
      </div>
      <div class="bw-item">
        <span class="bw-label">采集模式</span>
        <el-tag :type="getModeTagType(latestBandwidth.mode)" size="small" effect="plain">
          {{ latestBandwidth.mode || 'auto' }}
        </el-tag>
      </div>
      <div class="bw-item">
        <span class="bw-label">协议类型</span>
        <el-tag :type="getProtocolTagType(latestBandwidth.protocol)" size="small" effect="plain">
          {{ getProtocolLabel(latestBandwidth.protocol) }}
        </el-tag>
      </div>
      <div class="bw-item">
        <span class="bw-label">最后更新</span>
        <span class="bw-value time">{{ latestBandwidth.time || '--' }}</span>
      </div>
      <el-button text type="info" size="small" @click="showDiagnostic" class="diagnostic-btn">
        <el-icon><InfoFilled /></el-icon>
        诊断
      </el-button>
    </div>

    <!-- Diagnostic dialog -->
    <el-dialog v-model="diagnosticVisible" title="流量采集诊断" width="500px">
      <div v-if="diagnosticInfo" class="diagnostic-content">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="RDMA 设备">
            <el-tag v-if="diagnosticInfo.has_rdma" type="success">检测到</el-tag>
            <el-tag v-else type="info">未检测到</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="TOE Offload">
            <el-tag v-if="diagnosticInfo.has_toe" type="success">检测到</el-tag>
            <el-tag v-else type="info">未检测到</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="推荐模式">
            <el-tag type="primary">{{ diagnosticInfo.recommended_mode }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="检测协议">
            {{ diagnosticInfo.detected_protocol }}
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="diagnosticInfo.rdma_devices && diagnosticInfo.rdma_devices.length" class="diag-section">
          <h4>RDMA 设备</h4>
          <el-tag v-for="dev in diagnosticInfo.rdma_devices" :key="dev.name" style="margin: 2px">
            {{ dev.name }} ({{ dev.type || dev.link_layer }})
          </el-tag>
        </div>

        <div v-if="diagnosticInfo.toe_ports && diagnosticInfo.toe_ports.length" class="diag-section">
          <h4>TOE Offload 端口</h4>
          <el-tag v-for="p in diagnosticInfo.toe_ports" :key="p" style="margin: 2px">{{ p }}</el-tag>
        </div>

        <div v-if="diagnosticInfo.notes && diagnosticInfo.notes.length" class="diag-section">
          <h4>诊断说明</h4>
          <ul>
            <li v-for="(note, idx) in diagnosticInfo.notes" :key="idx">{{ note }}</li>
          </ul>
        </div>
      </div>
      <div v-else class="diagnostic-loading">
        <el-skeleton :rows="5" animated />
      </div>
    </el-dialog>

    <div v-if="!selectedPort" class="no-port-hint">
      <el-empty description="请先选择一个端口以查看流量曲线" :image-size="80" />
    </div>

    <div v-else class="chart-wrapper">
      <div v-show="loading" class="chart-loading">
        <el-skeleton :rows="6" animated />
      </div>
      <div v-show="!loading && chartData.length === 0" class="chart-empty">
        <el-empty description="暂无流量数据，请同步后重试" :image-size="80" />
      </div>
      <div v-show="!loading && chartData.length > 0" ref="chartContainer" class="chart-container"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { Refresh, InfoFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import * as echarts from 'echarts'

const props = defineProps({
  arrayId: { type: String, required: true },
})

const ports = ref([])
const selectedPort = ref('')
const timeRange = ref(30)
const chartData = ref([])
const loading = ref(false)
const loadingPorts = ref(false)
const syncing = ref(false)
const chartContainer = ref(null)
const autoRefresh = ref(true)
const diagnosticVisible = ref(false)
const diagnosticInfo = ref(null)

let chartInstance = null
let refreshTimer = null

// Latest bandwidth values for summary bar
const latestBandwidth = computed(() => {
  if (chartData.value.length === 0) return null
  const last = chartData.value[chartData.value.length - 1]
  return {
    tx: last.tx_rate_bps || 0,
    rx: last.rx_rate_bps || 0,
    time: formatTime(last.ts),
    mode: last.mode || 'auto',
    protocol: last.protocol || 'ethernet',
  }
})

function getModeTagType(mode) {
  const types = {
    rdma: 'warning',
    toe: 'warning',
    ethtool: '',
    sysfs: 'info',
    auto: 'success',
    command: 'danger',
  }
  return types[mode] || ''
}

function getProtocolTagType(protocol) {
  const types = {
    rdma: 'warning',
    roce: 'warning',
    toe: 'warning',
    ethernet: '',
  }
  return types[protocol] || 'info'
}

function getProtocolLabel(protocol) {
  const labels = {
    rdma: 'RDMA',
    roce: 'RoCE',
    toe: 'TOE/iSCSI',
    ethernet: 'Ethernet',
    unknown: '未知',
  }
  return labels[protocol] || protocol
}

async function showDiagnostic() {
  diagnosticVisible.value = true
  diagnosticInfo.value = null
  try {
    const res = await api.getTrafficDiagnostic(props.arrayId)
    diagnosticInfo.value = res.data
  } catch (e) {
    ElMessage.error('获取诊断信息失败')
    diagnosticInfo.value = { notes: ['获取诊断信息失败: ' + (e.message || '未知错误')] }
  }
}

// Bandwidth auto-unit formatter
function formatBandwidth(bps) {
  if (bps == null || isNaN(bps)) return '0 b/s'
  const abs = Math.abs(bps)
  if (abs >= 1e9) return (bps / 1e9).toFixed(2) + ' Gb/s'
  if (abs >= 1e6) return (bps / 1e6).toFixed(2) + ' Mb/s'
  if (abs >= 1e3) return (bps / 1e3).toFixed(2) + ' Kb/s'
  return bps.toFixed(0) + ' b/s'
}

function formatTime(isoStr) {
  try {
    const d = new Date(isoStr)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return isoStr
  }
}

async function fetchPorts() {
  loadingPorts.value = true
  try {
    const res = await api.getTrafficPorts(props.arrayId)
    ports.value = res.data.ports || []
    if (ports.value.length > 0 && !selectedPort.value) {
      selectedPort.value = ports.value[0]
      await fetchTrafficData()
    }
  } catch (e) {
    console.error('Failed to fetch ports:', e)
  } finally {
    loadingPorts.value = false
  }
}

async function fetchTrafficData() {
  if (!selectedPort.value) return
  loading.value = true
  try {
    const res = await api.getTrafficData(props.arrayId, selectedPort.value, timeRange.value)
    chartData.value = res.data.data || []
    loading.value = false  // Must set false BEFORE nextTick so chart container renders in DOM
    await nextTick()
    renderChart()
  } catch (e) {
    console.error('Failed to fetch traffic data:', e)
    ElMessage.error('获取流量数据失败')
  } finally {
    loading.value = false
  }
}

async function syncAndRefresh() {
  syncing.value = true
  try {
    await api.syncTraffic(props.arrayId)
    await fetchPorts()
    if (selectedPort.value) {
      await fetchTrafficData()
    }
    ElMessage.success('流量数据已同步')
  } catch (e) {
    ElMessage.error('同步失败')
  } finally {
    syncing.value = false
  }
}

function renderChart() {
  if (!chartContainer.value || chartData.value.length === 0) return

  // With v-show, the container stays in DOM, so the instance stays valid.
  // Just init once; if somehow DOM is stale, dispose and re-create.
  if (chartInstance && !document.body.contains(chartInstance.getDom())) {
    chartInstance.dispose()
    chartInstance = null
  }

  if (!chartInstance) {
    chartInstance = echarts.init(chartContainer.value)
  } else {
    // Container might have been hidden (v-show=false) and now visible again;
    // ensure ECharts recalculates dimensions.
    chartInstance.resize()
  }

  const times = chartData.value.map(d => formatTime(d.ts))
  const txRates = chartData.value.map(d => d.tx_rate_bps || 0)
  const rxRates = chartData.value.map(d => d.rx_rate_bps || 0)

  // Show symbols (dots) when data points are few, otherwise hide for cleanliness
  const showSymbol = chartData.value.length <= 10
  const symbolSize = chartData.value.length <= 3 ? 8 : 5

  const option = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(30, 30, 30, 0.85)',
      borderColor: 'transparent',
      borderWidth: 0,
      textStyle: {
        color: '#e0e0e0',
        fontSize: 12,
      },
      padding: [8, 12],
      formatter: (params) => {
        if (!params || params.length === 0) return ''
        const time = params[0].axisValue
        let html = `<div style="font-size:11px;color:#aaa;margin-bottom:4px">${time}</div>`
        for (const p of params) {
          const color = p.color
          const name = p.seriesName
          const val = formatBandwidth(p.value)
          html += `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">`
          html += `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color}"></span>`
          html += `<span>${name}</span>`
          html += `<span style="margin-left:auto;font-weight:600">${val}</span>`
          html += `</div>`
        }
        return html
      },
    },
    legend: {
      data: ['TX (发送)', 'RX (接收)'],
      bottom: 0,
      textStyle: { fontSize: 12 },
    },
    grid: {
      left: 60,
      right: 20,
      top: 20,
      bottom: 40,
    },
    xAxis: {
      type: 'category',
      data: times,
      axisLabel: {
        fontSize: 10,
        rotate: times.length > 30 ? 45 : 0,
      },
      boundaryGap: false,
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        formatter: (v) => formatBandwidth(v),
        fontSize: 10,
      },
      splitLine: {
        lineStyle: { type: 'dashed', color: '#e8e8e8' },
      },
    },
    series: [
      {
        name: 'TX (发送)',
        type: 'line',
        data: txRates,
        smooth: txRates.length > 2,
        showSymbol: showSymbol,
        symbol: 'circle',
        symbolSize: symbolSize,
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.1 },
        itemStyle: { color: '#409eff' },
      },
      {
        name: 'RX (接收)',
        type: 'line',
        data: rxRates,
        smooth: rxRates.length > 2,
        showSymbol: showSymbol,
        symbol: 'circle',
        symbolSize: symbolSize,
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.1 },
        itemStyle: { color: '#67c23a' },
      },
    ],
  }

  chartInstance.setOption(option, true)
}

function handleResize() {
  chartInstance?.resize()
}

function startAutoRefresh() {
  stopAutoRefresh()
  if (autoRefresh.value && selectedPort.value) {
    refreshTimer = setInterval(autoSyncAndRefresh, 30000)
  }
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

async function autoSyncAndRefresh() {
  if (document.hidden || syncing.value || loading.value || !selectedPort.value) return
  try {
    await api.syncTraffic(props.arrayId)
    await fetchTrafficData()
  } catch {
    // Silent — don't disturb the user during auto-refresh
  }
}

watch(autoRefresh, startAutoRefresh)
watch(selectedPort, startAutoRefresh)

onMounted(() => {
  fetchPorts()
  window.addEventListener('resize', handleResize)
  startAutoRefresh()
})

onUnmounted(() => {
  stopAutoRefresh()
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<style scoped>
.port-traffic {
  padding: 8px 0;
}

.traffic-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.chart-container {
  width: 100%;
  height: 360px;
}

.no-port-hint,
.chart-loading,
.chart-empty {
  padding: 40px 0;
  text-align: center;
}

.auto-refresh-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}

.auto-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

/* Bandwidth summary bar */
.bandwidth-bar {
  display: flex;
  gap: 24px;
  padding: 10px 16px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  margin-bottom: 12px;
}

.bw-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.bw-label {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  font-weight: 500;
}

.bw-value {
  font-size: 16px;
  font-weight: 700;
  font-family: 'Menlo', 'Consolas', monospace;
}

.bw-value.tx {
  color: #409eff;
}

.bw-value.rx {
  color: #67c23a;
}

.bw-value.time {
  font-size: 13px;
  font-weight: 400;
  color: var(--el-text-color-regular);
}

.diagnostic-btn {
  margin-left: auto;
}

.diagnostic-content {
  font-size: 14px;
}

.diag-section {
  margin-top: 16px;
}

.diag-section h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.diag-section ul {
  margin: 0;
  padding-left: 20px;
}

.diag-section li {
  margin: 4px 0;
  color: var(--el-text-color-regular);
}

.diagnostic-loading {
  padding: 20px;
}
</style>
