<template>
  <el-config-provider :locale="zhCn">
    <div class="app-container">
      <el-container>
        <!-- Sidebar -->
        <AppSidebar />

        <!-- Main Content -->
        <el-container>
          <AppHeader
            :online-users="onlineUsers"
            :online-count="onlineCount"
            :current-user="currentUser"
            :alert-count="alertCount"
            :show-nickname-dialog="showNicknameDialog"
            :show-claim-dialog="showClaimDialog"
            :nickname-input="nicknameInput"
            :claim-input="claimInput"
            :force-rename="forceRename"
            @load-online-users="loadOnlineUsers"
            @toggle-sound="toggleSound"
            @show-nickname-dialog="showNicknameDialog = true"
            @show-claim-dialog="showClaimDialog = true"
            @save-nickname="saveNickname"
            @claim-nickname="claimNickname"
          />

          <!-- Critical event banner -->
          <CriticalBanner
            :critical-events="alertStore.criticalEvents"
            :suppressed-list="alertStore.suppressedList"
            :show-detail="showSuppressedDetail"
            @ack-all="handleAckAllVisible"
            @toggle-detail="showSuppressedDetail = !showSuppressedDetail"
            @clear-all="alertStore.clearAllSuppressions()"
            @clear-suppression="alertStore.clearSuppression"
          />

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
import { ElMessage } from 'element-plus'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { useAlertStore } from './stores/alerts'
import { setSoundEnabled } from './utils/notification'
import api from './api'
import AppSidebar from './components/AppSidebar.vue'
import AppHeader from './components/AppHeader.vue'
import CriticalBanner from './components/CriticalBanner.vue'

const alertStore = useAlertStore()

const showSuppressedDetail = ref(false)

// Online users state
const onlineUsers = ref([])
const onlineCount = ref(0)
const currentUser = reactive({ ip: '', nickname: '', color: '#409eff' })
const showNicknameDialog = ref(false)
const nicknameInput = ref('')
const forceRename = ref(false)
const showClaimDialog = ref(false)
const claimInput = ref('')
let userCountInterval = null

const alertCount = computed(() => alertStore.recentCount)

function toggleSound(val) {
  setSoundEnabled(val)
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
    if (currentUser.nickname_compliant === false) {
      forceRename.value = true
      showNicknameDialog.value = true
      return
    }
    forceRename.value = false
    if (!currentUser.nickname && !sessionStorage.getItem('nicknamePromptShown')) {
      showNicknameDialog.value = true
      sessionStorage.setItem('nicknamePromptShown', '1')
    }
  } catch (e) {
    console.debug('Failed to load current user:', e)
  }
}

async function saveNickname(val) {
  const nickname = val || nicknameInput.value
  try {
    const res = await api.setNickname(nickname)
    Object.assign(currentUser, res.data)
    forceRename.value = false
    showNicknameDialog.value = false
    ElMessage.success('昵称已保存')
  } catch (e) {
    const detail = e?.response?.data?.detail || ''
    if (e?.response?.status === 400) {
      ElMessage.error(detail || '昵称包含不当词汇，请修改')
      return
    }
    if (e?.response?.status === 409) {
      ElMessage.error('昵称已被使用，请换一个')
      return
    }
    ElMessage.error(detail || '保存失败')
  }
}

async function claimNickname(val) {
  const nickname = val || claimInput.value
  if (!nickname.trim()) {
    ElMessage.warning('请输入昵称')
    return
  }
  try {
    const res = await api.claimNickname(nickname.trim())
    Object.assign(currentUser, res.data)
    showClaimDialog.value = false
    claimInput.value = ''
    if (currentUser.nickname_compliant === false) {
      forceRename.value = true
      showNicknameDialog.value = true
      ElMessage.warning('当前昵称不符合规范，请先修改昵称')
      return
    }
    ElMessage.success('认领成功，身份已恢复')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '认领失败，请确认昵称正确')
  }
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

// Initialize WebSocket connection
onMounted(() => {
  alertStore.connectWebSocket()
  loadCurrentUser()
  loadOnlineUsers()
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
