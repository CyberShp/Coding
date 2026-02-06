<template>
  <div class="agent-config">
    <div class="config-header">
      <div class="config-info">
        <el-tag v-if="configExists" type="success" size="small">配置已存在</el-tag>
        <el-tag v-else type="warning" size="small">配置不存在</el-tag>
        <span v-if="configPath" class="config-path">{{ configPath }}</span>
      </div>
      <div class="config-actions">
        <el-button size="small" @click="loadConfig" :loading="loading">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
        <el-button size="small" @click="restoreConfig" :loading="restoring" :disabled="!configExists">
          <el-icon><RefreshLeft /></el-icon>
          还原备份
        </el-button>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon closable @close="error = ''" />

    <div class="config-editor-wrapper" v-loading="loading">
      <div class="editor-toolbar">
        <span class="editor-label">Agent 配置 (JSON)</span>
        <div class="editor-options">
          <el-checkbox v-model="restartAfterSave" size="small">保存后重启 Agent</el-checkbox>
        </div>
      </div>
      
      <el-input
        v-model="configText"
        type="textarea"
        :rows="18"
        placeholder="Agent 配置 JSON"
        class="config-textarea"
        :class="{ 'has-error': jsonError }"
      />
      
      <div v-if="jsonError" class="json-error">
        <el-icon><Warning /></el-icon>
        JSON 格式错误: {{ jsonError }}
      </div>
    </div>

    <div class="config-footer">
      <el-button @click="formatJson" :disabled="!configText">格式化</el-button>
      <el-button type="primary" @click="saveConfig" :loading="saving" :disabled="!configText || !!jsonError">
        保存配置
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, RefreshLeft, Warning } from '@element-plus/icons-vue'
import api from '@/api'

const props = defineProps({
  arrayId: {
    type: String,
    required: true
  }
})

// State
const loading = ref(false)
const saving = ref(false)
const restoring = ref(false)
const configExists = ref(false)
const configPath = ref('')
const configText = ref('')
const error = ref('')
const jsonError = ref('')
const restartAfterSave = ref(false)

// Validate JSON as user types
watch(configText, (text) => {
  if (!text) {
    jsonError.value = ''
    return
  }
  try {
    JSON.parse(text)
    jsonError.value = ''
  } catch (e) {
    jsonError.value = e.message
  }
})

async function loadConfig() {
  loading.value = true
  error.value = ''
  
  try {
    const res = await api.getAgentConfig(props.arrayId)
    configExists.value = res.data.exists
    configPath.value = res.data.config_path
    
    if (res.data.exists && res.data.config) {
      configText.value = JSON.stringify(res.data.config, null, 2)
    } else if (res.data.raw) {
      configText.value = res.data.raw
    } else {
      configText.value = getDefaultConfig()
    }
    
    if (res.data.error) {
      error.value = res.data.error
    }
  } catch (e) {
    error.value = e.response?.data?.detail || '加载配置失败'
  } finally {
    loading.value = false
  }
}

function getDefaultConfig() {
  return JSON.stringify({
    "observers": {
      "error_code": { "enabled": true, "interval": 60 },
      "link_status": { "enabled": true, "interval": 30 },
      "card_recovery": { "enabled": true, "interval": 120 },
      "alarm_type": { "enabled": true, "interval": 60 },
      "memory_leak": { "enabled": true, "interval": 300 },
      "cpu_usage": { "enabled": true, "interval": 60 },
      "cmd_response": { "enabled": true, "interval": 30 },
      "sig_monitor": { "enabled": true, "interval": 60 },
      "sensitive_info": { "enabled": true, "interval": 3600 }
    },
    "logging": {
      "level": "INFO",
      "file": "/var/log/observation-points/alerts.log"
    }
  }, null, 2)
}

function formatJson() {
  try {
    const obj = JSON.parse(configText.value)
    configText.value = JSON.stringify(obj, null, 2)
    jsonError.value = ''
    ElMessage.success('格式化成功')
  } catch (e) {
    ElMessage.error('无法格式化：JSON 格式错误')
  }
}

async function saveConfig() {
  if (jsonError.value) {
    ElMessage.error('请先修正 JSON 格式错误')
    return
  }
  
  try {
    const configObj = JSON.parse(configText.value)
    
    await ElMessageBox.confirm(
      restartAfterSave.value 
        ? '保存配置并重启 Agent？' 
        : '确定要保存配置吗？',
      '确认保存',
      { type: 'warning' }
    )
    
    saving.value = true
    const res = await api.updateAgentConfig(props.arrayId, configObj, restartAfterSave.value)
    
    if (res.data.success) {
      ElMessage.success(res.data.message || '配置已保存')
      if (res.data.agent_restarted === false && restartAfterSave.value) {
        ElMessage.warning('配置已保存，但 Agent 重启失败: ' + (res.data.restart_error || ''))
      }
    }
    
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.detail || '保存失败')
    }
  } finally {
    saving.value = false
  }
}

async function restoreConfig() {
  await ElMessageBox.confirm('确定要从备份还原配置吗？当前配置将被覆盖。', '确认还原', { type: 'warning' })
  
  restoring.value = true
  try {
    await api.restoreAgentConfig(props.arrayId)
    ElMessage.success('配置已还原')
    await loadConfig()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '还原失败')
  } finally {
    restoring.value = false
  }
}

// Load on mount
onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.agent-config {
  padding: 15px;
}

.config-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
}

.config-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.config-path {
  color: #909399;
  font-size: 12px;
  font-family: monospace;
}

.config-actions {
  display: flex;
  gap: 8px;
}

.config-editor-wrapper {
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  overflow: hidden;
}

.editor-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #f5f7fa;
  border-bottom: 1px solid #dcdfe6;
}

.editor-label {
  font-size: 14px;
  color: #606266;
}

.config-textarea :deep(.el-textarea__inner) {
  font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.5;
  border: none;
  border-radius: 0;
  resize: none;
}

.config-textarea.has-error :deep(.el-textarea__inner) {
  background-color: #fef0f0;
}

.json-error {
  padding: 8px 12px;
  background: #fef0f0;
  color: #f56c6c;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 5px;
}

.config-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 15px;
}
</style>
