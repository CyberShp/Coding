<template>
  <div class="issues-page">
    <div class="page-header">
      <h2>建议反馈</h2>
      <el-button type="primary" @click="showCreate = true">新建建议</el-button>
    </div>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="待处理" name="open" />
      <el-tab-pane label="已解决" name="resolved" />
      <el-tab-pane label="不解决" name="rejected" />
      <el-tab-pane label="已采纳" name="adopted" />
    </el-tabs>

    <el-table :data="issues" v-loading="loading" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="title" label="标题" min-width="200" />
      <el-table-column prop="created_by_nickname" label="提交者" width="120">
        <template #default="{ row }">
          {{ row.created_by_nickname || row.created_by_ip || '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="提交时间" width="180">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text @click="viewIssue(row)">查看</el-button>
          <el-dropdown
            v-if="canChangeStatus(row)"
            @command="(cmd) => changeStatus(row, cmd)"
          >
            <el-button size="small" text>修改状态</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="open">待处理</el-dropdown-item>
                <el-dropdown-item command="resolved">已解决</el-dropdown-item>
                <el-dropdown-item command="rejected">不解决</el-dropdown-item>
                <el-dropdown-item command="adopted">已采纳</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <!-- Create dialog -->
    <el-dialog v-model="showCreate" title="新建建议" width="500px" @close="resetCreateForm">
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="80px">
        <el-form-item label="标题" prop="title">
          <el-input v-model="createForm.title" placeholder="简要描述" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="内容" prop="content">
          <el-input v-model="createForm.content" type="textarea" :rows="5" placeholder="详细描述改进点" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">提交</el-button>
      </template>
    </el-dialog>

    <!-- View/Status dialog -->
    <el-dialog v-model="showView" :title="selectedIssue?.title" width="600px">
      <div v-if="selectedIssue" class="issue-detail">
        <p class="content">{{ selectedIssue.content }}</p>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="提交者">
            {{ selectedIssue.created_by_nickname || selectedIssue.created_by_ip }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusType(selectedIssue.status)">{{ statusLabel(selectedIssue.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="提交时间">{{ formatDate(selectedIssue.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="更新时间">{{ formatDate(selectedIssue.updated_at) }}</el-descriptions-item>
          <el-descriptions-item label="处理备注" :span="2" v-if="selectedIssue.resolution_note">
            {{ selectedIssue.resolution_note }}
          </el-descriptions-item>
        </el-descriptions>
        <div v-if="canChangeStatus(selectedIssue)" class="status-change">
          <el-select v-model="statusChangeTo" placeholder="修改状态" style="width: 120px">
            <el-option label="待处理" value="open" />
            <el-option label="已解决" value="resolved" />
            <el-option label="不解决" value="rejected" />
            <el-option label="已采纳" value="adopted" />
          </el-select>
          <el-input v-model="resolutionNote" placeholder="备注（可选）" style="width: 200px; margin-left: 8px" />
          <el-button type="primary" size="small" @click="applyStatusChange" style="margin-left: 8px">应用</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()
const currentUserIp = ref('')

const activeTab = ref('open')
const issues = ref([])
const loading = ref(false)
const showCreate = ref(false)
const showView = ref(false)
const selectedIssue = ref(null)
const statusChangeTo = ref('')
const resolutionNote = ref('')
const createFormRef = ref(null)

const createForm = reactive({ title: '', content: '' })
const createRules = {
  title: [{ required: true, message: '请输入标题', trigger: 'blur' }],
  content: [{ required: true, message: '请输入内容', trigger: 'blur' }],
}

const statusLabels = { open: '待处理', resolved: '已解决', rejected: '不解决', adopted: '已采纳' }
const statusTypes = { open: 'warning', resolved: 'success', rejected: 'info', adopted: 'success' }

function statusLabel(s) { return statusLabels[s] || s }
function statusType(s) { return statusTypes[s] || 'info' }

function formatDate(d) {
  if (!d) return '-'
  return new Date(d).toLocaleString('zh-CN')
}

async function loadIssues() {
  loading.value = true
  try {
    const res = await api.getIssues(activeTab.value)
    issues.value = res.data || []
  } catch (e) {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

function canChangeStatus(issue) {
  return authStore.isAdmin || (currentUserIp.value && issue.created_by_ip === currentUserIp.value)
}

function viewIssue(row) {
  selectedIssue.value = row
  statusChangeTo.value = row.status
  resolutionNote.value = row.resolution_note || ''
  showView.value = true
}

async function changeStatus(row, status) {
  try {
    await api.updateIssueStatus(row.id, status)
    ElMessage.success('状态已更新')
    loadIssues()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '更新失败')
  }
}

async function applyStatusChange() {
  if (!selectedIssue.value || !statusChangeTo.value) return
  try {
    await api.updateIssueStatus(selectedIssue.value.id, statusChangeTo.value, resolutionNote.value)
    ElMessage.success('状态已更新')
    selectedIssue.value = { ...selectedIssue.value, status: statusChangeTo.value, resolution_note: resolutionNote.value }
    loadIssues()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '更新失败')
  }
}

function resetCreateForm() {
  createForm.title = ''
  createForm.content = ''
}

async function submitCreate() {
  if (!createFormRef.value) return
  await createFormRef.value.validate(async (valid) => {
    if (!valid) return
    try {
      await api.createIssue(createForm)
      ElMessage.success('提交成功')
      showCreate.value = false
      resetCreateForm()
      loadIssues()
    } catch (e) {
      ElMessage.error('提交失败')
    }
  })
}

watch(activeTab, () => loadIssues())

onMounted(async () => {
  try {
    const res = await api.getCurrentUser()
    currentUserIp.value = res.data?.ip || ''
  } catch (_) {}
  loadIssues()
})
</script>

<style scoped>
.issues-page {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0;
  font-size: 20px;
}

.issue-detail .content {
  white-space: pre-wrap;
  margin-bottom: 16px;
  line-height: 1.6;
}

.status-change {
  margin-top: 16px;
  display: flex;
  align-items: center;
}
</style>
