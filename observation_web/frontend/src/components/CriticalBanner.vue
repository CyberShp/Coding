<template>
  <div class="alert-banners">
    <!-- Critical event banner -->
    <div v-if="hasCriticalEvents" class="critical-banner">
      <el-icon><WarningFilled /></el-icon>
      <span class="critical-text">
        {{ criticalEvents.length }} 个关键事件需要关注
        <template v-if="latestCritical">
          — {{ latestCritical.observer_name }}: {{ (latestCritical.message || '').substring(0, 60) }}
        </template>
      </span>
      <el-button type="danger" size="small" plain @click="$router.push('/alerts')">查看</el-button>
      <el-button size="small" text @click="$emit('ack-all')">全部忽略 24 小时</el-button>
    </div>

    <!-- Suppressed state banner -->
    <div v-if="suppressedList.length > 0 && !hasCriticalEvents" class="suppressed-banner">
      <el-icon><InfoFilled /></el-icon>
      <span class="suppressed-text">{{ suppressedList.length }} 个观察点的告警已被抑制</span>
      <el-button size="small" text @click="$emit('toggle-detail')">
        {{ showDetail ? '收起' : '详情' }}
      </el-button>
      <el-button size="small" text type="warning" @click="$emit('clear-all')">
        取消全部抑制
      </el-button>
    </div>
    <div v-if="showDetail && suppressedList.length > 0" class="suppressed-detail">
      <div v-for="item in suppressedList" :key="item.observer" class="suppressed-item">
        <span class="suppressed-observer">{{ item.observer }}</span>
        <span class="suppressed-remaining">{{ formatRemaining(item.expiresAt) }}</span>
        <el-button size="small" text type="warning" @click="$emit('clear-suppression', item.observer)">
          取消抑制
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
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

function formatRemaining(expiresAt) {
  const ms = expiresAt - Date.now()
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
</style>
