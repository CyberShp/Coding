<template>
  <div class="array-detail" v-loading="loading">
    <!-- Page Header -->
    <el-page-header @back="$router.back()">
      <template #content>
        <div class="page-header-content">
          <span class="page-title">{{ array?.name || '阵列详情' }}</span>
          <div class="header-actions">
            <el-button v-if="array && array.state !== 'connected'" type="primary" size="small" @click="handleConnect">连接</el-button>
            <el-button v-else-if="array" size="small" @click="handleDisconnect">断开</el-button>
            <el-button size="small" @click="handleRefresh" :loading="refreshing">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
          </div>
        </div>
      </template>
    </el-page-header>

    <div v-if="loading && !array" class="skeleton-zone">
      <el-skeleton :rows="3" animated />
    </div>

    <div class="content" v-if="array">
      <!-- Zone 1: Status Header (F203 + F204) -->
      <ArrayStatusHeader />

      <!-- Zone 2: Active Anomalies -->
      <AnomalyPanel @open-issue="openIssueDetail" @ack-issue="onAnomalyAcked" />

      <!-- Zones 3 + 5: Events + Observer -->
      <div class="zones-3-5-container">
        <AlertDisplay class="zone-events" @ack="handleAck" @undo-ack="handleUndoAck" @modify-ack="handleModifyAck" />
        <ObserverPanel class="zone-observer-status" />
      </div>

      <!-- Operational Zones (collapsed by default) -->
      <OperationsPanel />

      <!-- Alert Detail Drawer -->
      <AlertDetailDrawer v-model="drawerVisible" :alert="selectedAlert" @ack-changed="onAckChanged" />
    </div>

    <!-- Connect Dialog -->
    <el-dialog v-model="connectDialogVisible" title="连接阵列" width="400px">
      <el-form :model="connectForm">
        <el-form-item label="密码">
          <el-input v-model="connectForm.password" type="password" show-password placeholder="SSH 密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="connectDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="doConnect" :loading="connecting">连接</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, watch, provide, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useArrayStore } from '../stores/arrays'
import { useAlertStore } from '../stores/alerts'
import api from '../api'
import AlertDetailDrawer from '@/components/AlertDetailDrawer.vue'
import ArrayStatusHeader from '@/components/array-detail/ArrayStatusHeader.vue'
import AnomalyPanel from '@/components/array-detail/AnomalyPanel.vue'
import AlertDisplay from '@/components/array-detail/AlertDisplay.vue'
import ObserverPanel from '@/components/array-detail/ObserverPanel.vue'
import OperationsPanel from '@/components/array-detail/OperationsPanel.vue'

const route = useRoute()
const arrayStore = useArrayStore()
const alertStore = useAlertStore()

// ───── Core state ─────
const loading = ref(true)
const refreshing = ref(false)
const connecting = ref(false)
const connectDialogVisible = ref(false)
const connectForm = reactive({ password: '' })

const array = ref(null)
const recentAlerts = ref([])
const selectedAlert = ref(null)
const drawerVisible = ref(false)
const tags = ref([])
const watchers = ref([])
let pageAbortController = null

// ───── provide ─────
provide('arrayDetail', {
  array,
  recentAlerts,
  tags,
  watchers,
  selectedAlert,
  refresh: () => loadArray(),
  openAlertDrawer: (alert) => { selectedAlert.value = alert; drawerVisible.value = true },
})

// ───── Alert dedup ─────
const seenAlertKeys = new Set()
function _alertKey(a) {
  return a.id || `${a.timestamp}_${a.observer_name}_${(a.message || '').slice(0, 50)}`
}

// ───── Issue / Alert handlers ─────
function openIssueDetail(issue) {
  selectedAlert.value = {
    id: issue.alert_id, array_id: array.value?.array_id,
    observer_name: issue.observer, level: issue.level,
    message: issue.message, details: issue.details || {},
    timestamp: issue.latest || issue.since || '',
  }
  drawerVisible.value = true
}

function onAnomalyAcked(issue) {
  if (array.value?.active_issues) {
    array.value.active_issues = array.value.active_issues.filter(i => i.key !== issue.key)
  }
}

function onAckChanged({ alertId, acked }) {
  const a = recentAlerts.value.find(x => x.id === alertId)
  if (a) a.is_acked = acked
  if (array.value?.array_id) loadArray()
}

function errMsg(e, fallback) {
  const d = e?.response?.data?.detail
  return typeof d === 'string' ? d : (typeof e?.message === 'string' ? e.message : fallback)
}

async function handleAck({ alertIds, ackType = 'dismiss' }) {
  try {
    await api.ackAlerts(alertIds, '', { ack_type: ackType })
    ElMessage.success('已确认')
    recentAlerts.value.forEach(a => { if (alertIds.includes(a.id)) a.is_acked = true })
    if (array.value?.active_issues) await loadArray()
  } catch (e) { ElMessage.error('确认失败: ' + errMsg(e, '未知错误')) }
}

async function handleUndoAck({ alertIds }) {
  try {
    await api.batchUndoAck(alertIds)
    ElMessage.success('已撤销确认')
    recentAlerts.value.forEach(a => { if (alertIds.includes(a.id)) a.is_acked = false })
    if (array.value?.active_issues) await loadArray()
  } catch (e) { ElMessage.error('撤销失败: ' + errMsg(e, '未知错误')) }
}

async function handleModifyAck({ alertIds, ackType }) {
  try {
    await api.batchModifyAck(alertIds, ackType)
    ElMessage.success('已更改确认类型')
  } catch (e) { ElMessage.error('更改失败: ' + errMsg(e, '未知错误')) }
}

// ───── Data loading ─────
async function loadRecentAlerts(signal) {
  if (!array.value?.array_id) return
  try {
    const res = await api.getAlerts({ array_id: array.value.array_id, limit: 20 }, { signal })
    recentAlerts.value = res.data.items || res.data || []
  } catch (e) {
    if (e?.name !== 'CanceledError' && e?.code !== 'ERR_CANCELED') console.error('Failed to load alerts:', e)
  }
}

async function loadTags() {
  try {
    const res = await api.getTags({ signal: pageAbortController?.signal })
    tags.value = res.data || []
  } catch (e) {
    if (e?.name !== 'CanceledError' && e?.code !== 'ERR_CANCELED') console.error('Failed to load tags:', e)
  }
}

async function loadWatchers() {
  if (!array.value?.array_id) return
  try {
    const res = await api.getArrayWatchers(array.value.array_id, { signal: pageAbortController?.signal })
    watchers.value = res.data || []
  } catch (e) {
    if (e?.name !== 'CanceledError' && e?.code !== 'ERR_CANCELED') watchers.value = []
  }
}

async function loadArray() {
  if (pageAbortController) pageAbortController.abort()
  pageAbortController = new AbortController()
  const { signal } = pageAbortController
  loading.value = true
  try {
    const response = await api.getArrayStatus(route.params.id, { signal })
    array.value = response.data
    await Promise.all([loadRecentAlerts(signal), loadWatchers()])
  } catch (e) {
    if (e?.name !== 'CanceledError' && e?.code !== 'ERR_CANCELED') ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

// ───── Connection handlers ─────
async function handleConnect() {
  const saved = arrayStore.arrays.find(s => s.array_id === array.value?.array_id)
  if (saved?.has_saved_password) {
    connecting.value = true
    try {
      const result = await arrayStore.connectArray(array.value.array_id, '')
      ElMessage.success('自动连接成功')
      if (result?.agent_status === 'not_deployed') ElMessage.warning(result.hint || 'Agent 未部署')
      await loadArray(); return
    } catch { ElMessage.warning('已保存密码连接失败，请重新输入') }
    finally { connecting.value = false }
  }
  connectForm.password = ''
  connectDialogVisible.value = true
}

async function doConnect() {
  connecting.value = true
  try {
    const result = await arrayStore.connectArray(array.value.array_id, connectForm.password)
    ElMessage.success('连接成功')
    connectDialogVisible.value = false
    if (result?.agent_status === 'not_deployed') ElMessage.warning(result.hint || 'Agent 未部署')
    await loadArray()
  } catch (e) { ElMessage.error(errMsg(e, '连接失败')) }
  finally { connecting.value = false }
}

async function handleDisconnect() {
  try {
    await arrayStore.disconnectArray(array.value.array_id)
    ElMessage.success('已断开连接')
    await loadArray()
  } catch { ElMessage.error('断开连接失败') }
}

// ───── Refresh ─────
let refreshInFlight = false

async function handleRefresh() {
  if (refreshInFlight) return
  refreshInFlight = true
  refreshing.value = true
  try {
    await arrayStore.refreshArray(array.value.array_id)
    await loadArray()
    ElMessage.success('刷新成功')
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || '刷新失败'
    ElMessage.error(typeof msg === 'string' ? msg : '刷新失败')
  } finally { refreshing.value = false; refreshInFlight = false }
}

// ───── Auto-refresh (30s silent) ─────
let refreshTimer = null
let silentRefreshFails = 0

async function silentRefresh() {
  if (document.hidden || refreshing.value || connecting.value || refreshInFlight) return
  refreshInFlight = true
  try {
    const response = await api.getArrayStatus(route.params.id, { signal: pageAbortController?.signal })
    array.value = response.data
    await loadRecentAlerts(pageAbortController?.signal)
    silentRefreshFails = 0
  } catch (e) {
    if (e?.name === 'CanceledError' || e?.code === 'ERR_CANCELED') return
    if (++silentRefreshFails >= 3) { ElMessage.warning('自动刷新多次失败，请检查阵列连接状态'); silentRefreshFails = 0 }
  } finally { refreshInFlight = false }
}

// ───── WebSocket alert watcher ─────
watch(() => alertStore.recentAlerts, (newList) => {
  if (!array.value?.array_id) return
  const newItems = []
  for (const alert of newList) {
    if (alert.array_id !== array.value.array_id) continue
    const key = _alertKey(alert)
    if (seenAlertKeys.has(key)) continue
    seenAlertKeys.add(key)
    newItems.push(alert)
  }
  if (!newItems.length) return
  recentAlerts.value.unshift(...newItems)
  if (recentAlerts.value.length > 50) recentAlerts.value = recentAlerts.value.slice(0, 50)
}, { deep: true })

// Watch for status WS updates
watch(() => arrayStore.currentArray, (newVal) => {
  if (newVal && newVal.array_id === route.params.id) array.value = { ...array.value, ...newVal }
}, { deep: true })

// ───── Lifecycle ─────
onMounted(() => { loadTags(); loadArray(); refreshTimer = setInterval(silentRefresh, 30000); arrayStore.connectStatusWebSocket() })
onUnmounted(() => {
  if (pageAbortController) { pageAbortController.abort(); pageAbortController = null }
  if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null }
  arrayStore.disconnectStatusWebSocket()
})
</script>

<style scoped>
.array-detail { padding: 20px; max-width: 1400px; margin: 0 auto; }
.page-header-content { display: flex; align-items: center; gap: 16px; }
.page-title { font-size: 18px; font-weight: 600; }
.header-actions { display: flex; gap: 8px; }
.content { margin-top: 20px; display: flex; flex-direction: column; gap: 16px; }
.skeleton-zone { margin-top: 24px; padding: 20px; }
.zones-3-5-container { display: flex; flex-direction: column; gap: 16px; }

@media (min-width: 1201px) {
  .zones-3-5-container { flex-direction: row; }
  .zones-3-5-container .zone-events { flex: 0 0 calc(60% - 8px); max-width: calc(60% - 8px); }
  .zones-3-5-container .zone-observer-status { flex: 0 0 calc(40% - 8px); max-width: calc(40% - 8px); }
}
</style>
