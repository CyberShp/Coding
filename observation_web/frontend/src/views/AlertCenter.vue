<template>
  <div class="alert-center">
    <el-card>
      <template #header>
        <AlertFilterBar
          :filters="filters"
          @update:filters="Object.assign(filters, $event)"
          :exporting="exporting"
          v-model:aggregate-mode="aggregateMode"
          @search="loadAlerts"
          @export="exportAlerts"
        />
      </template>

      <!-- Stats -->
      <AlertStats :stats="stats" />

      <!-- Alert Table (flat mode with folding) -->
      <div v-if="!aggregateMode" v-loading="loading">
        <FoldedAlertList
          :alerts="alerts"
          :show-array-id="true"
          :selectable="true"
          v-model:selected-ids="selectedIds"
          @select="openDrawer"
          @ack="handleAck"
          @undo-ack="handleUndoAck"
          @modify-ack="handleModifyAck"
        />
        <!-- 批量操作栏 (sticky bottom toolbar) -->
        <BatchActionBar
          :count="selectedIds.length"
          @batch-undo="handleBatchUndo"
          @batch-modify="handleBatchModify"
          @clear="selectedIds = []"
        />
      </div>

      <!-- Aggregated view -->
      <AggregatedAlertList
        v-else
        :alerts="alerts"
        :loading="loading"
        :quick-acked-ids="quickAckedIds"
        @open="openDrawer"
        @quick-ack="handleQuickAck"
      />

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
import { ElMessage } from 'element-plus'
import api from '../api'
import { ackUndoErrorMessage } from '@/utils/alertHelpers'
import { useAlertStore } from '@/stores/alerts'
import { usePreferencesStore } from '@/stores/preferences'
import { useArrayStore } from '@/stores/arrays'
import AlertDetailDrawer from '@/components/AlertDetailDrawer.vue'
import FoldedAlertList from '@/components/FoldedAlertList.vue'
import AlertFilterBar from '@/components/alert-center/AlertFilterBar.vue'
import AlertStats from '@/components/alert-center/AlertStats.vue'
import AggregatedAlertList from '@/components/alert-center/AggregatedAlertList.vue'
import BatchActionBar from '@/components/alert-center/BatchActionBar.vue'

const route = useRoute()
const alertStore = useAlertStore()
const preferencesStore = usePreferencesStore()
const arrayStore = useArrayStore()
const loading = ref(false)
const exporting = ref(false)
const alerts = ref([])
const stats = ref(null)
const drawerVisible = ref(false)
const selectedAlert = ref(null)
const aggregateMode = ref(false)
const selectedIds = ref([])
const quickAckedIds = ref(new Set())

/**
 * Get all visible (filtered) alert IDs for Ctrl+A select-all
 */
const allVisibleAlertIds = computed(() => {
  return alerts.value.filter(a => a.id).map(a => a.id)
})

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

function _getAllowedArrayIds() {
  if (!preferencesStore.personalViewActive) return null
  const watchedIds = preferencesStore.watchedArrayIds || []
  const watchedTags = new Set(preferencesStore.watchedTagIds || [])
  return new Set([
    ...watchedIds,
    ...arrayStore.arrays.filter(a => a.tag_id != null && watchedTags.has(a.tag_id)).map(a => a.array_id)
  ])
}

function openDrawer(row) {
  selectedAlert.value = row
  drawerVisible.value = true
}

async function handleAck({ alertIds, ackType = 'dismiss' }) {
  try {
    await api.ackAlerts(alertIds, '', { ack_type: ackType })
    ElMessage.success('已确认')
    alerts.value.forEach(a => {
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
    alerts.value.forEach(a => {
      if (alertIds.includes(a.id)) a.is_acked = false
    })
  } catch (e) {
    ElMessage.error(ackUndoErrorMessage(e))
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

async function handleBatchUndo() {
  if (selectedIds.value.length === 0) return
  try {
    await api.batchUndoAck(selectedIds.value)
    ElMessage.success('已撤销确认')
    alerts.value.forEach(a => {
      if (selectedIds.value.includes(a.id)) a.is_acked = false
    })
    selectedIds.value = []
  } catch (e) {
    ElMessage.error(ackUndoErrorMessage(e))
  }
}

async function handleBatchModify(ackType) {
  if (selectedIds.value.length === 0) return
  try {
    const expiresHours = ackType === 'dismiss' ? 24 : null
    await api.batchModifyAck(selectedIds.value, ackType, expiresHours)
    ElMessage.success('已批量确认')
    alerts.value.forEach(a => {
      if (selectedIds.value.includes(a.id)) a.is_acked = true
    })
    selectedIds.value = []
  } catch (e) {
    ElMessage.error('批量确认失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function handleQuickAck(item) {
  if (!item.id) return
  try {
    await api.ackAlerts([item.id], '', { ack_type: 'dismiss' })
    item.is_acked = true
    quickAckedIds.value.add(item.id)
    // Remove the "已处理" text after 2 seconds
    setTimeout(() => {
      quickAckedIds.value.delete(item.id)
    }, 2000)
  } catch (e) {
    ElMessage.error('确认失败: ' + (e.response?.data?.detail || e.message))
  }
}

function handleKeyDown(e) {
  // Ctrl+A (Windows/Linux) or Cmd+A (Mac): select all visible alerts
  if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
    // Only act when in flat (non-aggregate) mode and not in an input
    const tag = e.target?.tagName?.toLowerCase()
    if (tag === 'input' || tag === 'textarea') return
    if (aggregateMode.value) return
    e.preventDefault()
    selectedIds.value = [...allVisibleAlertIds.value]
  }
}

function onAckChanged({ alertId, acked }) {
  const a = alerts.value.find(x => x.id === alertId)
  if (a) a.is_acked = acked
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

    // Personal view: client-side filter by watched arrays/tags
    const allowed = _getAllowedArrayIds()
    if (allowed) {
      alerts.value = alerts.value.filter(a => allowed.has(a.array_id))
    }

    // Auto-translate alarm_type alerts when AI is available
    alertStore.checkAIAvailability().then(() => {
      for (const a of alerts.value) alertStore.autoTranslateAlert(a)
    })

    // Load stats
    const statsResponse = await api.getAlertStats(filters.hours)
    stats.value = statsResponse.data
    pagination.total = allowed ? alerts.value.length : statsResponse.data.total
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

    // Personal view: skip alerts from non-watched arrays
    const allowed = _getAllowedArrayIds()
    if (allowed && !allowed.has(latest.array_id)) return

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

  // Keyboard shortcut: Ctrl+A / Cmd+A to select all visible alerts
  document.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  document.removeEventListener('keydown', handleKeyDown)
})
</script>

<style scoped>
.alert-center {
  padding: 20px;
}

.pagination {
  margin-top: 20px;
  justify-content: flex-end;
}
</style>
