<template>
  <el-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" title="创建测试任务" width="500px">
    <el-form :model="form" label-width="100px">
      <el-form-item label="任务名称" required>
        <el-input v-model="form.name" placeholder="如: 控制器下电测试 #3" />
      </el-form-item>
      <el-form-item label="测试类型">
        <el-select v-model="form.task_type" style="width: 100%">
          <el-option
            v-for="(label, key) in taskTypes"
            :key="key"
            :label="label"
            :value="key"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="关联阵列">
        <el-select
          v-model="form.array_ids"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="选择阵列（留空关联全部）"
          style="width: 100%"
        >
          <el-option
            v-for="a in allArrays"
            :key="a.array_id"
            :label="a.name"
            :value="a.array_id"
            :disabled="isArrayLocked(a.array_id)"
          >
            <span>{{ a.name }}</span>
            <el-tag
              v-if="isArrayLocked(a.array_id)"
              type="danger"
              size="small"
              effect="plain"
              style="margin-left: 8px"
            >
              已锁定
            </el-tag>
          </el-option>
        </el-select>
        <div v-if="lockedArraysSelected.length" class="lock-warning">
          <el-icon><Warning /></el-icon>
          选中的阵列中有 {{ lockedArraysSelected.length }} 个被锁定，启动时可能失败
        </div>
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.notes" type="textarea" :rows="3" />
      </el-form-item>
      <el-form-item label="预期观察点">
        <el-transfer
          v-model="form.expected_observers"
          :data="observerTransferData"
          :titles="['全量观察点', '预期观察点']"
          filterable
          style="width: 100%"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" @click="createTask" :loading="creating">创建</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { Warning } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '../../api'
import { getObserverName } from '@/utils/alertTranslator'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  taskTypes: { type: Object, default: () => ({}) },
  allArrays: { type: Array, default: () => [] },
  activeLocks: { type: Array, default: () => [] },
  commonObservers: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'created'])

const creating = ref(false)

const form = reactive({
  name: '',
  task_type: 'custom',
  array_ids: [],
  expected_observers: [],
  notes: '',
})

const observerTransferData = computed(() => props.commonObservers.map(name => ({
  key: name,
  label: getObserverName(name),
})))

const lockedArrayIds = computed(() => props.activeLocks.map(l => l.array_id))

function isArrayLocked(arrayId) {
  return lockedArrayIds.value.includes(arrayId)
}

const lockedArraysSelected = computed(() => {
  return form.array_ids.filter(id => isArrayLocked(id))
})

async function createTask() {
  if (!form.name.trim()) {
    ElMessage.warning('请输入任务名称')
    return
  }
  creating.value = true
  try {
    await api.createTestTask({
      name: form.name,
      task_type: form.task_type,
      array_ids: form.array_ids,
      expected_observers: form.expected_observers,
      notes: form.notes,
    })
    ElMessage.success('任务创建成功')
    emit('update:modelValue', false)
    form.name = ''
    form.notes = ''
    form.array_ids = []
    form.expected_observers = []
    emit('created')
  } finally {
    creating.value = false
  }
}
</script>

<style scoped>
.lock-warning {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
  font-size: 12px;
  color: #e6a23c;
}
</style>
