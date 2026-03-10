<template>
  <el-dialog
    :model-value="visible"
    title="批量任务进度"
    width="760px"
    append-to-body
    :close-on-click-modal="false"
    @close="$emit('close')"
  >
    <div class="meta-row">
      <el-tag size="small" type="info">操作：{{ actionLabel }}</el-tag>
      <span class="meta-text">已完成 {{ completed }}/{{ total }}</span>
      <span class="meta-text">成功 {{ successCount }}，失败 {{ failedCount }}</span>
    </div>
    <el-progress :percentage="progressPercent" :status="failedCount > 0 ? 'exception' : undefined" />

    <el-table :data="rows" size="small" height="360" style="margin-top: 12px">
      <el-table-column prop="name" label="阵列" min-width="150" show-overflow-tooltip />
      <el-table-column prop="host" label="IP" width="140" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="rowStatusType(row.status)" size="small" effect="plain">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="详情" min-width="320" show-overflow-tooltip>
        <template #default="{ row }">
          <span>{{ row.detail || '--' }}</span>
        </template>
      </el-table-column>
    </el-table>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  actionLabel: { type: String, default: '' },
  total: { type: Number, default: 0 },
  completed: { type: Number, default: 0 },
  successCount: { type: Number, default: 0 },
  rows: { type: Array, default: () => [] },
})

defineEmits(['close'])

const failedCount = computed(() => Math.max(0, props.completed - props.successCount))
const progressPercent = computed(() => {
  if (!props.total) return 0
  return Math.min(100, Math.round((props.completed / props.total) * 100))
})

function rowStatusType(status) {
  if (status === '成功') return 'success'
  if (status === '成功(有警告)') return 'warning'
  if (status === '失败') return 'danger'
  if (status === '进行中') return 'warning'
  return 'info'
}
</script>

<style scoped>
.meta-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.meta-text {
  color: #606266;
  font-size: 12px;
}
</style>
