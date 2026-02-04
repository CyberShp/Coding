<template>
  <div class="array-detail" v-loading="loading">
    <el-page-header @back="$router.back()">
      <template #content>
        <span class="page-title">{{ array?.name || '阵列详情' }}</span>
      </template>
    </el-page-header>

    <div class="content" v-if="array">
      <!-- Basic Info -->
      <el-card class="info-card">
        <template #header>
          <div class="card-header">
            <span>基本信息</span>
            <div class="actions">
              <el-button 
                v-if="array.state !== 'connected'"
                type="primary"
                size="small"
                @click="handleConnect"
              >
                连接
              </el-button>
              <el-button 
                v-else
                size="small"
                @click="handleDisconnect"
              >
                断开
              </el-button>
              <el-button size="small" @click="handleRefresh" :loading="refreshing">
                <el-icon><Refresh /></el-icon>
                刷新
              </el-button>
            </div>
          </div>
        </template>
        
        <el-descriptions :column="3" border>
          <el-descriptions-item label="名称">{{ array.name }}</el-descriptions-item>
          <el-descriptions-item label="地址">{{ array.host }}:{{ array.port }}</el-descriptions-item>
          <el-descriptions-item label="用户名">{{ array.username }}</el-descriptions-item>
          <el-descriptions-item label="连接状态">
            <el-tag :type="getStateType(array.state)">{{ getStateText(array.state) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Agent 状态">
            <el-tag v-if="array.agent_running" type="success">运行中</el-tag>
            <el-tag v-else-if="array.agent_deployed" type="warning">已部署</el-tag>
            <el-tag v-else type="info">未部署</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="最后刷新">
            {{ array.last_refresh ? formatDateTime(array.last_refresh) : '-' }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- Observer Status -->
      <el-card class="observer-card">
        <template #header>
          <span>观察点状态</span>
        </template>
        
        <el-table :data="observerList" stripe>
          <el-table-column label="观察点" prop="name" width="150">
            <template #default="{ row }">
              {{ getObserverName(row.name) }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="getObserverStatusType(row.status)">
                {{ getObserverStatusText(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="说明" prop="message" />
        </el-table>
        
        <el-empty v-if="observerList.length === 0" description="暂无数据" />
      </el-card>

      <!-- Agent Controls -->
      <el-card class="agent-card">
        <template #header>
          <div class="card-header">
            <span>Agent 控制</span>
            <el-tag v-if="array.agent_running" type="success">运行中</el-tag>
            <el-tag v-else-if="array.agent_deployed" type="warning">已部署</el-tag>
            <el-tag v-else type="info">未部署</el-tag>
          </div>
        </template>

        <div class="agent-actions">
          <el-progress
            v-if="isOperating"
            :percentage="100"
            :indeterminate="true"
            :duration="2"
            status="success"
          >
            <span>{{ operationText }}</span>
          </el-progress>

          <div class="agent-buttons">
            <el-button
              type="primary"
              size="small"
              :loading="deploying"
              :disabled="array.state !== 'connected'"
              @click="handleDeployAgent"
            >
              部署 Agent
            </el-button>
            <el-button
              size="small"
              :loading="restarting"
              :disabled="array.state !== 'connected'"
              @click="handleRestartAgent"
            >
              重启 Agent
            </el-button>
            <el-button
              size="small"
              :loading="stopping"
              :disabled="array.state !== 'connected'"
              @click="handleStopAgent"
            >
              停止 Agent
            </el-button>
          </div>
        </div>
      </el-card>

      <!-- Recent Alerts -->
      <el-card class="alerts-card">
        <template #header>
          <span>最近告警</span>
        </template>
        
        <el-table :data="array.recent_alerts || []" stripe max-height="400">
          <el-table-column label="时间" width="180">
            <template #default="{ row }">
              {{ formatDateTime(row.timestamp) }}
            </template>
          </el-table-column>
          <el-table-column label="级别" width="80">
            <template #default="{ row }">
              <el-tag :type="getLevelType(row.level)" size="small">
                {{ getLevelText(row.level) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="观察点" width="120">
            <template #default="{ row }">
              {{ getObserverName(row.observer_name) }}
            </template>
          </el-table-column>
          <el-table-column label="消息" prop="message" show-overflow-tooltip />
        </el-table>
        
        <el-empty v-if="!array.recent_alerts?.length" description="暂无告警" />
      </el-card>
    </div>

    <!-- Connect Dialog -->
    <el-dialog v-model="connectDialogVisible" title="连接阵列" width="400px">
      <el-form :model="connectForm">
        <el-form-item label="密码">
          <el-input 
            v-model="connectForm.password" 
            type="password" 
            show-password 
            placeholder="SSH 密码" 
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="connectDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="doConnect" :loading="connecting">连接</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useArrayStore } from '../stores/arrays'
import api from '../api'

const route = useRoute()
const arrayStore = useArrayStore()

const loading = ref(true)
const refreshing = ref(false)
const connectDialogVisible = ref(false)
const connecting = ref(false)
const array = ref(null)
const deploying = ref(false)
const stopping = ref(false)
const restarting = ref(false)

const connectForm = reactive({
  password: '',
})

const observerList = computed(() => {
  if (!array.value?.observer_status) return []
  return Object.entries(array.value.observer_status)
    .filter(([name]) => name !== '_meta')
    .map(([name, info]) => ({
      name,
      status: info.status,
      message: info.message,
    }))
})

const isOperating = computed(() => deploying.value || stopping.value || restarting.value)

const operationText = computed(() => {
  if (deploying.value) return '部署中...'
  if (restarting.value) return '重启中...'
  if (stopping.value) return '停止中...'
  return ''
})

const OBSERVER_NAMES = {
  error_code: '误码监测',
  link_status: '链路状态',
  card_recovery: '卡修复',
  alarm_type: 'AlarmType',
  memory_leak: '内存泄漏',
  cpu_usage: 'CPU利用率',
  cmd_response: '命令响应',
  sig_monitor: 'sig信号',
  sensitive_info: '敏感信息',
}

function getObserverName(name) {
  return OBSERVER_NAMES[name] || name
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

function getObserverStatusType(status) {
  const types = {
    ok: 'success',
    warning: 'warning',
    error: 'danger',
    unknown: 'info',
  }
  return types[status] || 'info'
}

function getObserverStatusText(status) {
  const texts = {
    ok: '正常',
    warning: '警告',
    error: '错误',
    unknown: '未知',
  }
  return texts[status] || status
}

function getLevelType(level) {
  const types = {
    info: 'info',
    warning: 'warning',
    error: 'danger',
    critical: 'danger',
  }
  return types[level] || 'info'
}

function getLevelText(level) {
  const texts = {
    info: '信息',
    warning: '警告',
    error: '错误',
    critical: '严重',
  }
  return texts[level] || level
}

function formatDateTime(timestamp) {
  if (!timestamp) return '-'
  return new Date(timestamp).toLocaleString('zh-CN')
}

async function loadArray() {
  loading.value = true
  try {
    const arrayId = route.params.id
    const response = await api.getArrayStatus(arrayId)
    array.value = response.data
  } catch (error) {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

function handleConnect() {
  connectForm.password = ''
  connectDialogVisible.value = true
}

async function doConnect() {
  connecting.value = true
  try {
    const result = await arrayStore.connectArray(array.value.array_id, connectForm.password)
    ElMessage.success('连接成功')
    connectDialogVisible.value = false
    if (result?.agent_status === 'not_deployed') {
      ElMessage.warning(result.hint || 'Agent 未部署')
    }
    await loadArray()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '连接失败')
  } finally {
    connecting.value = false
  }
}

async function handleDisconnect() {
  try {
    await arrayStore.disconnectArray(array.value.array_id)
    ElMessage.success('已断开连接')
    await loadArray()
  } catch (error) {
    ElMessage.error('断开连接失败')
  }
}

async function handleRefresh() {
  refreshing.value = true
  try {
    await arrayStore.refreshArray(array.value.array_id)
    await loadArray()
    ElMessage.success('刷新成功')
  } catch (error) {
    ElMessage.error('刷新失败')
  } finally {
    refreshing.value = false
  }
}

async function handleDeployAgent() {
  deploying.value = true
  try {
    await api.deployAgent(array.value.array_id)
    ElMessage.success('部署成功')
    await loadArray()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '部署失败')
  } finally {
    deploying.value = false
  }
}

async function handleRestartAgent() {
  restarting.value = true
  try {
    await api.restartAgent(array.value.array_id)
    ElMessage.success('重启成功')
    await loadArray()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '重启失败')
  } finally {
    restarting.value = false
  }
}

async function handleStopAgent() {
  stopping.value = true
  try {
    await api.stopAgent(array.value.array_id)
    ElMessage.success('停止成功')
    await loadArray()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '停止失败')
  } finally {
    stopping.value = false
  }
}

onMounted(loadArray)
</script>

<style scoped>
.array-detail {
  padding: 20px;
}

.page-title {
  font-size: 18px;
  font-weight: 500;
}

.content {
  margin-top: 20px;
}

.info-card,
.observer-card,
.agent-card,
.alerts-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.actions {
  display: flex;
  gap: 8px;
}

.agent-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.agent-buttons {
  display: flex;
  gap: 8px;
}
</style>
