<template>
  <div class="admin-monitors">
    <el-card>
      <template #header>
        <div class="page-header">
          <span>观察点管理</span>
          <el-button type="primary" size="small" @click="openCreateDrawer">
            <el-icon><Plus /></el-icon>
            创建自定义观察点
          </el-button>
        </div>
      </template>

      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-radio-group v-model="filterCategory" size="small">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button label="port">端口级</el-radio-button>
          <el-radio-button label="card">卡件级</el-radio-button>
          <el-radio-button label="system">系统级</el-radio-button>
          <el-radio-button label="custom">自定义</el-radio-button>
        </el-radio-group>
        <el-input
          v-model="searchText"
          placeholder="搜索名称 / 观察点名"
          clearable
          size="small"
          style="width: 220px"
        />
      </div>

      <!-- 统一列表 -->
      <el-table
        :data="filteredRows"
        v-loading="loading"
        row-key="rowKey"
        :row-class-name="rowClassName"
        @row-click="handleRowClick"
        stripe
      >
        <el-table-column label="名称" min-width="140">
          <template #default="{ row }">
            <span class="obs-label">{{ row.label }}</span>
            <code v-if="row.isBuiltin" class="obs-code">{{ row.name }}</code>
          </template>
        </el-table-column>
        <el-table-column label="分类" width="90">
          <template #default="{ row }">
            <el-tag :type="CATEGORY_TAG_TYPE[row.category]" size="small">{{ CATEGORY_LABELS[row.category] || row.category }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag :type="row.isBuiltin ? '' : 'warning'" size="small" effect="plain">{{ row.isBuiltin ? '内置' : '自定义' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="级别" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.alert_level" :type="getLevelType(row.alert_level)" size="small">{{ LEVEL_LABELS[row.alert_level] || row.alert_level }}</el-tag>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="间隔" width="75">
          <template #default="{ row }">{{ row.interval }}s</template>
        </el-table-column>
        <el-table-column label="版本 / 范围" width="125">
          <template #default="{ row }">
            <span v-if="row.isBuiltin" class="text-muted">内置</span>
            <template v-else>
              <code class="obs-code">v{{ row.version || 1 }}</code>
              <span class="scope-label">{{ { private: '个人', team: '团队', global: '全局' }[row.visibility] || '团队' }}</span>
            </template>
          </template>
        </el-table-column>
        <el-table-column label="开关" width="70">
          <template #default="{ row }">
            <el-switch
              v-model="row.enabled"
              size="small"
              @click.stop
              @change="(val) => handleToggle(row, val)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click.stop="openDetailDrawer(row)">
              {{ row.isBuiltin ? '配置' : '编辑' }}
            </el-button>
            <template v-if="!row.isBuiltin">
              <el-button size="small" text type="danger" @click.stop="handleDelete(row)">删除</el-button>
              <el-button size="small" text type="success" @click.stop="openStudio(row)">运行状态</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <CustomObserverStudio
      v-model="studioVisible"
      :template="studioTemplate"
      @saved="handleStudioSaved"
    />

    <!-- 详情 / 编辑 抽屉 -->
    <el-drawer
      v-model="drawerVisible"
      :title="drawerTitle"
      size="480px"
      destroy-on-close
    >
      <!-- 内置观察点表单 -->
      <template>
        <el-form
          :model="drawerForm"
          label-width="110px"
          label-position="left"
          class="drawer-form"
        >
          <el-divider content-position="left">基本信息</el-divider>
          <el-form-item label="名称">
            <span>{{ drawerForm.name }}</span>
          </el-form-item>
          <el-form-item label="观察点名">
            <code>{{ drawerForm.obs_name }}</code>
          </el-form-item>
          <el-form-item label="描述">
            <span class="text-secondary">{{ drawerForm.description }}</span>
          </el-form-item>
          <el-form-item label="分类">
            <el-tag :type="CATEGORY_TAG_TYPE[drawerForm.category]" size="small">
              {{ CATEGORY_LABELS[drawerForm.category] }}
            </el-tag>
          </el-form-item>

          <el-divider content-position="left">可调参数</el-divider>
          <el-form-item label="开关">
            <el-switch v-model="drawerForm.enabled" />
            <span class="form-hint">关闭后 Agent 将跳过此观察点</span>
          </el-form-item>
          <el-form-item label="检查间隔">
            <el-input-number v-model="drawerForm.interval" :min="5" :max="3600" />
            <span class="form-unit">秒</span>
          </el-form-item>
        </el-form>
        <div class="drawer-tip">
          修改后需重新下发 Agent 配置才能生效
        </div>
      </template>

      <template #footer>
        <el-button @click="drawerVisible = false">取消</el-button>
        <el-button type="primary" @click="submitBuiltinConfig">保存配置</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api from '@/api'
import CustomObserverStudio from '@/components/admin/CustomObserverStudio.vue'

const CATEGORY_LABELS = { port: '端口级', card: '卡件级', system: '系统级', custom: '自定义' }
const CATEGORY_TAG_TYPE = { port: '', card: 'warning', system: 'success', custom: 'info' }
const LEVEL_LABELS = { info: '信息', warning: '警告', error: '错误', critical: '严重' }

const BUILTIN_OBSERVERS = [
  { name: 'error_code', label: '端口误码', category: 'port', description: '监测 ethtool/sysfs 端口统计计数器和 PCIe AER 误码增量', interval: 30, alert_level: 'warning' },
  { name: 'link_status', label: '链路状态', category: 'port', description: '端口 carrier/operstate 监测，检测 link down/up 及速率变化', interval: 5, alert_level: 'warning' },
  { name: 'port_fec', label: 'FEC 模式', category: 'port', description: '端口 FEC 前向纠错模式变化检测 (ethtool --show-fec)', interval: 30, alert_level: 'warning' },
  { name: 'port_speed', label: '端口速率', category: 'port', description: '端口协商速率变化检测', interval: 30, alert_level: 'warning' },
  { name: 'port_traffic', label: '端口流量', category: 'port', description: '端口 TX/RX 流量采集（仅采集，不告警）', interval: 30, alert_level: null },
  { name: 'port_error_code', label: '端口误码(anytest)', category: 'port', description: 'anytest portgeterr 专用端口误码监测 (0x2/0x11 端口)', interval: 30, alert_level: 'warning' },
  { name: 'sfp_monitor', label: '光模块监测', category: 'port', description: 'anytest sfpallinfo 光模块温度、健康状态、速率异常检测', interval: 60, alert_level: 'warning' },
  { name: 'card_recovery', label: '卡修复', category: 'card', description: 'messages 日志中 "recover chiperr" 事件检测', interval: 30, alert_level: 'warning' },
  { name: 'card_info', label: '卡件信息', category: 'card', description: '卡件 RunningState、HealthState、Model 异常检测', interval: 60, alert_level: 'warning' },
  { name: 'pcie_bandwidth', label: 'PCIe 带宽', category: 'card', description: 'PCIe 链路宽度/速率降级检测与恢复', interval: 60, alert_level: 'warning' },
  { name: 'alarm_type', label: '告警事件', category: 'system', description: 'system_alarm.txt 中 AlarmType 0/1/2 事件、故障、恢复', interval: 30, alert_level: 'warning' },
  { name: 'cpu_usage', label: 'CPU 使用率', category: 'system', description: '/proc/stat CPU0 利用率持续超阈值告警', interval: 60, alert_level: 'warning' },
  { name: 'memory_leak', label: '内存泄漏', category: 'system', description: 'free -m 连续 N 次内存增长则判定疑似泄漏', interval: 60, alert_level: 'warning' },
  { name: 'process_crash', label: '进程崩溃', category: 'system', description: '日志中 segfault、core dump、OOM kill 事件', interval: 30, alert_level: 'error' },
  { name: 'process_restart', label: '进程重拉', category: 'system', description: '进程 -v 参数变化检测（重拉/重启）', interval: 30, alert_level: 'warning' },
  { name: 'io_timeout', label: 'IO 超时', category: 'system', description: '日志中 I/O error、scsi error、timeout 等异常', interval: 30, alert_level: 'error' },
  { name: 'abnormal_reset', label: '异常复位', category: 'system', description: 'log_reset.txt 中异常复位事件检测', interval: 120, alert_level: 'warning' },
  { name: 'start_work', label: '开工状态检查', category: 'system', description: '执行 anytest sysgetstartwork；未开工时仅保留该检查并跳过其他观察点', interval: 180, alert_level: 'warning' },
  { name: 'cmd_response', label: '命令响应', category: 'system', description: '监测命令执行耗时，超时告警', interval: 60, alert_level: 'warning' },
  { name: 'sig_monitor', label: '信号监测', category: 'system', description: 'messages 中异常信号检测（白名单外）', interval: 30, alert_level: 'warning' },
  { name: 'sensitive_info', label: '敏感信息', category: 'system', description: '日志中明文密码、NQN/IQN 等敏感信息检测', interval: 120, alert_level: 'info' },
  { name: 'custom_commands', label: '内部命令', category: 'system', description: '执行配置的内部命令，按条件触发告警', interval: 60, alert_level: 'warning' },
  { name: 'controller_state', label: '控制器状态', category: 'system', description: '控制器 online/offline/degraded 状态变化检测', interval: 60, alert_level: 'error' },
  { name: 'disk_state', label: '磁盘状态', category: 'system', description: '磁盘 online/offline/rebuilding 等状态变化检测', interval: 60, alert_level: 'error' },
]

const loading = ref(false)
const templates = ref([])
const observerOverrides = ref({})
const filterCategory = ref('')
const searchText = ref('')
const studioVisible = ref(false)
const studioTemplate = ref(null)

// Drawer state
const drawerVisible = ref(false)
const drawerForm = reactive({
  name: '', obs_name: '', description: '', category: 'system', enabled: true, interval: 60,
})

const drawerTitle = computed(() => `配置: ${drawerForm.name}`)

const allRows = computed(() => {
  const ov = observerOverrides.value
  const builtinRows = BUILTIN_OBSERVERS.map(obs => {
    const override = ov[obs.name]
    return {
      ...obs,
      rowKey: `builtin_${obs.name}`,
      label: obs.label,
      isBuiltin: true,
      enabled: override ? override.enabled : true,
      interval: override?.interval ?? obs.interval,
    }
  })
  const customRows = templates.value.map(t => ({
    ...t,
    rowKey: `custom_${t.id}`,
    label: t.name,
    isBuiltin: false,
    enabled: t.is_enabled !== false,
    alert_level: t.alert_level,
  }))
  return [...builtinRows, ...customRows]
})

const filteredRows = computed(() => {
  let rows = allRows.value
  if (filterCategory.value) {
    if (filterCategory.value === 'custom') {
      rows = rows.filter(r => !r.isBuiltin)
    } else {
      rows = rows.filter(r => r.category === filterCategory.value)
    }
  }
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    rows = rows.filter(r =>
      (r.label || '').toLowerCase().includes(q) ||
      (r.name || '').toLowerCase().includes(q)
    )
  }
  return rows
})

function getLevelType(level) {
  return { info: 'info', warning: 'warning', error: 'danger', critical: 'danger' }[level] || 'info'
}

function rowClassName({ row }) {
  if (!row.enabled) return 'row-disabled'
  return ''
}

function handleRowClick(row) {
  openDetailDrawer(row)
}

// ── Drawer ──

function openCreateDrawer() {
  openStudio(null)
}

function openStudio(template) {
  studioTemplate.value = template ? { ...template } : null
  studioVisible.value = true
}

function handleStudioSaved() {
  loadTemplates()
}

function openDetailDrawer(row) {
  if (!row.isBuiltin) {
    openStudio(row)
    return
  }
  const override = observerOverrides.value[row.name]
  Object.assign(drawerForm, {
    name: row.label,
    obs_name: row.name,
    description: row.description || '',
    category: row.category,
    enabled: override ? override.enabled : true,
    interval: override?.interval ?? row.interval,
  })
  drawerVisible.value = true
}

async function submitBuiltinConfig() {
  const obsName = drawerForm.obs_name
  try {
    await api.updateObserverConfig(obsName, {
      enabled: drawerForm.enabled,
      interval: drawerForm.interval,
    })
    observerOverrides.value[obsName] = {
      enabled: drawerForm.enabled,
      interval: drawerForm.interval,
    }
    ElMessage.success('配置已保存（下次下发 Agent 时生效）')
    drawerVisible.value = false
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function handleToggle(row, val) {
  if (row.isBuiltin) {
    try {
      await api.updateObserverConfig(row.name, { enabled: val })
      observerOverrides.value[row.name] = {
        ...observerOverrides.value[row.name],
        enabled: val,
      }
    } catch (e) {
      row.enabled = !val
      ElMessage.error('切换失败: ' + (e.response?.data?.detail || e.message))
    }
  } else {
    try {
      await api.updateMonitorTemplate(row.id, { is_enabled: val })
    } catch (e) {
      row.enabled = !val
      ElMessage.error('切换失败: ' + (e.response?.data?.detail || e.message))
    }
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(`确定删除模板「${row.label}」？`, '确认删除', { type: 'warning' })
    await api.deleteMonitorTemplate(row.id)
    ElMessage.success('已删除')
    loadTemplates()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
    }
  }
}

// ── Data loading ──

async function loadTemplates() {
  loading.value = true
  try {
    const res = await api.getMonitorTemplates()
    templates.value = res.data || []
  } catch (e) {
    ElMessage.error('加载模板失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

async function loadObserverOverrides() {
  try {
    const res = await api.getObserverConfigs()
    const map = {}
    for (const item of (res.data || [])) {
      map[item.observer_name] = {
        enabled: item.enabled,
        interval: item.interval,
        params: item.params || {},
      }
    }
    observerOverrides.value = map
  } catch {
    // Admin not logged in or API not available — use defaults
  }
}

onMounted(() => {
  loadTemplates()
  loadObserverOverrides()
})
</script>

<style scoped>
.admin-monitors {
  padding: 20px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  gap: 12px;
}
.obs-label {
  font-weight: 500;
}
.obs-code {
  display: inline-block;
  margin-left: 6px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  background: var(--el-fill-color-light);
  padding: 0 5px;
  border-radius: 3px;
}
.scope-label {
  margin-left: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.text-muted {
  color: var(--el-text-color-placeholder);
}
.text-secondary {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.5;
}
:deep(.row-disabled) {
  opacity: 0.5;
}
:deep(.el-table__row) {
  cursor: pointer;
}
.drawer-form {
  padding: 0 8px;
}
.form-unit {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.form-hint {
  margin-left: 12px;
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}
.drawer-tip {
  margin: 16px 16px 0;
  padding: 10px 14px;
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.5;
}
</style>
