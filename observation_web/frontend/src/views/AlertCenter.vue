<template>
  <div class="alert-center">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>告警中心</span>
          <div class="filter-actions">
            <el-select v-model="filters.level" placeholder="告警级别" clearable style="width: 120px">
              <el-option label="信息" value="info" />
              <el-option label="警告" value="warning" />
              <el-option label="错误" value="error" />
              <el-option label="严重" value="critical" />
            </el-select>
            <el-select v-model="filters.observer" placeholder="观察点" clearable style="width: 140px">
              <el-option v-for="(name, key) in OBSERVER_NAMES" :key="key" :label="name" :value="key" />
            </el-select>
            <el-select v-model="filters.hours" style="width: 120px">
              <el-option label="最近 1 小时" :value="1" />
              <el-option label="最近 6 小时" :value="6" />
              <el-option label="最近 24 小时" :value="24" />
              <el-option label="最近 7 天" :value="168" />
            </el-select>
            <el-button type="primary" @click="loadAlerts">
              <el-icon><Search /></el-icon>
              查询
            </el-button>
            <el-button type="success" @click="exportAlerts" :loading="exporting">
              <el-icon><Download /></el-icon>
              导出
            </el-button>
            <el-switch
              v-model="aggregateMode"
              active-text="聚合"
              inactive-text="平铺"
              @change="loadAlerts"
              style="margin-left: 8px"
            />
          </div>
        </div>
      </template>

      <!-- Stats -->
      <el-row :gutter="20" class="stats-row">
        <el-col :span="6">
          <div class="stat-item">
            <div class="stat-value">{{ stats?.total || 0 }}</div>
            <div class="stat-label">总告警数</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat-item">
            <div class="stat-value error-text">{{ (stats?.by_level?.error || 0) + (stats?.by_level?.critical || 0) }}</div>
            <div class="stat-label">错误</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat-item">
            <div class="stat-value warning-text">{{ stats?.by_level?.warning || 0 }}</div>
            <div class="stat-label">警告</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat-item">
            <div class="stat-value info-text">{{ stats?.by_level?.info || 0 }}</div>
            <div class="stat-label">信息</div>
          </div>
        </el-col>
      </el-row>

      <!-- Alert Table (flat mode with folding) -->
      <div v-if="!aggregateMode" v-loading="loading" class="folded-alerts">
        <template v-for="(group, gIdx) in foldedAlerts" :key="gIdx">
          <!-- 单条告警（无需折叠） -->
          <div v-if="group.count === 1" class="fold-item" @click="openDrawer(group.items[0])">
            <div class="fold-row">
              <span class="fold-time">{{ formatDateTime(group.items[0].timestamp) }}</span>
              <el-tag :type="getLevelType(group.items[0].level)" size="small">{{ getLevelText(group.items[0].level) }}</el-tag>
              <span class="fold-array">{{ group.items[0].array_id }}</span>
              <span class="fold-obs">{{ getObserverLabel(group.items[0].observer_name) }}</span>
              <span class="fold-msg">{{ getTranslatedSummary(group.items[0]) }}</span>
              <el-icon class="row-arrow"><ArrowRight /></el-icon>
            </div>
          </div>
          <!-- 折叠的重复告警 -->
          <div v-else class="fold-item fold-group" :class="{ expanded: group.expanded }">
            <div class="fold-row fold-header" @click="group.expanded = !group.expanded">
              <span class="fold-time">{{ formatDateTime(group.latestTime) }}</span>
              <el-tag :type="getLevelType(group.worstLevel)" size="small">{{ getLevelText(group.worstLevel) }}</el-tag>
              <span class="fold-array">{{ group.arrayId }}</span>
              <span class="fold-obs">{{ getObserverLabel(group.observer) }}</span>
              <span class="fold-msg">{{ group.summaryMsg }}</span>
              <el-tag type="warning" size="small" effect="plain" round>
                × {{ group.count }}
              </el-tag>
              <el-icon class="fold-arrow" :class="{ rotated: group.expanded }"><ArrowRight /></el-icon>
            </div>
            <!-- 展开的子项 -->
            <transition name="fold-expand">
              <div v-show="group.expanded" class="fold-children">
                <div
                  v-for="(item, iIdx) in group.items"
                  :key="iIdx"
                  class="fold-child"
                  @click.stop="openDrawer(item)"
                >
                  <span class="fold-time">{{ formatDateTime(item.timestamp) }}</span>
                  <el-tag :type="getLevelType(item.level)" size="small">{{ getLevelText(item.level) }}</el-tag>
                  <span class="fold-msg">{{ getTranslatedSummary(item) }}</span>
                  <el-icon class="row-arrow"><ArrowRight /></el-icon>
                </div>
              </div>
            </transition>
          </div>
        </template>
        <el-empty v-if="!loading && foldedAlerts.length === 0" description="暂无告警" />
      </div>

      <!-- Aggregated view -->
      <div v-else v-loading="loading" class="aggregated-list">
        <div
          v-for="(item, idx) in alerts"
          :key="idx"
          class="agg-item"
          :class="{ 'is-group': item.is_aggregated }"
          @click="openDrawer(item)"
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
            <div class="agg-header">
              <el-tag :type="getLevelType(item.level)" size="small">{{ getLevelText(item.level) }}</el-tag>
              <span class="agg-obs">{{ getObserverLabel(item.observer_name) }}</span>
              <span class="agg-msg">{{ getTranslatedSummary(item) }}</span>
              <span class="agg-time">{{ formatDateTime(item.timestamp) }}</span>
            </div>
          </template>
        </div>
        <el-empty v-if="!loading && alerts.length === 0" description="暂无告警" />
      </div>

      <!-- 告警详情抽屉 -->
      <AlertDetailDrawer v-model="drawerVisible" :alert="selectedAlert" />

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
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Search, Download, ArrowRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import AlertDetailDrawer from '@/components/AlertDetailDrawer.vue'
import { translateAlert, getObserverName, OBSERVER_NAMES, LEVEL_LABELS, LEVEL_TAG_TYPES } from '@/utils/alertTranslator'

const route = useRoute()
const loading = ref(false)
const exporting = ref(false)
const alerts = ref([])
const stats = ref(null)
const drawerVisible = ref(false)
const selectedAlert = ref(null)
const aggregateMode = ref(false)

// ───── 告警折叠逻辑 ─────
const LEVEL_RANK = { critical: 4, error: 3, warning: 2, info: 1 }

/**
 * 将告警按 observer_name + array_id + 消息摘要 分组折叠。
 * 去除消息中的数字/时间戳以匹配"几乎一样"的告警。
 */
const foldedAlerts = computed(() => {
  const groups = []
  const map = new Map()

  for (const alert of alerts.value) {
    // 生成折叠 key：observer + array + 消息骨架（去数字/时间）
    const skeleton = (alert.message || '')
      .replace(/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}[:\d.]*/g, '#TIME#')  // 时间戳
      .replace(/\d+/g, '#N#')  // 数字
      .replace(/\s+/g, ' ')
      .trim()
      .substring(0, 80)  // 前80字符做 key

    const key = `${alert.observer_name}|${alert.array_id}|${skeleton}`

    if (map.has(key)) {
      const g = map.get(key)
      g.items.push(alert)
      g.count++
      // 更新最新时间和最高级别
      if (alert.timestamp > g.latestTime) g.latestTime = alert.timestamp
      if ((LEVEL_RANK[alert.level] || 0) > (LEVEL_RANK[g.worstLevel] || 0)) g.worstLevel = alert.level
    } else {
      const group = {
        key,
        observer: alert.observer_name,
        arrayId: alert.array_id,
        summaryMsg: getTranslatedSummary(alert),
        latestTime: alert.timestamp,
        worstLevel: alert.level,
        count: 1,
        expanded: false,
        items: [alert],
      }
      map.set(key, group)
      groups.push(group)
    }
  }

  return groups
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
  const result = translateAlert(row)
  return result.summary || row.message
}

function openDrawer(row) {
  selectedAlert.value = row
  drawerVisible.value = true
}

function formatDateTime(timestamp) {
  if (!timestamp) return '-'
  return new Date(timestamp).toLocaleString('zh-CN')
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
    
    // Load stats
    const statsResponse = await api.getAlertStats(filters.hours)
    stats.value = statsResponse.data
    pagination.total = statsResponse.data.total
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

onMounted(() => {
  // Apply filter from URL query params (e.g. ?level=error)
  if (route.query.level) {
    filters.level = route.query.level
  }
  if (route.query.observer) {
    filters.observer = route.query.observer
  }
  loadAlerts()
})
</script>

<style scoped>
.alert-center {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.filter-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.stats-row {
  margin-bottom: 20px;
  padding: 16px 0;
  border-bottom: 1px solid #ebeef5;
}

.stat-item {
  text-align: center;
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: #303133;
}

.stat-label {
  font-size: 14px;
  color: #909399;
}

.error-text {
  color: #f56c6c;
}

.warning-text {
  color: #e6a23c;
}

.info-text {
  color: #909399;
}

.clickable-table :deep(tr) {
  cursor: pointer;
}

.translated-msg {
  font-size: 13px;
  line-height: 1.6;
}

.row-arrow {
  color: var(--el-text-color-placeholder);
  font-size: 14px;
}

.pagination {
  margin-top: 20px;
  justify-content: flex-end;
}

/* Aggregated view styles */
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

/* ───── Folded alerts view ───── */
.folded-alerts {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
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
</style>
