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
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createTask" :loading="creating">创建</el-button>
      </template>
    </el-dialog>

    <!-- Summary dialog -->
    <el-dialog v-model="showSummaryDialog" title="测试任务摘要" width="700px">
      <div v-if="summaryData" class="summary-content">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="任务名称">{{ summaryData.name }}</el-descriptions-item>
          <el-descriptions-item label="测试类型">{{ summaryData.task_type }}</el-descriptions-item>
          <el-descriptions-item label="持续时间">{{ formatDuration(summaryData.duration_seconds) }}</el-descriptions-item>
          <el-descriptions-item label="总告警数">{{ summaryData.alert_total }}</el-descriptions-item>
        </el-descriptions>

        <!-- Expected vs Unexpected breakdown -->
        <div class="expectation-section" v-if="summaryData.alert_total > 0">
          <h4>告警预期分析</h4>
          <el-row :gutter="16">
            <el-col :span="8">
              <div class="summary-stat expected">
                <div class="stat-val">{{ summaryData.expected_count || 0 }}</div>
                <div class="stat-lbl">预期内告警</div>
                <div class="stat-hint">可忽略</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="summary-stat unexpected">
                <div class="stat-val">{{ summaryData.unexpected_count || (summaryData.alert_total - (summaryData.expected_count || 0)) }}</div>
                <div class="stat-lbl">非预期告警</div>
                <div class="stat-hint">需关注</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="summary-stat unknown">
                <div class="stat-val">{{ summaryData.unknown_count || 0 }}</div>
                <div class="stat-lbl">未分类</div>
                <div class="stat-hint">无匹配规则</div>
              </div>
            </el-col>
          </el-row>
          <el-alert type="info" :closable="false" style="margin-top: 12px">
            <template #title>
              <span>💡 预期告警由"告警预期规则"自动判定，可在<el-link type="primary" @click="showRulesConfig = true">规则配置</el-link>中调整</span>
            </template>
          </el-alert>
        </div>

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

    <!-- Alert Rules Config Dialog -->
    <el-dialog v-model="showRulesConfig" title="告警预期规则配置" width="800px">
      <div class="rules-config">
        <div class="rules-toolbar">
          <el-button type="primary" size="small" @click="showAddRuleDialog = true">
            <el-icon><Plus /></el-icon> 添加规则
          </el-button>
          <el-button size="small" @click="loadRules">刷新</el-button>
          <el-button size="small" @click="handleInitBuiltin">初始化内置规则</el-button>
        </div>

        <el-table :data="alertRules" v-loading="loadingRules" size="small">
          <el-table-column label="规则名称" prop="name" min-width="140" />
          <el-table-column label="适用任务类型" width="180">
            <template #default="{ row }">
              <el-tag v-for="t in (row.task_types || []).slice(0, 3)" :key="t" size="small" style="margin: 2px">
                {{ taskTypes[t] || t }}
              </el-tag>
              <span v-if="(row.task_types || []).length > 3">+{{ row.task_types.length - 3 }}</span>
            </template>
          </el-table-column>
          <el-table-column label="观察点" width="140">
            <template #default="{ row }">
              {{ (row.observer_patterns || []).join(', ') || '全部' }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-switch v-model="row.is_enabled" size="small" @change="handleToggleRule(row)" />
            </template>
          </el-table-column>
          <el-table-column label="内置" width="60">
            <template #default="{ row }">
              <el-tag v-if="row.is_builtin" type="info" size="small">内置</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button
                v-if="!row.is_builtin"
                type="danger"
                size="small"
                link
                @click="handleDeleteRule(row)"
              >删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>

    <!-- Add Rule Dialog -->
    <el-dialog v-model="showAddRuleDialog" title="添加告警预期规则" width="500px">
      <el-form :model="ruleForm" label-width="100px">
        <el-form-item label="规则名称" required>
          <el-input v-model="ruleForm.name" placeholder="如: 端口down期间链路状态变化" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="ruleForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="适用任务类型">
          <el-select v-model="ruleForm.task_types" multiple style="width: 100%">
            <el-option v-for="(label, key) in taskTypes" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="观察点">
          <el-select v-model="ruleForm.observer_patterns" multiple allow-create filterable style="width: 100%">
            <el-option v-for="o in commonObservers" :key="o" :label="o" :value="o" />
          </el-select>
        </el-form-item>
        <el-form-item label="告警级别">
          <el-checkbox-group v-model="ruleForm.level_patterns">
            <el-checkbox value="info">信息</el-checkbox>
            <el-checkbox value="warning">警告</el-checkbox>
            <el-checkbox value="error">错误</el-checkbox>
            <el-checkbox value="critical">严重</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddRuleDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreateRule" :loading="creatingRule">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, reactive, onMounted } from 'vue'
import { Plus, Lock, Refresh, Warning } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import { getObserverName } from '@/utils/alertTranslator'

const loading = ref(false)
const creating = ref(false)
const loadingLocks = ref(false)
const loadingRules = ref(false)
const creatingRule = ref(false)
const tasks = ref([])
const activeLocks = ref([])
const alertRules = ref([])
const showCreateDialog = ref(false)
const showSummaryDialog = ref(false)
const showRulesConfig = ref(false)
const showAddRuleDialog = ref(false)
const summaryData = ref(null)

const commonObservers = [
  'link_status', 'port_speed', 'alarm_type', 'error_code',
  'controller_state', 'card_info', 'card_recovery', 'disk_state',
  'cpu_usage', 'memory_leak', 'process_crash',
]

const ruleForm = reactive({
  name: '',
  description: '',
  task_types: [],
  observer_patterns: [],
  level_patterns: [],
  message_patterns: [],
})

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

const form = reactive({
  name: '',
  task_type: 'custom',
  array_ids: [],
  notes: '',
})

const lockedArrayIds = computed(() => activeLocks.value.map(l => l.array_id))

function isArrayLocked(arrayId) {
  return lockedArrayIds.value.includes(arrayId)
}

const lockedArraysSelected = computed(() => {
  return form.array_ids.filter(id => isArrayLocked(id))
})

const observerStats = computed(() => {
  if (!summaryData.value?.by_observer) return []
  return Object.entries(summaryData.value.by_observer).map(([k, v]) => ({
    name: getObserverName(k),
    count: v,
  })).sort((a, b) => b.count - a.count)
})

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

async function loadRules() {
  loadingRules.value = true
  try {
    const res = await api.getAlertRules()
    alertRules.value = res.data || []
  } catch (e) {
    console.error('Failed to load rules:', e)
  } finally {
    loadingRules.value = false
  }
}

async function handleToggleRule(rule) {
  try {
    await api.toggleAlertRule(rule.id)
  } catch (e) {
    rule.is_enabled = !rule.is_enabled
    ElMessage.error('切换规则状态失败')
  }
}

async function handleDeleteRule(rule) {
  try {
    await ElMessageBox.confirm(`确定要删除规则 "${rule.name}" 吗？`, '提示', { type: 'warning' })
    await api.deleteAlertRule(rule.id)
    ElMessage.success('规则已删除')
    await loadRules()
  } catch (_) {}
}

async function handleInitBuiltin() {
  try {
    await api.initBuiltinRules()
    ElMessage.success('内置规则已初始化')
    await loadRules()
  } catch (e) {
    ElMessage.error('初始化失败')
  }
}

async function handleCreateRule() {
  if (!ruleForm.name.trim()) {
    ElMessage.warning('请输入规则名称')
    return
  }
  creatingRule.value = true
  try {
    await api.createAlertRule({
      name: ruleForm.name,
      description: ruleForm.description,
      task_types: ruleForm.task_types,
      observer_patterns: ruleForm.observer_patterns,
      level_patterns: ruleForm.level_patterns,
      message_patterns: ruleForm.message_patterns,
    })
    ElMessage.success('规则创建成功')
    showAddRuleDialog.value = false
    Object.assign(ruleForm, { name: '', description: '', task_types: [], observer_patterns: [], level_patterns: [], message_patterns: [] })
    await loadRules()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally {
    creatingRule.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadTasks(), loadArrays(), loadLocks(), loadRules()])
})
</script>

<style scoped>
.test-tasks { padding: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; gap: 10px; }
.muted { color: var(--el-text-color-placeholder); }

.locks-banner { margin-bottom: 16px; }
.locks-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }

.lock-warning {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
  font-size: 12px;
  color: #e6a23c;
}

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

.expectation-section {
  margin: 16px 0;
  padding: 16px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
}
.expectation-section h4 { margin: 0 0 12px; font-size: 14px; }

.summary-stat.expected { background: #e8f5e9; }
.summary-stat.expected .stat-val { color: #4caf50; }
.summary-stat.unexpected { background: #ffebee; }
.summary-stat.unexpected .stat-val { color: #f44336; }
.summary-stat.unknown { background: #fff3e0; }
.summary-stat.unknown .stat-val { color: #ff9800; }
.stat-hint { font-size: 11px; color: var(--el-text-color-secondary); margin-top: 4px; }

.rules-config { min-height: 300px; }
.rules-toolbar { display: flex; gap: 10px; margin-bottom: 16px; }
</style>
