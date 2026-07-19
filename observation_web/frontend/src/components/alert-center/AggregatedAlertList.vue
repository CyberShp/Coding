<template>
  <div v-loading="loading" class="aggregated-list">
    <div
      v-for="(item, idx) in alerts"
      :key="idx"
      class="agg-item"
      :class="{ 'is-group': item.is_aggregated }"
      @click="$emit('open', item)"
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
        <el-tooltip
          placement="right"
          :show-after="500"
          :enterable="true"
          :hide-after="0"
          effect="dark"
        >
          <template #content>
            <div class="tooltip-ai-context">
              <div class="tooltip-context-line">{{ OBSERVER_CONTEXT[item.observer_name] || '观察点告警，请查看详情' }}</div>
              <div class="tooltip-similar-line">最近 24h 同类告警: {{ getSimilarAlertCount(item.observer_name) }} 条</div>
            </div>
          </template>
          <div class="agg-header">
            <el-tag :type="getLevelType(item.level)" size="small">{{ getLevelText(item.level) }}</el-tag>
            <span class="agg-obs">{{ getObserverLabel(item.observer_name) }}</span>
            <span class="agg-msg">{{ getTranslatedSummary(item) }}</span>
            <span class="agg-time">{{ formatDateTime(item.timestamp) }}</span>
            <!-- Quick ack button for unacknowledged alerts -->
            <span v-if="quickAckedIds.has(item.id)" class="quick-ack-done">已处理</span>
            <el-button
              v-else-if="!item.is_acked"
              class="quick-ack-btn"
              size="small"
              type="success"
              circle
              plain
              @click.stop="$emit('quick-ack', item)"
            >
              <el-icon><Check /></el-icon>
            </el-button>
          </div>
        </el-tooltip>
      </template>
    </div>
    <el-empty v-if="!loading && alerts.length === 0" description="暂无告警" />
  </div>
</template>

<script setup>
import { Check } from '@element-plus/icons-vue'
import { useAlertStore } from '@/stores/alerts'
import { translateAlert, getObserverName, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'

const props = defineProps({
  alerts: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  quickAckedIds: { type: Set, default: () => new Set() },
})
defineEmits(['open', 'quick-ack'])

const alertStore = useAlertStore()

// AI context descriptions for observer types
const OBSERVER_CONTEXT = {
  cpu_usage: 'CPU 使用率超阈值，建议检查进程占用',
  disk_health: '磁盘健康异常，建议检查 SMART 状态',
  port_traffic: '端口流量异常，可能存在带宽瓶颈',
  error_code: '设备报错代码，参考厂商手册',
  temperature: '温度超限，检查散热和环境',
  fan_status: '风扇状态异常，检查硬件',
  power_supply: '电源异常，检查冗余状态',
  connection_status: '连接状态变化，检查网络',
}

function getSimilarAlertCount(observerName) {
  return props.alerts.filter(a => a.observer_name === observerName).length
}

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
  // Prefer AI translation for alarm_type alerts when available
  if (row.observer_name === 'alarm_type' && row.id) {
    const aiText = alertStore.getAITranslation(row.id)
    if (aiText) return aiText
  }
  const result = translateAlert(row)
  return result.summary || row.message
}

function formatDateTime(timestamp) {
  if (!timestamp) return '-'
  return new Date(timestamp).toLocaleString('zh-CN')
}
</script>

<style scoped>
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

/* ─── Quick ack button on aggregated rows ─── */
.quick-ack-btn {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  padding: 0;
  font-size: 12px;
  margin-left: 4px;
  opacity: 0;
  transition: opacity 0.2s;
}

.agg-item:hover .quick-ack-btn {
  opacity: 1;
}

.quick-ack-done {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--el-color-success);
  margin-left: 4px;
  animation: quick-ack-fade 2s ease forwards;
}

@keyframes quick-ack-fade {
  0% { opacity: 1; }
  70% { opacity: 1; }
  100% { opacity: 0; }
}

/* ─── Tooltip AI context styles ─── */
.tooltip-ai-context {
  font-size: 13px;
  line-height: 1.6;
  max-width: 280px;
}

.tooltip-context-line {
  margin-bottom: 4px;
}

.tooltip-similar-line {
  color: #a0cfff;
  font-size: 12px;
}
</style>
