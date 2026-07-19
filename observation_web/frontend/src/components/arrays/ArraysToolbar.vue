<template>
  <div class="card-header">
    <span>阵列管理</span>
    <div class="header-actions">
      <el-input
        :model-value="searchIp"
        @update:model-value="$emit('update:searchIp', $event)"
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
      <el-button @click="$emit('add-tag')">
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
      <el-button type="primary" @click="$emit('add-array')">
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

<script setup>
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Collection, Upload, Download } from '@element-plus/icons-vue'
import api from '../../api'

const props = defineProps({
  searchIp: { type: String, default: '' },
})
const emit = defineEmits(['update:searchIp', 'search', 'clear', 'add-tag', 'add-array', 'reload'])

const importFileRef = ref(null)
const importing = ref(false)

function handleSearch() {
  const ip = (props.searchIp || '').trim()
  if (!ip) {
    clearSearch()
    return
  }
  emit('search', ip)
}

function clearSearch() {
  emit('update:searchIp', '')
  emit('clear')
}

function downloadTemplate() {
  const BOM = '\uFEFF'
  const header = 'name,host,port,username,password,tag_l1,tag_l2'
  const example = '示例阵列,192.168.1.100,22,root,your_password,机房A,机柜01'
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
    const msg = `导入完成：新增 ${d.created || 0}，跳过 ${d.skipped || 0}（已存在），无效 ${d.invalid || 0}，共 ${d.total_rows || 0} 行`
    if ((d.errors || []).length > 0) {
      ElMessage.warning(`${msg}，${d.errors.length} 行有错误`)
      const reasonMap = {
        host_already_exists: '主机地址已存在',
        name_and_host_empty: '名称和地址均为空',
        name_empty: '名称为空',
        host_empty: '地址为空',
        parse_error: '行数据解析失败',
      }
      const lines = d.errors
        .slice(0, 30)
        .map(e => `第 ${e.row || '?'} 行: ${reasonMap[e.reason] || e.reason || '未知错误'}`)
      const tail = d.errors.length > 30 ? `\n... 其余 ${d.errors.length - 30} 行错误未展示` : ''
      await ElMessageBox.alert(lines.join('\n') + tail, '批量导入错误明细', {
        type: 'warning',
        confirmButtonText: '知道了',
      })
    } else {
      ElMessage.success(msg)
    }
    emit('reload')
  } catch (e) {
    ElMessage.error('导入失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    importing.value = false
  }
}
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 10px;
}
</style>
