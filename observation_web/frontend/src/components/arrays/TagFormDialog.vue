<template>
  <el-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" :title="editingTag ? '编辑标签' : '添加标签'" width="400px" @keyup.enter="handleAddTag">
    <el-form :model="tagForm" :rules="tagRules" ref="tagFormRef" label-width="80px" @submit.prevent="handleAddTag">
      <el-form-item label="上级标签">
        <el-select v-model="tagForm.parent_id" placeholder="不选则为一级标签" clearable style="width: 100%">
          <el-option
            v-for="t in l1Tags"
            :key="t.id"
            :label="t.name"
            :value="t.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="名称" prop="name">
        <el-input v-model="tagForm.name" placeholder="标签名称" @keyup.enter="handleAddTag" />
      </el-form-item>
      <el-form-item label="颜色">
        <el-color-picker v-model="tagForm.color" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="tagForm.description" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" @click="handleAddTag" :loading="tagSubmitting">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  editingTag: { type: Object, default: null },
  l1Tags: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const tagFormRef = ref(null)
const tagSubmitting = ref(false)

const tagForm = reactive({
  name: '',
  color: '#409eff',
  description: '',
  parent_id: null,
})

const tagRules = {
  name: [{ required: true, message: '请输入标签名称', trigger: 'blur' }],
}

watch(() => props.modelValue, (visible) => {
  if (!visible) return
  if (props.editingTag) {
    Object.assign(tagForm, {
      name: props.editingTag.name,
      color: props.editingTag.color,
      description: props.editingTag.description,
      parent_id: props.editingTag.parent_id ?? null,
    })
  } else {
    Object.assign(tagForm, { name: '', color: '#409eff', description: '', parent_id: null })
  }
})

async function handleAddTag() {
  try {
    await tagFormRef.value.validate()
  } catch {
    return
  }

  const payload = {
    name: tagForm.name,
    color: tagForm.color,
    description: tagForm.description,
    parent_id: tagForm.parent_id || null,
    level: tagForm.parent_id ? 2 : 1,
  }

  tagSubmitting.value = true
  try {
    if (props.editingTag) {
      await api.updateTag(props.editingTag.id, payload)
      ElMessage.success('更新成功')
    } else {
      await api.createTag(payload)
      ElMessage.success('创建成功')
    }
    emit('update:modelValue', false)
    emit('saved')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '操作失败')
  } finally {
    tagSubmitting.value = false
  }
}
</script>
