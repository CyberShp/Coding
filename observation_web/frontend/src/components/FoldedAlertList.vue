<template>
  <div class="folded-alerts" :class="{ compact }">
    <template v-for="(group, gIdx) in foldedAlerts" :key="gIdx">
      <!-- Single alert (no fold) -->
      <div v-if="group.count === 1" class="fold-item" :class="{ 'is-acked': group.items[0].is_acked }" @click="handleRowClick(group.items[0])">
        <div class="fold-row">
          <el-checkbox
            v-if="selectable"
            :model-value="selectedIdsSet.has(group.items[0].id)"
            @click.stop
            @update:model-value="toggleSelect(group.items[0].id)"
          />
          <span class="fold-time">{{ formatDateTime(group.items[0].timestamp) }}</span>
          <el-tag :type="getLevelType(group.items[0].level)" size="small">{{ getLevelText(group.items[0].level) }}</el-tag>
          <span v-if="showArrayId" class="fold-array">{{ group.items[0].array_name || group.items[0].array_id }}</span>
          <span class="fold-obs">{{ getObserverLabel(group.items[0].observer_name) }}</span>
          <span class="fold-msg">{{ getSummary(group.items[0]) }}</span>
          <el-dropdown v-if="group.items[0].is_acked" trigger="click" @command="(cmd) => handleAckedAction(group.items[0], cmd)">
            <el-tag type="success" size="small" effect="plain" class="ack-badge ack-action">已确认<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-tag>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="undo">撤销确认</el-dropdown-item>
                <el-dropdown-item command="confirmed_ok">更改为 确认无问题</el-dropdown-item>
                <el-dropdown-item command="dismiss">更改为 忽略24h</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-dropdown v-else trigger="click" @command="(cmd) => handleAckSingle(group.items[0], cmd)">
            <el-button size="small" text type="success" class="ack-btn">
              <el-icon><Check /></el-icon>确认<el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="confirmed_ok">确认无问题</el-dropdown-item>
                <el-dropdown-item command="dismiss">忽略 24 小时</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-icon class="row-arrow"><ArrowRight /></el-icon>
        </div>
      </div>
      <!-- Folded repeated alerts -->
      <div v-else class="fold-item fold-group" :class="{ expanded: group.expanded }">
        <div class="fold-row fold-header" @click="handleToggle(group)">
          <el-checkbox
            v-if="selectable"
            :model-value="isGroupAllSelected(group)"
            :indeterminate="isGroupPartiallySelected(group)"
            @click.stop
            @update:model-value="toggleGroupSelect(group)"
          />
          <span class="fold-time">{{ formatDateTime(group.latestTime) }}</span>
          <el-tag :type="getLevelType(group.worstLevel)" size="small">{{ getLevelText(group.worstLevel) }}</el-tag>
          <span v-if="showArrayId" class="fold-array">{{ group.arrayName || group.arrayId }}</span>
          <span class="fold-obs">{{ getObserverLabel(group.observer) }}</span>
          <span class="fold-msg">{{ group.summaryMsg }}</span>
          <el-tag type="warning" size="small" effect="plain" round>
            &times; {{ group.count }}
          </el-tag>
          <el-dropdown v-if="isGroupAllAcked(group)" trigger="click" @command="(cmd) => handleAckedGroupAction(group, cmd)">
            <el-tag type="success" size="small" effect="plain" class="ack-badge ack-action">全部已确认<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-tag>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="undo">撤销全组确认</el-dropdown-item>
                <el-dropdown-item command="confirmed_ok">更改为 全部确认无问题</el-dropdown-item>
                <el-dropdown-item command="dismiss">更改为 全部忽略24h</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-dropdown v-else trigger="click" @command="(cmd) => handleAckGroup(group, cmd)">
            <el-button size="small" text type="success" class="ack-btn" @click.stop>
              <el-icon><Check /></el-icon>确认全组<el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="confirmed_ok">全部确认无问题</el-dropdown-item>
                <el-dropdown-item command="dismiss">全部忽略 24 小时</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
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
              <el-checkbox
                v-if="selectable"
                :model-value="selectedIdsSet.has(item.id)"
                @click.stop
                @update:model-value="toggleSelect(item.id)"
              />
              <span class="fold-time">{{ formatDateTime(item.timestamp) }}</span>
              <el-tag :type="getLevelType(item.level)" size="small">{{ getLevelText(item.level) }}</el-tag>
              <span class="fold-msg">{{ getSummary(item) }}</span>
              <el-dropdown v-if="item.is_acked" trigger="click" @command="(cmd) => handleAckedAction(item, cmd)">
                <el-tag type="success" size="small" effect="plain" class="ack-badge ack-action">已确认<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-tag>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="undo">撤销确认</el-dropdown-item>
                    <el-dropdown-item command="confirmed_ok">更改为 确认无问题</el-dropdown-item>
                    <el-dropdown-item command="dismiss">更改为 忽略24h</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-dropdown v-else trigger="click" @command="(cmd) => handleAckSingle(item, cmd)">
                <el-button size="small" text type="success" class="ack-btn" @click.stop>
                  <el-icon><Check /></el-icon>确认<el-icon class="el-icon--right"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="confirmed_ok">确认无问题</el-dropdown-item>
                    <el-dropdown-item command="dismiss">忽略 24 小时</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
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
import { ArrowRight, ArrowDown, Check } from '@element-plus/icons-vue'
import { translateAlert, getObserverName, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'
import { useAlertFolding } from '@/composables/useAlertFolding'
import { toRef, computed } from 'vue'

const props = defineProps({
  /** Raw alert array (reactive) */
  alerts: { type: Array, required: true },
  /** Whether to show the array_id column (hide in detail page) */
  showArrayId: { type: Boolean, default: true },
  /** Compact mode for sidebar / dashboard */
  compact: { type: Boolean, default: false },
  /** Empty state text */
  emptyText: { type: String, default: '暂无告警' },
  /** Enable multi-select with checkboxes */
  selectable: { type: Boolean, default: false },
  /** Selected alert IDs (v-model:selectedIds) */
  selectedIds: { type: Array, default: () => [] },
})

const emit = defineEmits(['select', 'ack', 'undoAck', 'modifyAck', 'update:selectedIds'])

const { foldedAlerts, toggleExpand } = useAlertFolding(toRef(props, 'alerts'))

const selectedIdsSet = computed(() => new Set(props.selectedIds || []))

function handleToggle(group) {
  toggleExpand(group.key)
}

function handleRowClick(item) {
  emit('select', item)
}

function toggleSelect(id) {
  const set = new Set(props.selectedIds || [])
  if (set.has(id)) return emit('update:selectedIds', props.selectedIds.filter(x => x !== id))
  emit('update:selectedIds', [...(props.selectedIds || []), id])
}

function toggleGroupSelect(group) {
  const ids = group.items.filter(i => i.id).map(i => i.id)
  const set = new Set(props.selectedIds || [])
  const allSelected = ids.every(id => set.has(id))
  if (allSelected) {
    emit('update:selectedIds', (props.selectedIds || []).filter(x => !ids.includes(x)))
  } else {
    const merged = new Set([...(props.selectedIds || []), ...ids])
    emit('update:selectedIds', Array.from(merged))
  }
}

function isGroupAllSelected(group) {
  const ids = group.items.filter(i => i.id).map(i => i.id)
  const set = selectedIdsSet.value
  return ids.length > 0 && ids.every(id => set.has(id))
}

function isGroupPartiallySelected(group) {
  const ids = group.items.filter(i => i.id).map(i => i.id)
  const set = selectedIdsSet.value
  const count = ids.filter(id => set.has(id)).length
  return count > 0 && count < ids.length
}

function handleChildClick(item) {
  emit('select', item)
}

function handleAckSingle(item, ackType = 'dismiss') {
  if (item.id) {
    emit('ack', { alertIds: [item.id], ackType })
  }
}

function handleAckGroup(group, ackType = 'dismiss') {
  const ids = group.items.filter(i => i.id && !i.is_acked).map(i => i.id)
  if (ids.length) {
    emit('ack', { alertIds: ids, ackType })
  }
}

function handleAckedAction(item, cmd) {
  if (!item.id) return
  if (cmd === 'undo') {
    emit('undoAck', { alertIds: [item.id] })
  } else {
    emit('modifyAck', { alertIds: [item.id], ackType: cmd })
  }
}

function handleAckedGroupAction(group, cmd) {
  const ids = group.items.filter(i => i.id).map(i => i.id)
  if (!ids.length) return
  if (cmd === 'undo') {
    emit('undoAck', { alertIds: ids })
  } else {
    emit('modifyAck', { alertIds: ids, ackType: cmd })
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
