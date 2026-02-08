<template>
  <el-config-provider :locale="zhCn">
    <div class="app-container">
      <el-container>
        <!-- Sidebar -->
        <el-aside width="200px" class="sidebar">
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
            <el-menu-item index="/data">
              <el-icon><Files /></el-icon>
              <span>数据管理</span>
            </el-menu-item>
            <el-menu-item index="/tasks">
              <el-icon><Timer /></el-icon>
              <span>定时任务</span>
            </el-menu-item>
            <el-menu-item index="/test-tasks">
              <el-icon><Stopwatch /></el-icon>
              <span>测试任务</span>
            </el-menu-item>
          </el-menu>
        </el-aside>

        <!-- Main Content -->
        <el-container>
          <el-header class="header">
            <div class="header-left">
              <el-breadcrumb separator="/">
                <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
                <el-breadcrumb-item v-if="currentRoute">{{ currentRoute }}</el-breadcrumb-item>
              </el-breadcrumb>
            </div>
            <div class="header-right">
              <el-tooltip content="开启/关闭告警提示音">
                <el-switch
                  v-model="soundOn"
                  active-text=""
                  inactive-text=""
                  size="small"
                  style="margin-right: 8px"
                  @change="toggleSound"
                />
              </el-tooltip>
              <el-badge :value="alertCount" :hidden="alertCount === 0" class="alert-badge">
                <el-button :icon="Bell" circle @click="$router.push('/alerts')" />
              </el-badge>
              <el-dropdown>
                <el-button :icon="User" circle />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item>个人设置</el-dropdown-item>
                    <el-dropdown-item divided>退出登录</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </el-header>

          <!-- Critical event banner -->
          <div v-if="alertStore.hasCriticalEvents" class="critical-banner">
            <el-icon><WarningFilled /></el-icon>
            <span class="critical-text">
              {{ alertStore.criticalEvents.length }} 个关键事件需要关注
              <template v-if="latestCritical">
                — {{ latestCritical.observer_name }}: {{ (latestCritical.message || '').substring(0, 60) }}
              </template>
            </span>
            <el-button type="danger" size="small" plain @click="$router.push('/alerts')">查看</el-button>
            <el-button size="small" text @click="alertStore.acknowledgeAllCritical()">全部已知</el-button>
          </div>

          <el-main class="main-content">
            <router-view v-slot="{ Component }">
              <transition name="fade" mode="out-in">
                <component :is="Component" />
              </transition>
            </router-view>
          </el-main>
        </el-container>
      </el-container>
    </div>
  </el-config-provider>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { Monitor, Odometer, Cpu, Bell, Search, Setting, User, Warning, Files, Timer, WarningFilled, Stopwatch } from '@element-plus/icons-vue'
import { useAlertStore } from './stores/alerts'
import { setSoundEnabled } from './utils/notification'

const route = useRoute()
const alertStore = useAlertStore()
const soundOn = ref(false)

const activeMenu = computed(() => route.path)
const currentRoute = computed(() => {
  const routes = {
    '/': '',
    '/arrays': '阵列管理',
    '/alerts': '告警中心',
    '/query': '自定义查询',
    '/settings': '系统设置',
    '/system-alerts': '系统告警',
    '/data': '数据管理',
    '/tasks': '定时任务',
    '/test-tasks': '测试任务',
  }
  return routes[route.path] || ''
})

const alertCount = computed(() => alertStore.recentCount)
const latestCritical = computed(() => alertStore.criticalEvents[0] || null)

function toggleSound(val) {
  setSoundEnabled(val)
}

// Initialize WebSocket connection
onMounted(() => {
  alertStore.connectWebSocket()
})

onUnmounted(() => {
  alertStore.disconnectWebSocket()
})
</script>

<style>
:root {
  --sidebar-bg: #304156;
  --sidebar-text: #bfcbd9;
  --sidebar-active: #409eff;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  height: 100%;
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', Arial, sans-serif;
}

.app-container {
  height: 100%;
}

.el-container {
  height: 100%;
}

.sidebar {
  background-color: var(--sidebar-bg);
  overflow-y: auto;
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
}

.sidebar-menu .el-menu-item:hover {
  background-color: rgba(255, 255, 255, 0.1);
}

.sidebar-menu .el-menu-item.is-active {
  color: #fff;
  background-color: var(--sidebar-active);
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e6e6e6;
  background-color: #fff;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.alert-badge {
  margin-right: 8px;
}

/* Critical event banner */
.critical-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 20px;
  background: #fef0f0;
  border-bottom: 2px solid #f56c6c;
  color: #f56c6c;
  font-size: 14px;
  animation: critical-pulse 2s ease-in-out infinite;
}
.critical-banner .el-icon {
  font-size: 18px;
}
.critical-text {
  flex: 1;
  font-weight: 600;
}
@keyframes critical-pulse {
  0%, 100% { background: #fef0f0; }
  50% { background: #fde2e2; }
}

.main-content {
  background-color: #f5f7fa;
  overflow-y: auto;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
