<template>
  <el-drawer
    v-model="visible"
    :title="drawerTitle"
    direction="rtl"
    size="480px"
    :before-close="handleClose"
  >
    <template v-if="alert">
      <!-- 摘要卡片 -->
      <el-card shadow="never" class="drawer-section">
        <template #header>
          <div class="section-header">
            <el-icon><Warning /></el-icon>
            <span>告警摘要</span>
          </div>
        </template>
        <div class="summary-content">
          <el-tag
            :type="levelTagType"
            effect="dark"
            size="small"
            class="level-tag"
          >
            {{ levelLabel }}
          </el-tag>
          <span class="observer-badge">{{ observerName }}</span>
          <p class="summary-text">{{ translated.summary }}</p>
          <div class="meta-row">
            <span class="meta-item">
              <el-icon><Clock /></el-icon>
              {{ formatTime(alert.timestamp) }}
            </span>
            <span v-if="alert.array_name" class="meta-item">
              <el-icon><Monitor /></el-icon>
              {{ alert.array_name }}
            </span>
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
              :type="translated.parsed.alarm_type === 0 ? 'info' : 'warning'"
              size="small"
            >
              {{ translated.parsed.alarm_type === 0 ? '历史告警上报 (type 0)' : '事件生成 (type 1)' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="告警名称">
            {{ translated.parsed.alarm_name || '--' }}
          </el-descriptions-item>
          <el-descriptions-item label="告警 ID">
            {{ translated.parsed.alarm_id || '--' }}
          </el-descriptions-item>
          <el-descriptions-item label="动作">
            <el-tag
              v-if="translated.parsed.is_send"
              type="danger"
              size="small"
              effect="plain"
            >
              告警上报 (send alarm)
            </el-tag>
            <el-tag
              v-else-if="translated.parsed.is_resume"
              type="success"
              size="small"
              effect="plain"
            >
              告警恢复 (resume alarm)
            </el-tag>
            <el-tag v-else size="small" type="info">通知</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="恢复状态">
            <template v-if="translated.parsed.is_history">
              <el-tag type="info" size="small">历史上报 - 不走恢复</el-tag>
            </template>
            <template v-else-if="translated.parsed.recovered">
              <el-tag type="success" size="small">已恢复</el-tag>
            </template>
            <template v-else>
              <el-tag type="danger" size="small">未恢复</el-tag>
            </template>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 事件列表（alarm_type 多事件时显示） -->
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
          <div
            v-for="(evt, idx) in translated.events"
            :key="idx"
            class="event-item"
          >
            <div class="event-header">
              <el-tag
                :type="evt.is_resume ? 'success' : (evt.is_history ? 'info' : 'danger')"
                size="small"
                effect="plain"
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
          <div class="section-header">
            <el-icon><DocumentCopy /></el-icon>
            <span>原始消息</span>
          </div>
        </template>
        <div class="raw-message">
          <pre>{{ translated.original || alert.message }}</pre>
        </div>
      </el-card>

      <!-- 详细信息（details JSON） -->
      <el-card v-if="hasDetails" shadow="never" class="drawer-section">
        <template #header>
          <div class="section-header">
            <el-icon><More /></el-icon>
            <span>详细数据</span>
          </div>
        </template>
        <div class="raw-message">
          <pre>{{ formattedDetails }}</pre>
        </div>
      </el-card>
    </template>

    <template v-else>
      <el-empty description="请选择一条告警查看详情" />
    </template>
  </el-drawer>
</template>

<script setup>
import { computed } from 'vue'
import { Warning, Clock, Monitor, InfoFilled, List, Document, DocumentCopy, More } from '@element-plus/icons-vue'
import { translateAlert, getObserverName, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  alert: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue'])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

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
  try {
    return JSON.stringify(props.alert?.details, null, 2)
  } catch {
    return String(props.alert?.details)
  }
})

function formatTime(ts) {
  if (!ts) return '--'
  const d = new Date(ts)
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function handleClose(done) {
  done()
}
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

.summary-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.level-tag {
  align-self: flex-start;
}

.observer-badge {
  display: inline-block;
  padding: 2px 8px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border-radius: 4px;
  font-size: 12px;
  align-self: flex-start;
}

.summary-text {
  margin: 4px 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--el-text-color-primary);
  word-break: break-word;
}

.meta-row {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.event-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.event-item {
  padding: 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}

.event-header {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.event-name {
  font-weight: 500;
  font-size: 13px;
}

.event-id {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.event-raw {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
  padding: 6px 8px;
  border-radius: 4px;
  word-break: break-all;
  font-family: monospace;
}

.log-path code {
  display: block;
  padding: 8px;
  background: var(--el-fill-color-lighter);
  border-radius: 4px;
  font-size: 13px;
  word-break: break-all;
}

.raw-message pre {
  margin: 0;
  padding: 8px;
  background: var(--el-fill-color-lighter);
  border-radius: 4px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow-y: auto;
  font-family: monospace;
}
</style>
