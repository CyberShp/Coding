<template>
  <div class="sidebar">
    <div class="logo">
      <el-icon><Monitor /></el-icon>
      <span>观察点监控</span>
    </div>
    <el-menu
      :default-active="activeMenu"
      router
      class="sidebar-menu"
    >
      <el-menu-item index="/">
        <el-icon><Odometer /></el-icon>
        <span>仪表盘</span>
      </el-menu-item>
      <el-menu-item index="/arrays">
        <el-icon><Cpu /></el-icon>
        <span>阵列管理</span>
      </el-menu-item>
      <el-menu-item index="/alerts">
        <el-icon><Bell /></el-icon>
        <span>告警中心</span>
      </el-menu-item>
      <el-menu-item index="/query">
        <el-icon><Search /></el-icon>
        <span>自定义查询</span>
      </el-menu-item>
      <el-menu-item index="/settings">
        <el-icon><Setting /></el-icon>
        <span>系统设置</span>
      </el-menu-item>
      <el-menu-item index="/system-alerts">
        <el-icon><Warning /></el-icon>
        <span>系统告警</span>
      </el-menu-item>
      <el-menu-item index="/tasks">
        <el-icon><Timer /></el-icon>
        <span>定时任务</span>
      </el-menu-item>
      <el-menu-item index="/test-tasks">
        <el-icon><Stopwatch /></el-icon>
        <span>测试任务</span>
      </el-menu-item>
      <el-menu-item index="/issues">
        <el-icon><ChatDotRound /></el-icon>
        <span>建议反馈</span>
      </el-menu-item>
      <el-menu-item index="/card-inventory">
        <el-icon><Box /></el-icon>
        <span>卡件列表</span>
      </el-menu-item>
      <el-menu-item v-if="authStore.isAdmin" index="/admin/monitors">
        <el-icon><Bell /></el-icon>
        <span>告警管理</span>
      </el-menu-item>
    </el-menu>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Monitor, Odometer, Cpu, Bell, Search, Setting, Warning, Timer, Stopwatch, ChatDotRound, Box } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const authStore = useAuthStore()

const activeMenu = computed(() => route.path)
</script>

<style scoped>
.sidebar {
  background-color: var(--sidebar-bg);
  overflow-y: auto;
  height: 100%;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 18px;
  font-weight: bold;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.logo .el-icon {
  font-size: 24px;
  margin-right: 8px;
}

.sidebar-menu {
  border-right: none;
  background-color: transparent;
}

.sidebar-menu .el-menu-item {
  color: var(--sidebar-text);
  padding-left: 20px !important;
}

.sidebar-menu .el-menu-item:hover {
  background-color: rgba(255, 255, 255, 0.1);
}

.sidebar-menu .el-menu-item.is-active {
  color: #fff;
  background-color: var(--sidebar-active);
}
</style>
