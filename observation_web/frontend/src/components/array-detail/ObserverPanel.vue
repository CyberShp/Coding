<template>
  <!-- Zone 5: Observer Status (Phase 3 will add CRUD section here) -->
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
</template>

<script setup>
import { computed, inject } from 'vue'
import { getObserverName as getObserverLabel } from '@/utils/alertTranslator'

const { array } = inject('arrayDetail')

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

function getObserverName(name) { return getObserverLabel(name) }

function formatDateTime(timestamp) {
  if (!timestamp) return '-'
  return new Date(timestamp).toLocaleString('zh-CN')
}
</script>

<style scoped>
.zone-card { border-radius: 8px; transition: box-shadow 0.3s; }
.zone-card:hover { box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08); }
.zone-title { font-weight: 600; font-size: 15px; display: flex; align-items: center; gap: 6px; }
.card-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.observer-table { width: 100%; }
.observer-name { font-weight: 500; display: block; }
.observer-key { font-size: 11px; color: #909399; font-family: 'SF Mono', 'Fira Code', monospace; }
.observer-error { color: #f56c6c; font-size: 12px; }
.observer-ok { color: #909399; }
</style>
