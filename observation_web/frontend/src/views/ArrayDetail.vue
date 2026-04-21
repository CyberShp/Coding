<template>
  <div class="array-detail" v-loading="loading">
    <!-- Page Header -->
    <el-page-header @back="$router.back()">
      <template #content>
        <div class="page-header-content">
          <span class="page-title">{{ array?.name || '阵列详情' }}</span>
          <div class="header-actions">
            <el-button
              v-if="array && array.state !== 'connected'"
              type="primary"
              size="small"
              @click="handleConnect"
            >连接</el-button>
            <el-button
              v-else-if="array"
              size="small"
              @click="handleDisconnect"
            >断开</el-button>
            <el-button size="small" @click="handleRefresh" :loading="refreshing">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
          </div>
        </div>
      </template>
    </el-page-header>

    <!-- Skeleton loading state -->
    <div v-if="loading && !array" class="skeleton-zone">
      <el-skeleton :rows="3" animated />
    </div>

    <div class="content" v-if="array">

      <!-- ════════════════════════════════════════════════
           Zone 1: Status Strip (compact single-line)
           ════════════════════════════════════════════════ -->
      <div class="status-strip">
        <span class="status-dot" :class="`dot-${getStateType(array.state)}`"></span>
        <span class="strip-name">{{ array.name }}</span>
        <span class="strip-separator">|</span>
        <span class="strip-ip">{{ array.host }}:{{ array.port }}</span>
        <span class="strip-separator">|</span>
        <span class="strip-mode">{{ enrollmentModeText }}</span>
        <div class="strip-tags">
          <el-tag
            v-for="w in watchers"
            :key="w.ip"
            :style="{ borderColor: w.color, color: w.color }"
            effect="plain"
            size="small"
            class="watcher-tag"
          >{{ w.nickname || w.ip }}</el-tag>
          <el-select
            v-model="array.tag_id"
            placeholder="标签"
            size="small"
            clearable
            style="width: 140px"
            @change="handleTagChange"
          >
            <el-option
              v-for="tag in tags"
              :key="tag.id"
              :label="tag.parent_name ? `${tag.parent_name} / ${tag.name}` : tag.name"
              :value="tag.id"
            />
          </el-select>
        </div>
        <!-- F203: Collection Heartbeat Indicator -->
        <div class="heartbeat-badge" :class="heartbeatState">
          <span class="heartbeat-dot"></span>
          <span class="heartbeat-text">{{ heartbeatLabel }}</span>
        </div>
      </div>

      <!-- F204: Observer Activity Map -->
      <div v-if="observerMapEntries.length > 0" class="observer-map">
        <el-tooltip
          v-for="obs in observerMapEntries"
          :key="obs.name"
          :content="obs.tooltip"
          placement="top"
        >
          <span class="obs-dot" :class="obs.dotClass">
            <span class="obs-label">{{ obs.shortName }}</span>
          </span>
        </el-tooltip>
      </div>

      <!-- ════════════════════════════════════════════════
           Zone 2: 活跃异常 (Active Anomalies) — No Tabs
           ════════════════════════════════════════════════ -->

      <!-- Fail-Strip: always visible when collection failures exist -->
      <div v-if="collectionFailures.length > 0" class="fail-strip">
        <div class="fail-strip-header">
          <el-icon color="#ff4d4f"><CircleCheck /></el-icon>
          <span class="fail-strip-title">采集失败 ({{ collectionFailures.length }})</span>
        </div>
        <div class="fail-strip-items">
          <span
            v-for="issue in collectionFailures"
            :key="issue.key"
            class="fail-strip-item"
            @click="openIssueDetail(issue)"
          >
            <strong>{{ getObserverName(issue.observer) }}</strong>: {{ issue.message }}
          </span>
        </div>
      </div>

      <!-- Real Anomalies: always visible inline -->
      <el-card class="zone-card zone-anomalies" shadow="hover">
        <template #header>
          <div class="card-header">
            <el-tooltip content="来自系统级观察点：CPU、内存、AlarmType、PCIe、卡件等，不含端口误码/链路">
              <span class="zone-title">真异常</span>
            </el-tooltip>
            <div class="header-meta">
              <el-tag v-if="realAnomalies.length > 0" type="danger" size="small" effect="dark">{{ realAnomalies.length }} 项</el-tag>
              <el-tag v-else type="success" size="small" effect="dark">无异常</el-tag>
              <span v-if="unackedCount > 0" class="unacked-hint">未确认 {{ unackedCount }} 条</span>
            </div>
          </div>
        </template>

        <div v-if="realAnomalies.length > 0" class="issues-list">
          <div
            v-for="issue in realAnomalies"
            :key="issue.key"
            class="issue-item"
            :class="[`issue-${issue.level}`]"
            @click="openIssueDetail(issue)"
          >
            <div class="issue-row">
              <span class="issue-title">{{ issue.title }}</span>
              <el-tag :type="issue.level === 'error' || issue.level === 'critical' ? 'danger' : 'warning'" size="small">
                {{ issue.level === 'error' || issue.level === 'critical' ? '错误' : '警告' }}
              </el-tag>
              <span class="issue-observer">{{ getObserverName(issue.observer) }}</span>
              <span class="issue-since" v-if="issue.since">持续 {{ formatRelativeTime(issue.since) }}</span>
              <el-button
                v-if="issue.alert_id"
                size="small"
                type="success"
                text
                class="issue-ack-btn"
                @click.stop="handleAckIssue(issue)"
              ><el-icon><Check /></el-icon> 忽略</el-button>
            </div>
            <div class="issue-message">{{ issue.message }}</div>
          </div>
        </div>
        <div v-else class="issues-empty">
          <el-icon :size="40" color="#67c23a"><CircleCheck /></el-icon>
          <p>所有监测项正常运行</p>
        </div>
      </el-card>

      <!-- Expected Anomalies + Recovery Events: collapsible -->
      <el-collapse v-if="expectedAnomalies.length > 0 || recoveryEvents.length > 0" v-model="anomalyCollapseActive" class="anomaly-collapse">
        <el-collapse-item v-if="expectedAnomalies.length > 0" :title="`预期异常 (${expectedAnomalies.length})`" name="expected">
          <div class="issues-list">
            <div
              v-for="issue in expectedAnomalies"
              :key="issue.key"
              class="issue-item issue-suppressed"
              @click="openIssueDetail(issue)"
            >
              <div class="issue-row">
                <span class="issue-title">{{ issue.title }}</span>
                <el-tag type="info" size="small">已忽略</el-tag>
                <span class="issue-observer">{{ getObserverName(issue.observer) }}</span>
                <span class="issue-acked">确认人: {{ (issue.acked_by_nickname || issue.acked_by_ip) || '--' }}</span>
                <span class="issue-expires" v-if="issue.ack_expires_at">恢复: {{ formatDateTime(issue.ack_expires_at) }}</span>
              </div>
              <div class="issue-message">{{ issue.message }}</div>
            </div>
          </div>
        </el-collapse-item>

        <el-collapse-item v-if="recoveryEvents.length > 0" :title="`恢复事件 (${recoveryEvents.length})`" name="recovery">
          <div class="issues-list">
            <div v-for="evt in recoveryEvents" :key="evt.id || evt.key" class="issue-item issue-recovery">
              <div class="issue-row">
                <span class="issue-title">{{ evt.title || evt.message }}</span>
                <el-tag type="success" size="small">已恢复</el-tag>
                <span class="issue-observer">{{ getObserverName(evt.observer || evt.observer_name) }}</span>
              </div>
              <div class="issue-message">{{ evt.message }}</div>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <!-- ════════════════════════════════════════════════
           Zones 3 + 5: Widescreen 2-Column Layout
           ════════════════════════════════════════════════ -->
      <div class="zones-3-5-container">
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
                    @click="streamMode = !streamMode; causalMode = false"
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
                    @click="causalMode = !causalMode; if (causalMode) { streamMode = false; loadCausalData() }"
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
                <el-button size="small" text @click="$router.push('/alerts')">查看全部</el-button>
              </div>
            </div>
          </template>

          <!-- List mode (original) -->
          <transition name="fade" mode="out-in">
            <div v-if="!streamMode && !causalMode" :key="eventTimeWindow" class="event-stream-body">
              <FoldedAlertList
                :alerts="filteredAlerts"
                :show-array-id="false"
                empty-text="该时段暂无告警事件"
                @select="openAlertDrawer"
                @ack="handleAck"
                @undo-ack="handleUndoAck"
                @modify-ack="handleModifyAck"
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
              <span v-if="getStreamLatencyMs(alert) >= 5000" class="stream-latency" :class="getStreamLatencyMs(alert) >= 15000 ? 'latency-slow' : 'latency-normal'">
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

        <!-- Zone 5: 观察点状态 (Observer Status) -->
        <el-card class="zone-card zone-observer-status" shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="zone-title">观察点状态</span>
              <el-tag type="info" size="small">{{ observerList.length }} 个观察点</el-tag>
            </div>
          </template>

          <el-table :data="observerList" stripe size="small" class="observer-table" empty-text="暂无观察点数据">
            <el-table-column prop="name" label="名称" min-width="140">
              <template #default="{ row }">
                <span class="observer-name">{{ getObserverName(row.name) }}</span>
                <span class="observer-key">{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="最近执行时间" min-width="160">
              <template #default="{ row }">
                {{ row.last_run ? formatDateTime(row.last_run) : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="最近成功时间" min-width="160">
              <template #default="{ row }">
                {{ row.last_success ? formatDateTime(row.last_success) : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="最近失败原因" min-width="200">
              <template #default="{ row }">
                <span v-if="row.last_error" class="observer-error">{{ row.last_error }}</span>
                <span v-else class="observer-ok">-</span>
              </template>
            </el-table-column>
            <el-table-column label="平均耗时" min-width="100" align="center">
              <template #default="{ row }">
                {{ row.avg_duration != null ? `${row.avg_duration.toFixed(1)}s` : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="状态" min-width="80" align="center">
              <template #default="{ row }">
                <el-tag :type="row.healthy === false ? 'danger' : 'success'" size="small">
                  {{ row.healthy === false ? '异常' : '正常' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>

      <!-- ════════════════════════════════════════════════
           Zone 4: AI 释义 — Floating Button + Drawer
           ════════════════════════════════════════════════ -->
      <div class="ai-fab" @click="aiDrawerVisible = true">
        <el-icon :size="22"><MagicStick /></el-icon>
        <span class="ai-fab-label">AI 释义</span>
      </div>

      <el-drawer
        v-model="aiDrawerVisible"
        title="中文释义 / AI 深解释"
        direction="rtl"
        size="400px"
      >
        <!-- Local lightweight interpretation for selected alert -->
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

        <!-- AI enhanced interpretation -->
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

      <!-- ════════════════════════════════════════════════
           Operational Zones (collapsed by default)
           ════════════════════════════════════════════════ -->
      <el-collapse v-model="expandedOps" class="ops-collapse">
        <!-- Performance Monitor -->
        <el-collapse-item title="性能监控" name="perf" v-if="array.state === 'connected'">
          <PerformanceMonitor :array-id="array.array_id" />
        </el-collapse-item>

        <!-- Event Timeline -->
        <el-collapse-item title="事件时间线" name="timeline">
          <EventTimeline :array-id="array.array_id" />
        </el-collapse-item>

        <!-- Snapshot & Diff -->
        <el-collapse-item title="状态快照与对比" name="snapshot">
          <SnapshotDiff :array-id="array.array_id" />
        </el-collapse-item>

        <!-- Agent Controls -->
        <el-collapse-item name="agent">
          <template #title>
            <span>Agent 控制</span>
            <el-tag v-if="array.agent_running" type="success" size="small" style="margin-left:8px">运行中</el-tag>
            <el-tag v-else-if="array.agent_deployed" type="warning" size="small" style="margin-left:8px">已部署</el-tag>
            <el-tag v-else type="info" size="small" style="margin-left:8px">未部署</el-tag>
          </template>

          <div class="agent-actions">
            <el-progress
              v-if="isOperating"
              :percentage="100"
              :indeterminate="true"
              :duration="2"
              status="success"
            >
              <span>{{ operationText }}</span>
            </el-progress>
            <div class="agent-buttons">
              <el-button type="primary" size="small" :loading="deploying" :disabled="array.state !== 'connected'" @click="handleDeployAgent">部署 Agent</el-button>
              <el-button type="success" size="small" :loading="starting" :disabled="array.state !== 'connected' || array.agent_running" @click="handleStartAgent">启动 Agent</el-button>
              <el-button size="small" :loading="restarting" :disabled="array.state !== 'connected'" @click="handleRestartAgent">重启 Agent</el-button>
              <el-button type="danger" size="small" :loading="stopping" :disabled="array.state !== 'connected' || !array.agent_running" @click="handleStopAgent">停止 Agent</el-button>
            </div>
          </div>
        </el-collapse-item>

        <!-- Log Viewer -->
        <el-collapse-item title="在线日志查看器" name="logs" v-if="array.state === 'connected'">
          <div class="log-viewer-wrapper">
            <LogViewer :array-id="array.array_id" />
          </div>
        </el-collapse-item>
      </el-collapse>

      <!-- Alert Detail Drawer -->
      <AlertDetailDrawer v-model="drawerVisible" :alert="selectedAlert" @ack-changed="onAckChanged" />
    </div>

    <!-- Connect Dialog -->
    <el-dialog v-model="connectDialogVisible" title="连接阵列" width="400px">
      <el-form :model="connectForm">
        <el-form-item label="密码">
          <el-input
            v-model="connectForm.password"
            type="password"
            show-password
            placeholder="SSH 密码"
          />
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
import { ref, reactive, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, ArrowRight, CircleCheck, Check, User, MagicStick, Loading, VideoPlay, List, Share } from '@element-plus/icons-vue'
import { useArrayStore } from '../stores/arrays'
import { useAlertStore } from '../stores/alerts'
import api from '../api'
import LogViewer from '../components/LogViewer.vue'
import PerformanceMonitor from '../components/PerformanceMonitor.vue'
import EventTimeline from '../components/EventTimeline.vue'
import SnapshotDiff from '../components/SnapshotDiff.vue'
import AlertDetailDrawer from '@/components/AlertDetailDrawer.vue'
import FoldedAlertList from '@/components/FoldedAlertList.vue'
import CausalAlertTree from '@/components/CausalAlertTree.vue'
import { translateAlert, getObserverName as getObserverLabel, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'

const route = useRoute()
const arrayStore = useArrayStore()
const alertStore = useAlertStore()

// ───── Core state ─────
const loading = ref(true)
const refreshing = ref(false)
const connectDialogVisible = ref(false)
const connecting = ref(false)
const array = ref(null)
const deploying = ref(false)
const starting = ref(false)
const stopping = ref(false)
const restarting = ref(false)

const connectForm = reactive({ password: '' })

const recentAlerts = ref([])
const drawerVisible = ref(false)
const selectedAlert = ref(null)
const tags = ref([])
const watchers = ref([])
let pageAbortController = null

const aiSummaryLoading = ref(false)
const aiSummaryError = ref('')
const aiSummaryText = ref('')

// ───── Zone 2: Anomaly collapse (expected + recovery) ─────
const anomalyCollapseActive = ref([])

// ───── Zone 4: AI Drawer ─────
const aiDrawerVisible = ref(false)

// ───── Zone 3: Time window ─────
const eventTimeWindow = ref('24h')

// ───── Operational collapse ─────
const expandedOps = ref([])

// ───── Computed: Active issues ─────
const activeIssues = computed(() => array.value?.active_issues || [])

const realAnomalies = computed(() => activeIssues.value.filter(i => !i.suppressed && i.level !== 'collection_error'))
const expectedAnomalies = computed(() => activeIssues.value.filter(i => i.suppressed))
const collectionFailures = computed(() => activeIssues.value.filter(i => i.level === 'collection_error'))
const recoveryEvents = computed(() => {
  return recentAlerts.value.filter(a => a.level === 'recovery' || a.is_recovery)
})

const unackedCount = computed(() => recentAlerts.value.filter(a => !a.is_acked).length)

// ───── Zone 1: Status computed values ─────
const agentDotClass = computed(() => {
  if (array.value?.agent_running && array.value?.agent_healthy) return 'dot-success'
  if (array.value?.agent_running && !array.value?.agent_healthy) return 'dot-warning'
  if (array.value?.agent_deployed) return 'dot-warning'
  return 'dot-info'
})

const agentStatusText = computed(() => {
  if (array.value?.agent_running && array.value?.agent_healthy) return '运行中（健康）'
  if (array.value?.agent_running && !array.value?.agent_healthy) return '运行中（无心跳/异常）'
  if (array.value?.agent_deployed) return '已部署未运行'
  return '未部署'
})

const overallHealthType = computed(() => {
  const issues = realAnomalies.value
  if (issues.length === 0) return 'success'
  if (issues.some(i => i.level === 'critical' || i.level === 'error')) return 'danger'
  return 'warning'
})

const overallHealthText = computed(() => {
  const issues = realAnomalies.value
  if (issues.length === 0) return '健康'
  if (issues.some(i => i.level === 'critical' || i.level === 'error')) return '异常'
  return '降级'
})

const enrollmentModeText = computed(() => {
  const mode = array.value?.enrollment_mode || array.value?.collect_mode
  const map = {
    ssh_only: 'SSH only',
    agent_preferred: 'Agent 优先',
    agent_only: 'Agent only',
  }
  return map[mode] || 'SSH only'
})

const dataFreshnessClass = computed(() => {
  if (!array.value?.last_refresh) return 'freshness-stale'
  const ageMs = Date.now() - new Date(array.value.last_refresh).getTime()
  if (ageMs < 5 * 60 * 1000) return 'freshness-fresh'
  if (ageMs < 30 * 60 * 1000) return 'freshness-ok'
  return 'freshness-stale'
})

// ───── F203: Collection Heartbeat ─────
const heartbeatAgeMs = ref(0)
let heartbeatTimer = null

function updateHeartbeatAge() {
  const ts = array.value?.last_refresh || array.value?.last_heartbeat_at
  if (!ts) {
    heartbeatAgeMs.value = Infinity
    return
  }
  heartbeatAgeMs.value = Date.now() - new Date(ts).getTime()
}

const heartbeatState = computed(() => {
  const interval = (array.value?.collect_interval_s || 60) * 1000
  const age = heartbeatAgeMs.value
  if (age === Infinity) return 'hb-interrupted'
  if (age < interval * 2) return 'hb-active'
  if (age < interval * 5) return 'hb-delayed'
  return 'hb-interrupted'
})

const heartbeatLabel = computed(() => {
  const age = heartbeatAgeMs.value
  if (age === Infinity) return '未采集'
  if (age < 60000) return `${Math.round(age / 1000)}s`
  if (age < 3600000) return `${Math.round(age / 60000)}m`
  return `${Math.round(age / 3600000)}h`
})

// ───── F204: Observer Activity Map ─────
const OBSERVER_SHORT_NAMES = {
  alarm_type: 'Alarm',
  disk_smart: 'SMART',
  rebuild_status: 'Rebuild',
  bbu_status: 'BBU',
  fan_temp: 'Fan',
  pcie_error: 'PCIe',
  controller_status: 'Ctrl',
  enclosure_status: 'Encl',
  pool_status: 'Pool',
  card_info: 'Card',
}

const observerMapEntries = computed(() => {
  const obsStatus = array.value?.observer_status || {}
  return Object.entries(obsStatus).map(([name, info]) => {
    const lastTs = info.last_active_ts ? new Date(info.last_active_ts) : null
    const ageMs = lastTs ? Date.now() - lastTs.getTime() : Infinity
    const isAlerting = info.status === 'error' || info.status === 'critical'
    let dotClass = 'obs-gray'  // >1h or unknown
    if (isAlerting) dotClass = 'obs-red'
    else if (ageMs < 3600000) dotClass = 'obs-green'

    const ageText = lastTs
      ? (ageMs < 60000 ? `${Math.round(ageMs/1000)}s ago` : ageMs < 3600000 ? `${Math.round(ageMs/60000)}m ago` : `${Math.round(ageMs/3600000)}h ago`)
      : '无数据'
    const tooltip = `${name}: ${info.status || 'unknown'} (${ageText})`

    return {
      name,
      shortName: OBSERVER_SHORT_NAMES[name] || name.slice(0, 6),
      dotClass,
      tooltip,
    }
  })
})

// ───── Zone 3: Time window filter ─────
const TIME_WINDOW_MS = {
  '1h': 3600000,
  '6h': 6 * 3600000,
  '24h': 24 * 3600000,
  '72h': 72 * 3600000,
  '7d': 7 * 24 * 3600000,
  '21d': 21 * 24 * 3600000,
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
  // Time window change re-filters existing data via computed
  // F200: Also refresh causal data if in causal mode
  if (causalMode.value) loadCausalData()
}

// ───── F200: Causal DAG Mode ─────
const causalMode = ref(false)
const causalLoading = ref(false)
const causalTrees = ref([])
const causalTotalAlerts = ref(0)
const causalRulesCount = ref(0)

async function loadCausalData() {
  if (!array.value) return
  causalLoading.value = true
  try {
    const hours = TIME_WINDOW_HOURS[eventTimeWindow.value] || 24
    const res = await api.getCausalAlerts({
      array_id: array.value.array_id, hours,
    })
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

const streamAlerts = computed(() => _streamItems.value)
const streamPendingCount = computed(() => _streamPending.value.length)

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

// Flush pending alerts when unpausing
watch(streamPaused, (paused) => {
  if (!paused && _streamPending.value.length > 0) {
    _streamItems.value.push(..._streamPending.value)
    _streamPending.value = []
    if (_streamItems.value.length > STREAM_MAX_ITEMS) {
      _streamItems.value = _streamItems.value.slice(-STREAM_MAX_ITEMS)
    }
  }
})

// Seed stream on enter; clear on leave
watch(streamMode, (active) => {
  if (active) {
    _streamKeyCounter = 0
    const seeded = [...recentAlerts.value]
      .reverse()
      .map(a => ({ ...a, _streamKey: `s${++_streamKeyCounter}` }))
    _streamItems.value = seeded
    _streamPending.value = []
    // Register seed alerts so refresh/reconnect won't duplicate them
    for (const a of recentAlerts.value) {
      seenAlertKeys.add(_alertKey(a))
    }
    nextTick(() => {
      streamBottomRef.value?.scrollIntoView({ behavior: 'instant' })
    })
  } else {
    _streamItems.value = []
    _streamPending.value = []
  }
})

// Auto-scroll to bottom when new stream items arrive
watch(
  () => _streamItems.value.length,
  () => {
    if (streamPaused.value) return
    nextTick(() => {
      streamBottomRef.value?.scrollIntoView({ behavior: 'smooth' })
    })
  }
)

function formatStreamTime(ts) {
  if (!ts) return '--:--:--'
  const d = new Date(ts)
  if (isNaN(d.getTime())) return '--:--:--'
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

// F206: Latency helpers for stream mode
function getStreamLatencyMs(alert) {
  if (!alert.created_at || !alert.timestamp) return 0
  const ms = new Date(alert.created_at).getTime() - new Date(alert.timestamp).getTime()
  return (isNaN(ms) || ms < 0) ? 0 : ms
}

function formatStreamLatency(alert) {
  const ms = getStreamLatencyMs(alert)
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

// ───── Zone 4: Local interpretation for selected alert ─────
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

// ───── Zone 5: Observer list ─────
const observerList = computed(() => {
  const status = array.value?.observer_status || array.value?.observers || {}
  if (Array.isArray(status)) return status
  return Object.entries(status).map(([name, info]) => ({
    name,
    last_run: info.last_run || info.last_executed || info.last_active_ts,
    last_success: info.last_success || (info.status === 'ok' ? info.last_active_ts : null),
    last_error: info.last_error || info.error,
    avg_duration: info.avg_duration ?? info.duration,
    healthy: info.healthy ?? (info.status === 'ok' || info.status === 'healthy'),
  }))
})

// ───── Utility functions ─────
function getAlertTranslation(alert) {
  return translateAlert(alert)
}

function getObserverName(name) {
  return getObserverLabel(name)
}

function getStateType(state) {
  const types = { connected: 'success', connecting: 'warning', disconnected: 'info', error: 'danger' }
  return types[state] || 'info'
}

function getStateText(state) {
  const texts = { connected: '已连接', connecting: '连接中', disconnected: '未连接', error: '错误' }
  return texts[state] || state
}

function errMsg(error, fallback) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (typeof error?.message === 'string') return error.message
  return fallback
}

function getLevelType(level) {
  return LEVEL_TAG_TYPES[level] || 'info'
}

function getLevelText(level) {
  return LEVEL_LABELS[level] || level
}

function formatDateTime(timestamp) {
  if (!timestamp) return '-'
  return new Date(timestamp).toLocaleString('zh-CN')
}

function formatRelativeTime(ts) {
  if (!ts) return ''
  const now = Date.now()
  const then = new Date(ts).getTime()
  if (isNaN(then)) return ts
  const diffSec = Math.floor((now - then) / 1000)
  if (diffSec < 60) return `${diffSec} 秒前`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr} 小时前`
  const diffDay = Math.floor(diffHr / 24)
  return `${diffDay} 天前`
}

const isOperating = computed(() => deploying.value || starting.value || stopping.value || restarting.value)

const operationText = computed(() => {
  if (deploying.value) return '部署中...'
  if (starting.value) return '启动中...'
  if (restarting.value) return '重启中...'
  if (stopping.value) return '停止中...'
  return ''
})

// ───── Issue / Alert handlers ─────
async function handleAckIssue(issue) {
  if (!issue.alert_id) return
  try {
    await api.ackAlerts([issue.alert_id])
    ElMessage.success('已确认消除')
    if (array.value?.active_issues) {
      array.value.active_issues = array.value.active_issues.filter(i => i.key !== issue.key)
    }
  } catch (e) {
    ElMessage.error('确认失败: ' + errMsg(e, '未知错误'))
  }
}

function openIssueDetail(issue) {
  selectedAlert.value = {
    id: issue.alert_id,
    array_id: array.value?.array_id,
    observer_name: issue.observer,
    level: issue.level,
    message: issue.message,
    details: issue.details || {},
    timestamp: issue.latest || issue.since || '',
  }
  drawerVisible.value = true
}

function openAlertDrawer(alert) {
  selectedAlert.value = alert
  drawerVisible.value = true
}

async function handleAck({ alertIds, ackType = 'dismiss' }) {
  try {
    await api.ackAlerts(alertIds, '', { ack_type: ackType })
    ElMessage.success('已确认')
    recentAlerts.value.forEach(a => { if (alertIds.includes(a.id)) a.is_acked = true })
    if (array.value?.active_issues) await loadArray()
  } catch (e) {
    ElMessage.error('确认失败: ' + errMsg(e, '未知错误'))
  }
}

async function handleUndoAck({ alertIds }) {
  try {
    await api.batchUndoAck(alertIds)
    ElMessage.success('已撤销确认')
    recentAlerts.value.forEach(a => { if (alertIds.includes(a.id)) a.is_acked = false })
    if (array.value?.active_issues) await loadArray()
  } catch (e) {
    ElMessage.error('撤销失败: ' + errMsg(e, '未知错误'))
  }
}

async function handleModifyAck({ alertIds, ackType }) {
  try {
    await api.batchModifyAck(alertIds, ackType)
    ElMessage.success('已更改确认类型')
  } catch (e) {
    ElMessage.error('更改失败: ' + errMsg(e, '未知错误'))
  }
}

function onAckChanged({ alertId, acked }) {
  const a = recentAlerts.value.find(x => x.id === alertId)
  if (a) a.is_acked = acked
  if (array.value?.array_id) loadArray()
}

// ───── AI Summary ─────
async function fetchAISummary() {
  aiSummaryLoading.value = true
  aiSummaryError.value = ''
  aiSummaryText.value = ''
  try {
    const { data: statusData } = await api.checkAIStatus()
    if (!statusData?.available) {
      aiSummaryError.value = 'AI 解读服务暂不可用'
      return
    }
    const firstWithAlertId = activeIssues.value.find(i => i.alert_id)
    if (!firstWithAlertId) {
      aiSummaryError.value = '当前异常暂无关联告警 ID，请点击上方单项在侧栏查看详情'
      return
    }
    const { data } = await api.getAIInterpretation(firstWithAlertId.alert_id)
    aiSummaryText.value = data.interpretation || '暂无解读内容'
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || 'AI 解读请求失败'
    aiSummaryError.value = typeof msg === 'string' ? msg : JSON.stringify(msg)
  } finally {
    aiSummaryLoading.value = false
  }
}

// ───── Alert dedup keys (shared by WS watcher + loadRecentAlerts) ─────
const seenAlertKeys = new Set()

function _alertKey(a) {
  return a.id || `${a.timestamp}_${a.observer_name}_${(a.message || '').slice(0, 50)}`
}

// ───── Data loading ─────
async function loadRecentAlerts(signal = undefined) {
  if (!array.value?.array_id) return
  try {
    const res = await api.getAlerts({ array_id: array.value.array_id, limit: 20 }, { signal })
    const newAlerts = res.data.items || res.data || []
    recentAlerts.value = newAlerts
    // F205: push unseen alerts to stream (handles silent refresh / reconnect catch-up)
    if (streamMode.value) {
      const unseen = []
      for (const alert of newAlerts) {
        const key = _alertKey(alert)
        if (!seenAlertKeys.has(key)) {
          seenAlertKeys.add(key)
          unseen.push(alert)
        }
      }
      for (let i = unseen.length - 1; i >= 0; i--) {
        _pushStreamAlert(unseen[i])
      }
    }
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    console.error('Failed to load alerts:', error)
  }
}

async function loadTags() {
  try {
    const signal = pageAbortController?.signal
    const res = await api.getTags({ signal })
    tags.value = res.data || []
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    console.error('Failed to load tags:', error)
  }
}

async function handleTagChange(tagId) {
  if (!array.value?.array_id) return
  try {
    await api.updateArray(array.value.array_id, { tag_id: tagId || null })
    ElMessage.success('标签已更新')
    await loadArray()
  } catch (e) {
    ElMessage.error('更新失败: ' + errMsg(e, '未知错误'))
  }
}

async function loadWatchers() {
  if (!array.value?.array_id) return
  try {
    const signal = pageAbortController?.signal
    const res = await api.getArrayWatchers(array.value.array_id, { signal })
    watchers.value = res.data || []
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    watchers.value = []
  }
}

async function loadArray() {
  if (pageAbortController) pageAbortController.abort()
  pageAbortController = new AbortController()
  const { signal } = pageAbortController
  loading.value = true
  try {
    const arrayId = route.params.id
    const response = await api.getArrayStatus(arrayId, { signal })
    array.value = response.data
    await Promise.all([loadRecentAlerts(signal), loadWatchers()])
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

// ───── Connection handlers ─────
async function handleConnect() {
  const statusData = arrayStore.arrays.find(s => s.array_id === array.value?.array_id)
  if (statusData?.has_saved_password) {
    connecting.value = true
    try {
      const result = await arrayStore.connectArray(array.value.array_id, '')
      ElMessage.success('自动连接成功')
      if (result?.agent_status === 'not_deployed') {
        ElMessage.warning(result.hint || 'Agent 未部署')
      }
      await loadArray()
      return
    } catch (error) {
      ElMessage.warning('已保存密码连接失败，请重新输入')
    } finally {
      connecting.value = false
    }
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
    if (result?.agent_status === 'not_deployed') {
      ElMessage.warning(result.hint || 'Agent 未部署')
    }
    await loadArray()
  } catch (error) {
    ElMessage.error(errMsg(error, '连接失败'))
  } finally {
    connecting.value = false
  }
}

async function handleDisconnect() {
  try {
    await arrayStore.disconnectArray(array.value.array_id)
    ElMessage.success('已断开连接')
    await loadArray()
  } catch (error) {
    ElMessage.error('断开连接失败')
  }
}

// ───── Refresh handlers ─────
let refreshInFlight = false

async function handleRefresh() {
  if (refreshInFlight) return
  refreshInFlight = true
  refreshing.value = true
  try {
    await arrayStore.refreshArray(array.value.array_id)
    await loadArray()
    ElMessage.success('刷新成功')
  } catch (error) {
    const msg = error.response?.data?.detail || error.message || '刷新失败'
    ElMessage.error(typeof msg === 'string' ? msg : '刷新失败')
  } finally {
    refreshing.value = false
    refreshInFlight = false
  }
}

// ───── Agent handlers ─────
async function handleDeployAgent() {
  deploying.value = true
  try {
    const res = await api.deployAgent(array.value.array_id)
    const data = res?.data ?? res
    if (data?.warnings && data.warnings.length > 0) {
      ElMessage.warning('部署成功（有警告）：' + data.warnings.join('; '))
    } else {
      ElMessage.success('部署成功')
    }
    await loadArray()
  } catch (error) {
    ElMessage.error(errMsg(error, '部署失败'))
  } finally {
    deploying.value = false
  }
}

async function handleStartAgent() {
  starting.value = true
  try {
    await api.startAgent(array.value.array_id)
    ElMessage.success('启动成功')
    await loadArray()
  } catch (error) {
    ElMessage.error(errMsg(error, '启动失败'))
  } finally {
    starting.value = false
  }
}

async function handleRestartAgent() {
  restarting.value = true
  try {
    await api.restartAgent(array.value.array_id)
    ElMessage.success('重启成功')
    await loadArray()
  } catch (error) {
    ElMessage.error(errMsg(error, '重启失败'))
  } finally {
    restarting.value = false
  }
}

async function handleStopAgent() {
  stopping.value = true
  try {
    await api.stopAgent(array.value.array_id)
    ElMessage.success('停止成功')
    await loadArray()
  } catch (error) {
    ElMessage.error(errMsg(error, '停止失败'))
  } finally {
    stopping.value = false
  }
}

// ───── Auto-refresh (30s silent) ─────
let refreshTimer = null
let silentRefreshFails = 0
const MAX_SILENT_FAILS = 3

async function silentRefresh() {
  if (document.hidden) return
  if (isOperating.value || refreshing.value || connecting.value) return
  if (refreshInFlight) return

  refreshInFlight = true
  try {
    const arrayId = route.params.id
    const signal = pageAbortController?.signal
    const response = await api.getArrayStatus(arrayId, { signal })
    array.value = response.data
    await loadRecentAlerts(signal)
    silentRefreshFails = 0
  } catch (err) {
    if (err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') return
    silentRefreshFails++
    console.warn(`Silent refresh failed (${silentRefreshFails}/${MAX_SILENT_FAILS}):`, err.message)
    if (silentRefreshFails >= MAX_SILENT_FAILS) {
      ElMessage.warning('自动刷新多次失败，请检查阵列连接状态')
      silentRefreshFails = 0
    }
  } finally {
    refreshInFlight = false
  }
}

// ───── WebSocket watcher ─────
watch(
  () => alertStore.recentAlerts,
  (newList) => {
    if (!array.value?.array_id) return
    const arrayId = array.value.array_id
    // Consume ALL unseen alerts for this array (handles batch refill on reconnect)
    const newItems = []
    for (const alert of newList) {
      if (alert.array_id !== arrayId) continue
      const key = _alertKey(alert)
      if (seenAlertKeys.has(key)) continue
      seenAlertKeys.add(key)
      newItems.push(alert)
    }
    if (newItems.length === 0) return
    recentAlerts.value.unshift(...newItems)
    if (recentAlerts.value.length > 50) {
      recentAlerts.value = recentAlerts.value.slice(0, 50)
    }
    // F205: push to live stream (oldest first for chronological order)
    if (streamMode.value) {
      for (let i = newItems.length - 1; i >= 0; i--) {
        _pushStreamAlert(newItems[i])
      }
    }
  },
  { deep: true }
)

// ───── Lifecycle ─────
onMounted(() => {
  loadTags()
  loadArray()
  refreshTimer = setInterval(silentRefresh, 30000)
  // F203: heartbeat age ticker (update every second)
  updateHeartbeatAge()
  heartbeatTimer = setInterval(updateHeartbeatAge, 1000)
  // Connect status WebSocket — real-time updates without manual refresh
  arrayStore.connectStatusWebSocket()
})

onUnmounted(() => {
  if (pageAbortController) {
    pageAbortController.abort()
    pageAbortController = null
  }
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
  arrayStore.disconnectStatusWebSocket()
})

// Watch for status WebSocket updates to currentArray
watch(
  () => arrayStore.currentArray,
  (newVal) => {
    if (newVal && newVal.array_id === route.params.id) {
      array.value = { ...array.value, ...newVal }
    }
  },
  { deep: true },
)
</script>

<style scoped>
/* ───── Layout ───── */
.array-detail {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.page-title {
  font-size: 18px;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.content {
  margin-top: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.skeleton-zone {
  margin-top: 24px;
  padding: 20px;
}

/* ───── Zone Cards ───── */
.zone-card {
  border-radius: 8px;
  transition: box-shadow 0.3s;
}

.zone-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
}

.zone-title {
  font-weight: 600;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* ───── Zone 1: Status Strip ───── */
.status-strip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  background: #fafafa;
  border-bottom: 1px solid #ebeef5;
  border-radius: 6px;
  font-size: 13px;
  flex-wrap: wrap;
  min-height: 40px;
}

.strip-name {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}

.strip-ip {
  color: #606266;
  font-family: 'SF Mono', 'Fira Code', monospace;
}

.strip-mode {
  color: #909399;
  font-size: 12px;
}

.strip-separator {
  color: #dcdfe6;
  font-size: 12px;
}

.strip-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}

/* Status dots */
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

.dot-success { background: #67c23a; box-shadow: 0 0 6px rgba(103, 194, 58, 0.5); }
.dot-warning { background: #e6a23c; box-shadow: 0 0 6px rgba(230, 162, 60, 0.5); }
.dot-danger  { background: #f56c6c; box-shadow: 0 0 6px rgba(245, 108, 108, 0.5); }
.dot-info    { background: #909399; }

/* Data freshness */
.freshness-fresh { color: #67c23a; }
.freshness-ok    { color: #e6a23c; }
.freshness-stale { color: #f56c6c; }

/* ───── F203: Heartbeat Badge ───── */
.heartbeat-badge {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
  margin-left: 8px;
  white-space: nowrap;
}
.heartbeat-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}
.hb-active { background: #f0fdf4; color: #16a34a; }
.hb-active .heartbeat-dot { background: #16a34a; animation: hb-pulse 2s infinite; }
.hb-delayed { background: #fffbeb; color: #d97706; }
.hb-delayed .heartbeat-dot { background: #d97706; }
.hb-interrupted { background: #fef2f2; color: #dc2626; }
.hb-interrupted .heartbeat-dot { background: #dc2626; }

@keyframes hb-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.7); }
}

/* ───── F204: Observer Activity Map ───── */
.observer-map {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  flex-wrap: wrap;
  border-bottom: 1px solid #f0f0f0;
}
.obs-dot {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  cursor: default;
  transition: all 0.2s;
}
.obs-dot:hover { transform: scale(1.05); }
.obs-label { font-weight: 500; }
.obs-green { background: #f0fdf4; color: #16a34a; }
.obs-green::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: #16a34a; display: inline-block; }
.obs-gray { background: #f5f5f5; color: #8c8c8c; }
.obs-gray::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: #8c8c8c; display: inline-block; }
.obs-red { background: #fef2f2; color: #dc2626; }
.obs-red::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: #dc2626; display: inline-block; animation: obs-blink 1s infinite; }

@keyframes obs-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.watcher-tag {
  font-size: 11px;
}

/* ───── Zone 2: Fail-Strip + Anomalies ───── */
.fail-strip {
  background: #fff2f0;
  border-left: 4px solid #ff4d4f;
  border-radius: 6px;
  padding: 10px 14px;
}

.fail-strip-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-weight: 600;
  font-size: 13px;
  color: #cf1322;
}

.fail-strip-title {
  color: #cf1322;
}

.fail-strip-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.fail-strip-item {
  font-size: 12px;
  color: #434343;
  cursor: pointer;
  padding: 2px 0;
  transition: color 0.2s;
}

.fail-strip-item:hover {
  color: #ff4d4f;
}

.fail-strip-item strong {
  font-weight: 600;
  color: #595959;
}

.anomaly-collapse {
  border: none;
}

.anomaly-collapse :deep(.el-collapse-item__header) {
  font-size: 13px;
  font-weight: 500;
  color: #606266;
}

.unacked-hint {
  font-size: 12px;
  color: var(--el-color-danger);
  font-weight: 500;
}

.issues-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 360px;
  overflow-y: auto;
}

.issue-item {
  padding: 10px 14px;
  border-radius: 8px;
  border-left: 4px solid #dcdfe6;
  background: #fafafa;
  cursor: pointer;
  transition: all 0.2s ease;
}

.issue-item:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  transform: translateX(3px);
}

.issue-warning  { border-left-color: #e6a23c; background: #fdf6ec; }
.issue-error,
.issue-critical { border-left-color: #f56c6c; background: #fef0f0; }
.issue-suppressed {
  opacity: 0.7;
  background: #f5f7fa !important;
  border-left-color: #909399 !important;
}
.issue-failure  { border-left-color: #f56c6c; background: #fef0f0; }
.issue-recovery { border-left-color: #67c23a; background: #f0f9eb; }

.issue-suppressed .issue-title,
.issue-suppressed .issue-message { color: #909399; }
.issue-acked, .issue-expires { font-size: 11px; color: #909399; margin-left: 6px; }

.issue-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.issue-title {
  font-weight: 600;
  font-size: 13px;
  color: #303133;
}

.issue-message {
  font-size: 12px;
  color: #606266;
  line-height: 1.5;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.issue-observer {
  font-family: monospace;
  font-size: 11px;
  background: #f0f2f5;
  padding: 1px 6px;
  border-radius: 4px;
  color: #909399;
}

.issue-since {
  font-size: 11px;
  font-style: italic;
  color: #909399;
}

.issue-ack-btn {
  margin-left: auto;
  font-size: 11px;
}

.issues-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 0;
  color: #67c23a;
}

.issues-empty p {
  margin-top: 8px;
  color: #909399;
  font-size: 14px;
}

.issues-empty-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 0;
  color: #909399;
  font-size: 13px;
}

/* ───── Zones 3+5: 2-Column Layout ───── */
.zones-3-5-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

@media (min-width: 1201px) {
  .zones-3-5-container {
    flex-direction: row;
  }
  .zones-3-5-container .zone-events {
    flex: 0 0 calc(60% - 8px);
    max-width: calc(60% - 8px);
  }
  .zones-3-5-container .zone-observer-status {
    flex: 0 0 calc(40% - 8px);
    max-width: calc(40% - 8px);
  }
}

/* ───── Zone 3: Event Stream ───── */
.event-stream-body {
  min-height: 100px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ───── Zone 4: AI Interpretation ───── */
.interpretation-section {
  margin-bottom: 16px;
  padding: 12px 16px;
  background: #f8f9fb;
  border-radius: 8px;
  border-left: 3px solid var(--el-color-primary);
}

.interpretation-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.interpretation-alert-title {
  font-weight: 600;
  font-size: 13px;
  color: #303133;
}

.interpretation-body {
  font-size: 13px;
  line-height: 1.7;
  color: #606266;
}

.zh-message {
  margin: 0 0 6px;
}

.zh-suggestion {
  margin: 0;
  display: flex;
  align-items: flex-start;
  gap: 4px;
  color: var(--el-color-primary);
}

.ai-section {
  min-height: 60px;
}

.ai-summary-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--el-text-color-secondary);
  font-size: 14px;
  padding: 8px 0;
}

.ai-summary-error {
  font-size: 13px;
}

.ai-summary-content {
  font-size: 14px;
  line-height: 1.7;
}

.ai-summary-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.ai-summary-trigger {
  padding: 8px 0;
}

.ai-summary-hint {
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* ───── Zone 4: AI FAB + Drawer ───── */
.ai-fab {
  position: fixed;
  bottom: 32px;
  right: 32px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 18px;
  background: var(--el-color-primary);
  color: #fff;
  border-radius: 24px;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.4);
  transition: transform 0.2s, box-shadow 0.2s;
  z-index: 100;
  font-size: 13px;
  font-weight: 500;
}

.ai-fab:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(64, 158, 255, 0.5);
}

.ai-fab-label {
  white-space: nowrap;
}

/* ───── Zone 5: Observer Status ───── */
.observer-table {
  width: 100%;
}

.observer-name {
  font-weight: 600;
  font-size: 13px;
  display: block;
}

.observer-key {
  font-family: monospace;
  font-size: 11px;
  color: #909399;
}

.observer-error {
  color: #f56c6c;
  font-size: 12px;
}

.observer-ok {
  color: #909399;
}

/* ───── Operational Collapse ───── */
.ops-collapse {
  margin-top: 4px;
}

.ops-collapse :deep(.el-collapse-item__header) {
  font-weight: 600;
  font-size: 14px;
}

.agent-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.agent-buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.log-viewer-wrapper {
  height: 500px;
}

/* ───── F205: Live Alert Stream ───── */
.live-stream-container {
  max-height: 480px;
  overflow-y: auto;
  padding: 8px 0;
}

.stream-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
  color: #909399;
  font-size: 13px;
}

.stream-alert-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-bottom: 1px solid #f5f5f5;
  cursor: pointer;
  transition: background 0.15s;
  font-size: 13px;
}

.stream-alert-row:hover {
  background: #f5f7fa;
}

.stream-level-critical,
.stream-level-error {
  border-left: 3px solid #f56c6c;
}

.stream-level-warning {
  border-left: 3px solid #e6a23c;
}

.stream-level-info {
  border-left: 3px solid #909399;
}

.stream-level-recovery {
  border-left: 3px solid #67c23a;
}

.stream-time {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 11px;
  color: #909399;
  white-space: nowrap;
  flex-shrink: 0;
}

.stream-level-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.stream-level-dot.dot-critical,
.stream-level-dot.dot-error { background: #f56c6c; }
.stream-level-dot.dot-warning { background: #e6a23c; }
.stream-level-dot.dot-info { background: #909399; }
.stream-level-dot.dot-recovery { background: #67c23a; }

.stream-observer {
  font-size: 11px;
  font-weight: 500;
  color: #606266;
  white-space: nowrap;
  flex-shrink: 0;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stream-message {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #303133;
}

.stream-latency {
  flex-shrink: 0;
  font-size: 10px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  padding: 1px 5px;
  border-radius: 6px;
  white-space: nowrap;
}

.stream-latency.latency-normal {
  background: #f5f5f5;
  color: #8c8c8c;
}

.stream-latency.latency-slow {
  background: #fff7e6;
  color: #d46b08;
}
</style>
