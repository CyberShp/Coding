<template>
  <!-- Zone 5: Observer Status + Phase 3 Template Builder -->
  <el-card class="zone-card zone-observer-status" shadow="hover">
    <template #header>
      <div class="card-header">
        <span class="zone-title">观察点状态</span>
        <el-tag type="info" size="small">{{ observerList.length }} 个观察点</el-tag>
      </div>
    </template>

    <!-- Observer status table -->
    <el-table :data="observerList" stripe size="small" class="observer-table" empty-text="暂无观察点数据">
      <el-table-column prop="name" label="名称" min-width="140">
        <template #default="{ row }">
          <span class="observer-name">{{ getObserverName(row.name) }}</span>
          <span class="observer-key">{{ row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column label="最近执行时间" min-width="160">
        <template #default="{ row }">
          {{ row.last_run ? formatDateTime(row.last_run) : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="最近成功时间" min-width="160">
        <template #default="{ row }">
          {{ row.last_success ? formatDateTime(row.last_success) : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="最近失败原因" min-width="200">
        <template #default="{ row }">
          <span v-if="row.last_error" class="observer-error">{{ row.last_error }}</span>
          <span v-else class="observer-ok">-</span>
        </template>
      </el-table-column>
      <el-table-column label="平均耗时" min-width="100" align="center">
        <template #default="{ row }">
          {{ row.avg_duration != null ? `${row.avg_duration.toFixed(1)}s` : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="状态" min-width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="row.healthy === false ? 'danger' : 'success'" size="small">
            {{ row.healthy === false ? '异常' : '正常' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <!-- Phase 3: Template Builder -->
    <div class="template-builder-section">
      <div class="builder-header" @click="builderExpanded = !builderExpanded">
        <el-icon><MagicStick /></el-icon>
        <span class="builder-title">自定义观察点模板生成器</span>
        <el-icon class="expand-icon" :class="{ expanded: builderExpanded }"><ArrowDown /></el-icon>
      </div>

      <div v-show="builderExpanded" class="builder-body">
        <!-- Step 1: NL input -->
        <div class="builder-step">
          <div class="step-label">第一步：描述你想监控什么</div>
          <div class="nl-input-row">
            <el-input
              v-model="nlDescription"
              placeholder="例如：监控 eth0 端口的链路状态是否发生变化；检测 /var/log/messages 中是否出现 OOM 字样"
              :disabled="generating"
              clearable
              @keydown.enter.prevent="handleGenerate"
            />
            <el-button
              type="primary"
              :loading="generating"
              :disabled="!nlDescription.trim()"
              @click="handleGenerate"
            >
              <el-icon><MagicStick /></el-icon> AI 生成
            </el-button>
          </div>
          <div v-if="generateError" class="error-hint">{{ generateError }}</div>
        </div>

        <!-- Step 2: Template preview / edit -->
        <div v-if="template" class="builder-step">
          <div class="step-label">第二步：预览并调整模板</div>
          <div class="template-form">
            <div class="form-row">
              <label>名称</label>
              <el-input v-model="template.name" size="small" style="width:200px" />
            </div>
            <div class="form-row">
              <label>命令</label>
              <el-input v-model="template.command" size="small" style="flex:1" />
            </div>
            <div class="form-row">
              <label>提取策略</label>
              <el-select v-model="template.strategy" size="small" style="width:130px">
                <el-option v-for="s in STRATEGIES" :key="s" :label="s" :value="s" />
              </el-select>
              <label style="margin-left:12px">触发条件</label>
              <el-select v-model="template.match_condition" size="small" style="width:140px">
                <el-option v-for="c in CONDITIONS" :key="c.value" :label="c.label" :value="c.value" />
              </el-select>
              <el-input
                v-if="['gt','lt','eq','ne'].includes(template.match_condition)"
                v-model="template.match_threshold"
                size="small"
                placeholder="阈值"
                style="width:80px; margin-left:8px"
              />
            </div>
            <div class="form-row">
              <label>级别</label>
              <el-select v-model="template.alert_level" size="small" style="width:120px">
                <el-option label="info" value="info" />
                <el-option label="warning" value="warning" />
                <el-option label="error" value="error" />
                <el-option label="critical" value="critical" />
              </el-select>
              <label style="margin-left:12px">间隔(s)</label>
              <el-input-number v-model="template.interval" size="small" :min="5" :max="3600" style="width:100px" />
              <label style="margin-left:12px">冷却(s)</label>
              <el-input-number v-model="template.cooldown" size="small" :min="0" :max="86400" style="width:100px" />
            </div>
            <div class="form-row">
              <label>消息模板</label>
              <el-input v-model="template.alert_message_template" size="small" style="flex:1"
                placeholder="可用 {value} {command} {old} {new}" />
            </div>
          </div>

          <!-- Step 3: Test run -->
          <div class="builder-step" style="margin-top:12px">
            <div class="step-label">第三步：在当前阵列试运行</div>
            <div class="test-run-row">
              <el-button
                size="small"
                :loading="testing"
                :disabled="!array?.array_id || array?.state !== 'connected'"
                @click="handleTestRun"
              >
                <el-icon><VideoPlay /></el-icon> 试运行
              </el-button>
              <span v-if="array?.state !== 'connected'" class="test-hint">（阵列未连接）</span>
            </div>

            <div v-if="testResult" class="test-result">
              <div class="test-result-row">
                <el-tag :type="testResult.condition_met ? 'danger' : 'success'" size="small">
                  {{ testResult.condition_met ? '⚠ 条件触发' : '✓ 条件未触发' }}
                </el-tag>
                <span class="result-kv">exit_code: <code>{{ testResult.exit_code }}</code></span>
                <span class="result-kv">提取值: <code>{{ testResult.value ?? '(null)' }}</code></span>
              </div>
              <div v-if="testResult.extraction_note" class="result-note">{{ testResult.extraction_note }}</div>
              <pre class="result-output">{{ testResult.raw_output || '(no output)' }}</pre>
            </div>
          </div>

          <!-- Step 4: Save -->
          <div class="builder-step builder-actions">
            <el-button type="primary" size="small" :loading="saving" @click="handleSave">
              保存为模板
            </el-button>
            <el-button size="small" @click="resetBuilder">重置</el-button>
            <span v-if="saveSuccess" class="save-success">✓ 已保存（可在管理后台部署到阵列）</span>
          </div>
        </div>
      </div>
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed, inject } from 'vue'
import { ElMessage } from 'element-plus'
import { MagicStick, ArrowDown, VideoPlay } from '@element-plus/icons-vue'
import { getObserverName as getObserverLabel } from '@/utils/alertTranslator'
import api from '@/api'

const { array } = inject('arrayDetail')

// ───── Observer status table ─────
const observerList = computed(() => {
  const status = array.value?.observer_status || array.value?.observers || {}
  if (Array.isArray(status)) return status
  return Object.entries(status).map(([name, info]) => ({
    name,
    last_run: info.last_run || info.last_executed || info.last_active_ts,
    last_success: info.last_success || (info.status === 'ok' ? info.last_active_ts : null),
    last_error: info.last_error || info.error,
    avg_duration: info.avg_duration ?? info.duration,
    healthy: info.healthy ?? (info.status === 'ok' || info.status === 'healthy'),
  }))
})

function getObserverName(name) { return getObserverLabel(name) }

function formatDateTime(timestamp) {
  if (!timestamp) return '-'
  return new Date(timestamp).toLocaleString('zh-CN')
}

// ───── Phase 3: Template Builder ─────
const builderExpanded = ref(false)
const nlDescription = ref('')
const generating = ref(false)
const generateError = ref('')
const template = ref(null)
const testing = ref(false)
const testResult = ref(null)
const saving = ref(false)
const saveSuccess = ref(false)

const STRATEGIES = ['pipe', 'kv', 'json', 'table', 'lines', 'diff', 'exit_code']
const CONDITIONS = [
  { value: 'found', label: '存在(found)' },
  { value: 'not_found', label: '不存在(not_found)' },
  { value: 'gt', label: '大于(gt)' },
  { value: 'lt', label: '小于(lt)' },
  { value: 'eq', label: '等于(eq)' },
  { value: 'ne', label: '不等于(ne)' },
]

async function handleGenerate() {
  if (!nlDescription.value.trim()) return
  generating.value = true
  generateError.value = ''
  template.value = null
  testResult.value = null
  try {
    const res = await api.generateObserverTemplate(nlDescription.value.trim())
    template.value = { strategy_config: {}, ...res.data.template }
    saveSuccess.value = false
  } catch (e) {
    const detail = e?.response?.data?.detail
    generateError.value = typeof detail === 'string' ? detail : (e?.message || 'AI 生成失败')
  } finally {
    generating.value = false
  }
}

async function handleTestRun() {
  if (!template.value || !array.value?.array_id) return
  testing.value = true
  testResult.value = null
  try {
    const res = await api.testExecuteTemplate(array.value.array_id, template.value)
    testResult.value = res.data
  } catch (e) {
    const detail = e?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '试运行失败')
  } finally {
    testing.value = false
  }
}

async function handleSave() {
  if (!template.value) return
  saving.value = true
  saveSuccess.value = false
  try {
    await api.createMonitorTemplate({
      name: template.value.name || 'custom_monitor',
      description: nlDescription.value.trim(),
      command: template.value.command,
      command_type: template.value.command_type || 'shell',
      interval: template.value.interval || 60,
      timeout: template.value.timeout || 30,
      match_type: template.value.strategy || 'regex',
      match_expression: JSON.stringify(template.value.strategy_config || {}),
      match_condition: template.value.match_condition || 'found',
      match_threshold: template.value.match_threshold || null,
      alert_level: template.value.alert_level || 'warning',
      alert_message_template: template.value.alert_message_template || '',
      cooldown: template.value.cooldown || 300,
      is_enabled: true,
    })
    saveSuccess.value = true
    ElMessage.success('模板已保存，可在管理后台部署到阵列')
  } catch (e) {
    const detail = e?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '保存失败')
  } finally {
    saving.value = false
  }
}

function resetBuilder() {
  template.value = null
  testResult.value = null
  generateError.value = ''
  saveSuccess.value = false
}
</script>

<style scoped>
.zone-card { border-radius: 8px; transition: box-shadow 0.3s; }
.zone-card:hover { box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08); }
.zone-title { font-weight: 600; font-size: 15px; display: flex; align-items: center; gap: 6px; }
.card-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.observer-table { width: 100%; }
.observer-name { font-weight: 500; display: block; }
.observer-key { font-size: 11px; color: #909399; font-family: 'SF Mono', 'Fira Code', monospace; }
.observer-error { color: #f56c6c; font-size: 12px; }
.observer-ok { color: #909399; }

/* Template Builder */
.template-builder-section { margin-top: 16px; border-top: 1px solid #f0f0f0; padding-top: 12px; }
.builder-header {
  display: flex; align-items: center; gap: 8px;
  cursor: pointer; padding: 6px 4px;
  color: var(--el-color-primary); font-weight: 500; font-size: 13px;
  user-select: none;
}
.builder-header:hover { color: var(--el-color-primary-dark-2); }
.builder-title { flex: 1; }
.expand-icon { transition: transform 0.3s; }
.expand-icon.expanded { transform: rotate(180deg); }

.builder-body { padding: 12px 4px 4px; }
.builder-step { margin-bottom: 16px; }
.step-label { font-size: 12px; color: #606266; font-weight: 500; margin-bottom: 8px; }

.nl-input-row { display: flex; gap: 8px; align-items: flex-start; }
.nl-input-row .el-input { flex: 1; }

.error-hint { color: #f56c6c; font-size: 12px; margin-top: 4px; }

.template-form { display: flex; flex-direction: column; gap: 8px; }
.form-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.form-row label { font-size: 12px; color: #606266; white-space: nowrap; min-width: 52px; }

.test-run-row { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.test-hint { font-size: 12px; color: #909399; }

.test-result { background: #f8f9fb; border-radius: 6px; padding: 10px 12px; font-size: 12px; }
.test-result-row { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.result-kv { color: #606266; }
.result-kv code { font-family: 'SF Mono', monospace; background: #f0f2f5; padding: 1px 5px; border-radius: 3px; }
.result-note { color: #909399; font-style: italic; margin-bottom: 4px; }
.result-output {
  background: #1a1a2e; color: #a8d8ea; border-radius: 4px;
  padding: 8px 10px; font-size: 11px; font-family: 'SF Mono', 'Fira Code', monospace;
  max-height: 160px; overflow-y: auto; white-space: pre-wrap; word-break: break-all;
  margin: 0;
}

.builder-actions { display: flex; align-items: center; gap: 10px; }
.save-success { color: #67c23a; font-size: 12px; font-weight: 500; }
</style>
