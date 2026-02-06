<template>
  <div class="log-viewer">
    <div class="log-header">
      <el-form :inline="true" class="log-controls">
        <el-form-item label="日志文件">
          <el-select v-model="selectedPath" placeholder="选择日志文件" filterable allow-create>
            <el-option-group label="常用路径">
              <el-option
                v-for="path in commonPaths"
                :key="path"
                :label="path"
                :value="path"
              />
            </el-option-group>
            <el-option-group v-if="discoveredFiles.length" label="发现的文件">
              <el-option
                v-for="file in discoveredFiles"
                :key="file.path"
                :label="`${file.name} (${file.size_human})`"
                :value="file.path"
              />
            </el-option-group>
          </el-select>
        </el-form-item>

        <el-form-item label="行数">
          <el-select v-model="lineCount" style="width: 100px">
            <el-option :value="50" label="50行" />
            <el-option :value="100" label="100行" />
            <el-option :value="200" label="200行" />
            <el-option :value="500" label="500行" />
          </el-select>
        </el-form-item>

        <el-form-item label="过滤">
          <el-input
            v-model="keyword"
            placeholder="关键字搜索"
            clearable
            style="width: 150px"
            @keyup.enter="loadLogs"
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="loading" @click="loadLogs">
            <el-icon><Refresh /></el-icon>
            加载
          </el-button>
          <el-button :disabled="!autoRefresh" @click="toggleAutoRefresh">
            <el-icon><Timer /></el-icon>
            {{ autoRefresh ? '停止刷新' : '自动刷新' }}
          </el-button>
          <el-button @click="discoverFiles" :loading="discovering">
            <el-icon><FolderOpened /></el-icon>
            扫描文件
          </el-button>
        </el-form-item>
      </el-form>

      <div v-if="logInfo" class="log-info">
        <el-tag size="small" type="info">
          {{ logInfo.lines_returned }} 行
        </el-tag>
        <el-tag v-if="logInfo.file_size" size="small">
          文件大小: {{ formatBytes(logInfo.file_size) }}
        </el-tag>
        <el-tag v-if="logInfo.modified_at" size="small">
          修改时间: {{ formatTime(logInfo.modified_at) }}
        </el-tag>
      </div>
    </div>

    <div class="log-content-wrapper">
      <div
        ref="logContent"
        class="log-content"
        :class="{ 'auto-scroll': autoScroll }"
      >
        <template v-if="logLines.length">
          <div
            v-for="(line, index) in logLines"
            :key="index"
            class="log-line"
            :class="getLineClass(line)"
          >
            <span class="line-number">{{ index + 1 }}</span>
            <span class="line-text" v-html="highlightLine(line)"></span>
          </div>
        </template>
        <div v-else-if="!loading" class="no-content">
          暂无日志内容
        </div>
      </div>
    </div>

    <div class="log-footer">
      <el-checkbox v-model="autoScroll">自动滚动</el-checkbox>
      <span class="refresh-status" v-if="autoRefresh">
        <el-icon class="is-loading"><Loading /></el-icon>
        自动刷新中 ({{ refreshInterval }}s)
      </span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Timer, FolderOpened, Loading } from '@element-plus/icons-vue'
import api from '@/api'

const props = defineProps({
  arrayId: {
    type: String,
    required: true
  }
})

// State
const selectedPath = ref('/var/log/messages')
const lineCount = ref(100)
const keyword = ref('')
const logContent = ref(null)
const logLines = ref([])
const logInfo = ref(null)
const loading = ref(false)
const discovering = ref(false)
const discoveredFiles = ref([])
const autoRefresh = ref(false)
const autoScroll = ref(true)
const refreshInterval = ref(5)

let refreshTimer = null

const commonPaths = [
  '/var/log/messages',
  '/var/log/syslog',
  '/var/log/dmesg',
  '/var/log/auth.log',
  '/var/log/secure',
  '/var/log/kern.log',
]

// Methods
function formatBytes(bytes) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

function formatTime(time) {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}

function getLineClass(line) {
  const lower = line.toLowerCase()
  if (lower.includes('error') || lower.includes('fail') || lower.includes('critical')) {
    return 'level-error'
  }
  if (lower.includes('warn')) {
    return 'level-warning'
  }
  if (lower.includes('debug')) {
    return 'level-debug'
  }
  return ''
}

function highlightLine(line) {
  if (!keyword.value) return escapeHtml(line)
  
  const escaped = escapeHtml(line)
  const regex = new RegExp(`(${escapeRegex(keyword.value)})`, 'gi')
  return escaped.replace(regex, '<mark>$1</mark>')
}

function escapeHtml(text) {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

function escapeRegex(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

async function loadLogs() {
  if (!props.arrayId || !selectedPath.value) return
  
  loading.value = true
  try {
    const params = {
      file_path: selectedPath.value,
      lines: lineCount.value,
    }
    if (keyword.value) {
      params.keyword = keyword.value
    }
    
    const res = await api.getArrayLogs(props.arrayId, params)
    logInfo.value = res.data
    logLines.value = (res.data.content || '').split('\n').filter(l => l.trim())
    
    if (autoScroll.value) {
      await nextTick()
      scrollToBottom()
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '加载日志失败')
  } finally {
    loading.value = false
  }
}

async function discoverFiles() {
  if (!props.arrayId) return
  
  discovering.value = true
  try {
    const res = await api.listLogFiles(props.arrayId, '/var/log')
    discoveredFiles.value = res.data.files || []
    ElMessage.success(`发现 ${discoveredFiles.value.length} 个日志文件`)
  } catch (e) {
    ElMessage.error('扫描失败')
  } finally {
    discovering.value = false
  }
}

function scrollToBottom() {
  if (logContent.value) {
    logContent.value.scrollTop = logContent.value.scrollHeight
  }
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    startAutoRefresh()
  } else {
    stopAutoRefresh()
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = setInterval(() => {
    loadLogs()
  }, refreshInterval.value * 1000)
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

// Lifecycle
onMounted(() => {
  loadLogs()
})

onUnmounted(() => {
  stopAutoRefresh()
})

// Watch for path changes
watch(selectedPath, () => {
  loadLogs()
})
</script>

<style scoped>
.log-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 400px;
}

.log-header {
  padding: 10px;
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;
}

.log-controls {
  margin-bottom: 10px;
}

.log-info {
  display: flex;
  gap: 10px;
}

.log-content-wrapper {
  flex: 1;
  overflow: hidden;
  background: #1e1e1e;
}

.log-content {
  height: 100%;
  overflow-y: auto;
  font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.5;
  padding: 10px;
}

.log-line {
  display: flex;
  padding: 2px 0;
  border-bottom: 1px solid #333;
}

.log-line:hover {
  background: rgba(255, 255, 255, 0.05);
}

.line-number {
  min-width: 50px;
  color: #666;
  text-align: right;
  padding-right: 10px;
  user-select: none;
  border-right: 1px solid #333;
  margin-right: 10px;
}

.line-text {
  color: #d4d4d4;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-line.level-error .line-text {
  color: #f56c6c;
}

.log-line.level-warning .line-text {
  color: #e6a23c;
}

.log-line.level-debug .line-text {
  color: #909399;
}

.log-line .line-text :deep(mark) {
  background: #d19a66;
  color: #1e1e1e;
  padding: 0 2px;
  border-radius: 2px;
}

.no-content {
  color: #666;
  text-align: center;
  padding: 40px;
}

.log-footer {
  padding: 10px;
  background: #f5f7fa;
  border-top: 1px solid #e4e7ed;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.refresh-status {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #67c23a;
  font-size: 12px;
}
</style>
