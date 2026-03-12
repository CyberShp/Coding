<template>
  <div class="alert-banners" role="alert" aria-live="polite">
    <!-- Critical event banner -->
    <div v-if="hasCriticalEvents" class="critical-banner" role="alert">
      <el-icon aria-hidden="true"><WarningFilled /></el-icon>
      <span class="critical-text">
        {{ criticalEvents.length }} 个关键事件需要关注
        <template v-if="latestCritical">
          — {{ latestCritical.observer_name }}: {{ (latestCritical.message || '').substring(0, 60) }}
        </template>
      </span>
      <el-button type="danger" size="small" plain @click="$router.push('/alerts')" aria-label="查看告警详情">查看</el-button>
      <el-button size="small" text @click="$emit('ack-all')" aria-label="忽略全部告警24小时">全部忽略 24 小时</el-button>
    </div>

    <!-- Suppressed state banner -->
    <div v-if="suppressedList.length > 0 && !hasCriticalEvents" class="suppressed-banner" role="status">
      <el-icon aria-hidden="true"><InfoFilled /></el-icon>
      <span class="suppressed-text">{{ suppressedList.length }} 个观察点的告警已被抑制</span>
      <el-button size="small" text @click="$emit('toggle-detail')" :aria-expanded="showDetail">
        {{ showDetail ? '收起' : '详情' }}
      </el-button>
      <el-button size="small" text type="warning" @click="$emit('clear-all')" aria-label="取消全部告警抑制">
        取消全部抑制
      </el-button>
    </div>
    <div v-if="showDetail && suppressedList.length > 0" class="suppressed-detail">
      <div v-for="item in suppressedList" :key="item.observer" class="suppressed-item">
        <span class="suppressed-observer">{{ item.observer }}</span>
        <span class="suppressed-remaining" :aria-label="formatRemaining(item.expiresAt)">{{ formatRemaining(item.expiresAt) }}</span>
        <el-button size="small" text type="warning" @click="$emit('clear-suppression', item.observer)" :aria-label="`取消${item.observer}的抑制`">
          取消抑制
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { WarningFilled, InfoFilled } from '@element-plus/icons-vue'

const props = defineProps({
  criticalEvents: {
    type: Array,
    default: () => []
  },
  suppressedList: {
    type: Array,
    default: () => []
  },
  showDetail: {
    type: Boolean,
    default: false
  }
})

defineEmits([
  'ack-all',
  'toggle-detail',
  'clear-all',
  'clear-suppression'
])

const hasCriticalEvents = computed(() => props.criticalEvents.length > 0)
const latestCritical = computed(() => props.criticalEvents[0] || null)

// Auto-refresh timer for remaining time
const now = ref(Date.now())
let timer = null

onMounted(() => {
  // Update every minute
  timer = setInterval(() => {
    now.value = Date.now()
  }, 60000)
})

onUnmounted(() => {
  if (timer) {
    clearInterval(timer)
  }
})

function formatRemaining(expiresAt) {
  const ms = expiresAt - now.value
  if (ms <= 0) return '已过期'
  const h = Math.floor(ms / (60 * 60 * 1000))
  const m = Math.floor((ms % (60 * 60 * 1000)) / (60 * 1000))
  if (h > 0) return `剩余 ${h}h${m}m`
  return `剩余 ${m}m`
}
</script>

<style scoped>
.alert-banners {
  width: 100%;
}

.critical-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background-color: #fef0f0;
  border: 1px solid #fde2e2;
  border-radius: 4px;
  margin-bottom: 8px;
}

.critical-banner .el-icon {
  color: #f56c6c;
  font-size: 18px;
}

.critical-text {
  flex: 1;
  font-size: 14px;
  color: #303133;
}

.suppressed-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background-color: #f4f4f5;
  border: 1px solid #e9e9eb;
  border-radius: 4px;
  margin-bottom: 8px;
}

.suppressed-banner .el-icon {
  color: #909399;
}

.suppressed-text {
  flex: 1;
  font-size: 14px;
  color: #606266;
}

.suppressed-detail {
  padding: 8px 16px;
  background-color: #fafafa;
  border: 1px solid #e9e9eb;
  border-top: none;
  border-radius: 0 0 4px 4px;
}

.suppressed-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px solid #ebeef5;
}

.suppressed-item:last-child {
  border-bottom: none;
}

.suppressed-observer {
  flex: 1;
  font-size: 13px;
  color: #303133;
}

.suppressed-remaining {
  font-size: 12px;
  color: #909399;
  min-width: 70px;
}
</style>
