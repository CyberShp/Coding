<template>
  <div class="app-container dark">
    <el-container>
      <el-header class="app-header">
        <div class="header-left">
          <h1 class="app-title">Packet Storm</h1>
          <span class="app-subtitle">Storage Protocol Testing Tool</span>
        </div>
        <div class="header-right">
          <el-tag :type="statusType" effect="dark" size="large">
            {{ connectionStatus }}
          </el-tag>
        </div>
      </el-header>

      <el-container>
        <el-aside width="200px" class="app-aside">
          <el-menu
            :default-active="$route.path"
            router
            class="sidebar-menu"
            background-color="#1a1a2e"
            text-color="#c0c0c0"
            active-text-color="#409EFF"
          >
            <el-menu-item index="/">
              <el-icon><Monitor /></el-icon>
              <span>Dashboard</span>
            </el-menu-item>
            <el-menu-item index="/config">
              <el-icon><Setting /></el-icon>
              <span>Configuration</span>
            </el-menu-item>
            <el-menu-item index="/session">
              <el-icon><VideoPlay /></el-icon>
              <span>Session</span>
            </el-menu-item>
            <el-menu-item index="/anomaly">
              <el-icon><Warning /></el-icon>
              <span>Anomalies</span>
            </el-menu-item>
            <el-menu-item index="/packets">
              <el-icon><Document /></el-icon>
              <span>Packet Log</span>
            </el-menu-item>
          </el-menu>
        </el-aside>

        <el-main class="app-main">
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Monitor, Setting, VideoPlay, Warning, Document } from '@element-plus/icons-vue'
import { useStatsStore } from '@/stores/stats'

const statsStore = useStatsStore()

const connectionStatus = computed(() => {
  return statsStore.connected ? 'Connected' : 'Disconnected'
})

const statusType = computed(() => {
  return statsStore.connected ? 'success' : 'danger'
})
</script>

<style>
:root {
  --bg-primary: #0f0f23;
  --bg-secondary: #1a1a2e;
  --bg-card: #16213e;
  --text-primary: #e0e0e0;
  --text-secondary: #a0a0a0;
  --accent: #409EFF;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  background-color: var(--bg-primary);
  color: var(--text-primary);
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
}

.app-container {
  min-height: 100vh;
}

.app-header {
  background-color: var(--bg-secondary);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid #2a2a3e;
  height: 60px;
}

.header-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.app-title {
  color: var(--accent);
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 1px;
}

.app-subtitle {
  color: var(--text-secondary);
  font-size: 13px;
}

.app-aside {
  background-color: var(--bg-secondary);
  border-right: 1px solid #2a2a3e;
  min-height: calc(100vh - 60px);
}

.sidebar-menu {
  border-right: none !important;
}

.app-main {
  background-color: var(--bg-primary);
  padding: 24px;
  min-height: calc(100vh - 60px);
}
</style>
