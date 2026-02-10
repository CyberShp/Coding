<template>
  <div class="folded-alerts" :class="{ compact }">
    <template v-for="(group, gIdx) in foldedAlerts" :key="gIdx">
      <!-- Single alert (no fold) -->
      <div v-if="group.count === 1" class="fold-item" :class="{ 'is-acked': group.items[0].is_acked }" @click="$emit('select', group.items[0])">
        <div class="fold-row">
          <span class="fold-time">{{ formatDateTime(group.items[0].timestamp) }}</span>
          <el-tag :type="getLevelType(group.items[0].level)" size="small">{{ getLevelText(group.items[0].level) }}</el-tag>
          <span v-if="showArrayId" class="fold-array">{{ group.items[0].array_name || group.items[0].array_id }}</span>
          <span class="fold-obs">{{ getObserverLabel(group.items[0].observer_name) }}</span>
          <span class="fold-msg">{{ getSummary(group.items[0]) }}</span>
          <el-tag v-if="group.items[0].is_acked" type="success" size="small" effect="plain" class="ack-badge">已确认</el-tag>
          <el-button v-else size="small" text type="success" class="ack-btn" @click.stop="handleAckSingle(group.items[0])">
            <el-icon><Check /></el-icon>确认
          </el-button>
          <el-icon class="row-arrow"><ArrowRight /></el-icon>
        </div>
      </div>
      <!-- Folded repeated alerts -->
      <div v-else class="fold-item fold-group" :class="{ expanded: group.expanded }">
        <div class="fold-row fold-header" @click="handleToggle(group)">
          <span class="fold-time">{{ formatDateTime(group.latestTime) }}</span>
          <el-tag :type="getLevelType(group.worstLevel)" size="small">{{ getLevelText(group.worstLevel) }}</el-tag>
          <span v-if="showArrayId" class="fold-array">{{ group.arrayName || group.arrayId }}</span>
          <span class="fold-obs">{{ getObserverLabel(group.observer) }}</span>
          <span class="fold-msg">{{ group.summaryMsg }}</span>
          <el-tag type="warning" size="small" effect="plain" round>
            &times; {{ group.count }}
          </el-tag>
          <el-tag v-if="isGroupAllAcked(group)" type="success" size="small" effect="plain" class="ack-badge">全部已确认</el-tag>
          <el-button v-else size="small" text type="success" class="ack-btn" @click.stop="handleAckGroup(group)">
            <el-icon><Check /></el-icon>确认全组
          </el-button>
          <el-icon class="fold-arrow" :class="{ rotated: group.expanded }"><ArrowRight /></el-icon>
        </div>
        <!-- Expanded children -->
        <transition name="fold-expand">
          <div v-show="group.expanded" class="fold-children">
            <div
              v-for="(item, iIdx) in group.items"
              :key="iIdx"
              class="fold-child"
              :class="{ 'is-acked': item.is_acked }"
              @click.stop="handleChildClick(item)"
            >
              <span class="fold-time">{{ formatDateTime(item.timestamp) }}</span>
              <el-tag :type="getLevelType(item.level)" size="small">{{ getLevelText(item.level) }}</el-tag>
              <span class="fold-msg">{{ getSummary(item) }}</span>
              <el-tag v-if="item.is_acked" type="success" size="small" effect="plain" class="ack-badge">已确认</el-tag>
              <el-button v-else size="small" text type="success" class="ack-btn" @click.stop="handleAckSingle(item)">
                <el-icon><Check /></el-icon>确认
              </el-button>
              <el-icon class="row-arrow"><ArrowRight /></el-icon>
            </div>
          </div>
        </transition>
      </div>
    </template>
    <el-empty v-if="foldedAlerts.length === 0" :description="emptyText" />
  </div>
</template>

<script setup>
import { ArrowRight, Check } from '@element-plus/icons-vue'
import { translateAlert, getObserverName, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'
import { useAlertFolding } from '@/composables/useAlertFolding'
import { toRef } from 'vue'

const props = defineProps({
  /** Raw alert array (reactive) */
  alerts: { type: Array, required: true },
  /** Whether to show the array_id column (hide in detail page) */
  showArrayId: { type: Boolean, default: true },
  /** Compact mode for sidebar / dashboard */
  compact: { type: Boolean, default: false },
  /** Empty state text */
  emptyText: { type: String, default: '暂无告警' },
})

const emit = defineEmits(['select', 'ack'])

const { foldedAlerts, toggleExpand } = useAlertFolding(toRef(props, 'alerts'))

function handleToggle(group) {
  toggleExpand(group.key)
}

function handleChildClick(item) {
  emit('select', item)
}

function handleAckSingle(item) {
  if (item.id) {
    emit('ack', { alertIds: [item.id] })
  }
}

function handleAckGroup(group) {
  const ids = group.items.filter(i => i.id && !i.is_acked).map(i => i.id)
  if (ids.length) {
    emit('ack', { alertIds: ids })
  }
}

function isGroupAllAcked(group) {
  return group.items.every(i => i.is_acked)
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

function getSummary(row) {
  const result = translateAlert(row)
  return result.summary || row.message
}

function formatDateTime(timestamp) {
  if (!timestamp) return '-'
  return new Date(timestamp).toLocaleString('zh-CN')
}
</script>

<style scoped>
.folded-alerts {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.fold-item {
  padding: 10px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}

.fold-item:hover {
  background: var(--el-fill-color-light);
}

/* Grouped (folded) items get a highlight left border */
.fold-item.fold-group {
  border-left: 3px solid var(--el-color-warning);
}

.fold-item.fold-group.expanded {
  border-left-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

/* Row layout */
.fold-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 24px;
}

.fold-time {
  flex-shrink: 0;
  width: 155px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.fold-array {
  flex-shrink: 0;
  width: 95px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fold-obs {
  flex-shrink: 0;
  width: 95px;
  font-size: 13px;
  font-weight: 500;
  color: var(--el-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fold-msg {
  flex: 1;
  font-size: 13px;
  color: var(--el-text-color-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.5;
}

/* Expand/collapse arrow */
.fold-arrow {
  flex-shrink: 0;
  font-size: 14px;
  color: var(--el-text-color-placeholder);
  transition: transform 0.2s;
}

.fold-arrow.rotated {
  transform: rotate(90deg);
}

.row-arrow {
  color: var(--el-text-color-placeholder);
  font-size: 14px;
}

/* Expanded children area */
.fold-children {
  margin-top: 8px;
  padding-left: 16px;
  border-left: 2px solid var(--el-border-color-light);
}

.fold-child {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s;
  font-size: 13px;
}

.fold-child:hover {
  background: var(--el-fill-color);
}

.fold-child .fold-time {
  width: 140px;
  font-size: 12px;
}

.fold-child .fold-msg {
  font-size: 12px;
}

/* Expand transition */
.fold-expand-enter-active,
.fold-expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}

.fold-expand-enter-from,
.fold-expand-leave-to {
  opacity: 0;
  max-height: 0;
}

.fold-expand-enter-to,
.fold-expand-leave-from {
  opacity: 1;
  max-height: 2000px;
}

/* Ack button / badge */
.ack-btn {
  flex-shrink: 0;
  padding: 2px 6px;
  font-size: 12px;
}

.ack-badge {
  flex-shrink: 0;
  font-size: 11px;
}

.is-acked {
  opacity: 0.6;
}

.is-acked .fold-msg {
  text-decoration: line-through;
  color: var(--el-text-color-placeholder);
}

/* ─── Compact mode adjustments (for dashboard sidebar) ─── */
.compact .fold-item {
  padding: 8px 10px;
}

.compact .fold-time {
  width: 55px;
  font-size: 12px;
}

.compact .fold-array {
  max-width: 80px;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.compact .fold-obs {
  width: 70px;
  font-size: 12px;
}

.compact .fold-msg {
  font-size: 12px;
}

.compact .fold-child {
  padding: 5px 8px;
}

.compact .fold-child .fold-time {
  width: 55px;
  font-size: 11px;
}
</style>
