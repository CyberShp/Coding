<template>
  <el-card v-if="task" class="active-task-banner">
    <div class="task-banner-content">
      <el-tag type="success" effect="dark" size="small">进行中</el-tag>
      <span class="task-name">{{ task.name }}</span>
      <el-tag size="small" effect="plain">{{ task.task_type_label || task.task_type }}</el-tag>
      <span class="task-duration">已运行 {{ duration }}</span>
      <el-button size="small" type="warning" plain @click="$router.push('/test-tasks')">管理</el-button>
    </div>
  </el-card>
</template>

<script setup>
defineProps({
  task: Object,
  duration: String,
})
</script>

<style scoped>
.active-task-banner {
  margin-bottom: 16px;
  border-left: 3px solid #67c23a;
}

.task-banner-content {
  display: flex;
  align-items: center;
  gap: 10px;
}

.task-name {
  font-weight: 600;
  font-size: 15px;
}

.task-duration {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-left: auto;
}
</style>
