<template>
  <div class="card-inventory-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <div class="header-left">
            <span>卡件列表</span>
            <el-tag v-if="lastSync" type="info" size="small" effect="plain" class="last-sync">
              最后更新: {{ lastSync }}
            </el-tag>
            <el-tag type="warning" size="small" effect="plain" class="last-sync">
              下次自动同步: {{ nextAutoSyncText }}
            </el-tag>
          </div>
          <div class="header-actions">
            <el-input
              v-model="searchQuery"
              placeholder="搜索 型号/BoardId/CardNo/阵列名/IP（空格分隔多关键词）"
              style="width: 360px"
              clearable
              @keyup.enter="loadData"
              @clear="loadData"
            >
              <template #append>
                <el-button @click="loadData">
                  <el-icon><Search /></el-icon>
                </el-button>
              </template>
            </el-input>
            <el-button type="primary" :loading="syncing" @click="syncCards">
              <el-icon><Refresh /></el-icon>
              同步卡件
            </el-button>
          </div>
        </div>
        <div class="filter-row">
          <div class="filter-item">
            <div class="filter-top">
              <span class="filter-label">Model</span>
              <div class="filter-mini-actions">
                <el-button link type="primary" @click="selectAll('model')">全选</el-button>
                <el-button link @click="clearFilter('model')">清空</el-button>
              </div>
            </div>
            <div class="filter-resizable">
              <el-select v-model="filters.model" multiple filterable collapse-tags collapse-tags-tooltip clearable style="width: 100%">
                <el-option v-for="item in modelOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </div>
          </div>

          <div class="filter-item">
            <div class="filter-top">
              <span class="filter-label">IP</span>
              <div class="filter-mini-actions">
                <el-button link type="primary" @click="selectAll('host')">全选</el-button>
                <el-button link @click="clearFilter('host')">清空</el-button>
              </div>
            </div>
            <div class="filter-resizable">
              <el-select v-model="filters.host" multiple filterable collapse-tags collapse-tags-tooltip clearable style="width: 100%">
                <el-option v-for="item in hostOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </div>
          </div>

          <div class="filter-item">
            <div class="filter-top">
              <span class="filter-label">一级标签</span>
              <div class="filter-mini-actions">
                <el-button link type="primary" @click="selectAll('tag_l1')">全选</el-button>
                <el-button link @click="clearFilter('tag_l1')">清空</el-button>
              </div>
            </div>
            <div class="filter-resizable">
              <el-select v-model="filters.tag_l1" multiple filterable collapse-tags collapse-tags-tooltip clearable style="width: 100%">
                <el-option v-for="item in tagL1Options" :key="item" :label="item" :value="item" />
              </el-select>
            </div>
          </div>

          <div class="filter-item">
            <div class="filter-top">
              <span class="filter-label">二级标签</span>
              <div class="filter-mini-actions">
                <el-button link type="primary" @click="selectAll('tag_l2')">全选</el-button>
                <el-button link @click="clearFilter('tag_l2')">清空</el-button>
              </div>
            </div>
            <div class="filter-resizable">
              <el-select v-model="filters.tag_l2" multiple filterable collapse-tags collapse-tags-tooltip clearable style="width: 100%">
                <el-option v-for="item in tagL2Options" :key="item" :label="item" :value="item" />
              </el-select>
            </div>
          </div>

          <div class="filter-actions">
            <el-button @click="resetAllFilters">重置筛选</el-button>
          </div>
        </div>
      </template>

      <el-table :data="paginatedCards" v-loading="loading" stripe max-height="calc(100vh - 220px)">
        <el-table-column prop="board_id" label="BoardId" min-width="100" show-overflow-tooltip />
        <el-table-column prop="card_no" label="CardNo" width="80" />
        <el-table-column prop="health_state" label="HealthState" width="110">
          <template #default="{ row }">
            <el-tag
              :type="stateTagType(row.health_state, 'NORMAL')"
              size="small" effect="plain"
            >{{ row.health_state || '--' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="running_state" label="RunningState" width="120">
          <template #default="{ row }">
            <el-tag
              :type="stateTagType(row.running_state, 'RUNNING')"
              size="small" effect="plain"
            >{{ row.running_state || '--' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="model" label="Model" min-width="200" show-overflow-tooltip />
        <el-table-column prop="array_name" label="阵列名称" min-width="120" show-overflow-tooltip />
        <el-table-column prop="array_host" label="IP" width="130">
          <template #default="{ row }">
            <code>{{ row.array_host || '--' }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="tag_l1" label="一级标签" width="100">
          <template #default="{ row }">
            <span>{{ row.tag_l1 || '--' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="tag_l2" label="二级标签" width="100">
          <template #default="{ row }">
            <span>{{ row.tag_l2 || '--' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_updated" label="最后更新时间" min-width="160">
          <template #default="{ row }">
            <span>{{ formatRelativeTime(row.last_updated) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-footer">
        <span class="total-count">共 {{ allCards.length }} 条（筛选后 {{ filteredCards.length }} 条）</span>
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="filteredCards.length"
          :page-sizes="[20, 50, 100, 200]"
          layout="total, sizes, prev, pager, next, jumper"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh } from '@element-plus/icons-vue'
import api from '../api'

const AUTO_SYNC_SECONDS = 300

const loading = ref(false)
const syncing = ref(false)
const allCards = ref([])
const searchQuery = ref('')
const lastSync = ref('')
const FILTER_STORAGE_KEY = 'card_inventory_filters'
const filters = ref({
  model: [],
  host: [],
  tag_l1: [],
  tag_l2: [],
})
const currentPage = ref(1)
const pageSize = ref(50)
const nextAutoSyncAt = ref(Date.now() + AUTO_SYNC_SECONDS * 1000)
const nowTs = ref(Date.now())

const modelOptions = computed(() => [...new Set(allCards.value.map(c => (c.model || '').trim()).filter(Boolean))].sort())
const hostOptions = computed(() => [...new Set(allCards.value.map(c => (c.array_host || '').trim()).filter(Boolean))].sort())
const tagL1Options = computed(() => [...new Set(allCards.value.map(c => (c.tag_l1 || '').trim()).filter(Boolean))].sort())
const tagL2Options = computed(() => [...new Set(allCards.value.map(c => (c.tag_l2 || '').trim()).filter(Boolean))].sort())

const filteredCards = computed(() => {
  const keywords = (searchQuery.value || '').trim().toLowerCase().split(/\s+/).filter(Boolean)
  return allCards.value.filter((card) => {
    if (keywords.length) {
      const searchable = `${card.model || ''} ${card.board_id || ''} ${card.card_no || ''} ${card.array_name || ''} ${card.array_host || ''}`.toLowerCase()
      if (!keywords.every(kw => searchable.includes(kw))) {
        return false
      }
    }
    if (filters.value.model.length && !filters.value.model.includes(card.model || '')) return false
    if (filters.value.host.length && !filters.value.host.includes(card.array_host || '')) return false
    if (filters.value.tag_l1.length && !filters.value.tag_l1.includes(card.tag_l1 || '')) return false
    if (filters.value.tag_l2.length && !filters.value.tag_l2.includes(card.tag_l2 || '')) return false
    return true
  })
})

const paginatedCards = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredCards.value.slice(start, start + pageSize.value)
})

const nextAutoSyncText = computed(() => {
  const diff = Math.max(0, Math.floor((nextAutoSyncAt.value - nowTs.value) / 1000))
  const mm = String(Math.floor(diff / 60)).padStart(2, '0')
  const ss = String(diff % 60).padStart(2, '0')
  return `${mm}:${ss}`
})

async function loadData() {
  loading.value = true
  try {
    const res = await api.getCardInventory()
    allCards.value = res.data || []
    currentPage.value = 1
    updateLastSync()
  } catch (e) {
    console.error('Failed to load card inventory:', e)
    allCards.value = []
  } finally {
    loading.value = false
  }
}

function updateLastSync() {
  if (allCards.value.length > 0) {
    const dates = allCards.value
      .map(c => c.last_updated)
      .filter(Boolean)
      .sort()
      .reverse()
    if (dates.length > 0) {
      lastSync.value = new Date(dates[0]).toLocaleString('zh-CN')
    }
  }
}

function stateTagType(value, expected) {
  if (!value) return 'info'
  return String(value).toUpperCase() === expected ? 'success' : 'danger'
}

function formatRelativeTime(ts) {
  if (!ts) return '--'
  const ms = new Date(ts).getTime()
  if (Number.isNaN(ms)) return '--'
  const diffSec = Math.floor((Date.now() - ms) / 1000)
  if (diffSec < 60) return `${Math.max(diffSec, 0)} 秒前`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour} 小时前`
  return new Date(ms).toLocaleString('zh-CN')
}

function selectAll(field) {
  if (field === 'model') filters.value.model = [...modelOptions.value]
  if (field === 'host') filters.value.host = [...hostOptions.value]
  if (field === 'tag_l1') filters.value.tag_l1 = [...tagL1Options.value]
  if (field === 'tag_l2') filters.value.tag_l2 = [...tagL2Options.value]
}

function clearFilter(field) {
  filters.value[field] = []
}

function resetAllFilters() {
  filters.value = { model: [], host: [], tag_l1: [], tag_l2: [] }
}

function restoreFilters() {
  try {
    const raw = localStorage.getItem(FILTER_STORAGE_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    filters.value = {
      model: Array.isArray(parsed.model) ? parsed.model : [],
      host: Array.isArray(parsed.host) ? parsed.host : [],
      tag_l1: Array.isArray(parsed.tag_l1) ? parsed.tag_l1 : [],
      tag_l2: Array.isArray(parsed.tag_l2) ? parsed.tag_l2 : [],
    }
  } catch {
    // ignore invalid localStorage data
  }
}

async function syncCards() {
  syncing.value = true
  try {
    const res = await api.syncCardInventory()
    const d = res.data || {}
    if (d.errors && d.errors.length > 0) {
      ElMessage.warning(`同步完成: ${d.synced} 条, ${d.errors.length} 个阵列出错`)
    } else {
      ElMessage.success(`同步完成: ${d.synced} 条卡件已更新`)
    }
    await loadData()
    nextAutoSyncAt.value = Date.now() + AUTO_SYNC_SECONDS * 1000
  } catch (e) {
    ElMessage.error('同步失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    syncing.value = false
  }
}

onMounted(async () => {
  await loadData()
})

onMounted(() => {
  restoreFilters()
})

let autoSyncTimer = null
let secondTicker = null

onMounted(() => {
  autoSyncTimer = setInterval(() => {
    if (!syncing.value) {
      syncCards()
    }
  }, AUTO_SYNC_SECONDS * 1000)
  secondTicker = setInterval(() => {
    nowTs.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  if (autoSyncTimer) clearInterval(autoSyncTimer)
  if (secondTicker) clearInterval(secondTicker)
})

watch(filters, (val) => {
  localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(val))
  currentPage.value = 1
}, { deep: true })

watch(searchQuery, () => {
  currentPage.value = 1
})

watch(pageSize, () => {
  currentPage.value = 1
})
</script>

<style scoped>
.card-inventory-page {
  padding: 20px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.filter-row {
  margin-top: 12px;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  flex-wrap: wrap;
}
.filter-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.filter-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.filter-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.filter-mini-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.filter-resizable {
  min-width: 140px;
  max-width: 360px;
  width: 220px;
  resize: horizontal;
  overflow: auto;
}
.filter-actions {
  margin-left: auto;
}
.last-sync {
  font-size: 12px;
}
.table-footer {
  padding: 12px 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
