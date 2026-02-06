<template>
  <div class="scheduled-tasks">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>定时任务</span>
          <el-button type="primary" @click="showCreateDialog">
            <el-icon><Plus /></el-icon>
            创建任务
          </el-button>
        </div>
      </template>

      <el-table :data="tasks" v-loading="loading" stripe>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="任务名称" width="180" />
        <el-table-column prop="cron_expr" label="Cron 表达式" width="120" />
        <el-table-column label="执行阵列" width="150">
          <template #default="{ row }">
            {{ row.array_ids?.length ? `${row.array_ids.length} 个阵列` : '所有已连接' }}
          </template>
        </el-table-column>
        <el-table-column label="上次执行" width="170">
          <template #default="{ row }">
            {{ formatTime(row.last_run_at) }}
          </template>
        </el-table-column>
        <el-table-column label="下次执行" width="170">
          <template #default="{ row }">
            {{ formatTime(row.next_run_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220">
          <template #default="{ row }">
            <el-button-group>
              <el-button size="small" @click="showEditDialog(row)">编辑</el-button>
              <el-button size="small" type="primary" @click="runNow(row)" :loading="runningId === row.id">
                执行
              </el-button>
              <el-button size="small" @click="viewResults(row)">历史</el-button>
              <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
            </el-button-group>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Recent Results -->
    <el-card class="results-card">
      <template #header>
        <span>最近执行记录</span>
      </template>

      <el-table :data="recentResults" stripe max-height="400">
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="task_name" label="任务" width="150" />
        <el-table-column label="执行时间" width="170">
          <template #default="{ row }">
            {{ formatTime(row.executed_at) }}
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">
            {{ getDuration(row) }}
          </template>
        </el-table-column>
        <el-table-column label="输出" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.output" class="output-preview">{{ row.output.slice(0, 100) }}</span>
            <span v-else-if="row.error" class="error-preview">{{ row.error }}</span>
            <span v-else class="no-output">-</span>
          </template>
        </el-table-column>
        <el-table-column width="60">
          <template #default="{ row }">
            <el-button size="small" link @click="showResultDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Create/Edit Dialog -->
    <el-dialog v-model="dialogVisible" :title="editingTask ? '编辑任务' : '创建任务'" width="600px">
      <el-form :model="taskForm" :rules="rules" ref="formRef" label-width="100px">
        <el-form-item label="任务名称" prop="name">
          <el-input v-model="taskForm.name" placeholder="任务名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="taskForm.description" type="textarea" rows="2" placeholder="任务描述（可选）" />
        </el-form-item>
        <el-form-item label="Cron 表达式" prop="cron_expr">
          <el-input v-model="taskForm.cron_expr" placeholder="分 时 日 月 周 (如: */5 * * * *)" />
          <div class="cron-help">
            常用: <el-tag size="small" @click="taskForm.cron_expr = '*/5 * * * *'">每5分钟</el-tag>
            <el-tag size="small" @click="taskForm.cron_expr = '0 * * * *'">每小时</el-tag>
            <el-tag size="small" @click="taskForm.cron_expr = '0 0 * * *'">每天0点</el-tag>
            <el-tag size="small" @click="taskForm.cron_expr = '0 8 * * 1-5'">工作日8点</el-tag>
          </div>
        </el-form-item>
        <el-form-item label="执行命令" prop="command">
          <el-input 
            v-model="taskForm.command" 
            type="textarea" 
            rows="3" 
            placeholder="在远程阵列上执行的 Shell 命令"
          />
        </el-form-item>
        <el-form-item label="目标阵列">
          <el-select v-model="taskForm.array_ids" multiple placeholder="留空则在所有已连接阵列执行">
            <el-option
              v-for="array in arrays"
              :key="array.array_id"
              :label="array.name"
              :value="array.array_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="taskForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- Result Detail Dialog -->
    <el-dialog v-model="resultDialogVisible" title="执行详情" width="700px">
      <el-descriptions :column="2" border v-if="selectedResult">
        <el-descriptions-item label="任务">{{ selectedResult.task_name }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="getStatusType(selectedResult.status)">
            {{ getStatusText(selectedResult.status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="开始时间">{{ formatTime(selectedResult.started_at) }}</el-descriptions-item>
        <el-descriptions-item label="结束时间">{{ formatTime(selectedResult.finished_at) }}</el-descriptions-item>
      </el-descriptions>

      <div v-if="selectedResult?.output" class="result-section">
        <h4>输出</h4>
        <pre class="result-output">{{ selectedResult.output }}</pre>
      </div>

      <div v-if="selectedResult?.error" class="result-section">
        <h4>错误</h4>
        <pre class="result-error">{{ selectedResult.error }}</pre>
      </div>
    </el-dialog>

    <!-- Task Results Dialog -->
    <el-dialog v-model="historyDialogVisible" title="执行历史" width="800px">
      <el-table :data="taskResults" stripe max-height="500">
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="执行时间" width="170">
          <template #default="{ row }">
            {{ formatTime(row.executed_at) }}
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">
            {{ getDuration(row) }}
          </template>
        </el-table-column>
        <el-table-column label="输出/错误" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.output">{{ row.output.slice(0, 100) }}</span>
            <span v-else-if="row.error" class="error-preview">{{ row.error }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column width="60">
          <template #default="{ row }">
            <el-button size="small" link @click="showResultDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api from '@/api'

// State
const loading = ref(false)
const saving = ref(false)
const tasks = ref([])
const arrays = ref([])
const recentResults = ref([])
const taskResults = ref([])
const dialogVisible = ref(false)
const resultDialogVisible = ref(false)
const historyDialogVisible = ref(false)
const editingTask = ref(null)
const selectedResult = ref(null)
const runningId = ref(null)
const formRef = ref(null)

const taskForm = reactive({
  name: '',
  description: '',
  cron_expr: '0 * * * *',
  command: '',
  array_ids: [],
  enabled: true,
})

const rules = {
  name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
  cron_expr: [{ required: true, message: '请输入 Cron 表达式', trigger: 'blur' }],
  command: [{ required: true, message: '请输入执行命令', trigger: 'blur' }],
}

// Methods
function formatTime(time) {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}

function getStatusType(status) {
  const types = {
    success: 'success',
    partial: 'warning',
    failed: 'danger',
    running: 'primary',
    pending: 'info',
  }
  return types[status] || 'info'
}

function getStatusText(status) {
  const texts = {
    success: '成功',
    partial: '部分成功',
    failed: '失败',
    running: '运行中',
    pending: '等待',
  }
  return texts[status] || status
}

function getDuration(result) {
  if (!result.started_at || !result.finished_at) return '-'
  const start = new Date(result.started_at)
  const end = new Date(result.finished_at)
  const ms = end - start
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
}

async function loadTasks() {
  loading.value = true
  try {
    const res = await api.getTasks()
    tasks.value = res.data
  } catch (e) {
    ElMessage.error('加载任务失败')
  } finally {
    loading.value = false
  }
}

async function loadArrays() {
  try {
    const res = await api.getArrays()
    arrays.value = res.data
  } catch (e) {
    console.error('Failed to load arrays:', e)
  }
}

async function loadRecentResults() {
  try {
    const res = await api.getRecentTaskResults(20)
    recentResults.value = res.data
  } catch (e) {
    console.error('Failed to load recent results:', e)
  }
}

function showCreateDialog() {
  editingTask.value = null
  Object.assign(taskForm, {
    name: '',
    description: '',
    cron_expr: '0 * * * *',
    command: '',
    array_ids: [],
    enabled: true,
  })
  dialogVisible.value = true
}

function showEditDialog(task) {
  editingTask.value = task
  Object.assign(taskForm, {
    name: task.name,
    description: task.description || '',
    cron_expr: task.cron_expr,
    command: task.command || '',
    array_ids: task.array_ids || [],
    enabled: task.enabled,
  })
  dialogVisible.value = true
}

async function handleSave() {
  await formRef.value.validate()
  
  saving.value = true
  try {
    if (editingTask.value) {
      await api.updateTask(editingTask.value.id, taskForm)
      ElMessage.success('任务已更新')
    } else {
      await api.createTask(taskForm)
      ElMessage.success('任务已创建')
    }
    dialogVisible.value = false
    await loadTasks()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function handleDelete(task) {
  await ElMessageBox.confirm(`确定要删除任务 "${task.name}" 吗？`, '确认删除', { type: 'warning' })
  
  try {
    await api.deleteTask(task.id)
    ElMessage.success('任务已删除')
    await loadTasks()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

async function runNow(task) {
  runningId.value = task.id
  try {
    await api.runTask(task.id)
    ElMessage.success('任务已执行')
    await Promise.all([loadTasks(), loadRecentResults()])
  } catch (e) {
    ElMessage.error('执行失败')
  } finally {
    runningId.value = null
  }
}

async function viewResults(task) {
  try {
    const res = await api.getTaskResults(task.id, 50)
    taskResults.value = res.data
    historyDialogVisible.value = true
  } catch (e) {
    ElMessage.error('加载历史失败')
  }
}

function showResultDetail(result) {
  selectedResult.value = result
  resultDialogVisible.value = true
}

// Lifecycle
onMounted(async () => {
  await Promise.all([loadTasks(), loadArrays(), loadRecentResults()])
})
</script>

<style scoped>
.scheduled-tasks {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.results-card {
  margin-top: 20px;
}

.cron-help {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.cron-help .el-tag {
  cursor: pointer;
}

.cron-help .el-tag:hover {
  background-color: #409eff;
  color: white;
}

.output-preview {
  color: #67c23a;
}

.error-preview {
  color: #f56c6c;
}

.no-output {
  color: #909399;
}

.result-section {
  margin-top: 20px;
}

.result-section h4 {
  margin-bottom: 10px;
  color: #303133;
}

.result-output {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 15px;
  border-radius: 4px;
  max-height: 300px;
  overflow: auto;
  font-family: monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}

.result-error {
  background: #fef0f0;
  color: #f56c6c;
  padding: 15px;
  border-radius: 4px;
  max-height: 200px;
  overflow: auto;
  font-family: monospace;
  font-size: 12px;
  white-space: pre-wrap;
}
</style>
