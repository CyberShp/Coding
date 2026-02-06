<template>
  <div class="data-management">
    <el-card class="page-header">
      <div class="header-content">
        <h2>数据管理</h2>
        <span class="sub-title">历史告警导入 · 归档转存 · 生命周期配置</span>
      </div>
    </el-card>

    <!-- Archive Stats Overview -->
    <el-row :gutter="20" class="stats-row">
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon active">
              <el-icon><DocumentChecked /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.active_count || 0 }}</div>
              <div class="stat-label">活跃告警</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon archived">
              <el-icon><FolderChecked /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.archive_count || 0 }}</div>
              <div class="stat-label">已归档</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon storage">
              <el-icon><Box /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ formatBytes(stats.archive_size_bytes) }}</div>
              <div class="stat-label">归档大小</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon time">
              <el-icon><Clock /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.oldest_archive || '-' }}</div>
              <div class="stat-label">最早归档月份</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20">
      <!-- History Import Panel -->
      <el-col :span="12">
        <el-card class="panel">
          <template #header>
            <div class="panel-header">
              <span><el-icon><Upload /></el-icon> 历史告警导入</span>
            </div>
          </template>

          <el-form label-width="100px">
            <el-form-item label="选择阵列">
              <el-select v-model="importForm.arrayId" placeholder="请选择阵列" @change="onArraySelect">
                <el-option
                  v-for="array in connectedArrays"
                  :key="array.id"
                  :label="array.name"
                  :value="array.id"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="导入模式">
              <el-radio-group v-model="importForm.mode">
                <el-radio label="incremental">增量导入</el-radio>
                <el-radio label="full">全量导入</el-radio>
                <el-radio label="selective">选择文件</el-radio>
              </el-radio-group>
            </el-form-item>

            <el-form-item v-if="importForm.mode === 'incremental'" label="导入天数">
              <el-input-number v-model="importForm.days" :min="1" :max="30" />
            </el-form-item>

            <el-form-item v-if="importForm.mode === 'selective'" label="日志文件">
              <el-checkbox-group v-model="importForm.selectedFiles">
                <el-checkbox
                  v-for="file in logFiles"
                  :key="file.name"
                  :label="file.name"
                >
                  {{ file.name }} ({{ file.size_human }})
                </el-checkbox>
              </el-checkbox-group>
            </el-form-item>

            <!-- Sync State Display -->
            <el-form-item v-if="syncState" label="同步状态">
              <div class="sync-info">
                <el-tag type="info" size="small">
                  已导入 {{ syncState.total_imported }} 条
                </el-tag>
                <el-tag v-if="syncState.last_sync_at" type="success" size="small">
                  上次同步: {{ formatTime(syncState.last_sync_at) }}
                </el-tag>
              </div>
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                :loading="importing"
                :disabled="!importForm.arrayId"
                @click="startImport"
              >
                <el-icon><Upload /></el-icon>
                开始导入
              </el-button>
            </el-form-item>
          </el-form>

          <!-- Import Result -->
          <el-alert
            v-if="importResult"
            :title="importResult.message"
            :type="importResult.success ? 'success' : 'error'"
            show-icon
            closable
            @close="importResult = null"
          >
            <template v-if="importResult.success">
              导入 {{ importResult.imported_count }} 条，跳过 {{ importResult.skipped_count }} 条
            </template>
          </el-alert>
        </el-card>
      </el-col>

      <!-- Archive Config Panel -->
      <el-col :span="12">
        <el-card class="panel">
          <template #header>
            <div class="panel-header">
              <span><el-icon><Setting /></el-icon> 归档配置</span>
            </div>
          </template>

          <el-form label-width="120px">
            <el-form-item label="活跃保留天数">
              <el-input-number
                v-model="archiveConfig.active_retention_days"
                :min="1"
                :max="30"
              />
              <span class="form-tip">告警在主表保留的天数</span>
            </el-form-item>

            <el-form-item label="归档保留天数">
              <el-input-number
                v-model="archiveConfig.archive_retention_days"
                :min="1"
                :max="90"
              />
              <span class="form-tip">归档数据保留的天数</span>
            </el-form-item>

            <el-form-item label="启用归档">
              <el-switch v-model="archiveConfig.archive_enabled" />
            </el-form-item>

            <el-form-item label="自动清理">
              <el-switch v-model="archiveConfig.auto_cleanup" />
              <span class="form-tip">超过保留期的归档将被自动删除</span>
            </el-form-item>

            <el-form-item>
              <el-button type="primary" @click="saveArchiveConfig" :loading="savingConfig">
                保存配置
              </el-button>
              <el-button type="warning" @click="runManualArchive" :loading="archiving">
                立即归档
              </el-button>
            </el-form-item>
          </el-form>

          <!-- Archive Result -->
          <el-alert
            v-if="archiveResult"
            :title="archiveResult.message"
            type="success"
            show-icon
            closable
            @close="archiveResult = null"
          />
        </el-card>
      </el-col>
    </el-row>

    <!-- Archive Query -->
    <el-card class="panel archive-query">
      <template #header>
        <div class="panel-header">
          <span><el-icon><Search /></el-icon> 归档查询</span>
        </div>
      </template>

      <el-form :inline="true">
        <el-form-item label="阵列">
          <el-select v-model="queryForm.arrayId" placeholder="全部" clearable>
            <el-option
              v-for="array in arrays"
              :key="array.id"
              :label="array.name"
              :value="array.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="月份">
          <el-date-picker
            v-model="queryForm.yearMonth"
            type="month"
            placeholder="选择月份"
            format="YYYY-MM"
            value-format="YYYY-MM"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="queryArchiveData" :loading="querying">
            查询归档
          </el-button>
        </el-form-item>
      </el-form>

      <el-table
        v-if="archiveAlerts.length"
        :data="archiveAlerts"
        style="width: 100%"
        max-height="400"
      >
        <el-table-column prop="timestamp" label="时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.timestamp) }}
          </template>
        </el-table-column>
        <el-table-column prop="level" label="级别" width="100">
          <template #default="{ row }">
            <el-tag :type="getLevelType(row.level)" size="small">
              {{ row.level }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="observer_name" label="观察点" width="150" />
        <el-table-column prop="message" label="消息" />
      </el-table>

      <el-empty v-else-if="queriedOnce" description="暂无归档数据" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DocumentChecked, FolderChecked, Box, Clock,
  Upload, Setting, Search
} from '@element-plus/icons-vue'
import api from '@/api'

// State
const stats = ref({})
const arrays = ref([])
const logFiles = ref([])
const syncState = ref(null)
const importing = ref(false)
const importResult = ref(null)
const savingConfig = ref(false)
const archiving = ref(false)
const archiveResult = ref(null)
const querying = ref(false)
const archiveAlerts = ref([])
const queriedOnce = ref(false)

// Forms
const importForm = reactive({
  arrayId: '',
  mode: 'incremental',
  days: 7,
  selectedFiles: []
})

const archiveConfig = reactive({
  active_retention_days: 7,
  archive_retention_days: 30,
  archive_enabled: true,
  auto_cleanup: true
})

const queryForm = reactive({
  arrayId: '',
  yearMonth: ''
})

// Computed
const connectedArrays = computed(() => {
  return arrays.value.filter(a => a.status === 'connected')
})

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

function getLevelType(level) {
  const types = {
    critical: 'danger',
    error: 'danger',
    warning: 'warning',
    info: 'info'
  }
  return types[level] || 'info'
}

async function loadStats() {
  try {
    const res = await api.getArchiveStats()
    stats.value = res.data
  } catch (e) {
    console.error('Failed to load stats:', e)
  }
}

async function loadArrays() {
  try {
    const [arraysRes, statusesRes] = await Promise.all([
      api.getArrays(),
      api.getArrayStatuses()
    ])
    const statusMap = {}
    for (const s of statusesRes.data) {
      statusMap[s.array_id] = s.connected ? 'connected' : 'disconnected'
    }
    arrays.value = arraysRes.data.map(a => ({
      ...a,
      status: statusMap[a.id] || 'disconnected'
    }))
  } catch (e) {
    console.error('Failed to load arrays:', e)
  }
}

async function loadArchiveConfig() {
  try {
    const res = await api.getArchiveConfig()
    Object.assign(archiveConfig, res.data)
  } catch (e) {
    console.error('Failed to load archive config:', e)
  }
}

async function onArraySelect() {
  if (!importForm.arrayId) {
    logFiles.value = []
    syncState.value = null
    return
  }

  try {
    const [logsRes, stateRes] = await Promise.all([
      api.getLogFiles(importForm.arrayId).catch(() => ({ data: [] })),
      api.getSyncState(importForm.arrayId).catch(() => ({ data: null }))
    ])
    logFiles.value = logsRes.data || []
    syncState.value = stateRes.data
  } catch (e) {
    console.error('Failed to load array info:', e)
  }
}

async function startImport() {
  if (!importForm.arrayId) {
    ElMessage.warning('请选择阵列')
    return
  }

  importing.value = true
  importResult.value = null

  try {
    const data = {
      mode: importForm.mode,
      days: importForm.days
    }
    if (importForm.mode === 'selective') {
      data.log_files = importForm.selectedFiles
    }

    const res = await api.importHistory(importForm.arrayId, data)
    importResult.value = res.data
    
    // Refresh stats and sync state
    await Promise.all([loadStats(), onArraySelect()])
    
    ElMessage.success(importResult.value.message)
  } catch (e) {
    importResult.value = {
      success: false,
      message: e.response?.data?.detail || '导入失败'
    }
    ElMessage.error(importResult.value.message)
  } finally {
    importing.value = false
  }
}

async function saveArchiveConfig() {
  savingConfig.value = true
  try {
    await api.updateArchiveConfig(archiveConfig)
    ElMessage.success('配置已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    savingConfig.value = false
  }
}

async function runManualArchive() {
  archiving.value = true
  archiveResult.value = null
  try {
    const res = await api.runArchive()
    archiveResult.value = res.data
    await loadStats()
    ElMessage.success(archiveResult.value.message)
  } catch (e) {
    ElMessage.error('归档失败')
  } finally {
    archiving.value = false
  }
}

async function queryArchiveData() {
  querying.value = true
  queriedOnce.value = true
  archiveAlerts.value = []

  try {
    const params = {}
    if (queryForm.arrayId) params.array_id = queryForm.arrayId
    if (queryForm.yearMonth) params.year_month = queryForm.yearMonth

    const res = await api.queryArchive(params)
    archiveAlerts.value = res.data || []
  } catch (e) {
    ElMessage.error('查询失败')
  } finally {
    querying.value = false
  }
}

// Lifecycle
onMounted(async () => {
  await Promise.all([
    loadStats(),
    loadArrays(),
    loadArchiveConfig()
  ])
})
</script>

<style scoped>
.data-management {
  padding: 20px;
}

.page-header {
  margin-bottom: 20px;
}

.header-content h2 {
  margin: 0 0 5px 0;
  font-size: 20px;
}

.sub-title {
  color: #909399;
  font-size: 14px;
}

.stats-row {
  margin-bottom: 20px;
}

.stat-card {
  height: 100%;
}

.stat-content {
  display: flex;
  align-items: center;
  padding: 10px 0;
}

.stat-icon {
  width: 60px;
  height: 60px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 15px;
}

.stat-icon .el-icon {
  font-size: 28px;
  color: white;
}

.stat-icon.active {
  background: linear-gradient(135deg, #409EFF, #66b1ff);
}

.stat-icon.archived {
  background: linear-gradient(135deg, #67C23A, #85ce61);
}

.stat-icon.storage {
  background: linear-gradient(135deg, #E6A23C, #ebb563);
}

.stat-icon.time {
  background: linear-gradient(135deg, #909399, #a6a9ad);
}

.stat-value {
  font-size: 24px;
  font-weight: bold;
  color: #303133;
}

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-top: 5px;
}

.panel {
  margin-bottom: 20px;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.form-tip {
  margin-left: 10px;
  color: #909399;
  font-size: 12px;
}

.sync-info {
  display: flex;
  gap: 10px;
}

.archive-query {
  margin-top: 20px;
}
</style>
