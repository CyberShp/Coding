<template>
  <div class="tag-arrays-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <div class="header-left">
            <el-button text @click="$router.push('/arrays')">
              <el-icon><ArrowLeft /></el-icon>
              返回
            </el-button>
            <span class="tag-title" v-if="tag">
              <span class="tag-dot" :style="{ background: tag.color }"></span>
              {{ tag.parent_name ? `${tag.parent_name} / ${tag.name}` : tag.name }}
              <el-tag size="small" effect="plain">{{ arrays.length }} 个阵列</el-tag>
            </span>
          </div>
          <div class="header-actions">
            <el-input
              v-model="searchIp"
              placeholder="搜索 IP"
              style="width: 200px"
              clearable
              @keyup.enter="handleSearch"
            >
              <template #append>
                <el-button @click="handleSearch">
                  <el-icon><Search /></el-icon>
                </el-button>
              </template>
            </el-input>
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
                  <el-dropdown-item command="refresh">
                    <el-icon><Refresh /></el-icon> 批量刷新
                  </el-dropdown-item>
                  <el-dropdown-item command="deploy-agent" divided>
                    <el-icon><Upload /></el-icon> 一键部署 Agent
                  </el-dropdown-item>
                  <el-dropdown-item command="restart-agent">
                    <el-icon><RefreshRight /></el-icon> 一键重启 Agent
                  </el-dropdown-item>
                  <el-dropdown-item command="stop-agent">
                    <el-icon><VideoPause /></el-icon> 一键停止 Agent
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
        :data="filteredArrays"
        v-loading="loading"
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
    <el-dialog v-model="dialogVisible" title="添加阵列" width="500px" @keyup.enter="handleAdd">
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
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleAdd" :loading="submitting">确定</el-button>
      </template>
    </el-dialog>

    <!-- Connect Dialog -->
    <el-dialog v-model="connectDialogVisible" title="连接阵列" width="400px" @keyup.enter="doConnect">
      <el-form :model="connectForm" @submit.prevent="doConnect">
        <el-form-item label="密码">
          <el-input
            v-model="connectForm.password"
            type="password"
            show-password
            placeholder="输入 SSH 密码（如果已配置密钥可留空）"
            @keyup.enter="doConnect"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="connectDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="doConnect" :loading="connecting">连接</el-button>
      </template>
    </el-dialog>

    <!-- Batch Connect Dialog -->
    <el-dialog v-model="batchConnectDialogVisible" title="批量连接" width="400px" @keyup.enter="doBatchConnect">
      <p class="batch-info">将连接 {{ selectedArrays.length }} 个阵列</p>
      <p class="batch-hint">已保存密码的阵列会自动使用本地密码；此处密码仅用于未保存密码的阵列。</p>
      <el-form :model="batchConnectForm" @submit.prevent="doBatchConnect">
        <el-form-item label="统一密码">
          <el-input
            v-model="batchConnectForm.password"
            type="password"
            show-password
            placeholder="可留空（自动使用已保存密码）"
            @keyup.enter="doBatchConnect"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchConnectDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="doBatchConnect" :loading="batchOperating">连接</el-button>
      </template>
    </el-dialog>

    <BatchProgressDialog
      :visible="progressVisible"
      :action-label="progressActionLabel"
      :total="progressTotal"
      :completed="progressCompleted"
      :success-count="progressSuccessCount"
      :rows="progressRows"
      @close="progressVisible = false"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, ArrowDown, Link, SwitchButton, Refresh, ArrowLeft, Search,
  Upload, RefreshRight, VideoPause
} from '@element-plus/icons-vue'
import api from '../api'
import BatchProgressDialog from '../components/BatchProgressDialog.vue'

const route = useRoute()

const tagId = computed(() => parseInt(route.params.tagId))
const tag = ref(null)
const arrays = ref([])
const loading = ref(false)
const searchIp = ref('')
const activeSearchIp = ref('')

const dialogVisible = ref(false)
const connectDialogVisible = ref(false)
const batchConnectDialogVisible = ref(false)
const submitting = ref(false)
const connecting = ref(false)
const batchOperating = ref(false)
const formRef = ref(null)
const currentArray = ref(null)
const selectedArrays = ref([])

const form = reactive({
  name: '',
  host: '',
  port: 22,
  username: 'root',
  password: '',
  key_path: '',
})

const connectForm = reactive({ password: '' })
const batchConnectForm = reactive({ password: '' })
const progressVisible = ref(false)
const progressTotal = ref(0)
const progressCompleted = ref(0)
const progressSuccessCount = ref(0)
const progressRows = ref([])
const progressActionLabel = ref('')

const rules = {
  name: [{ required: true, message: '请输入阵列名称', trigger: 'blur' }],
  host: [{ required: true, message: '请输入地址', trigger: 'blur' }],
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
}

const filteredArrays = computed(() => {
  if (!activeSearchIp.value) return arrays.value
  return arrays.value.filter(a => a.host && a.host.includes(activeSearchIp.value))
})

function getStateType(state) {
  const types = { connected: 'success', connecting: 'warning', disconnected: 'info', error: 'danger' }
  return types[state] || 'info'
}

function getStateText(state) {
  const texts = { connected: '已连接', connecting: '连接中', disconnected: '未连接', error: '错误' }
  return texts[state] || state
}

async function loadTag() {
  try {
    const res = await api.getTag(tagId.value)
    tag.value = res.data
  } catch (e) {
    ElMessage.error('获取标签信息失败')
  }
}

async function loadArrays() {
  loading.value = true
  try {
    const res = await api.getArrayStatuses(tagId.value)
    arrays.value = res.data || []
  } catch (e) {
    ElMessage.error('获取阵列列表失败')
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  activeSearchIp.value = searchIp.value.trim()
}

function showAddDialog() {
  Object.assign(form, {
    name: '',
    host: '',
    port: 22,
    username: 'root',
    password: '',
    key_path: '',
  })
  dialogVisible.value = true
}

async function handleAdd() {
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  submitting.value = true
  try {
    await api.createArray({ ...form, tag_id: tagId.value })
    ElMessage.success('添加成功')
    dialogVisible.value = false
    await loadArrays()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '添加失败')
  } finally {
    submitting.value = false
  }
}

async function handleConnect(row) {
  currentArray.value = row
  if (row.has_saved_password) {
    connecting.value = true
    try {
      await api.connectArray(row.array_id, '')
      ElMessage.success('自动连接成功')
      await loadArrays()
      return
    } catch {
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
    await api.connectArray(currentArray.value.array_id, connectForm.password)
    ElMessage.success('连接成功')
    connectDialogVisible.value = false
    await loadArrays()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '连接失败')
  } finally {
    connecting.value = false
  }
}

async function handleDisconnect(row) {
  try {
    await api.disconnectArray(row.array_id)
    ElMessage.success('已断开连接')
    await loadArrays()
  } catch {
    ElMessage.error('断开连接失败')
  }
}

async function handleDelete(row) {
  await ElMessageBox.confirm(`确定要删除阵列 "${row.name}" 吗？`, '确认删除', { type: 'warning' })
  try {
    await api.deleteArray(row.array_id)
    ElMessage.success('删除成功')
    await loadArrays()
  } catch {
    ElMessage.error('删除失败')
  }
}

function handleSelectionChange(selection) {
  selectedArrays.value = selection
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
  const actionNames = {
    disconnect: '断开',
    refresh: '刷新',
    'deploy-agent': '一键部署 Agent',
    'restart-agent': '一键重启 Agent',
    'stop-agent': '一键停止 Agent',
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
    const actionMap = {
      connect: '批量连接',
      disconnect: '批量断开',
      refresh: '批量刷新',
      'deploy-agent': '一键部署 Agent',
      'restart-agent': '一键重启 Agent',
      'stop-agent': '一键停止 Agent',
    }
    progressActionLabel.value = actionMap[action] || action
    progressVisible.value = true
    progressTotal.value = arrayIds.length
    progressCompleted.value = 0
    progressSuccessCount.value = 0
    const arrayMap = new Map(selectedArrays.value.map(a => [a.array_id, a]))
    progressRows.value = arrayIds.map(id => {
      const meta = arrayMap.get(id) || {}
      return {
        array_id: id,
        name: meta.name || id,
        host: meta.host || '',
        status: '等待中',
        detail: '',
      }
    })

    const token = localStorage.getItem('admin_token')
    const headers = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }
    if (token) headers.Authorization = `Bearer ${token}`
    const resp = await fetch(`/api/arrays/batch/${action}?stream=true`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ array_ids: arrayIds, password }),
    })
    if (!resp.ok || !resp.body) {
      throw new Error(`HTTP ${resp.status}`)
    }

    const decoder = new TextDecoder('utf-8')
    const reader = resp.body.getReader()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx = buffer.indexOf('\n\n')
      while (idx >= 0) {
        const rawEvent = buffer.slice(0, idx).trim()
        buffer = buffer.slice(idx + 2)
        idx = buffer.indexOf('\n\n')
        const dataLine = rawEvent
          .split('\n')
          .find(line => line.startsWith('data: '))
        if (!dataLine) continue
        const payload = JSON.parse(dataLine.slice(6))
        if (payload.type === 'progress' && payload.result) {
          const r = payload.result
          const row = progressRows.value.find(item => item.array_id === r.array_id)
          if (row) {
            row.status = r.success ? '成功' : '失败'
            const warnings = r.warnings?.length ? `（${r.warnings.length} 条警告）` : ''
            row.detail = r.success ? `${r.message || '完成'}${warnings}` : (r.error || '失败')
          }
          progressCompleted.value = payload.completed || progressCompleted.value
          progressSuccessCount.value = payload.success_count || progressSuccessCount.value
        } else if (payload.type === 'done') {
          progressCompleted.value = payload.completed || progressCompleted.value
          progressSuccessCount.value = payload.success_count || progressSuccessCount.value
        }
      }
    }

    if (progressSuccessCount.value === progressTotal.value) {
      ElMessage.success('批量操作完成：全部成功')
    } else if (progressSuccessCount.value > 0) {
      ElMessage.warning(`批量操作完成：${progressSuccessCount.value}/${progressTotal.value} 成功`)
    } else {
      ElMessage.error('批量操作失败')
    }
    await loadArrays()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '批量操作失败')
  } finally {
    batchOperating.value = false
  }
}

watch(tagId, async () => {
  if (tagId.value) {
    await Promise.all([loadTag(), loadArrays()])
  }
}, { immediate: true })
</script>

<style scoped>
.tag-arrays-page {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.tag-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 500;
}

.tag-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.batch-info {
  margin-bottom: 15px;
  color: #606266;
}

.batch-hint {
  margin-bottom: 12px;
  color: #909399;
  font-size: 12px;
}
</style>
