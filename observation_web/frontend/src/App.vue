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
              <!-- Online Users Indicator -->
              <el-popover
                placement="bottom"
                :width="250"
                trigger="hover"
                @before-enter="loadOnlineUsers"
              >
                <template #reference>
                  <div class="online-users-badge">
                    <el-icon><UserFilled /></el-icon>
                    <span class="online-count">{{ onlineCount }}</span>
                  </div>
                </template>
                <div class="online-users-list">
                  <div class="online-header">在线用户 ({{ onlineUsers.length }})</div>
                  <div v-if="onlineUsers.length === 0" class="no-users">暂无其他用户在线</div>
                  <div v-for="user in onlineUsers" :key="user.ip" class="user-item">
                    <span class="user-dot" :style="{ background: user.color }"></span>
                    <span class="user-name">{{ user.nickname || user.ip }}</span>
                    <span class="user-page" v-if="user.viewing_page">
                      {{ getPageName(user.viewing_page) }}
                    </span>
                  </div>
                </div>
              </el-popover>

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
                <span class="user-dropdown">
                  <span class="my-dot" :style="{ background: currentUser.color }"></span>
                  <el-button :icon="User" circle />
                </span>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item disabled>
                      <span style="color: #909399">{{ currentUser.nickname || currentUser.ip }}</span>
                    </el-dropdown-item>
                    <el-dropdown-item @click="showNicknameDialog = true">设置昵称</el-dropdown-item>
                    <el-dropdown-item @click="showClaimDialog = true">认领昵称</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>

            <!-- Nickname Dialog -->
            <el-dialog v-model="showNicknameDialog" title="设置昵称" width="360px">
              <el-input v-model="nicknameInput" placeholder="输入您的昵称" maxlength="20" show-word-limit />
              <template #footer>
                <el-button @click="showNicknameDialog = false">取消</el-button>
                <el-button type="primary" @click="saveNickname">保存</el-button>
              </template>
            </el-dialog>
            <!-- Claim Nickname Dialog (for IP change) -->
            <el-dialog v-model="showClaimDialog" title="认领昵称" width="360px">
              <p class="claim-hint">换过电脑或 IP 后，输入之前的昵称可恢复身份（锁定、历史等）</p>
              <el-input v-model="claimInput" placeholder="输入您之前的昵称" maxlength="20" show-word-limit />
              <template #footer>
                <el-button @click="showClaimDialog = false">取消</el-button>
                <el-button type="primary" @click="claimNickname">认领</el-button>
              </template>
            </el-dialog>
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
            <el-button size="small" text @click="handleAckAllVisible">全部忽略 24 小时</el-button>
          </div>

          <!-- Suppressed state banner -->
          <div v-if="alertStore.suppressedList.length > 0 && !alertStore.hasCriticalEvents" class="suppressed-banner">
            <el-icon><InfoFilled /></el-icon>
            <span class="suppressed-text">{{ alertStore.suppressedList.length }} 个观察点的告警已被抑制</span>
            <el-button size="small" text @click="showSuppressedDetail = !showSuppressedDetail">
              {{ showSuppressedDetail ? '收起' : '详情' }}
            </el-button>
            <el-button size="small" text type="warning" @click="alertStore.clearAllSuppressions()">
              取消全部抑制
            </el-button>
          </div>
          <div v-if="showSuppressedDetail && alertStore.suppressedList.length > 0" class="suppressed-detail">
            <div v-for="item in alertStore.suppressedList" :key="item.observer" class="suppressed-item">
              <span class="suppressed-observer">{{ item.observer }}</span>
              <span class="suppressed-remaining">{{ formatRemaining(item.expiresAt) }}</span>
              <el-button size="small" text type="warning" @click="alertStore.clearSuppression(item.observer)">
                取消抑制
              </el-button>
            </div>
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
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { Monitor, Odometer, Cpu, Bell, Search, Setting, User, Warning, Files, Timer, WarningFilled, Stopwatch, UserFilled, ChatDotRound, InfoFilled } from '@element-plus/icons-vue'
import { useAlertStore } from './stores/alerts'
import { setSoundEnabled } from './utils/notification'
import api from './api'

const route = useRoute()
const alertStore = useAlertStore()
const soundOn = ref(false)
const showSuppressedDetail = ref(false)

function formatRemaining(expiresAt) {
  const ms = expiresAt - Date.now()
  if (ms <= 0) return '已过期'
  const h = Math.floor(ms / (60 * 60 * 1000))
  const m = Math.floor((ms % (60 * 60 * 1000)) / (60 * 1000))
  if (h > 0) return `剩余 ${h}h${m}m`
  return `剩余 ${m}m`
}

async function handleAckAllVisible() {
  try {
    await api.ackAllVisible(2, 'dismiss')
    alertStore.acknowledgeAllCritical()
    ElMessage.success('已全部忽略 24 小时')
  } catch (e) {
    ElMessage.error('操作失败: ' + (e.response?.data?.detail || e.message))
  }
}

// Online users state
const onlineUsers = ref([])
const onlineCount = ref(0)
const currentUser = reactive({ ip: '', nickname: '', color: '#409eff' })
const showNicknameDialog = ref(false)
const nicknameInput = ref('')
const showClaimDialog = ref(false)
const claimInput = ref('')
let userCountInterval = null

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

function getPageName(path) {
  const names = {
    '/': '仪表盘',
    '/arrays': '阵列管理',
    '/alerts': '告警中心',
    '/query': '查询',
    '/test-tasks': '测试任务',
  }
  for (const [p, name] of Object.entries(names)) {
    if (path.startsWith(p) && p !== '/') return name
  }
  return names[path] || ''
}

async function loadOnlineUsers() {
  try {
    const res = await api.getOnlineUsers()
    onlineUsers.value = res.data || []
  } catch (e) {
    console.error('Failed to load online users:', e)
  }
}

async function loadUserCount() {
  try {
    const res = await api.getUserCount()
    onlineCount.value = res.data.online_count || 0
  } catch (e) {
    console.debug('Failed to load user count:', e)
  }
}

async function loadCurrentUser() {
  try {
    const res = await api.getCurrentUser()
    Object.assign(currentUser, res.data)
    nicknameInput.value = currentUser.nickname || ''
    if (!currentUser.nickname && !sessionStorage.getItem('nicknamePromptShown')) {
      showNicknameDialog.value = true
      sessionStorage.setItem('nicknamePromptShown', '1')
    }
  } catch (e) {
    console.debug('Failed to load current user:', e)
  }
}

async function saveNickname() {
  try {
    const res = await api.setNickname(nicknameInput.value)
    Object.assign(currentUser, res.data)
    showNicknameDialog.value = false
    ElMessage.success('昵称已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

async function claimNickname() {
  if (!claimInput.value.trim()) {
    ElMessage.warning('请输入昵称')
    return
  }
  try {
    const res = await api.claimNickname(claimInput.value.trim())
    Object.assign(currentUser, res.data)
    showClaimDialog.value = false
    claimInput.value = ''
    ElMessage.success('认领成功，身份已恢复')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '认领失败，请确认昵称正确')
  }
}

// Initialize WebSocket connection
onMounted(() => {
  alertStore.connectWebSocket()
  loadCurrentUser()
  loadUserCount()
  userCountInterval = setInterval(loadUserCount, 60000)
})

onUnmounted(() => {
  alertStore.disconnectWebSocket()
  if (userCountInterval) clearInterval(userCountInterval)
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

/* Suppressed state banner */
.suppressed-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 20px;
  background: #f4f4f5;
  border-bottom: 1px solid #e4e7ed;
  color: #606266;
  font-size: 14px;
}
.suppressed-banner .el-icon {
  font-size: 18px;
  color: #909399;
}
.suppressed-text {
  flex: 1;
}
.suppressed-detail {
  padding: 8px 20px 12px;
  background: #fafafa;
  border-bottom: 1px solid #e4e7ed;
  font-size: 13px;
}
.suppressed-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 0;
}
.suppressed-observer {
  font-weight: 500;
  min-width: 120px;
}
.suppressed-remaining {
  color: #909399;
  min-width: 80px;
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

/* Online users */
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

.user-dot, .my-dot {
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

.user-dropdown {
  display: flex;
  align-items: center;
  gap: 4px;
}

.claim-hint {
  color: #909399;
  font-size: 13px;
  margin-bottom: 12px;
  line-height: 1.5;
}

.my-dot {
  width: 10px;
  height: 10px;
}
</style>
