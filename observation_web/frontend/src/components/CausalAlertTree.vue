<template>
  <div class="causal-alert-tree">
    <div v-if="loading" class="causal-loading">
      <el-skeleton :rows="4" animated />
    </div>
    <div v-else-if="!trees.length" class="causal-empty">
      <el-empty description="暂无因果关系数据">
        <template #description>
          <p>系统需要积累足够的告警历史才能发现因果关系。</p>
          <p v-if="rulesCount === 0" class="hint">当前阵列尚未学习到因果规则。</p>
        </template>
      </el-empty>
    </div>
    <div v-else class="causal-forest">
      <div class="causal-summary">
        <el-tag type="info" size="small">{{ totalAlerts }} 条告警</el-tag>
        <el-tag type="success" size="small">{{ rootCount }} 个根因</el-tag>
        <el-tag type="warning" size="small">{{ consequenceCount }} 个后果</el-tag>
        <el-tag v-if="isolatedCount > 0" size="small">{{ isolatedCount }} 个独立</el-tag>
        <el-tag type="info" size="small" effect="plain">{{ rulesCount }} 条学习规则</el-tag>
      </div>

      <div
        v-for="(tree, idx) in trees"
        :key="tree.id || idx"
        class="causal-tree-root"
      >
        <CausalNode
          :node="tree"
          :depth="0"
          @select="$emit('select', $event)"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import CausalNode from './CausalNode.vue'

const props = defineProps({
  trees: { type: Array, default: () => [] },
  totalAlerts: { type: Number, default: 0 },
  rulesCount: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
})

defineEmits(['select'])

const rootCount = computed(() =>
  props.trees.filter(t => t.causal_role === 'root').length
)
const consequenceCount = computed(() => {
  let count = 0
  const walk = (nodes) => {
    for (const n of nodes) {
      if (n.causal_role === 'consequence') count++
      if (n.consequences?.length) walk(n.consequences)
    }
  }
  walk(props.trees)
  return count
})
const isolatedCount = computed(() =>
  props.trees.filter(t => t.causal_role === 'isolated').length
)
</script>

<style scoped>
.causal-alert-tree {
  padding: 8px 0;
}
.causal-summary {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  margin-bottom: 12px;
  background: var(--el-fill-color-lighter, #fafafa);
  border-radius: 6px;
}
.causal-forest {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.causal-tree-root {
  border-left: 3px solid var(--el-color-danger);
  border-radius: 4px;
  padding-left: 0;
  margin-bottom: 8px;
}
.causal-tree-root:last-child {
  margin-bottom: 0;
}
.causal-empty .hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 4px;
}
</style>
