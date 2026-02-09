<template>
  <div class="snapshot-diff">
    <div class="snap-actions">
      <el-button type="primary" size="small" @click="takeSnapshot" :loading="taking">
        拍摄快照
      </el-button>
      <el-button size="small" @click="loadSnapshots" :loading="loadingList">刷新列表</el-button>
    </div>

    <!-- Snapshot list -->
    <div v-if="snapshots.length > 0" class="snap-list">
      <el-table :data="snapshots" size="small" @selection-change="handleSelectionChange" ref="snapTable">
        <el-table-column type="selection" width="40" />
        <el-table-column label="标签" prop="label" min-width="120" />
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="观察点数" width="90">
          <template #default="{ row }">{{ Object.keys(row.data || {}).length }}</template>
        </el-table-column>
      </el-table>

      <el-button
        type="warning"
        size="small"
        style="margin-top: 8px"
        :disabled="selectedSnaps.length !== 2"
        @click="doDiff"
        :loading="diffing"
      >
        对比选中的 2 个快照
      </el-button>
    </div>
    <el-empty v-else-if="!loadingList" description="暂无快照" :image-size="60" />

    <!-- Diff result -->
    <div v-if="diffResult" class="diff-result">
      <h4>
        对比结果：{{ diffResult.snapshot_a.label }} vs {{ diffResult.snapshot_b.label }}
        <el-tag size="small" type="info">{{ diffResult.changes.length }} 项变化</el-tag>
      </h4>
      <el-table :data="diffResult.changes" size="small" v-if="diffResult.changes.length > 0">
        <el-table-column label="观察点" prop="key" width="120">
          <template #default="{ row }">{{ getObserverName(row.key) }}</template>
        </el-table-column>
        <el-table-column label="变化类型" width="90">
          <template #default="{ row }">
            <el-tag
              :type="row.change_type === 'added' ? 'success' : (row.change_type === 'removed' ? 'danger' : 'warning')"
              size="small"
            >
              {{ { added: '新增', removed: '丢失', changed: '变化' }[row.change_type] || row.change_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="之前" min-width="200">
          <template #default="{ row }">
            <span v-if="row.before" class="diff-cell before">
              {{ row.before?.level || '' }} — {{ (row.before?.message || '').substring(0, 60) }}
            </span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="之后" min-width="200">
          <template #default="{ row }">
            <span v-if="row.after" class="diff-cell after">
              {{ row.after?.level || '' }} — {{ (row.after?.message || '').substring(0, 60) }}
            </span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="两个快照完全一致" :image-size="60" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'
import { getObserverName } from '@/utils/alertTranslator'

const props = defineProps({
  arrayId: { type: String, required: true },
})

const snapshots = ref([])
const selectedSnaps = ref([])
const loadingList = ref(false)
const taking = ref(false)
const diffing = ref(false)
const diffResult = ref(null)

async function loadSnapshots() {
  loadingList.value = true
  try {
    const res = await api.getSnapshots(props.arrayId)
    snapshots.value = res.data || []
  } finally {
    loadingList.value = false
  }
}

async function takeSnapshot() {
  taking.value = true
  try {
    await api.createSnapshot(props.arrayId)
    ElMessage.success('快照已保存')
    await loadSnapshots()
  } catch (e) {
    ElMessage.error('拍摄快照失败')
  } finally {
    taking.value = false
  }
}

function handleSelectionChange(rows) {
  selectedSnaps.value = rows
}

async function doDiff() {
  if (selectedSnaps.value.length !== 2) return
  diffing.value = true
  diffResult.value = null
  try {
    const res = await api.diffSnapshots(selectedSnaps.value[0].id, selectedSnaps.value[1].id)
    diffResult.value = res.data
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || '对比失败'
    ElMessage.error(`快照对比失败: ${msg}`)
    console.error('Snapshot diff error:', e)
  } finally {
    diffing.value = false
  }
}

function formatTime(ts) {
  if (!ts) return '--'
  return new Date(ts).toLocaleString('zh-CN')
}

onMounted(loadSnapshots)
</script>

<style scoped>
.snapshot-diff { width: 100%; }
.snap-actions { display: flex; gap: 8px; margin-bottom: 12px; }
.snap-list { margin-bottom: 16px; }
.diff-result { margin-top: 16px; }
.diff-result h4 { margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
.diff-cell { font-size: 12px; }
.diff-cell.before { color: #f56c6c; }
.diff-cell.after { color: #67c23a; }
.muted { color: var(--el-text-color-placeholder); }
</style>
