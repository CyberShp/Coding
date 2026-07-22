<template>
  <div class="admin-monitors">
    <el-card>
      <template #header>
        <div class="page-header">
          <span>自定义监测</span>
          <el-button type="primary" size="small" @click="openCreateDrawer">
            <el-icon><Plus /></el-icon>
            创建自定义监测
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

      <!-- 可见性分区筛选（仅自定义监测有可见性） -->
      <div class="visibility-bar">
        <el-radio-group v-model="filterVisibility" size="small">
          <el-radio-button label="">全部自定义 ({{ customTotal }})</el-radio-button>
          <el-radio-button label="draft">我的草稿 ({{ visibilityGroups.draft.length }})</el-radio-button>
          <el-radio-button label="team">本组 ({{ visibilityGroups.team.length }})</el-radio-button>
          <el-radio-button label="global">全局库 ({{ visibilityGroups.global.length }})</el-radio-button>
        </el-radio-group>
        <span class="visibility-hint">全局库 / 本组的模板可直接“复用”部署到你关心的阵列</span>
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
        <el-table-column label="版本 / 可见性" width="150">
          <template #default="{ row }">
            <span v-if="row.isBuiltin" class="text-muted">内置</span>
            <template v-else>
              <code class="obs-code">v{{ row.version || 1 }}</code>
              <el-tag :type="VISIBILITY_TAG_TYPE[normalizeVisibility(row.visibility)]" size="small" effect="plain">
                {{ VISIBILITY_LABELS[normalizeVisibility(row.visibility)] }}
              </el-tag>
            </template>
          </template>
        </el-table-column>
        <el-table-column label="创建者" width="120">
          <template #default="{ row }">
            <span v-if="row.isBuiltin" class="text-muted">—</span>
            <span v-else class="creator-label">{{ row.created_by || '未知' }}</span>
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
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <!-- 内置观察点：配置 -->
            <el-button v-if="row.isBuiltin" size="small" text type="primary" @click.stop="openDetailDrawer(row)">
              配置
            </el-button>
            <template v-else>
              <!-- owner / admin: 编辑 / 删除 / 发布 -->
              <template v-if="canManage(row)">
                <el-button size="small" text type="primary" @click.stop="openStudio(row)">编辑</el-button>
                <el-button size="small" text type="danger" @click.stop="handleDelete(row)">删除</el-button>
                <el-button
                  v-for="action in publishTargets(row.visibility)"
                  :key="action.visibility"
                  size="small"
                  text
                  type="warning"
                  @click.stop="handlePublish(row, action)"
                >{{ action.label }}</el-button>
              </template>
              <!-- 非 owner：只读署名 -->
              <span v-else class="owner-note">由 {{ row.created_by || '未知' }} 创建</span>
              <!-- 任何登录用户都可复用部署 -->
              <el-button size="small" text type="success" @click.stop="openDeployDialog(row)">部署</el-button>
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

    <!-- 复用部署对话框：任何登录用户可将可见模板部署到阵列（版本固定） -->
    <el-dialog v-model="deployVisible" title="部署监测到阵列" width="480px" destroy-on-close>
      <template v-if="deployTarget">
        <div class="deploy-summary">
          <div><span class="deploy-key">监测</span>{{ deployTarget.name }}</div>
          <div>
            <span class="deploy-key">部署版本</span>
            <code class="obs-code">v{{ deployTarget.version || 1 }}</code>
            <span class="deploy-hint">（版本固定，作者后续改动不会自动影响此次部署）</span>
          </div>
          <div><span class="deploy-key">来源</span>{{ VISIBILITY_LABELS[normalizeVisibility(deployTarget.visibility)] }} · 由 {{ deployTarget.created_by || '未知' }} 创建</div>
        </div>
        <el-form label-width="90px" label-position="left" class="deploy-form">
          <el-form-item label="部署维度">
            <el-radio-group v-model="deployTargetType">
              <el-radio-button label="tag">按标签</el-radio-button>
              <el-radio-button label="array">按阵列</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="部署目标">
            <el-select
              v-model="deployTargetIds"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="选择目标"
              style="width: 100%"
            >
              <el-option
                v-for="item in deployOptions"
                :key="item.id"
                :label="deployOptionLabel(item)"
                :value="item.id"
              />
            </el-select>
          </el-form-item>
        </el-form>
      </template>
      <template #footer>
        <el-button @click="deployVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="deploying"
          :disabled="!deployTargetIds.length"
          @click="submitDeploy"
        >部署 v{{ deployTarget?.version || 1 }}</el-button>
      </template>
    </el-dialog>

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
import api, { extractError } from '@/api'
import CustomObserverStudio from '@/components/admin/CustomObserverStudio.vue'
import { useAuthStore } from '@/stores/auth'
import {
  VISIBILITY_LABELS,
  VISIBILITY_TAG_TYPE,
  normalizeVisibility,
  partitionByVisibility,
  canManageTemplate,
  publishTargets,
} from './monitorHelpers'

const authStore = useAuthStore()

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
const filterVisibility = ref('')
const searchText = ref('')
const studioVisible = ref(false)
const studioTemplate = ref(null)

// Deploy (reuse) dialog state
const deployVisible = ref(false)
const deployTarget = ref(null)
const deployTargetType = ref('tag')
const deployTargetIds = ref([])
const deploying = ref(false)
const arrays = ref([])
const tags = ref([])

const visibilityGroups = computed(() => partitionByVisibility(templates.value))
const customTotal = computed(() => templates.value.length)
const deployOptions = computed(() => (deployTargetType.value === 'tag' ? tags.value : arrays.value))

function canManage(row) {
  return canManageTemplate(row, authStore.currentUser, authStore.isAdmin)
}

function deployOptionLabel(item) {
  return item.array_id ? `${item.name} (${item.array_id})` : item.name
}

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
  // Visibility filter applies only to custom templates; when set, builtin rows
  // are hidden so the zone shows exactly its own templates.
  if (filterVisibility.value) {
    rows = rows.filter(r => !r.isBuiltin && normalizeVisibility(r.visibility) === filterVisibility.value)
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

async function handlePublish(row, action) {
  try {
    await ElMessageBox.confirm(
      `确定将「${row.name}」${action.label}？发布后该范围内用户均可见并复用。`,
      '确认发布',
      { type: 'warning' },
    )
    await api.publishMonitorTemplate(row.id, action.visibility)
    ElMessage.success('已发布')
    loadTemplates()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('发布失败: ' + extractError(e))
    }
  }
}

// ── Deploy (reuse) ──

function openDeployDialog(row) {
  deployTarget.value = row
  deployTargetType.value = 'tag'
  deployTargetIds.value = []
  deployVisible.value = true
  if (!arrays.value.length || !tags.value.length) loadDeployTargets()
}

async function loadDeployTargets() {
  try {
    const [arrayRes, tagRes] = await Promise.all([api.getArrays(), api.getTags()])
    arrays.value = arrayRes.data || []
    tags.value = tagRes.data || []
  } catch (e) {
    ElMessage.error('加载部署目标失败: ' + extractError(e))
  }
}

async function submitDeploy() {
  if (!deployTarget.value || !deployTargetIds.value.length) return
  deploying.value = true
  try {
    await api.deployMonitorTemplates([deployTarget.value.id], deployTargetType.value, deployTargetIds.value)
    ElMessage.success(`已部署 v${deployTarget.value.version || 1}，状态以 Agent 加载回执为准`)
    deployVisible.value = false
  } catch (e) {
    ElMessage.error('部署失败: ' + extractError(e))
  } finally {
    deploying.value = false
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
  margin-bottom: 12px;
  gap: 12px;
}
.visibility-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.visibility-hint {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}
.creator-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.owner-note {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
  margin-right: 8px;
}
.deploy-summary {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 12px 14px;
  margin-bottom: 16px;
  font-size: 13px;
  line-height: 1.9;
}
.deploy-key {
  display: inline-block;
  width: 68px;
  color: var(--el-text-color-secondary);
}
.deploy-hint {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
  margin-left: 6px;
}
.deploy-form {
  margin-top: 4px;
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
