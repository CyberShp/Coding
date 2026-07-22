<template>
  <div class="monitor-health">
    <el-card>
      <template #header>
        <div class="page-header">
          <span>监测健康度</span>
          <el-button size="small" :loading="loading" @click="load">
            <el-icon><Refresh /></el-icon>刷新
          </el-button>
        </div>
      </template>

      <div class="filter-bar">
        <el-select v-model="filterStatus" placeholder="按状态筛选" clearable size="small" style="width: 160px">
          <el-option v-for="s in statusOptions" :key="s" :label="STATUS_LABELS[s]?.label || s" :value="s" />
        </el-select>
        <el-select v-model="filterDeployedBy" placeholder="按部署人筛选" clearable filterable size="small" style="width: 180px">
          <el-option v-for="u in deployerOptions" :key="u" :label="u" :value="u" />
        </el-select>
        <span class="stale-legend">
          <span class="stale-swatch"></span>最后告警超过 {{ STALE_DAYS }} 天的部署，可能可清理
        </span>
        <span class="count-hint">共 {{ filteredRows.length }} 条部署（{{ staleCount }} 条可能可清理）</span>
      </div>

      <el-table
        :data="filteredRows"
        v-loading="loading"
        :row-class-name="rowClassName"
        empty-text="暂无部署记录"
        stripe
      >
        <el-table-column prop="template_name" label="监测模板" min-width="160" />
        <el-table-column prop="array_id" label="阵列" min-width="140" />
        <el-table-column prop="deployed_by" label="部署人" width="120">
          <template #default="{ row }">{{ row.deployed_by || '未知' }}</template>
        </el-table-column>
        <el-table-column label="版本" width="80">
          <template #default="{ row }"><code class="obs-code">v{{ row.version || 1 }}</code></template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="STATUS_LABELS[row.status]?.type || 'info'" size="small">
              {{ STATUS_LABELS[row.status]?.label || row.status || '未知' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最后告警时间" min-width="190">
          <template #default="{ row }">
            <span :class="{ 'stale-text': isStale(row) }">{{ formatTime(row.last_alert_at) }}</span>
            <el-tag v-if="isStale(row)" type="warning" size="small" effect="plain" class="stale-tag">可能可清理</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="确认时间" min-width="180">
          <template #default="{ row }">{{ formatTime(row.confirmed_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import api, { extractError } from '@/api'
import { isStaleDeployment } from './monitorHelpers'

const STALE_DAYS = 7
const STATUS_LABELS = {
  active: { label: '运行中', type: 'success' },
  paused: { label: '已暂停', type: 'info' },
  removed: { label: '已移除', type: 'info' },
  degraded: { label: '未确认', type: 'warning' },
  failed: { label: '失败', type: 'danger' },
}

const loading = ref(false)
const rows = ref([])
const filterStatus = ref('')
const filterDeployedBy = ref('')

const statusOptions = computed(() => [...new Set(rows.value.map(r => r.status).filter(Boolean))])
const deployerOptions = computed(() => [...new Set(rows.value.map(r => r.deployed_by).filter(Boolean))])

const filteredRows = computed(() => {
  return rows.value.filter(r => {
    if (filterStatus.value && r.status !== filterStatus.value) return false
    if (filterDeployedBy.value && r.deployed_by !== filterDeployedBy.value) return false
    return true
  })
})

function isStale(row) {
  return isStaleDeployment(row.last_alert_at, Date.now(), STALE_DAYS)
}

const staleCount = computed(() => filteredRows.value.filter(isStale).length)

function rowClassName({ row }) {
  return isStale(row) ? 'row-stale' : ''
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

async function load() {
  loading.value = true
  try {
    const res = await api.getMonitorHealth()
    rows.value = res.data || []
  } catch (e) {
    ElMessage.error('加载健康度失败: ' + extractError(e))
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.monitor-health {
  padding: 20px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.obs-code {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  background: var(--el-fill-color-light);
  padding: 0 5px;
  border-radius: 3px;
}
.stale-legend {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.stale-swatch {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 3px;
  background: var(--el-color-warning-light-7);
}
.count-hint {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
  margin-left: auto;
}
.stale-text {
  color: var(--el-color-warning-dark-2);
  font-weight: 500;
}
.stale-tag {
  margin-left: 8px;
}
:deep(.row-stale) {
  background: var(--el-color-warning-light-9);
}
</style>
