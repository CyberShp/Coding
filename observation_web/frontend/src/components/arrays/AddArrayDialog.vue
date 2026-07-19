<template>
  <el-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" title="添加阵列" width="500px" @keyup.enter="handleAdd">
    <el-form :model="form" :rules="rules" ref="formRef" label-width="80px" @submit.prevent="handleAdd">
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="阵列名称" @keyup.enter="handleAdd" />
      </el-form-item>
      <el-form-item label="地址" prop="host">
        <el-input v-model="form.host" placeholder="IP 地址或主机名" @keyup.enter="handleAdd" />
      </el-form-item>
      <el-form-item label="端口" prop="port">
        <el-input-number v-model="form.port" :min="1" :max="65535" />
      </el-form-item>
      <el-form-item label="用户名" prop="username">
        <el-input v-model="form.username" @keyup.enter="handleAdd" />
      </el-form-item>
      <el-form-item label="密码" prop="password">
        <el-input v-model="form.password" type="password" show-password placeholder="SSH 密码" @keyup.enter="handleAdd" />
      </el-form-item>
      <el-form-item label="密钥路径">
        <el-input v-model="form.key_path" placeholder="可选：SSH 密钥文件路径" @keyup.enter="handleAdd" />
      </el-form-item>
      <el-form-item label="标签">
        <el-select v-model="form.tag_id" placeholder="选择标签（可选）" clearable style="width: 100%">
          <el-option
            v-for="tag in tags"
            :key="tag.id"
            :label="tag.parent_name ? `${tag.parent_name} / ${tag.name}` : tag.name"
            :value="tag.id"
          >
            <span class="tag-option">
              <span class="tag-dot" :style="{ background: tag.color }"></span>
              {{ tag.parent_name ? `${tag.parent_name} / ${tag.name}` : tag.name }}
            </span>
          </el-option>
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" @click="handleAdd" :loading="submitting">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  tags: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'created'])

const formRef = ref(null)
const submitting = ref(false)

const form = reactive({
  name: '',
  host: '',
  port: 22,
  username: 'root',
  password: '',
  key_path: '',
  tag_id: null,
})

const rules = {
  name: [{ required: true, message: '请输入阵列名称', trigger: 'blur' }],
  host: [{ required: true, message: '请输入地址', trigger: 'blur' }],
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
}

watch(() => props.modelValue, (visible) => {
  if (visible) {
    Object.assign(form, {
      name: '',
      host: '',
      port: 22,
      username: 'root',
      password: '',
      key_path: '',
      tag_id: null,
    })
  }
})

async function handleAdd() {
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  submitting.value = true
  try {
    await api.createArray(form)
    ElMessage.success('添加成功')
    emit('update:modelValue', false)
    emit('created')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '添加失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.tag-option {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tag-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
</style>
