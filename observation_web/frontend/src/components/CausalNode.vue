<template>
  <div class="causal-node" :class="[`role-${node.causal_role}`, { 'is-root': depth === 0 }]">
    <div class="node-row" @click="$emit('select', node)">
      <!-- Indent guide lines -->
      <span v-if="depth > 0" class="indent-connector">
        <span v-for="i in depth" :key="i" class="indent-pipe">│</span>
        <span class="indent-branch">├─</span>
      </span>

      <!-- Role badge -->
      <el-tag
        v-if="node.causal_role === 'root'"
        type="danger"
        size="small"
        effect="dark"
        class="role-tag"
      >根因</el-tag>
      <el-tag
        v-else-if="node.causal_role === 'consequence'"
        type="warning"
        size="small"
        effect="plain"
        class="role-tag"
      >后果</el-tag>
      <el-tag
        v-else
        size="small"
        effect="plain"
        class="role-tag"
      >独立</el-tag>

      <!-- Level dot -->
      <span class="level-dot" :class="`dot-${node.level}`"></span>

      <!-- Observer -->
      <span class="node-observer">{{ node.observer_name }}</span>

      <!-- Message (truncated for display) -->
      <span class="node-message">{{ truncateMsg(node.message) }}</span>

      <!-- Causal edge info -->
      <span v-if="node.causal_edge" class="edge-info">
        <el-tooltip :content="edgeTooltip" placement="top">
          <el-tag size="small" type="info" effect="plain">
            {{ formatConfidence(node.causal_edge.confidence) }}
            · {{ formatLag(node.causal_edge.avg_lag) }}
          </el-tag>
        </el-tooltip>
      </span>

      <!-- Timestamp -->
      <span class="node-time">{{ formatTime(node.timestamp) }}</span>
    </div>

    <!-- Recursive children -->
    <div v-if="node.consequences?.length" class="node-children">
      <CausalNode
        v-for="(child, idx) in node.consequences"
        :key="child.id || idx"
        :node="child"
        :depth="depth + 1"
        @select="$emit('select', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  node: { type: Object, required: true },
  depth: { type: Number, default: 0 },
})

defineEmits(['select'])

function truncateMsg(msg) {
  if (!msg) return ''
  return msg.length > 80 ? msg.slice(0, 80) + '...' : msg
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatConfidence(c) {
  return `${Math.round((c || 0) * 100)}%`
}

function formatLag(lag) {
  if (!lag || lag < 1) return '<1s'
  if (lag < 60) return `${Math.round(lag)}s`
  return `${Math.round(lag / 60)}m`
}

const edgeTooltip = computed(() => {
  const e = props.node.causal_edge
  if (!e) return ''
  return `因果置信度 ${formatConfidence(e.confidence)}，平均延迟 ${formatLag(e.avg_lag)}，共现 ${e.co_occurrence} 次`
})
</script>

<style scoped>
.causal-node {
  font-size: 13px;
}
.node-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  cursor: pointer;
  border-radius: 4px;
  transition: background-color 0.15s;
}
.node-row:hover {
  background-color: var(--el-fill-color-light, #f5f5f5);
}
.role-tag {
  flex-shrink: 0;
  min-width: 36px;
  text-align: center;
}
.level-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-critical { background: #f56c6c; }
.dot-error { background: #e6a23c; }
.dot-warning { background: #e6a23c; }
.dot-info { background: #909399; }
.node-observer {
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
  min-width: 80px;
  font-family: monospace;
  font-size: 12px;
}
.node-message {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-primary);
}
.edge-info {
  flex-shrink: 0;
}
.node-time {
  flex-shrink: 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-family: monospace;
}
.indent-connector {
  display: inline-flex;
  align-items: center;
  color: var(--el-border-color, #dcdfe6);
  font-family: monospace;
  font-size: 12px;
  flex-shrink: 0;
}
.indent-pipe {
  margin-right: 2px;
}
.indent-branch {
  margin-right: 4px;
}
.node-children {
  margin-left: 16px;
}

/* Root nodes have bolder styling */
.is-root > .node-row {
  font-weight: 500;
  background-color: var(--el-color-danger-light-9, #fef0f0);
}
.is-root > .node-row:hover {
  background-color: var(--el-color-danger-light-8, #fde2e2);
}

/* Isolated nodes are dimmer */
.role-isolated > .node-row {
  opacity: 0.7;
}
</style>
