<template>
  <el-table :data="tasks" v-loading="loading" stripe>
    <el-table-column label="任务名称" prop="name" min-width="180" />
    <el-table-column label="测试类型" width="140">
      <template #default="{ row }">
        <el-tag size="small" effect="plain">{{ row.task_type_label || row.task_type }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column label="关联阵列" width="160">
      <template #default="{ row }">
        {{ (row.array_ids || []).join(', ') || '全部' }}
      </template>
    </el-table-column>
    <el-table-column label="状态" width="100">
      <template #default="{ row }">
        <el-tag
          :type="row.status === 'running' ? 'success' : (row.status === 'completed' ? 'info' : '')"
          size="small"
        >
          {{ { created: '待开始', running: '进行中', completed: '已完成' }[row.status] || row.status }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="持续时间" width="120">
      <template #default="{ row }">
        {{ row.duration_seconds ? formatDuration(row.duration_seconds) : '--' }}
      </template>
    </el-table-column>
    <el-table-column label="告警数" width="80">
      <template #default="{ row }">
        <el-tag v-if="row.alert_count > 0" type="danger" size="small">{{ row.alert_count }}</el-tag>
        <span v-else class="muted">0</span>
      </template>
    </el-table-column>
    <el-table-column label="创建时间" width="160">
      <template #default="{ row }">
        {{ formatTime(row.created_at) }}
      </template>
    </el-table-column>
    <el-table-column label="操作" width="280" fixed="right">
      <template #default="{ row }">
        <el-button
          v-if="row.status === 'created'"
          type="success" size="small"
          @click="$emit('start', row.id)"
        >开始</el-button>
        <el-button
          v-if="row.status === 'running'"
          type="warning" size="small"
          @click="$emit('stop', row.id)"
        >结束</el-button>
        <el-button
          v-if="row.status === 'completed' || row.status === 'running'"
          type="primary" size="small" plain
          @click="$emit('summary', row.id)"
        >摘要</el-button>
        <el-button
          type="danger" size="small" plain
          @click="$emit('delete', row.id)"
        >删除</el-button>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup>
defineProps({
  tasks: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})
defineEmits(['start', 'stop', 'summary', 'delete'])

function formatDuration(sec) {
  if (!sec) return '--'
  if (sec < 60) return `${Math.round(sec)}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
}

function formatTime(ts) {
  if (!ts) return '--'
  return new Date(ts).toLocaleString('zh-CN')
}
</script>

<style scoped>
.muted { color: var(--el-text-color-placeholder); }
</style>
