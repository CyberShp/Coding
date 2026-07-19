<template>
  <div class="arrays-page">
    <el-card>
      <template #header>
        <ArraysToolbar
          v-model:search-ip="searchIp"
          @search="handleSearch"
          @clear="clearSearch"
          @add-tag="showAddTagDialog"
          @add-array="showAddDialog"
          @reload="loadData"
        />
      </template>

      <!-- Tags Grid View -->
      <div v-loading="loading" class="tags-container">
        <!-- Search results mode -->
        <el-alert
          v-if="isSearchMode"
          :title="`搜索 '${activeSearchIp}' 的结果：找到 ${searchResult.total_count || 0} 个阵列`"
          type="info"
          show-icon
          closable
          @close="clearSearch"
          class="search-alert"
        />

        <!-- Grouped Tags View -->
        <TagGroupList v-if="!isSearchMode" />

        <!-- Flat view for search mode -->
        <div v-if="isSearchMode" class="tags-grid">
          <TagCard
            v-for="tag in displayTags"
            :key="tag.id"
            :tag="tag"
            :matches="getSearchTagArrays(tag.id)"
            show-parent-name
          />

          <!-- Untagged Arrays Card (search mode) -->
          <TagCard
            v-if="searchResult.untagged_arrays?.length"
            untagged
            :count="searchResult.untagged_arrays?.length || 0"
            :matches="searchResult.untagged_arrays || []"
          />
        </div>

        <!-- Empty state -->
        <el-empty v-if="tags.length === 0 && untaggedCount === 0 && !loading" description="暂无阵列，点击右上角添加">
          <el-button type="primary" @click="showAddDialog">添加阵列</el-button>
        </el-empty>
      </div>
    </el-card>

    <AddArrayDialog v-model="dialogVisible" :tags="tags" @created="loadData" />

    <TagFormDialog v-model="tagDialogVisible" :editing-tag="editingTag" :l1-tags="l1Tags" @saved="loadData" />

    <UntaggedArraysDialog v-model="untaggedDialogVisible" :tags="tags" @changed="loadData" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, provide } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import ArraysToolbar from '@/components/arrays/ArraysToolbar.vue'
import TagGroupList from '@/components/arrays/TagGroupList.vue'
import TagCard from '@/components/arrays/TagCard.vue'
import AddArrayDialog from '@/components/arrays/AddArrayDialog.vue'
import TagFormDialog from '@/components/arrays/TagFormDialog.vue'
import UntaggedArraysDialog from '@/components/arrays/UntaggedArraysDialog.vue'

const router = useRouter()

const loading = ref(false)
const tags = ref([])
const allStatuses = ref([])
const searchIp = ref('')
const activeSearchIp = ref('')
const searchResult = ref({})
const isSearchMode = computed(() => !!activeSearchIp.value)

const dialogVisible = ref(false)
const tagDialogVisible = ref(false)
const untaggedDialogVisible = ref(false)
const editingTag = ref(null)

const l1Tags = computed(() => tags.value.filter(t => t.level === 1))

const displayTags = computed(() => {
  if (!isSearchMode.value) return tags.value
  const tagIds = new Set((searchResult.value.tags || []).map(t => t.tag_id))
  return tags.value.filter(t => tagIds.has(t.id))
})

const tagStatuses = computed(() => {
  const result = {}
  for (const s of allStatuses.value) {
    const tid = s.tag_id || 0
    if (!result[tid]) {
      result[tid] = { connected: 0, disconnected: 0, error: 0 }
    }
    if (s.state === 'connected') result[tid].connected++
    else if (s.state === 'error') result[tid].error++
    else result[tid].disconnected++
  }
  return result
})

const untaggedCount = computed(() => {
  return allStatuses.value.filter(s => !s.tag_id).length
})

function getSearchTagArrays(tagId) {
  const tagData = (searchResult.value.tags || []).find(t => t.tag_id === tagId)
  return tagData?.arrays || []
}

async function loadTags() {
  try {
    const res = await api.getTags()
    tags.value = res.data || []
  } catch (e) {
    console.error('Failed to load tags:', e)
  }
}

async function loadStatuses() {
  try {
    const res = await api.getArrayStatuses()
    allStatuses.value = res.data || []
  } catch (e) {
    console.error('Failed to load statuses:', e)
  }
}

async function loadData() {
  loading.value = true
  try {
    await Promise.all([loadTags(), loadStatuses()])
  } finally {
    loading.value = false
  }
}

async function handleSearch(ip) {
  activeSearchIp.value = ip
  try {
    const res = await api.searchArrays(ip)
    searchResult.value = res.data
  } catch (e) {
    ElMessage.error('搜索失败')
  }
}

function clearSearch() {
  searchIp.value = ''
  activeSearchIp.value = ''
  searchResult.value = {}
}

function goToTag(tagId) {
  router.push(`/arrays/tag/${tagId}`)
}

function goToUntagged() {
  untaggedDialogVisible.value = true
}

function showAddDialog() {
  dialogVisible.value = true
}

function showAddTagDialog() {
  editingTag.value = null
  tagDialogVisible.value = true
}

function handleTagAction(action, tag) {
  if (action === 'edit') {
    editingTag.value = tag
    tagDialogVisible.value = true
  } else if (action === 'delete') {
    deleteTag(tag)
  }
}

async function deleteTag(tag) {
  await ElMessageBox.confirm(`确定要删除标签 "${tag.name}" 吗？阵列不会被删除，只会变为未分类。`, '确认删除', { type: 'warning' })
  try {
    await api.deleteTag(tag.id)
    ElMessage.success('删除成功')
    await loadData()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

provide('arraysCtx', {
  tags,
  tagStatuses,
  untaggedCount,
  goToTag,
  goToUntagged,
  handleTagAction,
})

onMounted(async () => {
  await loadData()
})
</script>

<style scoped>
.arrays-page {
  padding: 20px;
}

.tags-container {
  min-height: 200px;
}

.search-alert {
  margin-bottom: 16px;
}

.tags-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
</style>
