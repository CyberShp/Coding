<template>
  <div class="test-tasks">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>测试任务管理</span>
          <el-button type="primary" @click="showCreateDialog = true">
            <el-icon><Plus /></el-icon>
            创建任务
          </el-button>
        </div>
      </template>

      <!-- Task list -->
      <el-table :data="tasks" v-loading="loading" stripe>
        <el-table-column label="任务名称" prop="name" min-width="180" />
        <el-table-column label="测试类型" width="140">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.task_type_label || row.task_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="关联阵列" width="160">
          <template #default="{ row }">
            {{ (row.array_ids || []).join(', ') || '全部' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'running' ? 'success' : (row.status === 'completed' ? 'info' : '')"
              size="small"
            >
              {{ { created: '待开始', running: '进行中', completed: '已完成' }[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="持续时间" width="120">
          <template #default="{ row }">
            {{ row.duration_seconds ? formatDuration(row.duration_seconds) : '--' }}
          </template>
        </el-table-column>
        <el-table-column label="告警数" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.alert_count > 0" type="danger" size="small">{{ row.alert_count }}</el-tag>
            <span v-else class="muted">0</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'created'"
              type="success" size="small"
              @click="startTask(row.id)"
            >开始</el-button>
            <el-button
              v-if="row.status === 'running'"
              type="warning" size="small"
              @click="stopTask(row.id)"
            >结束</el-button>
            <el-button
              v-if="row.status === 'completed' || row.status === 'running'"
              type="primary" size="small" plain
              @click="viewSummary(row.id)"
            >摘要</el-button>
            <el-button
              type="danger" size="small" plain
              @click="deleteTask(row.id)"
            >删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Create dialog -->
    <el-dialog v-model="showCreateDialog" title="创建测试任务" width="500px">
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
            />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.notes" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createTask" :loading="creating">创建</el-button>
      </template>
    </el-dialog>

    <!-- Summary dialog -->
    <el-dialog v-model="showSummaryDialog" title="测试任务摘要" width="600px">
      <div v-if="summaryData" class="summary-content">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="任务名称">{{ summaryData.name }}</el-descriptions-item>
          <el-descriptions-item label="测试类型">{{ summaryData.task_type }}</el-descriptions-item>
          <el-descriptions-item label="持续时间">{{ formatDuration(summaryData.duration_seconds) }}</el-descriptions-item>
          <el-descriptions-item label="总告警数">{{ summaryData.alert_total }}</el-descriptions-item>
        </el-descriptions>

        <h4 style="margin: 16px 0 8px">按级别统计</h4>
        <el-row :gutter="12">
          <el-col v-for="(count, level) in summaryData.by_level" :key="level" :span="6">
            <div class="summary-stat">
              <div class="stat-val" :class="level">{{ count }}</div>
              <div class="stat-lbl">{{ { info: '信息', warning: '警告', error: '错误', critical: '严重' }[level] || level }}</div>
            </div>
          </el-col>
        </el-row>

        <h4 style="margin: 16px 0 8px">按观察点统计</h4>
        <el-table :data="observerStats" size="small">
          <el-table-column label="观察点" prop="name" />
          <el-table-column label="告警数" prop="count" width="100" />
        </el-table>

        <h4 v-if="summaryData.critical_events.length > 0" style="margin: 16px 0 8px; color: #f56c6c">
          关键事件 ({{ summaryData.critical_events.length }})
        </h4>
        <div v-for="(evt, idx) in summaryData.critical_events.slice(0, 20)" :key="idx" class="critical-item">
          <el-tag type="danger" size="small">{{ evt.level }}</el-tag>
          <span>{{ evt.observer }} — {{ evt.message }}</span>
          <span class="evt-time">{{ evt.timestamp }}</span>
        </div>
      </div>
      <el-empty v-else description="加载中..." />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, reactive, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import { getObserverName } from '@/utils/alertTranslator'

const loading = ref(false)
const creating = ref(false)
const tasks = ref([])
const showCreateDialog = ref(false)
const showSummaryDialog = ref(false)
const summaryData = ref(null)

const taskTypes = {
  normal_business: '正常业务',
  controller_poweroff: '控制器下电',
  card_poweroff: '接口卡下电',
  port_toggle: '端口开关',
  cable_pull: '线缆拔插',
  fault_injection: '系统故障注入',
  controller_upgrade: '控制器升级',
  custom: '自定义',
}

const allArrays = ref([])

const form = reactive({
  name: '',
  task_type: 'custom',
  array_ids: [],
  notes: '',
})

const observerStats = computed(() => {
  if (!summaryData.value?.by_observer) return []
  return Object.entries(summaryData.value.by_observer).map(([k, v]) => ({
    name: getObserverName(k),
    count: v,
  })).sort((a, b) => b.count - a.count)
})

async function loadTasks() {
  loading.value = true
  try {
    const res = await api.getTestTasks()
    tasks.value = res.data || []
  } finally {
    loading.value = false
  }
}

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
      notes: form.notes,
    })
    ElMessage.success('任务创建成功')
    showCreateDialog.value = false
    form.name = ''
    form.notes = ''
    form.array_ids = []
    await loadTasks()
  } finally {
    creating.value = false
  }
}

async function startTask(id) {
  try {
    await api.startTestTask(id)
    ElMessage.success('任务已开始')
    await loadTasks()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '启动失败')
  }
}

async function stopTask(id) {
  try {
    await api.stopTestTask(id)
    ElMessage.success('任务已结束')
    await loadTasks()
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

function formatDuration(sec) {
  if (!sec) return '--'
  if (sec < 60) return `${Math.round(sec)}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
}

function formatTime(ts) {
  if (!ts) return '--'
  return new Date(ts).toLocaleString('zh-CN')
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
  await Promise.all([loadTasks(), loadArrays()])
})
</script>

<style scoped>
.test-tasks { padding: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.muted { color: var(--el-text-color-placeholder); }

.summary-content { padding: 0 8px; }
.summary-stat { text-align: center; padding: 8px; background: var(--el-fill-color-light); border-radius: 6px; }
.stat-val { font-size: 24px; font-weight: bold; }
.stat-val.error, .stat-val.critical { color: #f56c6c; }
.stat-val.warning { color: #e6a23c; }
.stat-val.info { color: #909399; }
.stat-lbl { font-size: 12px; color: var(--el-text-color-secondary); }

.critical-item {
  display: flex; gap: 8px; align-items: center; padding: 6px 0;
  border-bottom: 1px solid var(--el-border-color-lighter); font-size: 13px;
}
.evt-time { margin-left: auto; font-size: 12px; color: var(--el-text-color-secondary); }
</style>
