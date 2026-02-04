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
      <!-- Array Status Matrix -->
      <el-col :span="16">
        <el-card class="content-card">
          <template #header>
            <div class="card-header">
              <span>阵列状态</span>
              <el-button text @click="loadArrays">
                <el-icon><Refresh /></el-icon>
              </el-button>
            </div>
          </template>
          <div class="array-grid" v-if="arrayStore.arrays.length > 0">
            <div
              v-for="arr in arrayStore.arrays"
              :key="arr.array_id"
              class="array-card"
              :class="getArrayStatusClass(arr)"
              @click="$router.push(`/arrays/${arr.array_id}`)"
            >
              <div class="array-status-dot" :class="getArrayStatusClass(arr)"></div>
              <div class="array-name">{{ arr.name }}</div>
              <div class="array-host">{{ arr.host }}</div>
            </div>
          </div>
          <el-empty v-else description="暂无阵列">
            <el-button type="primary" @click="$router.push('/arrays')">添加阵列</el-button>
          </el-empty>
        </el-card>

        <!-- Alert Trend Chart -->
        <el-card class="content-card chart-card">
          <template #header>
            <span>24小时告警趋势</span>
          </template>
          <v-chart :option="trendChartOption" autoresize style="height: 250px" />
        </el-card>
      </el-col>

      <!-- Recent Alerts -->
      <el-col :span="8">
        <el-card class="content-card alerts-card">
          <template #header>
            <div class="card-header">
              <span>实时告警</span>
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
  await arrayStore.fetchArrays()
}

async function loadData() {
  await Promise.all([
    loadArrays(),
    alertStore.fetchRecentAlerts(),
    api.getAlertSummary().then(res => summary.value = res.data),
    api.getAlertStats().then(res => stats.value = res.data),
  ])
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

.array-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 16px;
}

.array-card {
  padding: 16px;
  border-radius: 8px;
  background: #f5f7fa;
  cursor: pointer;
  transition: all 0.3s;
  position: relative;
}

.array-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
}

.array-status-dot {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.status-ok .array-status-dot { background: #67c23a; }
.status-warning .array-status-dot { background: #e6a23c; }
.status-error .array-status-dot { background: #f56c6c; }
.status-offline .array-status-dot { background: #909399; }

.array-name {
  font-weight: 500;
  margin-bottom: 4px;
}

.array-host {
  font-size: 12px;
  color: #909399;
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
