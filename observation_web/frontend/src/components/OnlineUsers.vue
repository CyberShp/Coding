<template>
  <el-popover
    placement="bottom"
    :width="250"
    trigger="hover"
    @before-enter="$emit('load-users')"
  >
    <template #reference>
      <div class="online-users-badge">
        <el-icon><UserFilled /></el-icon>
        <span class="online-count">{{ count }}</span>
      </div>
    </template>
    <div class="online-users-list">
      <div class="online-header">在线用户 ({{ users.length }})</div>
      <div v-if="users.length === 0" class="no-users">暂无其他用户在线</div>
      <div v-for="user in users" :key="user.ip" class="user-item">
        <span class="user-dot" :style="{ background: user.color }"></span>
        <span class="user-name">{{ user.nickname || user.ip }}</span>
        <span class="user-page" v-if="user.viewing_page">
          {{ getPageName(user.viewing_page) }}
        </span>
      </div>
    </div>
  </el-popover>
</template>

<script setup>
import { UserFilled } from '@element-plus/icons-vue'

defineProps({
  users: {
    type: Array,
    default: () => []
  },
  count: {
    type: Number,
    default: 0
  }
})

defineEmits(['load-users'])

function getPageName(path) {
  const names = {
    '/': '仪表盘',
    '/arrays': '阵列管理',
    '/alerts': '告警中心',
    '/query': '查询',
    '/test-tasks': '测试任务',
    '/card-inventory': '卡件列表',
  }
  for (const [p, name] of Object.entries(names)) {
    if (path.startsWith(p) && p !== '/') return name
  }
  return names[path] || ''
}
</script>

<style scoped>
.online-users-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: #f0f9eb;
  border-radius: 16px;
  cursor: pointer;
  color: #67c23a;
  font-size: 13px;
  transition: background 0.2s;
}

.online-users-badge:hover {
  background: #e1f3d8;
}

.online-count {
  font-weight: 600;
}

.online-users-list {
  max-height: 300px;
  overflow-y: auto;
}

.online-header {
  font-weight: 600;
  color: #303133;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid #ebeef5;
}

.no-users {
  color: #909399;
  font-size: 13px;
  text-align: center;
  padding: 10px 0;
}

.user-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 13px;
}

.user-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.user-name {
  flex: 1;
  color: #303133;
}

.user-page {
  color: #909399;
  font-size: 12px;
}
</style>
