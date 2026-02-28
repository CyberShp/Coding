<template>
  <div class="alert-center">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>告警中心</span>
          <div class="filter-actions">
            <el-select v-model="filters.level" placeholder="告警级别" clearable style="width: 120px">
              <el-option label="信息" value="info" />
              <el-option label="警告" value="warning" />
              <el-option label="错误" value="error" />
              <el-option label="严重" value="critical" />
            </el-select>
            <el-select v-model="filters.observer" placeholder="观察点" clearable style="width: 140px">
              <el-option v-for="(name, key) in OBSERVER_NAMES" :key="key" :label="name" :value="key" />
            </el-select>
            <el-select v-model="filters.hours" style="width: 120px">
              <el-option label="最近 1 小时" :value="1" />
              <el-option label="最近 6 小时" :value="6" />
              <el-option label="最近 24 小时" :value="24" />
              <el-option label="最近 7 天" :value="168" />
            </el-select>
            <el-button type="primary" @click="loadAlerts">
              <el-icon><Search /></el-icon>
              查询
            </el-button>
            <el-button type="success" @click="exportAlerts" :loading="exporting">
              <el-icon><Download /></el-icon>
              导出
            </el-button>
            <el-switch
              v-model="aggregateMode"
              active-text="聚合"
              inactive-text="平铺"
              @change="loadAlerts"
              style="margin-left: 8px"
            />
          </div>
        </div>
      </template>

      <!-- Stats -->
      <el-row :gutter="20" class="stats-row">
        <el-col :span="6">
          <div class="stat-item">
            <div class="stat-value">{{ stats?.total || 0 }}</div>
            <div class="stat-label">总告警数</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat-item">
            <div class="stat-value error-text">{{ (stats?.by_level?.error || 0) + (stats?.by_level?.critical || 0) }}</div>
            <div class="stat-label">错误</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat-item">
            <div class="stat-value warning-text">{{ stats?.by_level?.warning || 0 }}</div>
            <div class="stat-label">警告</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat-item">
            <div class="stat-value info-text">{{ stats?.by_level?.info || 0 }}</div>
            <div class="stat-label">信息</div>
          </div>
        </el-col>
      </el-row>

      <!-- Alert Table (flat mode with folding) -->
      <div v-if="!aggregateMode" v-loading="loading">
        <FoldedAlertList
          :alerts="alerts"
          :show-array-id="true"
          @select="openDrawer"
          @ack="handleAck"
        />
      </div>

      <!-- Aggregated view -->
      <div v-else v-loading="loading" class="aggregated-list">
        <div
          v-for="(item, idx) in alerts"
          :key="idx"
          class="agg-item"
          :class="{ 'is-group': item.is_aggregated }"
          @click="openDrawer(item)"
        >
          <template v-if="item.is_aggregated">
            <div class="agg-header">
              <el-tag :type="getLevelType(item.group.worst_level)" size="small" effect="dark">
                {{ item.group.group_type === 'storm' ? '风暴' : (item.group.group_type === 'root_cause' ? '关联' : '聚合') }}
              </el-tag>
              <span class="agg-label">{{ item.group.label }}</span>
              <el-tag size="small" type="info" effect="plain">{{ item.group.count }} 条</el-tag>
              <span class="agg-time">{{ formatDateTime(item.group.latest) }}</span>
            </div>
          </template>
          <template v-else>
            <div class="agg-header">
              <el-tag :type="getLevelType(item.level)" size="small">{{ getLevelText(item.level) }}</el-tag>
              <span class="agg-obs">{{ getObserverLabel(item.observer_name) }}</span>
              <span class="agg-msg">{{ getTranslatedSummary(item) }}</span>
              <span class="agg-time">{{ formatDateTime(item.timestamp) }}</span>
            </div>
          </template>
        </div>
        <el-empty v-if="!loading && alerts.length === 0" description="暂无告警" />
      </div>

      <!-- 告警详情抽屉 -->
      <AlertDetailDrawer v-model="drawerVisible" :alert="selectedAlert" @ack-changed="onAckChanged" />

      <!-- Pagination -->
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.size"
        :total="pagination.total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pagination"
        @size-change="loadAlerts"
        @current-change="loadAlerts"
      />
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Search, Download, ArrowRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import { useAlertStore } from '@/stores/alerts'
import AlertDetailDrawer from '@/components/AlertDetailDrawer.vue'
import FoldedAlertList from '@/components/FoldedAlertList.vue'
import { translateAlert, getObserverName, OBSERVER_NAMES, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'

const route = useRoute()
const alertStore = useAlertStore()
const loading = ref(false)
const exporting = ref(false)
const alerts = ref([])
const stats = ref(null)
const drawerVisible = ref(false)
const selectedAlert = ref(null)
const aggregateMode = ref(false)

const filters = reactive({
  level: '',
  observer: '',
  hours: 24,
})

const pagination = reactive({
  page: 1,
  size: 20,
  total: 0,
})

function getLevelType(level) {
  return LEVEL_TAG_TYPES[level] || 'info'
}

function getLevelText(level) {
  return LEVEL_LABELS[level] || level
}

function getObserverLabel(name) {
  return getObserverName(name)
}

function getTranslatedSummary(row) {
  const result = translateAlert(row)
  return result.summary || row.message
}

function openDrawer(row) {
  selectedAlert.value = row
  drawerVisible.value = true
}

async function handleAck({ alertIds }) {
  try {
    await api.ackAlerts(alertIds)
    ElMessage.success('已确认')
    alerts.value.forEach(a => {
      if (alertIds.includes(a.id)) a.is_acked = true
    })
  } catch (e) {
    ElMessage.error('确认失败: ' + (e.response?.data?.detail || e.message))
  }
}

function onAckChanged({ alertId, acked }) {
  const a = alerts.value.find(x => x.id === alertId)
  if (a) a.is_acked = acked
}

function formatDateTime(timestamp) {
  if (!timestamp) return '-'
  return new Date(timestamp).toLocaleString('zh-CN')
}

async function loadAlerts() {
  loading.value = true
  try {
    if (aggregateMode.value) {
      // Aggregated mode
      const params = { hours: filters.hours, limit: 200 }
      if (filters.level) params.level = filters.level
      const response = await api.getAggregatedAlerts(params)
      alerts.value = response.data || []
    } else {
      // Flat mode
      const params = {
        hours: filters.hours,
        limit: pagination.size,
        offset: (pagination.page - 1) * pagination.size,
      }
      if (filters.level) params.level = filters.level
      if (filters.observer) params.observer_name = filters.observer
      const response = await api.getAlerts(params)
      alerts.value = response.data
    }
    
    // Load stats
    const statsResponse = await api.getAlertStats(filters.hours)
    stats.value = statsResponse.data
    pagination.total = statsResponse.data.total
  } finally {
    loading.value = false
  }
}

async function exportAlerts() {
  exporting.value = true
  try {
    const params = {
      hours: filters.hours,
      format: 'csv',
    }
    if (filters.level) params.level = filters.level
    if (filters.observer) params.observer_name = filters.observer

    const response = await api.exportAlerts(params)
    
    // Create download link
    const blob = new Blob([response.data], { type: 'text/csv;charset=utf-8' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `alerts_${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    
    ElMessage.success('导出成功')
  } catch (error) {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

// ───── Auto-refresh (30s) ─────
let refreshTimer = null
let isRefreshing = false  // Lock to prevent concurrent refreshes

async function silentReloadAlerts() {
  if (document.hidden || loading.value || isRefreshing) return
  isRefreshing = true
  try {
    await loadAlerts()
  } catch {
    // Silent fail — next cycle will retry
  } finally {
    isRefreshing = false
  }
}

// ───── WebSocket: prepend new alerts in real-time ─────
// Watch the store's recentAlerts — when the store receives a WebSocket
// alert it pushes to recentAlerts; we mirror new entries into our list.
const _seenIds = new Set()
const MAX_SEEN_IDS = 500  // Prevent unbounded growth

function cleanupSeenIds() {
  if (_seenIds.size > MAX_SEEN_IDS) {
    // Keep only the most recent half
    const idsArray = Array.from(_seenIds)
    const toRemove = idsArray.slice(0, idsArray.length - MAX_SEEN_IDS / 2)
    toRemove.forEach(id => _seenIds.delete(id))
  }
}

watch(
  () => alertStore.recentAlerts,
  (newList) => {
    if (!newList || newList.length === 0) return
    const latest = newList[0]
    if (!latest || _seenIds.has(latest.id)) return
    _seenIds.add(latest.id)
    cleanupSeenIds()  // Prevent unbounded growth

    // Apply current filter — skip if it doesn't match
    if (filters.level && latest.level !== filters.level) return
    if (filters.observer && latest.observer_name !== filters.observer) return

    // Prepend to the alert list (only in flat mode)
    if (!aggregateMode.value) {
      alerts.value.unshift(latest)
      // Keep list length within page size
      if (alerts.value.length > pagination.size) {
        alerts.value.pop()
      }
      pagination.total += 1
    }

    // Bump stats counters
    if (stats.value) {
      stats.value.total = (stats.value.total || 0) + 1
      if (stats.value.by_level) {
        const lvl = latest.level || 'info'
        stats.value.by_level[lvl] = (stats.value.by_level[lvl] || 0) + 1
      }
    }
  },
  { deep: true }
)

onMounted(() => {
  // Apply filter from URL query params (e.g. ?level=error)
  if (route.query.level) {
    filters.level = route.query.level
  }
  if (route.query.observer) {
    filters.observer = route.query.observer
  }
  loadAlerts()

  // Ensure WebSocket is connected (idempotent)
  alertStore.connectWebSocket()

  // Periodic full reload every 30 seconds
  refreshTimer = setInterval(silentReloadAlerts, 30000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style scoped>
.alert-center {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.filter-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.stats-row {
  margin-bottom: 20px;
  padding: 16px 0;
  border-bottom: 1px solid #ebeef5;
}

.stat-item {
  text-align: center;
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

.error-text {
  color: #f56c6c;
}

.warning-text {
  color: #e6a23c;
}

.info-text {
  color: #909399;
}

.clickable-table :deep(tr) {
  cursor: pointer;
}

.translated-msg {
  font-size: 13px;
  line-height: 1.6;
}

.row-arrow {
  color: var(--el-text-color-placeholder);
  font-size: 14px;
}

.pagination {
  margin-top: 20px;
  justify-content: flex-end;
}

/* Aggregated view styles */
.aggregated-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}
.agg-item {
  padding: 10px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}
.agg-item:hover {
  background: var(--el-fill-color-light);
}
.agg-item.is-group {
  border-left: 3px solid var(--el-color-warning);
  background: var(--el-color-warning-light-9);
}
.agg-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.agg-label {
  font-weight: 600;
  font-size: 14px;
  color: var(--el-text-color-primary);
}
.agg-obs {
  font-weight: 500;
  font-size: 13px;
  color: var(--el-color-primary);
}
.agg-msg {
  flex: 1;
  font-size: 13px;
  color: var(--el-text-color-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agg-time {
  margin-left: auto;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

/* Folded alert list is now in FoldedAlertList.vue component */
</style>
