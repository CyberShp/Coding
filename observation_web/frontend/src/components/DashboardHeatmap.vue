<template>
  <el-col :span="16">
    <el-card class="content-card">
      <template #header>
        <div class="card-header">
          <span>阵列状态热力图</span>
          <el-button text size="small" @click="$emit('refresh')">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
      </template>

      <!-- Skeleton loading -->
      <div v-if="!initialLoaded" class="heatmap-grid">
        <div v-for="n in 12" :key="n" class="heatmap-dot heatmap-dot-skeleton" />
      </div>

      <!-- Status Heatmap Dot Grid -->
      <div v-else-if="filteredArrays.length > 0" class="heatmap-grid">
        <el-tooltip
          v-for="arr in filteredArrays"
          :key="arr.array_id"
          :content="getHeatmapTooltip(arr)"
          placement="top"
          :show-after="200"
        >
          <div
            class="heatmap-dot"
            :class="getHeatmapDotClass(arr)"
            @click="$router.push(`/arrays/${arr.array_id}`)"
          />
        </el-tooltip>
      </div>

      <el-empty v-else-if="personalViewActive" description="未配置关注的阵列或标签">
        <el-button type="primary" @click="$router.push('/settings')">配置个人视图</el-button>
      </el-empty>
      <el-empty v-else description="暂无阵列">
        <el-button type="primary" @click="$router.push('/arrays')">添加阵列</el-button>
      </el-empty>
    </el-card>
  </el-col>

  <!-- Alert Stream -->
  <el-col :span="8">
    <el-card class="content-card alerts-card">
      <template #header>
        <div class="card-header">
          <span>实时告警流</span>
          <el-badge
            :value="wsConnected ? 'LIVE' : 'OFFLINE'"
            :type="wsConnected ? 'success' : 'danger'"
            class="ws-badge"
          />
        </div>
      </template>
      <div class="alerts-list">
        <FoldedAlertList
          :alerts="filteredAlerts"
          :show-array-id="true"
          :compact="true"
          @select="$emit('select', $event)"
          @ack="$emit('ack', $event)"
          @undo-ack="$emit('undo-ack', $event)"
          @modify-ack="$emit('modify-ack', $event)"
        />
      </div>
    </el-card>
  </el-col>
</template>

<script setup>
import { Refresh } from '@element-plus/icons-vue'
import FoldedAlertList from './FoldedAlertList.vue'
import { getHeatmapDotClass, getHeatmapTooltip } from '@/utils/arrayStatus'

defineProps({
  initialLoaded: Boolean,
  filteredArrays: { type: Array, default: () => [] },
  filteredAlerts: { type: Array, default: () => [] },
  wsConnected: Boolean,
  personalViewActive: Boolean,
})

defineEmits(['refresh', 'select', 'ack', 'undo-ack', 'modify-ack'])
</script>

<style scoped>
.content-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.heatmap-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 8px 0;
}

.heatmap-dot {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.heatmap-dot:hover {
  transform: scale(1.3);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  z-index: 1;
}

.heatmap-dot.heatmap-healthy { background: #52c41a; }
.heatmap-dot.heatmap-warning { background: #faad14; }
.heatmap-dot.heatmap-error   { background: #ff4d4f; }
.heatmap-dot.heatmap-offline { background: #8c8c8c; }

.heatmap-dot-skeleton {
  background: linear-gradient(90deg, #f0f0f0 25%, #e8e8e8 50%, #f0f0f0 75%);
  background-size: 200% 100%;
  animation: skeleton-pulse 1.5s ease infinite;
  cursor: default;
}

@keyframes skeleton-pulse {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.alerts-card {
  height: calc(100vh - 280px);
  min-height: 400px;
  overflow: hidden;
}

.alerts-list {
  height: calc(100vh - 360px);
  min-height: 320px;
  overflow-y: auto;
}

.ws-badge {
  margin-left: 8px;
}

.ws-badge :deep(.el-badge__content) {
  font-size: 10px;
}
</style>
