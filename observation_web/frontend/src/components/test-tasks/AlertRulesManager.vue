<template>
  <div>
    <!-- Alert Rules Config Dialog -->
    <el-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" title="告警预期规则配置" width="800px">
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
import { ref, reactive, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../api'

defineProps({
  modelValue: { type: Boolean, default: false },
  taskTypes: { type: Object, default: () => ({}) },
  commonObservers: { type: Array, default: () => [] },
})
defineEmits(['update:modelValue'])

const alertRules = ref([])
const loadingRules = ref(false)
const creatingRule = ref(false)
const showAddRuleDialog = ref(false)

const ruleForm = reactive({
  name: '',
  description: '',
  task_types: [],
  observer_patterns: [],
  level_patterns: [],
  message_patterns: [],
})

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

onMounted(() => {
  loadRules()
})
</script>

<style scoped>
.rules-config { min-height: 300px; }
.rules-toolbar { display: flex; gap: 10px; margin-bottom: 16px; }
</style>
