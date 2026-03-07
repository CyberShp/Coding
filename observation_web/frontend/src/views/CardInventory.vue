<template>
  <div class="card-inventory-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>卡件列表</span>
          <div class="header-actions">
            <el-input
              v-model="searchQuery"
              placeholder="搜索名称、型号、描述"
              style="width: 220px"
              clearable
              @keyup.enter="loadData"
              @clear="loadData"
            >
              <template #append>
                <el-button @click="loadData">
                  <el-icon><Search /></el-icon>
                </el-button>
              </template>
            </el-input>
            <el-select
              v-model="filterDeviceType"
              placeholder="器件类型"
              clearable
              style="width: 140px"
              @change="loadData"
            >
              <el-option
                v-for="t in deviceTypes"
                :key="t"
                :label="t"
                :value="t"
              />
            </el-select>
            <el-button type="primary" @click="showAddDialog">
              <el-icon><Plus /></el-icon>
              添加卡件
            </el-button>
          </div>
        </div>
      </template>

      <el-table :data="cards" v-loading="loading" stripe>
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column prop="device_type" label="器件类型" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.device_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="model" label="型号" min-width="120" />
        <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="showEditDialog(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Add/Edit Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑卡件' : '添加卡件'"
      width="480px"
      @closed="resetForm"
    >
      <el-form :model="form" :rules="rules" ref="formRef" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="卡件名称" />
        </el-form-item>
        <el-form-item label="器件类型" prop="device_type">
          <el-select v-model="form.device_type" placeholder="选择类型" style="width: 100%">
            <el-option v-for="t in deviceTypes" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="型号" prop="model">
          <el-input v-model="form.model" placeholder="型号（可选）" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="描述（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ editingId ? '保存' : '添加' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import api from '../api'

const loading = ref(false)
const submitting = ref(false)
const cards = ref([])
const deviceTypes = ref([])
const searchQuery = ref('')
const filterDeviceType = ref('')
const dialogVisible = ref(false)
const editingId = ref(null)
const formRef = ref(null)

const form = reactive({
  name: '',
  device_type: '',
  model: '',
  description: '',
})

const rules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  device_type: [{ required: true, message: '请选择器件类型', trigger: 'change' }],
}

async function loadDeviceTypes() {
  try {
    const res = await api.getCardDeviceTypes()
    deviceTypes.value = res.data || []
  } catch (e) {
    deviceTypes.value = ['FC卡', '以太网卡', 'RAID卡', '控制器卡', '扩展卡', '其他']
  }
}

async function loadData() {
  loading.value = true
  try {
    const params = {}
    if (searchQuery.value?.trim()) params.q = searchQuery.value.trim()
    if (filterDeviceType.value) params.device_type = filterDeviceType.value
    const res = await api.getCardInventory(params)
    cards.value = res.data || []
  } catch (e) {
    console.error('Failed to load card inventory:', e)
    cards.value = []
  } finally {
    loading.value = false
  }
}

function showAddDialog() {
  editingId.value = null
  Object.assign(form, { name: '', device_type: '', model: '', description: '' })
  dialogVisible.value = true
}

function showEditDialog(row) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    device_type: row.device_type,
    model: row.model || '',
    description: row.description || '',
  })
  dialogVisible.value = true
}

function resetForm() {
  editingId.value = null
  formRef.value?.resetFields()
}

async function handleSubmit() {
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await api.updateCardItem(editingId.value, {
        name: form.name,
        device_type: form.device_type,
        model: form.model,
        description: form.description,
      })
      ElMessage.success('已更新')
    } else {
      await api.createCardItem({
        name: form.name,
        device_type: form.device_type,
        model: form.model,
        description: form.description,
      })
      ElMessage.success('已添加')
    }
    dialogVisible.value = false
    await loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row) {
  await ElMessageBox.confirm(`确定删除「${row.name}」？`, '确认删除', {
    type: 'warning',
  })
  try {
    await api.deleteCardItem(row.id)
    ElMessage.success('已删除')
    await loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

onMounted(async () => {
  await loadDeviceTypes()
  await loadData()
})
</script>

<style scoped>
.card-inventory-page {
  padding: 20px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
</style>
