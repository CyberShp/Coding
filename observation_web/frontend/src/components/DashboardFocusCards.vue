<template>
  <div class="focus-cards">
    <div
      class="focus-card focus-anomaly"
      :class="{ 'has-items': realAnomalyPending > 0, 'focus-pulse': realAnomalyPending > 0 }"
      @click="$router.push({ path: '/alerts', query: { level: 'error' } })"
    >
      <div class="focus-count">{{ realAnomalyPending }}</div>
      <div class="focus-label">真异常待处理</div>
    </div>
    <div
      class="focus-card focus-expected"
      :class="{ 'has-items': !!activeTask }"
      @click="$router.push('/test-tasks')"
    >
      <div class="focus-count">{{ activeTask ? 1 : 0 }}</div>
      <div class="focus-label">当前测试预期</div>
    </div>
    <div
      class="focus-card focus-collection"
      :class="{ 'has-items': collectionFailureCount > 0 }"
      @click="$router.push('/arrays')"
    >
      <div class="focus-count">{{ collectionFailureCount }}</div>
      <div class="focus-label">采集失败</div>
    </div>
    <div
      class="focus-card focus-recovered"
      :class="{ 'has-items': recentRecoveryCount > 0 }"
    >
      <div class="focus-count">{{ recentRecoveryCount }}</div>
      <div class="focus-label">最近恢复</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  realAnomalyPending: { type: Number, default: 0 },
  activeTask: Object,
  collectionFailureCount: { type: Number, default: 0 },
  recentRecoveryCount: { type: Number, default: 0 },
})
</script>

<style scoped>
.focus-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.focus-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
  border-left: 3px solid transparent;
}

.focus-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.focus-card.has-items.focus-anomaly    { border-left-color: #ff4d4f; background: #fff2f0; }
.focus-card.has-items.focus-expected   { border-left-color: #409eff; background: #ecf5ff; }
.focus-card.has-items.focus-collection { border-left-color: #faad14; background: #fffbe6; }
.focus-card.has-items.focus-recovered  { border-left-color: #52c41a; background: #f6ffed; }

.focus-pulse {
  animation: focus-pulse-anim 2s ease-in-out infinite;
}

@keyframes focus-pulse-anim {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255, 77, 79, 0.3); }
  50% { box-shadow: 0 0 0 6px rgba(255, 77, 79, 0); }
}

.focus-count {
  font-size: 22px;
  font-weight: 700;
  color: #303133;
  min-width: 28px;
}

.focus-label {
  font-size: 13px;
  color: #606266;
  white-space: nowrap;
}

@media (max-width: 1200px) {
  .focus-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .focus-cards {
    grid-template-columns: 1fr;
  }
}
</style>
