<template>
  <!-- Zone 3: 最近事件流 (Recent Event Stream) -->
  <el-card class="zone-card zone-events" shadow="hover">
    <template #header>
      <div class="card-header">
        <span class="zone-title">最近事件流</span>
        <div class="header-meta">
          <!-- F205: Stream/List mode toggle -->
          <el-tooltip :content="streamMode ? '切换到列表模式' : '切换到实时流模式'" placement="top">
            <el-button
              :type="streamMode ? 'primary' : 'default'"
              size="small"
              circle
              @click="toggleStreamMode"
            >
              <el-icon><VideoPlay v-if="!streamMode" /><List v-else /></el-icon>
            </el-button>
          </el-tooltip>
          <!-- F200: Causal DAG toggle -->
          <el-tooltip content="因果分析视图" placement="top">
            <el-button
              :type="causalMode ? 'primary' : 'default'"
              size="small"
              circle
              @click="toggleCausalMode"
            >
              <el-icon><Share /></el-icon>
            </el-button>
          </el-tooltip>
          <template v-if="!streamMode">
            <el-radio-group v-model="eventTimeWindow" size="small" @change="onTimeWindowChange">
              <el-radio-button label="1h">1h</el-radio-button>
              <el-radio-button label="6h">6h</el-radio-button>
              <el-radio-button label="24h">24h</el-radio-button>
              <el-radio-button label="72h">72h</el-radio-button>
              <el-radio-button label="7d">7d</el-radio-button>
              <el-radio-button label="21d">21d</el-radio-button>
            </el-radio-group>
          </template>
          <template v-if="streamMode">
            <el-button
              :type="streamPaused ? 'warning' : 'default'"
              size="small"
              @click="streamPaused = !streamPaused"
            >
              {{ streamPaused ? `▶ 继续 (${streamPendingCount} 条等待)` : '⏸ 暂停' }}
            </el-button>
            <el-tag type="success" size="small" effect="dark">LIVE</el-tag>
          </template>
          <el-button size="small" text @click="router.push('/alerts')">查看全部</el-button>
          <!-- Zone 4: AI 释义 trigger -->
          <el-button size="small" type="primary" plain @click="aiDrawerVisible = true">
            <el-icon><MagicStick /></el-icon> AI 释义
          </el-button>
        </div>
      </div>
    </template>

    <!-- List mode -->
    <transition name="fade" mode="out-in">
      <div v-if="!streamMode && !causalMode" :key="eventTimeWindow" class="event-stream-body">
        <FoldedAlertList
          :alerts="filteredAlerts"
          :show-array-id="false"
          empty-text="该时段暂无告警事件"
          @select="openAlertDrawer"
          @ack="(data) => emit('ack', data)"
          @undo-ack="(data) => emit('undo-ack', data)"
          @modify-ack="(data) => emit('modify-ack', data)"
        />
      </div>
    </transition>

    <!-- F205: Live stream mode -->
    <div v-if="streamMode" class="live-stream-container" ref="streamContainerRef">
      <div v-if="streamAlerts.length === 0" class="stream-empty">
        等待实时告警...
      </div>
      <div
        v-for="alert in streamAlerts"
        :key="alert._streamKey"
        class="stream-alert-row"
        :class="`stream-level-${alert.level}`"
        @click="openAlertDrawer(alert)"
      >
        <span class="stream-time">{{ formatStreamTime(alert.timestamp) }}</span>
        <span class="stream-level-dot" :class="`dot-${alert.level}`"></span>
        <span class="stream-observer">{{ getObserverName(alert.observer_name) }}</span>
        <span class="stream-message">{{ alert.message }}</span>
        <span
          v-if="getStreamLatencyMs(alert) >= 5000"
          class="stream-latency"
          :class="getStreamLatencyMs(alert) >= 15000 ? 'latency-slow' : 'latency-normal'"
        >
          {{ getStreamLatencyMs(alert) >= 15000 ? '⚠' : '⏱' }} {{ formatStreamLatency(alert) }}
        </span>
      </div>
      <div ref="streamBottomRef"></div>
    </div>

    <!-- F200: Causal DAG view -->
    <div v-if="causalMode && !streamMode" class="causal-view-body">
      <CausalAlertTree
        :trees="causalTrees"
        :total-alerts="causalTotalAlerts"
        :rules-count="causalRulesCount"
        :loading="causalLoading"
        @select="openAlertDrawer"
      />
    </div>
  </el-card>

  <!-- Zone 4: AI 释义 Drawer (trigger above, content here) -->
  <el-drawer
    v-model="aiDrawerVisible"
    title="中文释义 / AI 深解释"
    direction="rtl"
    size="400px"
  >
    <div v-if="selectedInterpretation" class="interpretation-section">
      <div class="interpretation-header">
        <el-tag size="small" type="info">本地释义</el-tag>
        <span class="interpretation-alert-title">{{ selectedInterpretation.title }}</span>
      </div>
      <div class="interpretation-body">
        <p v-if="selectedInterpretation.zhMessage" class="zh-message">{{ selectedInterpretation.zhMessage }}</p>
        <p v-if="selectedInterpretation.zhSuggestion" class="zh-suggestion">
          <el-icon><ArrowRight /></el-icon> {{ selectedInterpretation.zhSuggestion }}
        </p>
      </div>
    </div>

    <div class="ai-section">
      <div v-if="aiSummaryLoading" class="ai-summary-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>AI 正在解读...</span>
      </div>
      <div v-else-if="aiSummaryError" class="ai-summary-error">
        <el-alert type="warning" :title="aiSummaryError" show-icon :closable="false" />
        <el-button type="primary" plain size="small" style="margin-top:8px" @click="fetchAISummary">重试</el-button>
      </div>
      <div v-else-if="aiSummaryText" class="ai-summary-content">
        <el-tag size="small" type="success" style="margin-bottom:8px">AI 解读</el-tag>
        <div class="ai-summary-text">{{ aiSummaryText }}</div>
      </div>
      <div v-else class="ai-summary-trigger">
        <el-button
          type="primary"
          :loading="aiSummaryLoading"
          :disabled="activeIssues.length === 0"
          @click="fetchAISummary"
        >
          <el-icon><MagicStick /></el-icon>
          获取 AI 综合解读
        </el-button>
        <p class="ai-summary-hint">
          {{ activeIssues.length > 0
            ? '基于当前活跃异常的代表条目生成解读；点击上方单项可在侧栏查看该条 AI 解读'
            : '当有活跃异常时可获取 AI 解读' }}
        </p>
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { ref, computed, watch, nextTick, inject } from 'vue'
import { useRouter } from 'vue-router'
import { VideoPlay, List, Share, MagicStick, ArrowRight, Loading } from '@element-plus/icons-vue'
import FoldedAlertList from '@/components/FoldedAlertList.vue'
import CausalAlertTree from '@/components/CausalAlertTree.vue'
import { translateAlert, getObserverName as getObserverLabel } from '@/utils/alertTranslator'
import api from '@/api'

const { array, recentAlerts, selectedAlert, openAlertDrawer } = inject('arrayDetail')

const emit = defineEmits(['ack', 'undo-ack', 'modify-ack'])

const router = useRouter()

// ───── Zone 4: AI Drawer ─────
const aiDrawerVisible = ref(false)
const aiSummaryLoading = ref(false)
const aiSummaryError = ref('')
const aiSummaryText = ref('')

const activeIssues = computed(() => array.value?.active_issues || [])

const selectedInterpretation = computed(() => {
  if (!selectedAlert.value) return null
  const t = translateAlert(selectedAlert.value)
  if (!t) return null
  return {
    title: t.title || selectedAlert.value.observer_name || '',
    zhMessage: t.zhMessage || t.message || '',
    zhSuggestion: t.zhSuggestion || t.suggestion || '',
  }
})

async function fetchAISummary() {
  aiSummaryLoading.value = true
  aiSummaryError.value = ''
  aiSummaryText.value = ''
  try {
    const { data: statusData } = await api.checkAIStatus()
    if (!statusData?.available) { aiSummaryError.value = 'AI 解读服务暂不可用'; return }
    const firstWithAlertId = activeIssues.value.find(i => i.alert_id)
    if (!firstWithAlertId) { aiSummaryError.value = '当前异常暂无关联告警 ID，请点击上方单项在侧栏查看详情'; return }
    const { data } = await api.getAIInterpretation(firstWithAlertId.alert_id)
    aiSummaryText.value = data.interpretation || '暂无解读内容'
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || 'AI 解读请求失败'
    aiSummaryError.value = typeof msg === 'string' ? msg : JSON.stringify(msg)
  } finally {
    aiSummaryLoading.value = false
  }
}

// ───── Zone 3: Time window filter ─────
const eventTimeWindow = ref('24h')

const TIME_WINDOW_MS = {
  '1h': 3600000, '6h': 6 * 3600000, '24h': 24 * 3600000,
  '72h': 72 * 3600000, '7d': 7 * 24 * 3600000, '21d': 21 * 24 * 3600000,
}
const TIME_WINDOW_HOURS = { '1h': 1, '6h': 6, '24h': 24, '72h': 72, '7d': 168, '21d': 504 }

const filteredAlerts = computed(() => {
  const cutoff = Date.now() - (TIME_WINDOW_MS[eventTimeWindow.value] || TIME_WINDOW_MS['24h'])
  return recentAlerts.value.filter(a => {
    const ts = new Date(a.timestamp || a.created_at).getTime()
    return !isNaN(ts) && ts >= cutoff
  })
})

function onTimeWindowChange() {
  if (causalMode.value) loadCausalData()
}

// ───── F200: Causal DAG Mode ─────
const causalMode = ref(false)
const causalLoading = ref(false)
const causalTrees = ref([])
const causalTotalAlerts = ref(0)
const causalRulesCount = ref(0)

async function loadCausalData() {
  if (!array.value?.array_id) return
  causalLoading.value = true
  try {
    const hours = TIME_WINDOW_HOURS[eventTimeWindow.value] || 24
    const res = await api.getCausalAlerts({ array_id: array.value.array_id, hours })
    causalTrees.value = res.data.causal_trees || []
    causalTotalAlerts.value = res.data.total_alerts || 0
    causalRulesCount.value = res.data.rules_count || 0
  } catch (e) {
    console.error('Failed to load causal data:', e)
    causalTrees.value = []
  } finally {
    causalLoading.value = false
  }
}

// ───── F205: Live Alert Stream Mode ─────
const streamMode = ref(false)
const streamPaused = ref(false)
const streamContainerRef = ref(null)
const streamBottomRef = ref(null)

const _streamItems = ref([])
const _streamPending = ref([])
let _streamKeyCounter = 0
const STREAM_MAX_ITEMS = 200
const seenStreamKeys = new Set()

const streamAlerts = computed(() => _streamItems.value)
const streamPendingCount = computed(() => _streamPending.value.length)

function _alertKey(a) {
  return a.id || `${a.timestamp}_${a.observer_name}_${(a.message || '').slice(0, 50)}`
}

function _pushStreamAlert(alert) {
  const item = { ...alert, _streamKey: `s${++_streamKeyCounter}` }
  if (streamPaused.value) {
    _streamPending.value.push(item)
  } else {
    _streamItems.value.push(item)
    if (_streamItems.value.length > STREAM_MAX_ITEMS) {
      _streamItems.value = _streamItems.value.slice(-STREAM_MAX_ITEMS)
    }
  }
}

watch(streamPaused, (paused) => {
  if (!paused && _streamPending.value.length > 0) {
    _streamItems.value.push(..._streamPending.value)
    _streamPending.value = []
    if (_streamItems.value.length > STREAM_MAX_ITEMS) {
      _streamItems.value = _streamItems.value.slice(-STREAM_MAX_ITEMS)
    }
  }
})

watch(streamMode, (active) => {
  if (active) {
    _streamKeyCounter = 0
    seenStreamKeys.clear()
    const seeded = [...recentAlerts.value]
      .reverse()
      .map(a => { seenStreamKeys.add(_alertKey(a)); return { ...a, _streamKey: `s${++_streamKeyCounter}` } })
    _streamItems.value = seeded
    _streamPending.value = []
    nextTick(() => streamBottomRef.value?.scrollIntoView({ behavior: 'instant' }))
  } else {
    _streamItems.value = []
    _streamPending.value = []
    seenStreamKeys.clear()
  }
})

watch(() => _streamItems.value.length, () => {
  if (streamPaused.value) return
  nextTick(() => streamBottomRef.value?.scrollIntoView({ behavior: 'smooth' }))
})

// Watch injected recentAlerts for new items to push to stream
watch(() => recentAlerts.value, (newAlerts) => {
  if (!streamMode.value) return
  const newItems = []
  for (const alert of newAlerts) {
    const key = _alertKey(alert)
    if (!seenStreamKeys.has(key)) { seenStreamKeys.add(key); newItems.push(alert) }
  }
  for (let i = newItems.length - 1; i >= 0; i--) _pushStreamAlert(newItems[i])
}, { deep: true })

function toggleStreamMode() {
  streamMode.value = !streamMode.value
  if (streamMode.value) causalMode.value = false
}

function toggleCausalMode() {
  causalMode.value = !causalMode.value
  if (causalMode.value) { streamMode.value = false; loadCausalData() }
}

// ───── F205/F206: Stream formatting ─────
function formatStreamTime(ts) {
  if (!ts) return '--:--:--'
  const d = new Date(ts)
  return isNaN(d.getTime()) ? '--:--:--' : d.toLocaleTimeString('zh-CN', { hour12: false })
}

function getStreamLatencyMs(alert) {
  if (!alert.created_at || !alert.timestamp) return 0
  const ms = new Date(alert.created_at).getTime() - new Date(alert.timestamp).getTime()
  return (isNaN(ms) || ms < 0) ? 0 : ms
}

function formatStreamLatency(alert) {
  const ms = getStreamLatencyMs(alert)
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

function getObserverName(name) { return getObserverLabel(name) }
</script>

<style scoped>
.zone-card { border-radius: 8px; transition: box-shadow 0.3s; }
.zone-card:hover { box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08); }
.zone-title { font-weight: 600; font-size: 15px; display: flex; align-items: center; gap: 6px; }
.card-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.header-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.event-stream-body { min-height: 100px; }

.fade-enter-active, .fade-leave-active { transition: opacity 0.25s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* F205: Live Alert Stream */
.live-stream-container { max-height: 480px; overflow-y: auto; padding: 8px 0; }

.stream-empty {
  display: flex; align-items: center; justify-content: center;
  padding: 40px 0; color: #909399; font-size: 13px;
}

.stream-alert-row {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 12px; border-bottom: 1px solid #f5f5f5;
  cursor: pointer; transition: background 0.15s; font-size: 13px;
}
.stream-alert-row:hover { background: #f5f7fa; }

.stream-level-critical, .stream-level-error { border-left: 3px solid #f56c6c; }
.stream-level-warning { border-left: 3px solid #e6a23c; }
.stream-level-info { border-left: 3px solid #909399; }
.stream-level-recovery { border-left: 3px solid #67c23a; }

.stream-time { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 11px; color: #909399; white-space: nowrap; flex-shrink: 0; }
.stream-level-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.stream-level-dot.dot-critical, .stream-level-dot.dot-error { background: #f56c6c; }
.stream-level-dot.dot-warning { background: #e6a23c; }
.stream-level-dot.dot-info { background: #909399; }
.stream-level-dot.dot-recovery { background: #67c23a; }
.stream-observer { font-size: 11px; font-weight: 500; color: #606266; white-space: nowrap; flex-shrink: 0; max-width: 80px; overflow: hidden; text-overflow: ellipsis; }
.stream-message { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #303133; }
.stream-latency { flex-shrink: 0; font-size: 10px; font-family: 'SF Mono', 'Fira Code', monospace; padding: 1px 5px; border-radius: 6px; white-space: nowrap; }
.stream-latency.latency-normal { background: #f5f5f5; color: #8c8c8c; }
.stream-latency.latency-slow { background: #fff7e6; color: #d46b08; }

/* Zone 4: AI Drawer */
.interpretation-section { margin-bottom: 16px; padding: 12px 16px; background: #f8f9fb; border-radius: 8px; border-left: 3px solid var(--el-color-primary); }
.interpretation-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.interpretation-alert-title { font-weight: 600; font-size: 13px; color: #303133; }
.interpretation-body { font-size: 13px; line-height: 1.7; color: #606266; }
.zh-message { margin: 0 0 6px; }
.zh-suggestion { margin: 0; display: flex; align-items: flex-start; gap: 4px; color: var(--el-color-primary); }
.ai-section { min-height: 60px; }
.ai-summary-loading { display: flex; align-items: center; gap: 8px; color: var(--el-text-color-secondary); font-size: 14px; padding: 8px 0; }
.ai-summary-error { font-size: 13px; }
.ai-summary-content { font-size: 14px; line-height: 1.7; }
.ai-summary-text { white-space: pre-wrap; word-break: break-word; }
.ai-summary-trigger { padding: 8px 0; }
.ai-summary-hint { margin-top: 10px; font-size: 12px; color: var(--el-text-color-secondary); }
</style>
