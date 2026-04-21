<template>
  <!-- Zone 2: Active Anomalies (fail-strip + real/expected/recovery) -->
  <div>
    <!-- Fail-Strip -->
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
          @click="emit('open-issue', issue)"
        >
          <strong>{{ getObserverName(issue.observer) }}</strong>: {{ issue.message }}
        </span>
      </div>
    </div>

    <!-- Real Anomalies -->
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
          @click="emit('open-issue', issue)"
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
    <el-collapse v-if="expectedAnomalies.length > 0 || recoveryEvents.length > 0" v-model="collapseActive" class="anomaly-collapse">
      <el-collapse-item v-if="expectedAnomalies.length > 0" :title="`预期异常 (${expectedAnomalies.length})`" name="expected">
        <div class="issues-list">
          <div
            v-for="issue in expectedAnomalies"
            :key="issue.key"
            class="issue-item issue-suppressed"
            @click="emit('open-issue', issue)"
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
  </div>
</template>

<script setup>
import { ref, computed, inject } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheck, Check } from '@element-plus/icons-vue'
import api from '@/api'
import { getObserverName as getObserverLabel } from '@/utils/alertTranslator'

const { array, recentAlerts } = inject('arrayDetail')

const emit = defineEmits(['open-issue', 'ack-issue'])

const collapseActive = ref([])

const activeIssues = computed(() => array.value?.active_issues || [])
const realAnomalies = computed(() => activeIssues.value.filter(i => !i.suppressed && i.level !== 'collection_error'))
const expectedAnomalies = computed(() => activeIssues.value.filter(i => i.suppressed))
const collectionFailures = computed(() => activeIssues.value.filter(i => i.level === 'collection_error'))
const recoveryEvents = computed(() => recentAlerts.value.filter(a => a.level === 'recovery' || a.is_recovery))
const unackedCount = computed(() => recentAlerts.value.filter(a => !a.is_acked).length)

function getObserverName(name) {
  return getObserverLabel(name)
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
  return `${Math.floor(diffHr / 24)} 天前`
}

function formatDateTime(timestamp) {
  if (!timestamp) return '-'
  return new Date(timestamp).toLocaleString('zh-CN')
}

async function handleAckIssue(issue) {
  if (!issue.alert_id) return
  try {
    await api.ackAlerts([issue.alert_id])
    ElMessage.success('已确认消除')
    emit('ack-issue', issue)
  } catch (e) {
    const detail = e?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '确认失败')
  }
}
</script>

<style scoped>
.zone-card { border-radius: 8px; transition: box-shadow 0.3s; }
.zone-card:hover { box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08); }
.zone-title { font-weight: 600; font-size: 15px; display: flex; align-items: center; gap: 6px; }
.card-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.header-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.fail-strip { background: #fff2f0; border-left: 4px solid #ff4d4f; border-radius: 6px; padding: 10px 14px; }
.fail-strip-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; font-weight: 600; font-size: 13px; color: #cf1322; }
.fail-strip-title { color: #cf1322; }
.fail-strip-items { display: flex; flex-direction: column; gap: 4px; }
.fail-strip-item { font-size: 12px; color: #434343; cursor: pointer; padding: 2px 0; transition: color 0.2s; }
.fail-strip-item:hover { color: #ff4d4f; }
.fail-strip-item strong { font-weight: 600; color: #595959; }

.anomaly-collapse { border: none; }
.anomaly-collapse :deep(.el-collapse-item__header) { font-size: 13px; font-weight: 500; color: #606266; }
.unacked-hint { font-size: 12px; color: var(--el-color-danger); font-weight: 500; }

.issues-list { display: flex; flex-direction: column; gap: 6px; max-height: 360px; overflow-y: auto; }
.issue-item { padding: 10px 14px; border-radius: 8px; border-left: 4px solid #dcdfe6; background: #fafafa; cursor: pointer; transition: all 0.2s ease; }
.issue-item:hover { box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08); transform: translateX(3px); }
.issue-warning { border-left-color: #e6a23c; background: #fdf6ec; }
.issue-error, .issue-critical { border-left-color: #f56c6c; background: #fef0f0; }
.issue-suppressed { opacity: 0.7; background: #f5f7fa !important; border-left-color: #909399 !important; }
.issue-recovery { border-left-color: #67c23a; background: #f0f9eb; }
.issue-suppressed .issue-title, .issue-suppressed .issue-message { color: #909399; }
.issue-acked, .issue-expires { font-size: 11px; color: #909399; margin-left: 6px; }
.issue-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 4px; }
.issue-title { font-weight: 600; font-size: 13px; color: #303133; }
.issue-message { font-size: 12px; color: #606266; line-height: 1.5; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.issue-observer { font-family: monospace; font-size: 11px; background: #f0f2f5; padding: 1px 6px; border-radius: 4px; color: #909399; }
.issue-since { font-size: 11px; font-style: italic; color: #909399; }
.issue-ack-btn { margin-left: auto; font-size: 11px; }
.issues-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 32px 0; color: #67c23a; }
.issues-empty p { margin-top: 8px; color: #909399; font-size: 14px; }
</style>
