<template>
  <el-drawer
    :model-value="modelValue"
    size="min(1040px, 96vw)"
    destroy-on-close
    class="observer-studio"
    @update:model-value="$emit('update:modelValue', $event)"
    @open="initialize"
    @closed="stopPolling"
  >
    <template #header>
      <div class="studio-heading">
        <div>
          <strong>{{ editingId ? `编辑 ${form.name}` : '创建自定义观察点' }}</strong>
          <span v-if="savedTemplate" class="version-mark">v{{ savedTemplate.version }}</span>
        </div>
        <el-tag v-if="savedTemplate" :type="overallState.type" effect="plain">
          {{ overallState.label }}
        </el-tag>
      </div>
    </template>

    <div class="studio-flow">
      <section class="intent-band">
        <div class="section-title">
          <span class="step-index">01</span>
          <div><strong>定义观察目标</strong><small>自然语言生成后仍可完整编辑</small></div>
        </div>
        <div class="intent-row">
          <el-input
            v-model="description"
            placeholder="例如：每 30 秒检查控制器状态，出现 offline 连续两次时告警"
            clearable
            @keydown.enter.prevent="generateTemplate"
          />
          <el-button type="primary" :loading="generating" :disabled="!description.trim()" @click="generateTemplate">
            <el-icon><MagicStick /></el-icon>生成
          </el-button>
        </div>
      </section>

      <div class="editor-grid">
        <section class="editor-pane">
          <div class="section-title compact"><span class="step-index">02</span><strong>执行与提取</strong></div>
          <el-form label-position="top" size="small">
            <div class="two-columns">
              <el-form-item label="观察点名称"><el-input v-model="form.name" /></el-form-item>
              <el-form-item label="分类">
                <el-select v-model="form.category"><el-option label="自定义" value="custom" /><el-option label="端口" value="port" /><el-option label="卡件" value="card" /><el-option label="系统" value="system" /></el-select>
              </el-form-item>
            </div>
            <el-form-item label="执行命令"><el-input v-model="form.command" type="textarea" :rows="3" /></el-form-item>
            <div class="three-columns">
              <el-form-item label="提取策略">
                <el-select v-model="form.strategy"><el-option v-for="item in strategies" :key="item" :label="item" :value="item" /></el-select>
              </el-form-item>
              <el-form-item label="执行间隔"><el-input-number v-model="form.interval" :min="5" :max="3600" controls-position="right" /></el-form-item>
              <el-form-item label="超时"><el-input-number v-model="form.timeout" :min="1" :max="300" controls-position="right" /></el-form-item>
            </div>
            <el-form-item label="策略参数 JSON">
              <el-input v-model="strategyConfigText" type="textarea" :rows="4" class="code-input" @blur="syncStrategyConfig" />
              <small v-if="strategyError" class="field-error">{{ strategyError }}</small>
            </el-form-item>
            <div class="three-columns">
              <el-form-item label="触发条件">
                <el-select v-model="form.match_condition"><el-option v-for="item in conditions" :key="item.value" :label="item.label" :value="item.value" /></el-select>
              </el-form-item>
              <el-form-item label="阈值"><el-input v-model="form.match_threshold" :disabled="!needsThreshold" /></el-form-item>
              <el-form-item label="连续次数"><el-input-number v-model="form.consecutive_threshold" :min="1" :max="100" controls-position="right" /></el-form-item>
            </div>
          </el-form>
        </section>

        <aside class="behavior-pane">
          <div class="section-title compact"><span class="step-index">03</span><strong>告警与范围</strong></div>
          <el-form label-position="top" size="small">
            <el-form-item label="可见范围">
              <el-radio-group v-model="form.visibility" class="visibility-control">
                <el-radio-button label="private">个人</el-radio-button><el-radio-button label="team">团队</el-radio-button><el-radio-button label="global">全局</el-radio-button>
              </el-radio-group>
              <small>模板共享范围；阵列端是否执行由下方分配决定。</small>
            </el-form-item>
            <el-form-item v-if="form.visibility === 'team'" label="团队标识"><el-input v-model="form.team_scope" placeholder="例如 storage-test" /></el-form-item>
            <div class="two-columns">
              <el-form-item label="级别"><el-select v-model="form.alert_level"><el-option label="信息" value="info" /><el-option label="警告" value="warning" /><el-option label="错误" value="error" /><el-option label="严重" value="critical" /></el-select></el-form-item>
              <el-form-item label="冷却时间"><el-input-number v-model="form.cooldown" :min="0" :max="86400" controls-position="right" /></el-form-item>
            </div>
            <el-form-item label="告警消息"><el-input v-model="form.alert_message_template" type="textarea" :rows="2" placeholder="可用 {value} {old} {new} {exit_code}" /></el-form-item>
            <el-divider />
            <el-form-item label="分配方式">
              <el-radio-group v-model="targetType"><el-radio-button label="tag">标签</el-radio-button><el-radio-button label="array">阵列</el-radio-button></el-radio-group>
            </el-form-item>
            <el-form-item label="执行目标">
              <el-select v-model="targetIds" multiple filterable collapse-tags collapse-tags-tooltip>
                <el-option v-for="item in targetOptions" :key="item.id" :label="targetLabel(item)" :value="item.id" />
              </el-select>
            </el-form-item>
          </el-form>
        </aside>
      </div>

      <section class="trial-band">
        <div class="section-title compact"><span class="step-index">04</span><strong>在线试运行</strong></div>
        <div class="trial-toolbar">
          <el-select v-model="testArrayId" filterable placeholder="选择一个已连接阵列">
            <el-option v-for="item in arrays" :key="item.id" :label="targetLabel(item)" :value="item.array_id" />
          </el-select>
          <el-button :loading="testing" :disabled="!testArrayId || !form.command" @click="runTest"><el-icon><VideoPlay /></el-icon>试运行</el-button>
          <span v-if="testResult" class="trial-verdict" :class="{ triggered: testResult.condition_met }">{{ testResult.condition_met ? '条件已触发' : '条件未触发' }}</span>
        </div>
        <div v-if="testResult" class="trial-result">
          <dl><div><dt>退出码</dt><dd>{{ testResult.exit_code }}</dd></div><div><dt>提取值</dt><dd>{{ testResult.value ?? '-' }}</dd></div><div><dt>策略</dt><dd>{{ testResult.strategy }}</dd></div></dl>
          <pre>{{ testResult.raw_output || '(无输出)' }}</pre>
        </div>
      </section>

      <section v-if="savedTemplate" class="runtime-band">
        <div class="section-title compact">
          <span class="step-index">05</span><strong>运行状态</strong>
          <el-popover placement="bottom-start" trigger="click" width="360">
            <template #reference><el-button text size="small">{{ versions.length }} 个版本</el-button></template>
            <div class="version-list">
              <div v-for="item in versions" :key="item.id">
                <strong>v{{ item.version }}</strong><span>{{ item.created_by || '-' }}</span><time>{{ formatTime(item.created_at) }}</time>
                <el-button v-if="item.version !== savedTemplate.version" link type="primary" size="small" @click="restoreVersion(item)">恢复</el-button>
              </div>
            </div>
          </el-popover>
        </div>
        <el-table :data="deployments" size="small" empty-text="尚未下发到阵列">
          <el-table-column prop="array_id" label="阵列" min-width="150" />
          <el-table-column label="版本" width="80"><template #default="{ row }">v{{ row.desired_version }}</template></el-table-column>
          <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="deploymentState(row).type" size="small">{{ deploymentState(row).label }}</el-tag></template></el-table-column>
          <el-table-column prop="status_message" label="说明" min-width="220"><template #default="{ row }">{{ row.status_message || 'Agent 已确认加载目标配置' }}</template></el-table-column>
          <el-table-column prop="confirmed_at" label="确认时间" min-width="170" />
        </el-table>
      </section>
    </div>

    <template #footer>
      <div class="studio-footer">
        <span>{{ savedTemplate ? `当前版本 v${savedTemplate.version}` : '尚未保存' }}</span>
        <div><el-button @click="$emit('update:modelValue', false)">关闭</el-button><el-button :loading="saving" @click="save(false)"><el-icon><DocumentChecked /></el-icon>保存版本</el-button><el-button type="primary" :loading="deploying" :disabled="!targetIds.length && !hasPersistedAssignments && !deployments.length" @click="save(true)"><el-icon><Promotion /></el-icon>保存并下发</el-button></div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { DocumentChecked, MagicStick, Promotion, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '@/api'
import { createObserverForm, deploymentState, formToTemplatePayload, generatedTemplateToForm } from './customObserverForm'

const props = defineProps({ modelValue: Boolean, template: { type: Object, default: null } })
const emit = defineEmits(['update:modelValue', 'saved'])
const strategies = ['pipe', 'kv', 'json', 'table', 'lines', 'diff', 'exit_code']
const conditions = [{ value: 'found', label: '存在' }, { value: 'not_found', label: '不存在' }, { value: 'gt', label: '大于' }, { value: 'lt', label: '小于' }, { value: 'eq', label: '等于' }, { value: 'ne', label: '不等于' }]
const form = reactive(createObserverForm())
const description = ref('')
const strategyConfigText = ref('{}')
const strategyError = ref('')
const arrays = ref([])
const tags = ref([])
const targetType = ref('tag')
const targetIds = ref([])
const testArrayId = ref('')
const testResult = ref(null)
const versions = ref([])
const deployments = ref([])
const hasPersistedAssignments = ref(false)
const savedTemplate = ref(null)
const generating = ref(false)
const testing = ref(false)
const saving = ref(false)
const deploying = ref(false)
let pollTimer = null
const editingId = computed(() => savedTemplate.value?.id || props.template?.id)
const needsThreshold = computed(() => ['gt', 'lt', 'eq', 'ne'].includes(form.match_condition))
const targetOptions = computed(() => targetType.value === 'tag' ? tags.value : arrays.value)
const overallState = computed(() => deploymentState(deployments.value.find(item => item.status !== 'active') || deployments.value[0]))
function targetLabel(item) { return item.array_id ? `${item.name} (${item.array_id})` : item.name }
function formatTime(value) { return value ? new Date(value).toLocaleString('zh-CN') : '-' }
function applyForm(source) { Object.assign(form, createObserverForm(source)); description.value = form.description; strategyConfigText.value = JSON.stringify(form.strategy_config || {}, null, 2) }
function syncStrategyConfig() { try { form.strategy_config = JSON.parse(strategyConfigText.value || '{}'); strategyError.value = ''; return true } catch { strategyError.value = '策略参数必须是有效 JSON'; return false } }
async function initialize() {
  savedTemplate.value = props.template ? { ...props.template } : null
  applyForm(props.template || {})
  targetType.value = 'tag'
  targetIds.value = []
  hasPersistedAssignments.value = false
  deployments.value = []
  try {
    const [arrayRes, tagRes] = await Promise.all([api.getArrays(), api.getTags()])
    arrays.value = arrayRes.data || []
    tags.value = tagRes.data || []
    if (editingId.value) await loadRuntime()
    startPolling()
  } catch (error) {
    arrays.value = []
    tags.value = []
    ElMessage.error(error.response?.data?.detail || '阵列和标签加载失败，请稍后重试')
  }
}
async function generateTemplate() {
  generating.value = true
  try { const res = await api.generateObserverTemplate(description.value.trim()); applyForm(generatedTemplateToForm(res.data.template, description.value)); ElMessage.success('已生成，可继续调整或试运行') }
  catch (error) { ElMessage.error(error.response?.data?.detail || '生成失败') }
  finally { generating.value = false }
}
async function runTest() {
  if (!syncStrategyConfig()) return
  testing.value = true; testResult.value = null
  try { const res = await api.testExecuteTemplate(testArrayId.value, form); testResult.value = res.data }
  catch (error) { ElMessage.error(error.response?.data?.detail || '试运行失败') }
  finally { testing.value = false }
}
async function save(shouldDeploy) {
  if (!form.name.trim() || !form.command.trim()) { ElMessage.warning('请填写名称和执行命令'); return }
  if (!syncStrategyConfig()) return
  shouldDeploy ? deploying.value = true : saving.value = true
  try {
    const payload = formToTemplatePayload(form)
    const res = editingId.value ? await api.updateMonitorTemplate(editingId.value, payload) : await api.createMonitorTemplate(payload)
    savedTemplate.value = res.data
    if (shouldDeploy) await api.deployMonitorTemplates([res.data.id], targetType.value, targetIds.value)
    else await api.saveMonitorAssignments(res.data.id, targetType.value, targetIds.value)
    await loadRuntime(); startPolling(); emit('saved', res.data)
    ElMessage.success(shouldDeploy ? '已下发，状态以 Agent 加载回执为准' : `已保存为 v${res.data.version}`)
  } catch (error) { ElMessage.error(error.response?.data?.detail || error.message || '操作失败') }
  finally { saving.value = false; deploying.value = false }
}
async function loadRuntime() {
  if (!editingId.value) return
  const [versionRes, assignmentRes, deploymentRes] = await Promise.all([api.getMonitorTemplateVersions(editingId.value), api.getMonitorAssignments(editingId.value), api.getMonitorDeployments(editingId.value)])
  versions.value = versionRes.data || []; deployments.value = deploymentRes.data || []
  const assignments = assignmentRes.data || []
  hasPersistedAssignments.value = assignments.length > 0
  if (assignments.length) { targetType.value = assignments[0].target_type; targetIds.value = assignments.filter(item => item.target_type === targetType.value).map(item => item.target_id) }
}
async function restoreVersion(item) {
  saving.value = true
  try {
    const res = await api.restoreMonitorTemplateVersion(editingId.value, item.version)
    savedTemplate.value = res.data
    applyForm(res.data)
    await loadRuntime()
    emit('saved', res.data)
    ElMessage.success(`已将 v${item.version} 恢复为新版本 v${res.data.version}`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '恢复版本失败')
  } finally {
    saving.value = false
  }
}
function startPolling() { stopPolling(); if (editingId.value) pollTimer = window.setInterval(() => loadRuntime().catch(() => {}), 5000) }
function stopPolling() { if (pollTimer) window.clearInterval(pollTimer); pollTimer = null }
</script>

<style scoped src="./custom-observer-studio.css"></style>
