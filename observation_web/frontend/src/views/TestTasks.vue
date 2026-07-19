<template>
  <div class="test-tasks">
    <!-- Active Locks Banner -->
    <el-alert
      v-if="activeLocks.length > 0"
      type="warning"
      :closable="false"
      class="locks-banner"
    >
      <template #title>
        <span><el-icon><Lock /></el-icon> 当前有 {{ activeLocks.length }} 个阵列被锁定</span>
      </template>
      <div class="locks-list">
        <el-tag
          v-for="lock in activeLocks"
          :key="lock.array_id"
          type="warning"
          size="small"
          effect="plain"
          closable
          @close="handleForceUnlock(lock)"
        >
          {{ lock.array_id }} ({{ lock.task_name }} - {{ lock.locked_by_nickname || lock.locked_by_ip || '未知' }})
        </el-tag>
      </div>
    </el-alert>

    <el-card>
      <template #header>
        <div class="card-header">
          <span>测试任务管理</span>
          <div class="header-actions">
            <el-button @click="loadLocks" :loading="loadingLocks">
              <el-icon><Refresh /></el-icon>
              刷新锁定状态
            </el-button>
            <el-button type="primary" @click="showCreateDialog = true">
              <el-icon><Plus /></el-icon>
              创建任务
            </el-button>
          </div>
        </div>
      </template>

      <!-- Task list -->
      <TestTaskTable
        :tasks="tasks"
        :loading="loading"
        @start="startTask"
        @stop="stopTask"
        @summary="viewSummary"
        @delete="deleteTask"
      />
    </el-card>

    <!-- Create dialog -->
    <CreateTaskDialog
      v-model="showCreateDialog"
      :task-types="taskTypes"
      :all-arrays="allArrays"
      :active-locks="activeLocks"
      :common-observers="commonObservers"
      @created="loadTasks"
    />

    <!-- Summary dialog -->
    <TaskSummaryDialog
      v-model="showSummaryDialog"
      :summary-data="summaryData"
      @open-rules="showRulesConfig = true"
    />

    <!-- Alert Rules Management -->
    <AlertRulesManager
      v-model="showRulesConfig"
      :task-types="taskTypes"
      :common-observers="commonObservers"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Plus, Lock, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import TestTaskTable from '@/components/test-tasks/TestTaskTable.vue'
import CreateTaskDialog from '@/components/test-tasks/CreateTaskDialog.vue'
import TaskSummaryDialog from '@/components/test-tasks/TaskSummaryDialog.vue'
import AlertRulesManager from '@/components/test-tasks/AlertRulesManager.vue'

const loading = ref(false)
const loadingLocks = ref(false)
const tasks = ref([])
const activeLocks = ref([])
const showCreateDialog = ref(false)
const showSummaryDialog = ref(false)
const showRulesConfig = ref(false)
const summaryData = ref(null)

const commonObservers = [
  'link_status', 'port_speed', 'alarm_type', 'error_code',
  'controller_state', 'card_info', 'card_recovery', 'disk_state',
  'cpu_usage', 'memory_leak', 'process_crash',
]

const taskTypes = {
  // Basic
  normal_business: '正常业务',
  custom: '自定义',
  // Power operations
  controller_poweroff: '控制器下电',
  card_poweroff: '接口卡下电',
  full_poweroff: '整机下电',
  ups_test: 'UPS 切换测试',
  // Network/Port
  port_toggle: '端口开关',
  cable_pull: '线缆拔插',
  network_isolation: '网络隔离',
  link_flapping: '链路抖动测试',
  // Fault injection
  fault_injection: '系统故障注入',
  disk_fault: '磁盘故障注入',
  memory_pressure: '内存压力测试',
  io_error_injection: 'IO 错误注入',
  // Upgrade
  controller_upgrade: '控制器升级',
  firmware_upgrade: '固件升级',
  hot_upgrade: '热升级',
  rollback_test: '回滚测试',
  // HA
  failover_test: '故障切换测试',
  takeover_test: '接管测试',
  split_brain: '脑裂测试',
  // Performance
  stress_test: '压力测试',
  endurance_test: '耐久测试',
  benchmark: '性能基准测试',
  // Recovery
  disaster_recovery: '灾难恢复',
  data_migration: '数据迁移',
  rebuild_test: '重建测试',
}

const allArrays = ref([])

async function loadLocks() {
  loadingLocks.value = true
  try {
    const res = await api.getAllLocks()
    activeLocks.value = res.data || []
  } catch (e) {
    console.error('Failed to load locks:', e)
  } finally {
    loadingLocks.value = false
  }
}

async function handleForceUnlock(lock) {
  try {
    await ElMessageBox.confirm(
      `确定要强制解锁阵列 "${lock.array_id}" 吗？这可能会影响正在运行的测试任务 "${lock.task_name}"。`,
      '强制解锁',
      { type: 'warning' }
    )
    await api.forceUnlock(lock.array_id)
    ElMessage.success('已强制解锁')
    await loadLocks()
  } catch (_) {}
}

async function loadTasks() {
  loading.value = true
  try {
    const res = await api.getTestTasks()
    tasks.value = res.data || []
  } finally {
    loading.value = false
  }
}

async function startTask(id) {
  try {
    await api.startTestTask(id)
    ElMessage.success('任务已开始')
    await Promise.all([loadTasks(), loadLocks()])
  } catch (e) {
    const detail = e.response?.data?.detail
    if (detail && typeof detail === 'object' && detail.conflicts) {
      const conflicts = detail.conflicts
      const msg = conflicts.map(c =>
        `${c.array_id} (被 ${c.locked_by_nickname || c.locked_by_ip || '未知用户'} 的任务 "${c.locked_by_task_name}" 锁定)`
      ).join(';\n')
      ElMessageBox.alert(
        `无法启动任务，以下阵列被其他任务锁定：\n${msg}`,
        '启动失败 - 阵列锁定冲突',
        { type: 'error' }
      )
    } else {
      ElMessage.error(typeof detail === 'string' ? detail : (detail?.message || '启动失败'))
    }
  }
}

async function stopTask(id) {
  try {
    await api.stopTestTask(id)
    ElMessage.success('任务已结束')
    await Promise.all([loadTasks(), loadLocks()])
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '停止失败')
  }
}

async function deleteTask(id) {
  try {
    await ElMessageBox.confirm('确认删除此测试任务？', '提示', { type: 'warning' })
    await api.deleteTestTask(id)
    ElMessage.success('已删除')
    await loadTasks()
  } catch (_) {}
}

async function viewSummary(id) {
  summaryData.value = null
  showSummaryDialog.value = true
  try {
    const res = await api.getTestTaskSummary(id)
    summaryData.value = res.data
  } catch (e) {
    ElMessage.error('获取摘要失败')
  }
}

async function loadArrays() {
  try {
    const res = await api.getArrays()
    allArrays.value = res.data || []
  } catch (e) {
    console.error('Failed to load arrays:', e)
  }
}

onMounted(async () => {
  await Promise.all([loadTasks(), loadArrays(), loadLocks()])
})
</script>

<style scoped>
.test-tasks { padding: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; gap: 10px; }

.locks-banner { margin-bottom: 16px; }
.locks-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
</style>
