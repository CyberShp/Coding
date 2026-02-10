<template>
  <el-drawer
    v-model="visible"
    :title="drawerTitle"
    direction="rtl"
    size="520px"
    :before-close="handleClose"
  >
    <template v-if="alert">
      <!-- 三段式事件卡片 -->
      <el-card shadow="never" class="drawer-section event-card">
        <template #header>
          <div class="section-header">
            <el-tag :type="levelTagType" effect="dark" size="small">{{ levelLabel }}</el-tag>
            <span class="observer-badge">{{ observerName }}</span>
            <span v-if="alert.array_name || alert.array_id" class="meta-array">{{ alert.array_name || alert.array_id }}</span>
            <span class="meta-time">
              <el-icon><Clock /></el-icon>
              {{ formatTime(alert.timestamp) }}
            </span>
          </div>
        </template>

        <!-- 事件 -->
        <div class="three-part">
          <div class="part-row">
            <span class="part-label event-label">事件</span>
            <span class="part-text event-text">{{ translated.event || translated.summary || alert.message }}</span>
          </div>

          <!-- 影响 -->
          <div v-if="translated.impact" class="part-row">
            <span class="part-label impact-label">影响</span>
            <span class="part-text impact-text">{{ translated.impact }}</span>
          </div>

          <!-- 建议 -->
          <div v-if="translated.suggestion" class="part-row">
            <span class="part-label suggest-label">建议</span>
            <span class="part-text suggest-text">{{ translated.suggestion }}</span>
          </div>
        </div>
      </el-card>

      <!-- alarm_type 结构化信息 -->
      <el-card v-if="isAlarmType && translated.parsed" shadow="never" class="drawer-section">
        <template #header>
          <div class="section-header">
            <el-icon><InfoFilled /></el-icon>
            <span>结构化信息</span>
          </div>
        </template>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="告警类型">
            <el-tag
              :type="translated.parsed.alarm_type === 0 ? 'info' : translated.parsed.alarm_type === 2 ? 'success' : 'warning'"
              size="small"
            >
              {{ translated.parsed.alarm_type === 0 ? '事件上报 (event)' : translated.parsed.alarm_type === 1 ? '故障告警 (fault)' : '告警恢复 (resume)' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="AlarmId">
            <code>{{ translated.parsed.alarm_id || '--' }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="objType">
            <code>{{ translated.parsed.obj_type || translated.parsed.alarm_name || '--' }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="动作">
            <el-tag
              v-if="translated.parsed.is_send || translated.parsed.alarm_type === 1"
              type="danger" size="small" effect="plain"
            >故障告警</el-tag>
            <el-tag
              v-else-if="translated.parsed.is_resume || translated.parsed.alarm_type === 2"
              type="success" size="small" effect="plain"
            >告警恢复</el-tag>
            <el-tag
              v-else-if="translated.parsed.is_event || translated.parsed.alarm_type === 0"
              size="small" type="info" effect="plain"
            >事件上报</el-tag>
            <el-tag v-else size="small" type="info">通知</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="恢复状态">
            <template v-if="translated.parsed.is_event || translated.parsed.alarm_type === 0">
              <el-tag type="info" size="small">事件上报 - 无恢复策略</el-tag>
            </template>
            <template v-else-if="translated.parsed.recovered || translated.parsed.alarm_type === 2">
              <el-tag type="success" size="small">已恢复</el-tag>
            </template>
            <template v-else>
              <el-tag type="danger" size="small">未恢复</el-tag>
            </template>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 子告警列表（聚合模式下） -->
      <el-card
        v-if="alert.is_aggregated && alert.group"
        shadow="never"
        class="drawer-section"
      >
        <template #header>
          <div class="section-header">
            <el-icon><List /></el-icon>
            <span>聚合子告警 ({{ alert.group.count }} 条)</span>
          </div>
        </template>
        <div class="sub-alert-list">
          <div
            v-for="(sub, idx) in (alert.group.alerts || []).slice(0, 20)"
            :key="idx"
            class="sub-alert-item"
          >
            <el-tag :type="LEVEL_TAG_TYPES[sub.level] || 'info'" size="small" effect="plain">
              {{ LEVEL_LABELS[sub.level] || sub.level }}
            </el-tag>
            <span class="sub-obs">{{ getObserverName(sub.observer_name) }}</span>
            <span class="sub-msg">{{ (sub.message || '').substring(0, 80) }}</span>
            <span class="sub-time">{{ formatTime(sub.timestamp) }}</span>
          </div>
        </div>
      </el-card>

      <!-- 事件列表（alarm_type 多事件） -->
      <el-card
        v-if="isAlarmType && translated.events && translated.events.length > 1"
        shadow="never"
        class="drawer-section"
      >
        <template #header>
          <div class="section-header">
            <el-icon><List /></el-icon>
            <span>事件列表 ({{ translated.events.length }} 条)</span>
          </div>
        </template>
        <div class="event-list">
          <div v-for="(evt, idx) in translated.events" :key="idx" class="event-item">
            <div class="event-header">
              <el-tag
                :type="evt.is_resume ? 'success' : (evt.is_history ? 'info' : 'danger')"
                size="small" effect="plain"
              >
                {{ evt.is_resume ? '恢复' : (evt.is_history ? '历史上报' : '上报') }}
              </el-tag>
              <span class="event-name">{{ evt.alarm_name }}</span>
              <span v-if="evt.alarm_id" class="event-id">({{ evt.alarm_id }})</span>
            </div>
            <div v-if="evt.line" class="event-raw">{{ evt.line }}</div>
          </div>
        </div>
      </el-card>

      <!-- 日志来源 -->
      <el-card v-if="translated.log_path" shadow="never" class="drawer-section">
        <template #header>
          <div class="section-header">
            <el-icon><Document /></el-icon>
            <span>日志来源</span>
          </div>
        </template>
        <div class="log-path">
          <code>{{ translated.log_path }}</code>
        </div>
      </el-card>

      <!-- 原始消息 -->
      <el-card shadow="never" class="drawer-section">
        <template #header>
          <div class="section-header collapsible" @click="showOriginal = !showOriginal">
            <el-icon><DocumentCopy /></el-icon>
            <span>原始消息</span>
            <el-icon class="collapse-arrow" :class="{ expanded: showOriginal }"><ArrowRight /></el-icon>
          </div>
        </template>
        <div v-show="showOriginal" class="raw-message">
          <pre>{{ translated.original || alert.message }}</pre>
        </div>
      </el-card>

      <!-- 详细数据 -->
      <el-card v-if="hasDetails" shadow="never" class="drawer-section">
        <template #header>
          <div class="section-header collapsible" @click="showDetails = !showDetails">
            <el-icon><More /></el-icon>
            <span>详细数据</span>
            <el-icon class="collapse-arrow" :class="{ expanded: showDetails }"><ArrowRight /></el-icon>
          </div>
        </template>
        <div v-show="showDetails" class="raw-message">
          <pre>{{ formattedDetails }}</pre>
        </div>
      </el-card>

      <!-- 告警确认 -->
      <el-card shadow="never" class="drawer-section ack-section">
        <template #header>
          <div class="section-header">
            <el-icon><CircleCheck /></el-icon>
            <span>告警确认</span>
            <el-tag v-if="alert.is_acked || ackInfo" type="success" size="small" effect="dark" style="margin-left:auto">已确认</el-tag>
          </div>
        </template>

        <!-- Loading ack details -->
        <div v-if="ackLoading" class="ack-loading">
          <el-icon class="is-loading"><Loading /></el-icon> 加载确认信息...
        </div>

        <!-- Already acknowledged -->
        <div v-else-if="ackInfo" class="ack-details">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="确认人 IP">
              <code>{{ ackInfo.acked_by_ip }}</code>
            </el-descriptions-item>
            <el-descriptions-item label="确认时间">
              {{ formatTime(ackInfo.acked_at) }}
            </el-descriptions-item>
            <el-descriptions-item v-if="ackInfo.comment" label="备注">
              {{ ackInfo.comment }}
            </el-descriptions-item>
          </el-descriptions>
          <el-button
            type="warning"
            plain
            size="small"
            style="margin-top:12px"
            :loading="ackActing"
            @click="handleUnack"
          >撤销确认</el-button>
        </div>

        <!-- Not acknowledged -->
        <div v-else class="ack-form">
          <el-input
            v-model="ackComment"
            type="textarea"
            :rows="2"
            placeholder="备注（可选）"
            style="margin-bottom:10px"
          />
          <el-button
            type="success"
            :loading="ackActing"
            @click="handleAck"
          >
            <el-icon><Check /></el-icon> 确认非问题
          </el-button>
        </div>
      </el-card>
    </template>

    <template v-else>
      <el-empty description="请选择一条告警查看详情" />
    </template>
  </el-drawer>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { Warning, Clock, Monitor, InfoFilled, List, Document, DocumentCopy, More, ArrowRight, CircleCheck, Check, Loading } from '@element-plus/icons-vue'
import { translateAlert, getObserverName, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'
import { ElMessage } from 'element-plus'
import api from '@/api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  alert: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'ack-changed'])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const showOriginal = ref(false)
const showDetails = ref(false)

// Acknowledgement state
const ackInfo = ref(null)
const ackLoading = ref(false)
const ackActing = ref(false)
const ackComment = ref('')

const translated = computed(() => translateAlert(props.alert))
const isAlarmType = computed(() => props.alert?.observer_name === 'alarm_type')
const observerName = computed(() => getObserverName(props.alert?.observer_name))
const levelLabel = computed(() => LEVEL_LABELS[props.alert?.level] || props.alert?.level || '')
const levelTagType = computed(() => LEVEL_TAG_TYPES[props.alert?.level] || 'info')

const drawerTitle = computed(() => {
  if (!props.alert) return '告警详情'
  return `${observerName.value} - 告警详情`
})

const hasDetails = computed(() => {
  const d = props.alert?.details
  return d && typeof d === 'object' && Object.keys(d).length > 0
})

const formattedDetails = computed(() => {
  try { return JSON.stringify(props.alert?.details, null, 2) }
  catch { return String(props.alert?.details) }
})

// Lazy-load ack details when drawer opens or alert changes
watch(
  () => [props.modelValue, props.alert?.id],
  async ([open, alertId]) => {
    ackInfo.value = null
    ackComment.value = ''
    if (!open || !alertId) return
    await loadAckDetails(alertId)
  },
  { immediate: true },
)

async function loadAckDetails(alertId) {
  ackLoading.value = true
  try {
    const { data } = await api.getAlertAckDetails(alertId)
    ackInfo.value = Array.isArray(data) && data.length > 0 ? data[0] : null
  } catch {
    ackInfo.value = null
  } finally {
    ackLoading.value = false
  }
}

async function handleAck() {
  const alertId = props.alert?.id
  if (!alertId) return
  ackActing.value = true
  try {
    await api.ackAlerts([alertId], ackComment.value)
    ElMessage.success('已确认')
    await loadAckDetails(alertId)
    emit('ack-changed', { alertId, acked: true })
  } catch (e) {
    ElMessage.error('确认失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    ackActing.value = false
  }
}

async function handleUnack() {
  const alertId = props.alert?.id
  if (!alertId) return
  ackActing.value = true
  try {
    await api.unackAlert(alertId)
    ackInfo.value = null
    ElMessage.success('已撤销确认')
    emit('ack-changed', { alertId, acked: false })
  } catch (e) {
    ElMessage.error('撤销失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    ackActing.value = false
  }
}

function formatTime(ts) {
  if (!ts) return '--'
  const d = new Date(ts)
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function handleClose(done) { done() }
</script>

<style scoped>
.drawer-section {
  margin-bottom: 16px;
}
.drawer-section :deep(.el-card__header) {
  padding: 10px 16px;
  background-color: var(--el-fill-color-light);
}
.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 14px;
}
.section-header.collapsible {
  cursor: pointer;
}
.collapse-arrow {
  margin-left: auto;
  transition: transform 0.2s;
}
.collapse-arrow.expanded {
  transform: rotate(90deg);
}

/* Three-part event card */
.event-card :deep(.el-card__body) {
  padding: 12px 16px;
}
.meta-time {
  margin-left: auto;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  align-items: center;
  gap: 4px;
  font-weight: normal;
}
.observer-badge {
  display: inline-block;
  padding: 2px 8px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border-radius: 4px;
  font-size: 12px;
}
.meta-array {
  display: inline-block;
  padding: 2px 8px;
  background: var(--el-color-info-light-9);
  color: var(--el-color-info);
  border-radius: 4px;
  font-size: 12px;
}
.three-part {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.part-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.part-label {
  flex-shrink: 0;
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  min-width: 40px;
  text-align: center;
}
.event-label { background: #f56c6c22; color: #f56c6c; }
.impact-label { background: #e6a23c22; color: #e6a23c; }
.suggest-label { background: #67c23a22; color: #67c23a; }
.part-text {
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}
.event-text { color: var(--el-text-color-primary); font-weight: 500; }
.impact-text { color: var(--el-text-color-regular); }
.suggest-text { color: var(--el-text-color-secondary); }

/* Sub-alert list (aggregated) */
.sub-alert-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 300px;
  overflow-y: auto;
}
.sub-alert-item {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 6px 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  font-size: 12px;
  flex-wrap: wrap;
}
.sub-obs { font-weight: 500; color: var(--el-text-color-primary); }
.sub-msg { color: var(--el-text-color-regular); flex: 1; overflow: hidden; text-overflow: ellipsis; }
.sub-time { color: var(--el-text-color-secondary); white-space: nowrap; }

/* Event list */
.event-list { display: flex; flex-direction: column; gap: 10px; }
.event-item { padding: 8px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; }
.event-header { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.event-name { font-weight: 500; font-size: 13px; }
.event-id { font-size: 12px; color: var(--el-text-color-secondary); }
.event-raw {
  margin-top: 6px; font-size: 12px; color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter); padding: 6px 8px; border-radius: 4px;
  word-break: break-all; font-family: monospace;
}

.log-path code {
  display: block; padding: 8px; background: var(--el-fill-color-lighter);
  border-radius: 4px; font-size: 13px; word-break: break-all;
}
.raw-message pre {
  margin: 0; padding: 8px; background: var(--el-fill-color-lighter);
  border-radius: 4px; font-size: 12px; white-space: pre-wrap;
  word-break: break-word; max-height: 300px; overflow-y: auto;
  font-family: monospace;
}

/* Ack section */
.ack-section :deep(.el-card__body) {
  padding: 12px 16px;
}
.ack-loading {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.ack-details {
  font-size: 13px;
}
.ack-form {
  font-size: 13px;
}
</style>
