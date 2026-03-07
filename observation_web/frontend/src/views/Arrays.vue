<template>
  <div class="arrays-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>阵列管理</span>
          <div class="header-actions">
            <el-input
              v-model="searchIp"
              placeholder="搜索 IP"
              style="width: 200px"
              clearable
              @keyup.enter="handleSearch"
              @clear="clearSearch"
            >
              <template #append>
                <el-button @click="handleSearch">
                  <el-icon><Search /></el-icon>
                </el-button>
              </template>
            </el-input>
            <el-button @click="showAddTagDialog">
              <el-icon><Collection /></el-icon>
              添加标签
            </el-button>
            <el-button @click="downloadTemplate">
              <el-icon><Download /></el-icon>
              下载模板
            </el-button>
            <el-button @click="triggerImport" :loading="importing">
              <el-icon><Upload /></el-icon>
              批量导入
            </el-button>
            <el-button type="primary" @click="showAddDialog">
              <el-icon><Plus /></el-icon>
              添加阵列
            </el-button>
            <input
              ref="importFileRef"
              type="file"
              accept=".csv,.xlsx,.xls"
              style="display: none"
              @change="handleImportFile"
            />
          </div>
        </div>
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
        <div v-if="!isSearchMode" class="tags-grouped">
          <div v-for="group in groupedTags" :key="group.l1 ? group.l1.id : 'ungrouped'" class="tag-group">
            <!-- L1 Group Header -->
            <div v-if="group.l1" class="group-header" :style="{ borderLeftColor: group.l1.color }">
              <div class="group-title" @click="toggleGroup(group.l1.id)">
                <el-icon class="expand-icon" :class="{ expanded: expandedGroups.has(group.l1.id) }">
                  <ArrowRight />
                </el-icon>
                <span class="group-name">{{ group.l1.name }}</span>
                <el-tag size="small" effect="plain" class="group-count">{{ group.totalArrays }} 阵列</el-tag>
              </div>
              <div class="group-actions">
                <el-button text size="small" @click.stop="goToTag(group.l1.id)">查看全部</el-button>
                <el-dropdown @click.stop trigger="click" @command="(cmd) => handleTagAction(cmd, group.l1)">
                  <el-button text size="small" @click.stop>
                    <el-icon><MoreFilled /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="edit"><el-icon><Edit /></el-icon> 编辑</el-dropdown-item>
                      <el-dropdown-item command="delete" divided><el-icon><Delete /></el-icon> 删除</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </div>
            <!-- L2 Children (collapsible) -->
            <div v-show="!group.l1 || expandedGroups.has(group.l1.id)" class="group-children">
              <div class="tags-grid">
                <div v-for="tag in group.children" :key="tag.id" class="tag-card" @click="goToTag(tag.id)">
                  <div class="tag-header" :style="{ borderLeftColor: tag.color }">
                    <span class="tag-name">{{ tag.name }}</span>
                    <el-dropdown @click.stop trigger="click" @command="(cmd) => handleTagAction(cmd, tag)">
                      <el-button text size="small" @click.stop>
                        <el-icon><MoreFilled /></el-icon>
                      </el-button>
                      <template #dropdown>
                        <el-dropdown-menu>
                          <el-dropdown-item command="edit"><el-icon><Edit /></el-icon> 编辑</el-dropdown-item>
                          <el-dropdown-item command="delete" divided><el-icon><Delete /></el-icon> 删除</el-dropdown-item>
                        </el-dropdown-menu>
                      </template>
                    </el-dropdown>
                  </div>
                  <div class="tag-body">
                    <div class="tag-stat">
                      <span class="stat-value">{{ tag.array_count }}</span>
                      <span class="stat-label">阵列</span>
                    </div>
                    <div class="tag-status" v-if="tagStatuses[tag.id]">
                      <el-tag v-if="tagStatuses[tag.id].connected > 0" type="success" size="small" effect="plain">{{ tagStatuses[tag.id].connected }} 已连接</el-tag>
                      <el-tag v-if="tagStatuses[tag.id].error > 0" type="danger" size="small" effect="plain">{{ tagStatuses[tag.id].error }} 异常</el-tag>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Untagged Arrays Card (non-search mode) -->
        <div
          v-if="!isSearchMode && untaggedCount > 0"
          class="tags-grid"
          style="margin-top: 16px"
        >
          <div class="tag-card untagged-card" @click="goToUntagged">
            <div class="tag-header">
              <span class="tag-name">未分类阵列</span>
            </div>
            <div class="tag-body">
              <div class="tag-stat">
                <span class="stat-value">{{ untaggedCount }}</span>
                <span class="stat-label">阵列</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Flat view for search mode -->
        <div v-if="isSearchMode" class="tags-grid">
          <div
            v-for="tag in displayTags"
            :key="tag.id"
            class="tag-card"
            @click="goToTag(tag.id)"
          >
            <div class="tag-header" :style="{ borderLeftColor: tag.color }">
              <span class="tag-name">{{ tag.parent_name ? `${tag.parent_name} / ${tag.name}` : tag.name }}</span>
              <el-dropdown @click.stop trigger="click" @command="(cmd) => handleTagAction(cmd, tag)">
                <el-button text size="small" @click.stop>
                  <el-icon><MoreFilled /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="edit">
                      <el-icon><Edit /></el-icon> 编辑
                    </el-dropdown-item>
                    <el-dropdown-item command="delete" divided>
                      <el-icon><Delete /></el-icon> 删除
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
            <div class="tag-body">
              <div class="tag-stat">
                <span class="stat-value">{{ tag.array_count }}</span>
                <span class="stat-label">阵列</span>
              </div>
              <div class="tag-status" v-if="tagStatuses[tag.id]">
                <el-tag v-if="tagStatuses[tag.id].connected > 0" type="success" size="small" effect="plain">
                  {{ tagStatuses[tag.id].connected }} 已连接
                </el-tag>
                <el-tag v-if="tagStatuses[tag.id].error > 0" type="danger" size="small" effect="plain">
                  {{ tagStatuses[tag.id].error }} 异常
                </el-tag>
              </div>
              <div v-if="getSearchTagArrays(tag.id).length" class="search-matches">
                <div v-for="arr in getSearchTagArrays(tag.id)" :key="arr.array_id" class="match-item">
                  <span class="match-name">{{ arr.name }}</span>
                  <span class="match-ip">{{ arr.host }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Untagged Arrays Card (search mode) -->
          <div
            v-if="searchResult.untagged_arrays?.length"
            class="tag-card untagged-card"
            @click="goToUntagged"
          >
            <div class="tag-header">
              <span class="tag-name">未分类阵列</span>
            </div>
            <div class="tag-body">
              <div class="tag-stat">
                <span class="stat-value">{{ searchResult.untagged_arrays?.length }}</span>
                <span class="stat-label">阵列</span>
              </div>
              <div v-if="searchResult.untagged_arrays?.length" class="search-matches">
                <div v-for="arr in searchResult.untagged_arrays" :key="arr.array_id" class="match-item">
                  <span class="match-name">{{ arr.name }}</span>
                  <span class="match-ip">{{ arr.host }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Empty state -->
        <el-empty v-if="tags.length === 0 && untaggedCount === 0 && !loading" description="暂无阵列，点击右上角添加">
          <el-button type="primary" @click="showAddDialog">添加阵列</el-button>
        </el-empty>
      </div>
    </el-card>

    <!-- Add Array Dialog -->
    <el-dialog v-model="dialogVisible" title="添加阵列" width="500px" @keyup.enter="handleAdd">
      <el-form :model="form" :rules="rules" ref="formRef" label-width="80px" @submit.prevent="handleAdd">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="阵列名称" @keyup.enter="handleAdd" />
        </el-form-item>
        <el-form-item label="地址" prop="host">
          <el-input v-model="form.host" placeholder="IP 地址或主机名" @keyup.enter="handleAdd" />
        </el-form-item>
        <el-form-item label="端口" prop="port">
          <el-input-number v-model="form.port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" @keyup.enter="handleAdd" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="SSH 密码" @keyup.enter="handleAdd" />
        </el-form-item>
        <el-form-item label="密钥路径">
          <el-input v-model="form.key_path" placeholder="可选：SSH 密钥文件路径" @keyup.enter="handleAdd" />
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="form.tag_id" placeholder="选择标签（可选）" clearable style="width: 100%">
            <el-option
              v-for="tag in tags"
              :key="tag.id"
              :label="tag.parent_name ? `${tag.parent_name} / ${tag.name}` : tag.name"
              :value="tag.id"
            >
              <span class="tag-option">
                <span class="tag-dot" :style="{ background: tag.color }"></span>
                {{ tag.parent_name ? `${tag.parent_name} / ${tag.name}` : tag.name }}
              </span>
            </el-option>
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleAdd" :loading="submitting">确定</el-button>
      </template>
    </el-dialog>

    <!-- Add Tag Dialog -->
    <el-dialog v-model="tagDialogVisible" :title="editingTag ? '编辑标签' : '添加标签'" width="400px" @keyup.enter="handleAddTag">
      <el-form :model="tagForm" :rules="tagRules" ref="tagFormRef" label-width="80px" @submit.prevent="handleAddTag">
        <el-form-item label="上级标签">
          <el-select v-model="tagForm.parent_id" placeholder="不选则为一级标签" clearable style="width: 100%">
            <el-option
              v-for="t in l1Tags"
              :key="t.id"
              :label="t.name"
              :value="t.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="tagForm.name" placeholder="标签名称" @keyup.enter="handleAddTag" />
        </el-form-item>
        <el-form-item label="颜色">
          <el-color-picker v-model="tagForm.color" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="tagForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tagDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleAddTag" :loading="tagSubmitting">确定</el-button>
      </template>
    </el-dialog>

    <!-- Untagged Arrays Dialog -->
    <el-dialog v-model="untaggedDialogVisible" title="未分类阵列" width="800px">
      <el-table :data="untaggedArrays" v-loading="loadingUntagged" stripe max-height="400">
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="getStateType(row.state)" size="small">
              {{ getStateText(row.state) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="host" label="地址" />
        <el-table-column label="分配标签" width="180">
          <template #default="{ row }">
            <el-select
              :model-value="row.tag_id"
              placeholder="选择标签"
              size="small"
              clearable
              @change="(val) => assignTag(row, val)"
            >
              <el-option
                v-for="tag in tags"
                :key="tag.id"
                :label="tag.parent_name ? `${tag.parent_name} / ${tag.name}` : tag.name"
                :value="tag.id"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" @click="$router.push(`/arrays/${row.array_id}`)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, Search, Collection, MoreFilled, Edit, Delete, Upload, Download, ArrowRight
} from '@element-plus/icons-vue'
import api from '../api'
import { usePreferencesStore } from '../stores/preferences'

const router = useRouter()
const route = useRoute()
const preferencesStore = usePreferencesStore()

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
const submitting = ref(false)
const tagSubmitting = ref(false)
const loadingUntagged = ref(false)
const formRef = ref(null)
const tagFormRef = ref(null)
const importFileRef = ref(null)
const importing = ref(false)
const editingTag = ref(null)
const untaggedArrays = ref([])

const form = reactive({
  name: '',
  host: '',
  port: 22,
  username: 'root',
  password: '',
  key_path: '',
  tag_id: null,
})

const tagForm = reactive({
  name: '',
  color: '#409eff',
  description: '',
  parent_id: null,
})

const rules = {
  name: [{ required: true, message: '请输入阵列名称', trigger: 'blur' }],
  host: [{ required: true, message: '请输入地址', trigger: 'blur' }],
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
}

const tagRules = {
  name: [{ required: true, message: '请输入标签名称', trigger: 'blur' }],
}

const l1Tags = computed(() => tags.value.filter(t => t.level === 1))

const expandedGroups = ref(new Set())

const groupedTags = computed(() => {
  const l1Map = new Map()
  const standalone = []

  for (const tag of tags.value) {
    if (tag.level === 1) {
      l1Map.set(tag.id, { l1: tag, children: [], totalArrays: tag.array_count || 0 })
    }
  }

  for (const tag of tags.value) {
    if (tag.level === 2 || tag.level !== 1) {
      if (tag.parent_id && l1Map.has(tag.parent_id)) {
        const group = l1Map.get(tag.parent_id)
        group.children.push(tag)
        group.totalArrays += (tag.array_count || 0)
      } else {
        standalone.push(tag)
      }
    }
  }

  const groups = [...l1Map.values()]
  if (standalone.length > 0) {
    groups.push({ l1: null, children: standalone, totalArrays: standalone.reduce((s, t) => s + (t.array_count || 0), 0) })
  }
  return groups
})

watch(groupedTags, (groups) => {
  for (const g of groups) {
    if (g.l1 && !expandedGroups.value.has(g.l1.id)) {
      expandedGroups.value.add(g.l1.id)
    }
  }
}, { immediate: true })

function toggleGroup(l1Id) {
  if (expandedGroups.value.has(l1Id)) {
    expandedGroups.value.delete(l1Id)
  } else {
    expandedGroups.value.add(l1Id)
  }
}

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

function getStateType(state) {
  const types = { connected: 'success', connecting: 'warning', disconnected: 'info', error: 'danger' }
  return types[state] || 'info'
}

function getStateText(state) {
  const texts = { connected: '已连接', connecting: '连接中', disconnected: '未连接', error: '错误' }
  return texts[state] || state
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

async function handleSearch() {
  const ip = searchIp.value.trim()
  if (!ip) {
    clearSearch()
    return
  }
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

function downloadTemplate() {
  const BOM = '\uFEFF'
  const header = 'name,host,port,username,tag_l1,tag_l2,color'
  const example = '示例阵列,192.168.1.100,22,root,机房A,机柜01,#409EFF'
  const csv = BOM + header + '\n' + example + '\n'
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '阵列批量导入模板.csv'
  a.click()
  URL.revokeObjectURL(url)
}

function triggerImport() {
  importFileRef.value?.click()
}

async function handleImportFile(ev) {
  const file = ev.target?.files?.[0]
  if (!file) return
  ev.target.value = ''
  importing.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)
    const res = await api.importArrays(formData)
    const d = res.data || {}
    const msg = `导入完成：新增 ${d.created || 0} 个，跳过 ${d.skipped || 0} 个（已存在）`
    if ((d.errors || []).length > 0) {
      ElMessage.warning(`${msg}，${d.errors.length} 行有错误`)
    } else {
      ElMessage.success(msg)
    }
    await loadData()
  } catch (e) {
    ElMessage.error('导入失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    importing.value = false
  }
}

async function goToUntagged() {
  untaggedDialogVisible.value = true
  loadingUntagged.value = true
  try {
    const res = await api.getArrayStatuses()
    untaggedArrays.value = (res.data || []).filter(a => !a.tag_id)
  } finally {
    loadingUntagged.value = false
  }
}

async function assignTag(array, tagId) {
  try {
    await api.updateArray(array.array_id, { tag_id: tagId || null })
    ElMessage.success('标签已更新')
    await loadData()
    // Refresh untagged list
    untaggedArrays.value = untaggedArrays.value.filter(a => a.array_id !== array.array_id)
  } catch (e) {
    ElMessage.error('更新失败')
  }
}

function showAddDialog() {
  Object.assign(form, {
    name: '',
    host: '',
    port: 22,
    username: 'root',
    password: '',
    key_path: '',
    tag_id: null,
  })
  dialogVisible.value = true
}

async function handleAdd() {
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  submitting.value = true
  try {
    await api.createArray(form)
    ElMessage.success('添加成功')
    dialogVisible.value = false
    await loadData()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '添加失败')
  } finally {
    submitting.value = false
  }
}

function showAddTagDialog() {
  editingTag.value = null
  Object.assign(tagForm, { name: '', color: '#409eff', description: '', parent_id: null })
  tagDialogVisible.value = true
}

function handleTagAction(action, tag) {
  if (action === 'edit') {
    editingTag.value = tag
    Object.assign(tagForm, { name: tag.name, color: tag.color, description: tag.description, parent_id: tag.parent_id ?? null })
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

async function handleAddTag() {
  try {
    await tagFormRef.value.validate()
  } catch {
    return
  }

  const payload = {
    name: tagForm.name,
    color: tagForm.color,
    description: tagForm.description,
    parent_id: tagForm.parent_id || null,
    level: tagForm.parent_id ? 2 : 1,
  }

  tagSubmitting.value = true
  try {
    if (editingTag.value) {
      await api.updateTag(editingTag.value.id, payload)
      ElMessage.success('更新成功')
    } else {
      await api.createTag(payload)
      ElMessage.success('创建成功')
    }
    tagDialogVisible.value = false
    await loadData()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '操作失败')
  } finally {
    tagSubmitting.value = false
  }
}

onMounted(async () => {
  await loadData()
  if (route.path === '/arrays') {
    await preferencesStore.load()
    if (preferencesStore.defaultTagId) {
      router.replace(`/arrays/tag/${preferencesStore.defaultTagId}`)
    }
  }
})
</script>

<style scoped>
.arrays-page {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 10px;
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

.tag-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.tag-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  border-color: var(--el-color-primary-light-5);
}

.tag-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  border-left: 4px solid var(--el-color-primary);
  border-radius: 8px 8px 0 0;
}

.untagged-card .tag-header {
  border-left-color: var(--el-color-info);
}

.tag-name {
  font-weight: 500;
  font-size: 15px;
}

.tag-body {
  padding: 16px;
}

.tag-stat {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 12px;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--el-color-primary);
}

.stat-label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.tag-status {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.search-matches {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.match-item {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 13px;
}

.match-name {
  color: var(--el-text-color-primary);
}

.match-ip {
  color: var(--el-text-color-secondary);
  font-family: monospace;
}

.tag-option {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tag-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.tags-grouped {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.tag-group {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
}

.group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  border-left: 4px solid var(--el-color-primary);
}

.group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  flex: 1;
}

.expand-icon {
  transition: transform 0.2s;
  font-size: 14px;
  color: var(--el-text-color-secondary);
}

.expand-icon.expanded {
  transform: rotate(90deg);
}

.group-name {
  font-weight: 600;
  font-size: 16px;
}

.group-count {
  margin-left: 4px;
}

.group-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.group-children {
  padding: 16px;
}
</style>
