<template>
  <el-header class="header">
    <div class="header-left">
      <el-breadcrumb separator="/">
        <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
        <el-breadcrumb-item v-if="currentRoute">{{ currentRoute }}</el-breadcrumb-item>
      </el-breadcrumb>
    </div>
    <div class="header-right">
      <!-- Personal View Toggle -->
      <el-tooltip :content="preferencesStore.personalViewActive ? '切换到全局视图' : '切换到个人视图'">
        <el-button
          :type="preferencesStore.personalViewActive ? 'primary' : 'default'"
          size="small"
          round
          @click="preferencesStore.togglePersonalView"
        >
          <el-icon><Star /></el-icon>
          {{ preferencesStore.personalViewActive ? '个人' : '全局' }}
        </el-button>
      </el-tooltip>

      <!-- Online Users Indicator -->
      <OnlineUsers
        :users="onlineUsers"
        :count="onlineCount"
        @load-users="$emit('load-online-users')"
      />

      <el-tooltip content="开启/关闭告警提示音">
        <el-switch
          v-model="soundOn"
          active-text=""
          inactive-text=""
          size="small"
          style="margin-right: 8px"
          @change="$emit('toggle-sound', $event)"
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
            <el-dropdown-item @click="$emit('show-nickname-dialog')">设置昵称</el-dropdown-item>
            <el-dropdown-item @click="$emit('show-claim-dialog')">认领昵称</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <!-- Nickname Dialog -->
    <el-dialog
      v-model="nicknameDialogVisible"
      :title="forceRename ? '请修改昵称' : '设置昵称'"
      width="360px"
      :close-on-click-modal="!forceRename"
      :close-on-press-escape="!forceRename"
      :show-close="!forceRename"
    >
      <p class="claim-hint">
        {{
          forceRename
            ? '您的昵称不符合规范，请设置一个合法合规的昵称'
            : '昵称需要合法合规，不能包含侮辱性或低俗词汇'
        }}
      </p>
      <el-input v-model="localNicknameInput" placeholder="输入您的昵称" maxlength="20" show-word-limit />
      <template #footer>
        <el-button v-if="!forceRename" @click="closeNicknameDialog">取消</el-button>
        <el-button type="primary" @click="$emit('save-nickname', localNicknameInput)">保存</el-button>
      </template>
    </el-dialog>
    
    <!-- Claim Nickname Dialog (for IP change) -->
    <el-dialog v-model="claimDialogVisible" title="认领昵称" width="360px">
      <p class="claim-hint">换过电脑或 IP 后，输入之前的昵称可恢复身份（锁定、历史等）</p>
      <el-input v-model="localClaimInput" placeholder="输入您之前的昵称" maxlength="20" show-word-limit />
      <template #footer>
        <el-button @click="closeClaimDialog">取消</el-button>
        <el-button type="primary" @click="$emit('claim-nickname', localClaimInput)">认领</el-button>
      </template>
    </el-dialog>
  </el-header>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Bell, User, Star } from '@element-plus/icons-vue'
import { usePreferencesStore } from '../stores/preferences'
import OnlineUsers from './OnlineUsers.vue'

const route = useRoute()
const preferencesStore = usePreferencesStore()

const props = defineProps({
  onlineUsers: {
    type: Array,
    default: () => []
  },
  onlineCount: {
    type: Number,
    default: 0
  },
  currentUser: {
    type: Object,
    default: () => ({ ip: '', nickname: '', color: '#409eff' })
  },
  alertCount: {
    type: Number,
    default: 0
  },
  showNicknameDialog: {
    type: Boolean,
    default: false
  },
  showClaimDialog: {
    type: Boolean,
    default: false
  },
  nicknameInput: {
    type: String,
    default: ''
  },
  claimInput: {
    type: String,
    default: ''
  },
  forceRename: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits([
  'load-online-users',
  'toggle-sound',
  'show-nickname-dialog',
  'show-claim-dialog',
  'close-nickname-dialog',
  'close-claim-dialog',
  'save-nickname',
  'claim-nickname'
])

const soundOn = ref(false)

// Local state for inputs (sync with props)
const localNicknameInput = ref(props.nicknameInput)
const localClaimInput = ref(props.claimInput)

// Sync with props when they change
watch(() => props.nicknameInput, (val) => { localNicknameInput.value = val })
watch(() => props.claimInput, (val) => { localClaimInput.value = val })

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
    '/card-inventory': '卡件列表',
  }
  return routes[route.path] || ''
})

// Dialog visibility - use local refs, sync with props on open only
const nicknameDialogVisible = ref(false)
const claimDialogVisible = ref(false)

// Watch props to open dialogs (not close)
watch(() => props.showNicknameDialog, (val) => {
  if (val) nicknameDialogVisible.value = true
})
watch(() => props.showClaimDialog, (val) => {
  if (val) claimDialogVisible.value = true
})

const closeNicknameDialog = () => {
  nicknameDialogVisible.value = false
  emit('close-nickname-dialog')
}

const closeClaimDialog = () => {
  claimDialogVisible.value = false
  emit('close-claim-dialog')
}
</script>

<style scoped>
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

.user-dropdown {
  display: flex;
  align-items: center;
  gap: 4px;
}

.my-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.claim-hint {
  color: #909399;
  font-size: 13px;
  margin-bottom: 12px;
  line-height: 1.5;
}
</style>
