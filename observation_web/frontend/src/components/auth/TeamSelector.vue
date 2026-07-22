<template>
  <el-dialog v-model="visible" title="我的小组" width="420px" @open="loadTags">
    <p class="team-hint">选择你所在的特性小组（L1 标签），可多选、随时修改</p>

    <div v-if="tagsLoading" class="team-loading">加载中...</div>
    <el-empty v-else-if="level1Tags.length === 0" description="暂无小组标签" :image-size="60" />
    <el-checkbox-group v-else v-model="selectedIds" class="team-checkbox-group">
      <el-checkbox
        v-for="tag in level1Tags"
        :key="tag.id"
        :label="tag.id"
        class="team-checkbox"
      >
        {{ tag.name }}
      </el-checkbox>
    </el-checkbox-group>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../../stores/auth'
import api, { extractError } from '../../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const authStore = useAuthStore()

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})

const tags = ref([])
const tagsLoading = ref(false)
const selectedIds = ref([])
const saving = ref(false)

const level1Tags = computed(() => tags.value.filter(t => t.level === 1))

async function loadTags() {
  selectedIds.value = [...(authStore.currentUser?.teams || [])]
  tagsLoading.value = true
  try {
    const res = await api.getTags()
    tags.value = res.data || []
  } catch (e) {
    ElMessage.error(extractError(e, '加载小组标签失败'))
  } finally {
    tagsLoading.value = false
  }
}

async function handleSave() {
  saving.value = true
  try {
    await authStore.setTeams(selectedIds.value)
    visible.value = false
    ElMessage.success('小组已保存')
    emit('saved', selectedIds.value)
  } catch (e) {
    ElMessage.error(extractError(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

// Exposed for unit tests
defineExpose({ level1Tags, loadTags, selectedIds })
</script>

<style scoped>
.team-hint {
  color: #909399;
  font-size: 13px;
  margin-bottom: 12px;
  line-height: 1.5;
}
.team-loading {
  color: #909399;
  font-size: 13px;
  padding: 12px 0;
}
.team-checkbox-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 300px;
  overflow-y: auto;
}
.team-checkbox {
  margin-right: 0;
}
</style>
