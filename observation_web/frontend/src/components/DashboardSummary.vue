<template>
  <div class="summary-cards">
    <!-- Anomaly card: first position, 2x width -->
    <div
      v-if="activeAnomalyCount > 0"
      class="summary-card summary-card-anomaly clickable"
      @click="$router.push({ path: '/alerts', query: { level: 'error' } })"
    >
      <div class="summary-icon icon-danger">
        <el-icon size="22"><Warning /></el-icon>
      </div>
      <div class="summary-body">
        <template v-if="!initialLoaded">
          <div class="skeleton-value" />
        </template>
        <template v-else>
          <div class="summary-value">{{ activeAnomalyCount }}</div>
        </template>
        <div class="summary-label">活跃异常数</div>
      </div>
    </div>
    <!-- Green banner when no anomalies -->
    <div v-else class="summary-card summary-card-healthy">
      <div class="summary-icon icon-success">
        <el-icon size="22"><Monitor /></el-icon>
      </div>
      <div class="summary-body">
        <div class="summary-value healthy-text">系统运行平稳</div>
        <div class="summary-label">活跃异常数: 0</div>
      </div>
    </div>

    <!-- Needs manual -->
    <div class="summary-card clickable" @click="$router.push('/alerts')">
      <div class="summary-icon icon-warning">
        <el-icon size="22"><Bell /></el-icon>
      </div>
      <div class="summary-body">
        <template v-if="!initialLoaded">
          <div class="skeleton-value" />
        </template>
        <template v-else>
          <div class="summary-value">{{ needsManualCount }}</div>
        </template>
        <div class="summary-label">需要人工处理</div>
      </div>
    </div>

    <div class="summary-card clickable" @click="$router.push('/arrays')">
      <div class="summary-icon icon-success">
        <el-icon size="22"><Monitor /></el-icon>
      </div>
      <div class="summary-body">
        <template v-if="!initialLoaded">
          <div class="skeleton-value" />
        </template>
        <template v-else>
          <div class="summary-value">{{ onlineAgentCount }}</div>
        </template>
        <div class="summary-label">在线 Agent 数</div>
      </div>
    </div>

    <div class="summary-card">
      <div class="summary-icon icon-info">
        <el-icon size="22"><Clock /></el-icon>
      </div>
      <div class="summary-body">
        <template v-if="!initialLoaded">
          <div class="skeleton-value" />
        </template>
        <template v-else>
          <div class="freshness-row">
            <span class="freshness-dot dot-fresh" />
            <span class="freshness-num">{{ freshness.fresh }}</span>
            <span class="freshness-dot dot-stale" />
            <span class="freshness-num">{{ freshness.stale }}</span>
            <span class="freshness-dot dot-unknown" />
            <span class="freshness-num">{{ freshness.unknown }}</span>
          </div>
        </template>
        <div class="summary-label">数据新鲜度</div>
      </div>
    </div>

    <!-- Total arrays: demoted to last, smaller -->
    <div class="summary-card summary-card-demoted clickable" @click="$router.push('/arrays')">
      <div class="summary-icon icon-primary summary-icon-sm">
        <el-icon size="18"><Cpu /></el-icon>
      </div>
      <div class="summary-body">
        <template v-if="!initialLoaded">
          <div class="skeleton-value" />
        </template>
        <template v-else>
          <div class="summary-value summary-value-sm">{{ filteredTotalCount }}</div>
        </template>
        <div class="summary-label">纳管阵列总数</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Cpu, Bell, Warning, Monitor, Clock } from '@element-plus/icons-vue'

defineProps({
  initialLoaded: Boolean,
  freshness: { type: Object, default: () => ({ fresh: 0, stale: 0, unknown: 0 }) },
  activeAnomalyCount: { type: Number, default: 0 },
  needsManualCount: { type: Number, default: 0 },
  onlineAgentCount: { type: Number, default: 0 },
  filteredTotalCount: { type: Number, default: 0 },
})
</script>

<style scoped>
.summary-cards {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr 0.8fr;
  gap: 16px;
}

.summary-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px 18px;
  display: flex;
  align-items: center;
  gap: 14px;
  transition: all 0.2s ease;
}

.summary-card.clickable {
  cursor: pointer;
}

.summary-card.clickable:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.summary-card-anomaly {
  background: #fff2f0;
  border: 2px solid #ff4d4f;
}

.summary-card-anomaly .summary-value {
  color: #ff4d4f;
  font-size: 32px;
}

.summary-card-healthy {
  background: #f6ffed;
  border: 2px solid #52c41a;
}

.healthy-text {
  color: #52c41a !important;
  font-size: 18px !important;
  font-weight: 600 !important;
}

.summary-card-demoted {
  padding: 12px 14px;
}

.summary-card-demoted .summary-value-sm {
  font-size: 18px;
}

.summary-icon-sm {
  width: 36px;
  height: 36px;
  border-radius: 8px;
}

.summary-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.icon-primary { background: #409eff; }
.icon-success { background: #67c23a; }
.icon-info    { background: #909399; }
.icon-danger  { background: #f56c6c; }
.icon-warning { background: #e6a23c; }

.summary-body {
  min-width: 0;
}

.summary-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}

.summary-label {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
  white-space: nowrap;
}

.skeleton-value {
  width: 48px;
  height: 24px;
  border-radius: 4px;
  background: linear-gradient(90deg, #f0f0f0 25%, #e8e8e8 50%, #f0f0f0 75%);
  background-size: 200% 100%;
  animation: skeleton-pulse 1.5s ease infinite;
}

@keyframes skeleton-pulse {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.freshness-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.freshness-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.freshness-num {
  font-size: 16px;
  font-weight: 700;
  color: #303133;
  margin-right: 6px;
}

.dot-fresh   { background: #67c23a; }
.dot-stale   { background: #e6a23c; }
.dot-unknown { background: #c0c4cc; }

@media (max-width: 1200px) {
  .summary-cards {
    grid-template-columns: 2fr 1fr 1fr;
  }
  .summary-card-demoted {
    grid-column: span 1;
  }
}

@media (max-width: 768px) {
  .summary-cards {
    grid-template-columns: 1fr 1fr;
  }
  .summary-card-anomaly,
  .summary-card-healthy {
    grid-column: span 2;
  }
}
</style>
