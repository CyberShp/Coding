<template>
  <div>
    <!-- Grouped Tags View -->
    <div class="tags-grouped">
      <div v-for="group in groupedTags" :key="group.l1 ? group.l1.id : 'ungrouped'" class="tag-group">
        <!-- L1 Group Header -->
        <div v-if="group.l1" class="group-header" :style="{ borderLeftColor: group.l1.color }">
          <div class="group-title" @click="toggleGroup(group.l1.id)">
            <el-icon class="expand-icon" :class="{ expanded: expandedGroups.has(group.l1.id) }">
              <ArrowRight />
            </el-icon>
            <span class="group-name">{{ group.l1.name }}</span>
            <el-tag size="small" effect="plain" class="group-count">{{ group.totalArrays }} 阵列</el-tag>
          </div>
          <div class="group-actions">
            <el-button text size="small" @click.stop="goToTag(group.l1.id)">查看全部</el-button>
            <el-dropdown @click.stop trigger="click" @command="(cmd) => handleTagAction(cmd, group.l1)">
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
        </div>
        <!-- L2 Children (collapsible) -->
        <div v-show="!group.l1 || expandedGroups.has(group.l1.id)" class="group-children">
          <div class="tags-grid">
            <TagCard v-for="tag in group.children" :key="tag.id" :tag="tag" />
          </div>
        </div>
      </div>
    </div>

    <!-- Untagged Arrays Card (non-search mode) -->
    <div v-if="untaggedCount > 0" class="tags-grid" style="margin-top: 16px">
      <TagCard untagged :count="untaggedCount" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, inject } from 'vue'
import { MoreFilled, Edit, Delete, ArrowRight } from '@element-plus/icons-vue'
import TagCard from './TagCard.vue'

const { tags, untaggedCount, goToTag, handleTagAction } = inject('arraysCtx')

const expandedGroups = ref(new Set())

const groupedTags = computed(() => {
  const l1Map = new Map()
  const standalone = []

  for (const tag of tags.value) {
    if (tag.level === 1) {
      l1Map.set(tag.id, { l1: tag, children: [], totalArrays: tag.array_count || 0 })
    }
  }

  for (const tag of tags.value) {
    if (tag.level === 2 || tag.level !== 1) {
      if (tag.parent_id && l1Map.has(tag.parent_id)) {
        const group = l1Map.get(tag.parent_id)
        group.children.push(tag)
        group.totalArrays += (tag.array_count || 0)
      } else {
        standalone.push(tag)
      }
    }
  }

  const groups = [...l1Map.values()]
  if (standalone.length > 0) {
    groups.push({ l1: null, children: standalone, totalArrays: standalone.reduce((s, t) => s + (t.array_count || 0), 0) })
  }
  return groups
})

watch(groupedTags, (groups) => {
  for (const g of groups) {
    if (g.l1 && !expandedGroups.value.has(g.l1.id)) {
      expandedGroups.value.add(g.l1.id)
    }
  }
}, { immediate: true })

function toggleGroup(l1Id) {
  if (expandedGroups.value.has(l1Id)) {
    expandedGroups.value.delete(l1Id)
  } else {
    expandedGroups.value.add(l1Id)
  }
}
</script>

<style scoped>
.tags-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.tags-grouped {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.tag-group {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
}

.group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  border-left: 4px solid var(--el-color-primary);
}

.group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  flex: 1;
}

.expand-icon {
  transition: transform 0.2s;
  font-size: 14px;
  color: var(--el-text-color-secondary);
}

.expand-icon.expanded {
  transform: rotate(90deg);
}

.group-name {
  font-weight: 600;
  font-size: 16px;
}

.group-count {
  margin-left: 4px;
}

.group-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.group-children {
  padding: 16px;
}
</style>
