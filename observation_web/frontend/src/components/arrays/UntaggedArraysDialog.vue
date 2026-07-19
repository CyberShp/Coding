<template>
  <el-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" title="未分类阵列" width="800px">
    <el-table :data="untaggedArrays" v-loading="loadingUntagged" stripe max-height="400">
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="getStateType(row.state)" size="small">
            {{ getStateText(row.state) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="host" label="地址" />
      <el-table-column label="分配标签" width="180">
        <template #default="{ row }">
          <el-select
            :model-value="row.tag_id"
            placeholder="选择标签"
            size="small"
            clearable
            @change="(val) => assignTag(row, val)"
          >
            <el-option
              v-for="tag in tags"
              :key="tag.id"
              :label="tag.parent_name ? `${tag.parent_name} / ${tag.name}` : tag.name"
              :value="tag.id"
            />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button size="small" @click="$router.push(`/arrays/${row.array_id}`)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  tags: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'changed'])

const untaggedArrays = ref([])
const loadingUntagged = ref(false)

watch(() => props.modelValue, (visible) => {
  if (visible) loadUntagged()
})

async function loadUntagged() {
  loadingUntagged.value = true
  try {
    const res = await api.getArrayStatuses()
    untaggedArrays.value = (res.data || []).filter(a => !a.tag_id)
  } finally {
    loadingUntagged.value = false
  }
}

async function assignTag(array, tagId) {
  try {
    await api.updateArray(array.array_id, { tag_id: tagId || null })
    ElMessage.success('标签已更新')
    emit('changed')
    // Refresh untagged list
    untaggedArrays.value = untaggedArrays.value.filter(a => a.array_id !== array.array_id)
  } catch (e) {
    ElMessage.error('更新失败')
  }
}

function getStateType(state) {
  const types = { connected: 'success', connecting: 'warning', disconnected: 'info', error: 'danger' }
  return types[state] || 'info'
}

function getStateText(state) {
  const texts = { connected: '已连接', connecting: '连接中', disconnected: '未连接', error: '错误' }
  return texts[state] || state
}
</script>
