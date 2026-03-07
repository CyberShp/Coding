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
      </template>

      <el-table :data="cards" v-loading="loading" stripe max-height="calc(100vh - 220px)">
        <el-table-column prop="board_id" label="BoardId" min-width="100" show-overflow-tooltip />
        <el-table-column prop="card_no" label="CardNo" width="80" />
        <el-table-column prop="health_state" label="HealthState" width="110">
          <template #default="{ row }">
            <el-tag
              :type="row.health_state === 'Normal' ? 'success' : (row.health_state ? 'warning' : 'info')"
              size="small" effect="plain"
            >{{ row.health_state || '--' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="running_state" label="RunningState" width="120">
          <template #default="{ row }">
            <el-tag
              :type="row.running_state === 'Normal' ? 'success' : (row.running_state ? 'warning' : 'info')"
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
      </el-table>

      <div class="table-footer">
        <span class="total-count">共 {{ cards.length }} 条卡件</span>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh } from '@element-plus/icons-vue'
import api from '../api'

const loading = ref(false)
const syncing = ref(false)
const cards = ref([])
const searchQuery = ref('')
const lastSync = ref('')

async function loadData() {
  loading.value = true
  try {
    const params = {}
    if (searchQuery.value?.trim()) params.q = searchQuery.value.trim()
    const res = await api.getCardInventory(params)
    cards.value = res.data || []
    updateLastSync()
  } catch (e) {
    console.error('Failed to load card inventory:', e)
    cards.value = []
  } finally {
    loading.value = false
  }
}

function updateLastSync() {
  if (cards.value.length > 0) {
    const dates = cards.value
      .map(c => c.last_updated)
      .filter(Boolean)
      .sort()
      .reverse()
    if (dates.length > 0) {
      lastSync.value = new Date(dates[0]).toLocaleString('zh-CN')
    }
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
  } catch (e) {
    ElMessage.error('同步失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    syncing.value = false
  }
}

onMounted(loadData)
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
.last-sync {
  font-size: 12px;
}
.table-footer {
  padding: 12px 0;
  text-align: right;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
