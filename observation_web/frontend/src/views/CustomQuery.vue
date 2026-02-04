<template>
  <div class="custom-query">
    <el-row :gutter="20">
      <!-- Query Builder -->
      <el-col :span="14">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>自定义查询</span>
              <el-button type="primary" @click="executeQuery" :loading="executing" :disabled="!canExecute">
                <el-icon><CaretRight /></el-icon>
                执行查询
              </el-button>
            </div>
          </template>

          <el-form label-width="100px">
            <!-- Query Name -->
            <el-form-item label="查询名称">
              <el-input v-model="queryTask.name" placeholder="可选：查询名称" />
            </el-form-item>

            <!-- Target Arrays -->
            <el-form-item label="目标阵列">
              <el-checkbox-group v-model="queryTask.target_arrays">
                <el-checkbox 
                  v-for="arr in connectedArrays" 
                  :key="arr.array_id"
                  :label="arr.array_id"
                >
                  {{ arr.name }} ({{ arr.host }})
                </el-checkbox>
              </el-checkbox-group>
              <el-empty v-if="connectedArrays.length === 0" description="请先连接阵列" />
            </el-form-item>

            <!-- Commands -->
            <el-form-item label="命令列表">
              <div class="command-list">
                <div v-for="(cmd, index) in queryTask.commands" :key="index" class="command-item">
                  <el-input 
                    v-model="queryTask.commands[index]" 
                    placeholder="输入要执行的命令"
                    class="command-input"
                  />
                  <el-button 
                    type="danger" 
                    :icon="Delete" 
                    circle 
                    @click="removeCommand(index)"
                    :disabled="queryTask.commands.length <= 1"
                  />
                </div>
                <el-button type="primary" text @click="addCommand">
                  <el-icon><Plus /></el-icon>
                  添加命令
                </el-button>
              </div>
            </el-form-item>

            <!-- Rule Type -->
            <el-form-item label="规则类型">
              <el-radio-group v-model="queryTask.rule.rule_type">
                <el-radio label="valid_match">有效值匹配</el-radio>
                <el-radio label="invalid_match">无效值匹配</el-radio>
                <el-radio label="regex_extract">正则提取</el-radio>
              </el-radio-group>
            </el-form-item>

            <!-- Pattern -->
            <el-form-item label="匹配模式">
              <el-input 
                v-model="queryTask.rule.pattern" 
                placeholder="正则表达式，如: running|online"
              >
                <template #append>
                  <el-button @click="testPattern">测试</el-button>
                </template>
              </el-input>
              <div class="pattern-help">
                <el-tag type="info" size="small">示例: running|online</el-tag>
                <el-tag type="info" size="small">示例: state=(\w+)</el-tag>
                <el-tag type="info" size="small">示例: error|failed|degraded</el-tag>
              </div>
            </el-form-item>

            <!-- Expect Match -->
            <el-form-item label="预期结果">
              <el-radio-group v-model="queryTask.rule.expect_match">
                <el-radio :label="true">匹配成功 = 正常</el-radio>
                <el-radio :label="false">匹配成功 = 异常</el-radio>
              </el-radio-group>
            </el-form-item>

            <!-- Extract Fields -->
            <el-form-item label="提取字段" v-if="queryTask.rule.rule_type === 'regex_extract'">
              <div class="extract-fields">
                <div v-for="(field, index) in queryTask.rule.extract_fields" :key="index" class="field-item">
                  <el-input v-model="field.name" placeholder="字段名" style="width: 120px" />
                  <el-input v-model="field.pattern" placeholder="正则表达式" style="flex: 1; margin: 0 8px" />
                  <el-button type="danger" :icon="Delete" circle @click="removeField(index)" />
                </div>
                <el-button type="primary" text @click="addField">
                  <el-icon><Plus /></el-icon>
                  添加字段
                </el-button>
              </div>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- Results -->
        <el-card v-if="queryResult" class="result-card">
          <template #header>
            <div class="card-header">
              <span>查询结果</span>
              <span class="result-time">{{ formatDateTime(queryResult.completed_at) }}</span>
            </div>
          </template>

          <el-table :data="queryResult.results" stripe>
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="output-detail">
                  <p><strong>原始输出:</strong></p>
                  <pre>{{ row.output }}</pre>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="阵列" width="120" prop="array_name" />
            <el-table-column label="命令" prop="command" show-overflow-tooltip />
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.status === 'ok' ? 'success' : 'danger'" size="small">
                  {{ row.status === 'ok' ? '正常' : '异常' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="匹配结果" width="200">
              <template #default="{ row }">
                <span v-if="row.matched_values.length > 0">
                  {{ row.matched_values.join(', ') }}
                </span>
                <span v-else class="no-match">无匹配</span>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="80">
              <template #default="{ row }">
                {{ row.execution_time_ms }}ms
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <!-- Templates -->
      <el-col :span="10">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>查询模板</span>
              <el-button text @click="saveAsTemplate" :disabled="!queryTask.name">
                <el-icon><DocumentAdd /></el-icon>
                保存当前
              </el-button>
            </div>
          </template>

          <div class="template-list">
            <div 
              v-for="template in templates" 
              :key="template.id" 
              class="template-item"
              @click="loadTemplate(template)"
            >
              <div class="template-info">
                <div class="template-name">
                  {{ template.name }}
                  <el-tag v-if="template.is_builtin" type="info" size="small">内置</el-tag>
                </div>
                <div class="template-desc">{{ template.description }}</div>
              </div>
              <el-button 
                v-if="!template.is_builtin"
                type="danger"
                :icon="Delete"
                circle
                size="small"
                @click.stop="deleteTemplate(template.id)"
              />
            </div>
          </div>
        </el-card>

        <!-- Pattern Test -->
        <el-card class="test-card">
          <template #header>
            <span>模式测试</span>
          </template>

          <el-form label-width="80px">
            <el-form-item label="测试文本">
              <el-input 
                v-model="testText" 
                type="textarea" 
                :rows="4" 
                placeholder="输入测试文本"
              />
            </el-form-item>
            <el-form-item label="测试结果" v-if="testResult">
              <div class="test-result">
                <el-tag :type="testResult.is_normal ? 'success' : 'danger'">
                  {{ testResult.is_normal ? '正常' : '异常' }}
                </el-tag>
                <div v-if="testResult.matches.length > 0" class="matches">
                  匹配值: {{ testResult.matches.join(', ') }}
                </div>
                <div v-if="testResult.error" class="error-text">
                  错误: {{ testResult.error }}
                </div>
              </div>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { CaretRight, Delete, Plus, DocumentAdd } from '@element-plus/icons-vue'
import { useArrayStore } from '../stores/arrays'
import api from '../api'

const arrayStore = useArrayStore()

const executing = ref(false)
const templates = ref([])
const queryResult = ref(null)
const testText = ref('')
const testResult = ref(null)

const queryTask = reactive({
  name: '',
  commands: [''],
  target_arrays: [],
  rule: {
    rule_type: 'valid_match',
    pattern: '',
    expect_match: true,
    extract_fields: [],
  },
})

const connectedArrays = computed(() => 
  arrayStore.arrays.filter(a => a.state === 'connected')
)

const canExecute = computed(() => 
  queryTask.target_arrays.length > 0 && 
  queryTask.commands.some(c => c.trim())
)

function addCommand() {
  queryTask.commands.push('')
}

function removeCommand(index) {
  if (queryTask.commands.length > 1) {
    queryTask.commands.splice(index, 1)
  }
}

function addField() {
  queryTask.rule.extract_fields.push({ name: '', pattern: '' })
}

function removeField(index) {
  queryTask.rule.extract_fields.splice(index, 1)
}

async function executeQuery() {
  executing.value = true
  try {
    const task = {
      ...queryTask,
      commands: queryTask.commands.filter(c => c.trim()),
    }
    const response = await api.executeQuery(task)
    queryResult.value = response.data
    ElMessage.success('查询完成')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '查询失败')
  } finally {
    executing.value = false
  }
}

async function testPattern() {
  if (!queryTask.rule.pattern || !testText.value) {
    ElMessage.warning('请输入匹配模式和测试文本')
    return
  }

  try {
    const response = await api.testPattern({
      pattern: queryTask.rule.pattern,
      test_text: testText.value,
      rule_type: queryTask.rule.rule_type,
      expect_match: queryTask.rule.expect_match,
    })
    testResult.value = response.data
  } catch (error) {
    ElMessage.error('测试失败')
  }
}

async function loadTemplates() {
  try {
    const response = await api.getQueryTemplates()
    templates.value = response.data
  } catch (error) {
    console.error('Failed to load templates:', error)
  }
}

function loadTemplate(template) {
  queryTask.name = template.name
  queryTask.commands = [...template.commands]
  queryTask.rule = {
    rule_type: template.rule.rule_type,
    pattern: template.rule.pattern,
    expect_match: template.rule.expect_match,
    extract_fields: template.rule.extract_fields?.map(f => ({ ...f })) || [],
  }
  ElMessage.success(`已加载模板: ${template.name}`)
}

async function saveAsTemplate() {
  if (!queryTask.name) {
    ElMessage.warning('请输入查询名称')
    return
  }

  try {
    await api.createQueryTemplate({
      name: queryTask.name,
      description: '',
      commands: queryTask.commands.filter(c => c.trim()),
      rule: queryTask.rule,
    })
    ElMessage.success('模板保存成功')
    await loadTemplates()
  } catch (error) {
    ElMessage.error('保存失败')
  }
}

async function deleteTemplate(id) {
  try {
    await api.deleteQueryTemplate(id)
    ElMessage.success('删除成功')
    await loadTemplates()
  } catch (error) {
    ElMessage.error('删除失败')
  }
}

function formatDateTime(timestamp) {
  if (!timestamp) return ''
  return new Date(timestamp).toLocaleString('zh-CN')
}

onMounted(async () => {
  await Promise.all([
    arrayStore.fetchArrays(),
    loadTemplates(),
  ])
})
</script>

<style scoped>
.custom-query {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.command-list {
  width: 100%;
}

.command-item {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.command-input {
  flex: 1;
}

.pattern-help {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.extract-fields {
  width: 100%;
}

.field-item {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}

.result-card {
  margin-top: 20px;
}

.result-time {
  font-size: 12px;
  color: #909399;
}

.output-detail {
  padding: 16px;
  background: #f5f7fa;
}

.output-detail pre {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
  background: #fff;
  padding: 8px;
  border-radius: 4px;
  max-height: 300px;
  overflow-y: auto;
}

.no-match {
  color: #909399;
}

.template-list {
  max-height: 400px;
  overflow-y: auto;
}

.template-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.2s;
}

.template-item:hover {
  background: #f5f7fa;
}

.template-name {
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 8px;
}

.template-desc {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.test-card {
  margin-top: 20px;
}

.test-result {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.matches {
  font-size: 13px;
  color: #67c23a;
}

.error-text {
  color: #f56c6c;
  font-size: 13px;
}
</style>
