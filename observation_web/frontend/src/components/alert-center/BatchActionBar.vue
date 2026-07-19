<template>
  <transition name="batch-slide">
    <div v-if="count > 0" class="batch-actions-sticky">
      <div class="batch-actions-inner">
        <el-badge :value="count" type="primary" class="batch-badge">
          <span class="batch-count">已选 {{ count }} 条</span>
        </el-badge>
        <div class="batch-buttons">
          <el-button size="small" @click="$emit('batch-undo')">批量撤销</el-button>
          <el-button size="small" type="success" @click="$emit('batch-modify', 'confirmed_ok')">批量确认</el-button>
          <el-button size="small" type="warning" @click="$emit('batch-modify', 'dismiss')">批量忽略 24h</el-button>
          <el-button size="small" type="info" plain @click="$emit('clear')">清除选择</el-button>
        </div>
        <span class="batch-shortcut-hint">Ctrl+A 全选当前页</span>
      </div>
    </div>
  </transition>
</template>

<script setup>
defineProps({
  count: { type: Number, default: 0 },
})
defineEmits(['batch-undo', 'batch-modify', 'clear'])
</script>

<style scoped>
.batch-actions-sticky {
  position: sticky;
  bottom: 0;
  z-index: 10;
  background: #fff;
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.08);
  border-radius: 8px 8px 0 0;
  margin-top: 12px;
}

.batch-actions-inner {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 20px;
}

.batch-badge {
  flex-shrink: 0;
}

.batch-count {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  padding-right: 4px;
}

.batch-buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.batch-shortcut-hint {
  margin-left: auto;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  white-space: nowrap;
}

/* Batch toolbar slide transition */
.batch-slide-enter-active,
.batch-slide-leave-active {
  transition: all 0.25s ease;
}

.batch-slide-enter-from,
.batch-slide-leave-to {
  opacity: 0;
  transform: translateY(20px);
}
</style>
