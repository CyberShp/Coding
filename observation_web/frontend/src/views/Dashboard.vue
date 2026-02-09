<template>
  <div class="dashboard">
    <!-- Stats Cards -->
    <el-row :gutter="20" class="stats-row">
      <el-col :span="6">
        <el-card class="stat-card clickable" @click="$router.push('/arrays')">
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
        <el-card class="stat-card clickable" @click="$router.push('/arrays')">
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
        <el-card class="stat-card clickable" @click="$router.push('/alerts')">
          <div class="stat-content">
            <div class="stat-icon" style="background: #e6a23c">
              <el-icon size="28"><Bell /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ summary.total || summary.total_24h || 0 }}</div>
              <div class="stat-label">2h 告警</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card clickable" @click="$router.push({ path: '/alerts', query: { level: 'error' } })">
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

        <!-- Alert Trend Chart (multi-line by level) -->
        <el-card class="content-card chart-card">
          <template #header>
            <span>2小时告警趋势</span>
          </template>
          <v-chart :option="trendChartOption" autoresize style="height: 250px" />
        </el-card>
      </el-col>

      <!-- Recent Alerts Stream (with folding) -->
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
            <FoldedAlertList
              :alerts="alertStore.recentAlerts"
              :show-array-id="true"
              :compact="true"
              @select="openAlertDrawer"
            />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 告警详情抽屉 -->
    <AlertDetailDrawer v-model="drawerVisible" :alert="selectedAlert" />
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
import AlertDetailDrawer from '@/components/AlertDetailDrawer.vue'
import FoldedAlertList from '@/components/FoldedAlertList.vue'
import { translateAlert, getObserverName, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent])

const arrayStore = useArrayStore()
const alertStore = useAlertStore()

const summary = ref({})
const stats = ref(null)
const activeTask = ref(null)
const taskDuration = ref('')
const drawerVisible = ref(false)
const selectedAlert = ref(null)

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

async function loadArrays() {
  try {
    await arrayStore.fetchArrays()
  } catch (error) {
    console.error('Failed to load arrays:', error)
  }
}

async function loadActiveTask() {
  try {
    const res = await api.getTestTasks({ status: 'running', limit: 1 })
    const running = (res.data || [])[0]
    activeTask.value = running || null
    if (running && running.started_at) {
      const sec = (Date.now() - new Date(running.started_at).getTime()) / 1000
      if (sec < 60) taskDuration.value = `${Math.round(sec)}s`
      else if (sec < 3600) taskDuration.value = `${Math.floor(sec / 60)}m`
      else taskDuration.value = `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
    }
  } catch (_) {}
}

async function loadData() {
  // Load data in parallel with individual error handling
  const tasks = [
    loadArrays().catch(e => console.error('Load arrays failed:', e)),
    alertStore.fetchRecentAlerts().catch(e => console.error('Load alerts failed:', e)),
    api.getAlertSummary(2).then(res => summary.value = res.data).catch(e => console.error('Load summary failed:', e)),
    api.getAlertStats(2).then(res => stats.value = res.data).catch(e => console.error('Load stats failed:', e)),
    loadActiveTask(),
  ]
  
  await Promise.all(tasks)
}

onMounted(loadData)
</script>

<style scoped>
.dashboard {
  padding: 20px;
}

/* Active test task banner */
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

.stats-row {
  margin-bottom: 20px;
}

.stat-card {
  border-radius: 8px;
}

.stat-card.clickable {
  cursor: pointer;
  transition: all 0.2s;
}

.stat-card.clickable:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
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


.alerts-card {
  height: calc(100vh - 280px);
  overflow: hidden;
}

.alerts-list {
  max-height: calc(100vh - 350px);
  overflow-y: auto;
}

/* Alert items are now rendered by FoldedAlertList component */

.ws-badge :deep(.el-badge__content) {
  font-size: 10px;
}

.chart-card {
  margin-top: 20px;
}
</style>
