<template>
  <div class="tag-card" :class="{ 'untagged-card': untagged }" @click="onClick">
    <div class="tag-header" :style="untagged ? {} : { borderLeftColor: tag.color }">
      <span class="tag-name">{{ label }}</span>
      <el-dropdown v-if="!untagged" @click.stop trigger="click" @command="(cmd) => handleTagAction(cmd, tag)">
        <el-button text size="small" @click.stop>
          <el-icon><MoreFilled /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="edit"><el-icon><Edit /></el-icon> 编辑</el-dropdown-item>
            <el-dropdown-item command="delete" divided><el-icon><Delete /></el-icon> 删除</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
    <div class="tag-body">
      <div class="tag-stat">
        <span class="stat-value">{{ untagged ? count : tag.array_count }}</span>
        <span class="stat-label">阵列</span>
      </div>
      <div class="tag-status" v-if="!untagged && tagStatuses[tag.id]">
        <el-tag v-if="tagStatuses[tag.id].connected > 0" type="success" size="small" effect="plain">{{ tagStatuses[tag.id].connected }} 已连接</el-tag>
        <el-tag v-if="tagStatuses[tag.id].error > 0" type="danger" size="small" effect="plain">{{ tagStatuses[tag.id].error }} 异常</el-tag>
      </div>
      <div v-if="matches.length" class="search-matches">
        <div v-for="arr in matches" :key="arr.array_id" class="match-item">
          <span class="match-name">{{ arr.name }}</span>
          <span class="match-ip">{{ arr.host }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject } from 'vue'
import { MoreFilled, Edit, Delete } from '@element-plus/icons-vue'

const props = defineProps({
  tag: { type: Object, default: () => ({}) },
  matches: { type: Array, default: () => [] },
  untagged: { type: Boolean, default: false },
  count: { type: Number, default: 0 },
  showParentName: { type: Boolean, default: false },
})

const { tagStatuses, goToTag, goToUntagged, handleTagAction } = inject('arraysCtx')

const label = computed(() => {
  if (props.untagged) return '未分类阵列'
  return props.showParentName && props.tag.parent_name
    ? `${props.tag.parent_name} / ${props.tag.name}`
    : props.tag.name
})

function onClick() {
  if (props.untagged) goToUntagged()
  else goToTag(props.tag.id)
}
</script>

<style scoped>
.tag-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.tag-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  border-color: var(--el-color-primary-light-5);
}

.tag-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  border-left: 4px solid var(--el-color-primary);
  border-radius: 8px 8px 0 0;
}

.untagged-card .tag-header {
  border-left-color: var(--el-color-info);
}

.tag-name {
  font-weight: 500;
  font-size: 15px;
}

.tag-body {
  padding: 16px;
}

.tag-stat {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 12px;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--el-color-primary);
}

.stat-label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.tag-status {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.search-matches {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.match-item {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 13px;
}

.match-name {
  color: var(--el-text-color-primary);
}

.match-ip {
  color: var(--el-text-color-secondary);
  font-family: monospace;
}
</style>
