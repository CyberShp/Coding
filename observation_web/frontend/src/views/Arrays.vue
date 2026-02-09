<template>
  <div class="arrays-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>阵列管理</span>
          <div class="header-actions">
            <!-- Batch Actions -->
            <el-dropdown v-if="selectedArrays.length > 0" @command="handleBatchAction" trigger="click">
              <el-button>
                批量操作 ({{ selectedArrays.length }})
                <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="connect">
                    <el-icon><Link /></el-icon> 批量连接
                  </el-dropdown-item>
                  <el-dropdown-item command="disconnect">
                    <el-icon><SwitchButton /></el-icon> 批量断开
                  </el-dropdown-item>
                  <el-dropdown-item command="refresh" divided>
                    <el-icon><Refresh /></el-icon> 批量刷新
                  </el-dropdown-item>
                  <el-dropdown-item command="deploy-agent" divided>
                    <el-icon><Upload /></el-icon> 部署 Agent
                  </el-dropdown-item>
                  <el-dropdown-item command="start-agent">
                    <el-icon><VideoPlay /></el-icon> 启动 Agent
                  </el-dropdown-item>
                  <el-dropdown-item command="stop-agent">
                    <el-icon><VideoPause /></el-icon> 停止 Agent
                  </el-dropdown-item>
                  <el-dropdown-item command="restart-agent">
                    <el-icon><RefreshRight /></el-icon> 重启 Agent
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button type="primary" @click="showAddDialog">
              <el-icon><Plus /></el-icon>
              添加阵列
            </el-button>
          </div>
        </div>
      </template>

      <el-table 
        :data="arrayStore.arrays" 
        v-loading="arrayStore.loading" 
        stripe
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="getStateType(row.state)" size="small">
              {{ getStateText(row.state) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="host" label="地址" />
        <el-table-column prop="port" label="端口" width="80" />
        <el-table-column prop="username" label="用户名" width="100" />
        <el-table-column prop="folder" label="分组" />
        <el-table-column label="Agent" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.agent_running" type="success" size="small">运行中</el-tag>
            <el-tag v-else-if="row.agent_deployed" type="warning" size="small">已部署</el-tag>
            <el-tag v-else type="info" size="small">未部署</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280">
          <template #default="{ row }">
            <el-button-group>
              <el-button 
                v-if="row.state !== 'connected'"
                size="small"
                type="primary"
                @click="handleConnect(row)"
              >
                连接
              </el-button>
              <el-button 
                v-else
                size="small"
                @click="handleDisconnect(row)"
              >
                断开
              </el-button>
              <el-button 
                size="small"
                @click="$router.push(`/arrays/${row.array_id}`)"
              >
                详情
              </el-button>
              <el-button 
                size="small"
                type="danger"
                @click="handleDelete(row)"
              >
                删除
              </el-button>
            </el-button-group>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Add Array Dialog -->
    <el-dialog v-model="dialogVisible" title="添加阵列" width="500px">
      <el-form :model="form" :rules="rules" ref="formRef" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="阵列名称" />
        </el-form-item>
        <el-form-item label="地址" prop="host">
          <el-input v-model="form.host" placeholder="IP 地址或主机名" />
        </el-form-item>
        <el-form-item label="端口" prop="port">
          <el-input-number v-model="form.port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="SSH 密码" />
        </el-form-item>
        <el-form-item label="密钥路径">
          <el-input v-model="form.key_path" placeholder="可选：SSH 密钥文件路径" />
        </el-form-item>
        <el-form-item label="分组">
          <el-input v-model="form.folder" placeholder="可选：分组名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleAdd" :loading="submitting">确定</el-button>
      </template>
    </el-dialog>

    <!-- Connect Dialog -->
    <el-dialog v-model="connectDialogVisible" title="连接阵列" width="400px">
      <el-form :model="connectForm">
        <el-form-item label="密码">
          <el-input 
            v-model="connectForm.password" 
            type="password" 
            show-password 
            placeholder="输入 SSH 密码（如果已配置密钥可留空）" 
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="connectDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="doConnect" :loading="connecting">连接</el-button>
      </template>
    </el-dialog>

    <!-- Batch Connect Dialog -->
    <el-dialog v-model="batchConnectDialogVisible" title="批量连接" width="400px">
      <p class="batch-info">将连接 {{ selectedArrays.length }} 个阵列</p>
      <el-form :model="batchConnectForm">
        <el-form-item label="统一密码">
          <el-input 
            v-model="batchConnectForm.password" 
            type="password" 
            show-password 
            placeholder="所有阵列使用相同的 SSH 密码" 
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchConnectDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="doBatchConnect" :loading="batchOperating">连接</el-button>
      </template>
    </el-dialog>

    <!-- Batch Result Dialog -->
    <el-dialog v-model="batchResultDialogVisible" title="批量操作结果" width="500px">
      <div class="batch-summary">
        <el-tag type="success" size="large">成功: {{ batchResult.success_count }}</el-tag>
        <el-tag type="danger" size="large">失败: {{ batchResult.total - batchResult.success_count }}</el-tag>
      </div>
      <el-table :data="batchResult.results" max-height="300" class="batch-results">
        <el-table-column label="阵列" width="150">
          <template #default="{ row }">
            {{ getArrayName(row.array_id) }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.success ? 'success' : 'danger'" size="small">
              {{ row.success ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="消息" prop="message" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.message || row.error || '-' }}
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button type="primary" @click="batchResultDialogVisible = false">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { 
  Plus, ArrowDown, Link, SwitchButton, Refresh, Upload, 
  VideoPlay, VideoPause, RefreshRight 
} from '@element-plus/icons-vue'
import { useArrayStore } from '../stores/arrays'
import api from '../api'

const arrayStore = useArrayStore()

const dialogVisible = ref(false)
const connectDialogVisible = ref(false)
const batchConnectDialogVisible = ref(false)
const batchResultDialogVisible = ref(false)
const submitting = ref(false)
const connecting = ref(false)
const batchOperating = ref(false)
const formRef = ref(null)
const currentArray = ref(null)
const selectedArrays = ref([])
const batchResult = ref({ total: 0, success_count: 0, results: [] })

const form = reactive({
  name: '',
  host: '',
  port: 22,
  username: 'root',
  password: '',
  key_path: '',
  folder: '',
})

const connectForm = reactive({
  password: '',
})

const batchConnectForm = reactive({
  password: '',
})

const rules = {
  name: [{ required: true, message: '请输入阵列名称', trigger: 'blur' }],
  host: [{ required: true, message: '请输入地址', trigger: 'blur' }],
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
}

function getStateType(state) {
  const types = {
    connected: 'success',
    connecting: 'warning',
    disconnected: 'info',
    error: 'danger',
  }
  return types[state] || 'info'
}

function getStateText(state) {
  const texts = {
    connected: '已连接',
    connecting: '连接中',
    disconnected: '未连接',
    error: '错误',
  }
  return texts[state] || state
}

function showAddDialog() {
  Object.assign(form, {
    name: '',
    host: '',
    port: 22,
    username: 'root',
    password: '',
    key_path: '',
    folder: '',
  })
  dialogVisible.value = true
}

async function handleAdd() {
  await formRef.value.validate()
  
  submitting.value = true
  try {
    await arrayStore.createArray(form)
    ElMessage.success('添加成功')
    dialogVisible.value = false
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '添加失败')
  } finally {
    submitting.value = false
  }
}

async function handleConnect(row) {
  currentArray.value = row
  
  // 如果有保存的密码，先尝试自动连接
  if (row.has_saved_password) {
    connecting.value = true
    try {
      await arrayStore.connectArray(row.array_id, '')  // 后端自动使用已保存密码
      ElMessage.success('自动连接成功')
      return
    } catch (error) {
      // 自动连接失败，弹出密码框让用户重新输入
      ElMessage.warning('已保存的密码连接失败，请重新输入密码')
    } finally {
      connecting.value = false
    }
  }
  
  connectForm.password = ''
  connectDialogVisible.value = true
}

async function doConnect() {
  connecting.value = true
  try {
    await arrayStore.connectArray(currentArray.value.array_id, connectForm.password)
    ElMessage.success('连接成功')
    connectDialogVisible.value = false
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '连接失败')
  } finally {
    connecting.value = false
  }
}

async function handleDisconnect(row) {
  try {
    await arrayStore.disconnectArray(row.array_id)
    ElMessage.success('已断开连接')
  } catch (error) {
    ElMessage.error('断开连接失败')
  }
}

async function handleDelete(row) {
  await ElMessageBox.confirm(
    `确定要删除阵列 "${row.name}" 吗？`,
    '确认删除',
    { type: 'warning' }
  )
  
  try {
    await arrayStore.deleteArray(row.array_id)
    ElMessage.success('删除成功')
  } catch (error) {
    ElMessage.error('删除失败')
  }
}

// Batch operations
function handleSelectionChange(selection) {
  selectedArrays.value = selection
}

function getArrayName(arrayId) {
  const array = arrayStore.arrays.find(a => a.array_id === arrayId)
  return array?.name || arrayId
}

async function handleBatchAction(action) {
  if (selectedArrays.value.length === 0) {
    ElMessage.warning('请先选择阵列')
    return
  }

  if (action === 'connect') {
    batchConnectForm.password = ''
    batchConnectDialogVisible.value = true
    return
  }

  // Confirm other batch actions
  const actionNames = {
    'disconnect': '断开',
    'refresh': '刷新',
    'deploy-agent': '部署 Agent',
    'start-agent': '启动 Agent',
    'stop-agent': '停止 Agent',
    'restart-agent': '重启 Agent',
  }

  await ElMessageBox.confirm(
    `确定要对 ${selectedArrays.value.length} 个阵列执行"${actionNames[action]}"操作吗？`,
    '确认批量操作',
    { type: 'warning' }
  )

  await executeBatchAction(action)
}

async function doBatchConnect() {
  batchOperating.value = true
  try {
    await executeBatchAction('connect', batchConnectForm.password)
    batchConnectDialogVisible.value = false
  } finally {
    batchOperating.value = false
  }
}

async function executeBatchAction(action, password = null) {
  batchOperating.value = true
  
  try {
    const arrayIds = selectedArrays.value.map(a => a.array_id)
    const res = await api.batchAction(action, arrayIds, password)
    
    batchResult.value = res.data
    batchResultDialogVisible.value = true
    
    // Refresh array list
    await arrayStore.fetchArrays()
    
    if (res.data.success_count === res.data.total) {
      ElMessage.success(`批量操作完成：全部成功`)
    } else if (res.data.success_count > 0) {
      ElMessage.warning(`批量操作完成：${res.data.success_count}/${res.data.total} 成功`)
    } else {
      ElMessage.error(`批量操作失败`)
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '批量操作失败')
  } finally {
    batchOperating.value = false
  }
}

onMounted(() => {
  arrayStore.fetchArrays()
})
</script>

<style scoped>
.arrays-page {
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
}

.batch-info {
  margin-bottom: 15px;
  color: #606266;
}

.batch-summary {
  display: flex;
  gap: 20px;
  margin-bottom: 15px;
}

.batch-results {
  margin-top: 10px;
}
</style>
