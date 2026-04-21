<template>
  <!-- Operational Zones: collapsed by default -->
  <el-collapse v-model="expandedOps" class="ops-collapse">
    <!-- Performance Monitor -->
    <el-collapse-item title="性能监控" name="perf" v-if="array?.state === 'connected'">
      <PerformanceMonitor :array-id="array.array_id" />
    </el-collapse-item>

    <!-- Event Timeline -->
    <el-collapse-item title="事件时间线" name="timeline">
      <EventTimeline :array-id="array.array_id" />
    </el-collapse-item>

    <!-- Snapshot & Diff -->
    <el-collapse-item title="状态快照与对比" name="snapshot">
      <SnapshotDiff :array-id="array.array_id" />
    </el-collapse-item>

    <!-- Agent Controls -->
    <el-collapse-item name="agent">
      <template #title>
        <span>Agent 控制</span>
        <el-tag v-if="array?.agent_running" type="success" size="small" style="margin-left:8px">运行中</el-tag>
        <el-tag v-else-if="array?.agent_deployed" type="warning" size="small" style="margin-left:8px">已部署</el-tag>
        <el-tag v-else type="info" size="small" style="margin-left:8px">未部署</el-tag>
      </template>

      <div class="agent-actions">
        <el-progress
          v-if="isOperating"
          :percentage="100"
          :indeterminate="true"
          :duration="2"
          status="success"
        >
          <span>{{ operationText }}</span>
        </el-progress>
        <div class="agent-buttons">
          <el-button
            type="primary" size="small"
            :loading="deploying"
            :disabled="array?.state !== 'connected'"
            @click="handleDeployAgent"
          >部署 Agent</el-button>
          <el-button
            type="success" size="small"
            :loading="starting"
            :disabled="array?.state !== 'connected' || array?.agent_running"
            @click="handleStartAgent"
          >启动 Agent</el-button>
          <el-button
            size="small"
            :loading="restarting"
            :disabled="array?.state !== 'connected'"
            @click="handleRestartAgent"
          >重启 Agent</el-button>
          <el-button
            type="danger" size="small"
            :loading="stopping"
            :disabled="array?.state !== 'connected' || !array?.agent_running"
            @click="handleStopAgent"
          >停止 Agent</el-button>
        </div>
      </div>
    </el-collapse-item>

    <!-- Log Viewer -->
    <el-collapse-item title="在线日志查看器" name="logs" v-if="array?.state === 'connected'">
      <div class="log-viewer-wrapper">
        <LogViewer :array-id="array.array_id" />
      </div>
    </el-collapse-item>
  </el-collapse>
</template>

<script setup>
import { ref, computed, inject } from 'vue'
import { ElMessage } from 'element-plus'
import PerformanceMonitor from '@/components/PerformanceMonitor.vue'
import EventTimeline from '@/components/EventTimeline.vue'
import SnapshotDiff from '@/components/SnapshotDiff.vue'
import LogViewer from '@/components/LogViewer.vue'
import api from '@/api'

const { array, refresh } = inject('arrayDetail')

const emit = defineEmits([])

const expandedOps = ref([])
const deploying = ref(false)
const starting = ref(false)
const stopping = ref(false)
const restarting = ref(false)

const isOperating = computed(() => deploying.value || starting.value || stopping.value || restarting.value)

const operationText = computed(() => {
  if (deploying.value) return '部署中...'
  if (starting.value) return '启动中...'
  if (restarting.value) return '重启中...'
  if (stopping.value) return '停止中...'
  return ''
})

function errMsg(error, fallback) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (typeof error?.message === 'string') return error.message
  return fallback
}

async function handleDeployAgent() {
  deploying.value = true
  try {
    const res = await api.deployAgent(array.value.array_id)
    const data = res?.data ?? res
    if (data?.warnings?.length > 0) {
      ElMessage.warning('部署成功（有警告）：' + data.warnings.join('; '))
    } else {
      ElMessage.success('部署成功')
    }
    await refresh()
  } catch (error) {
    ElMessage.error(errMsg(error, '部署失败'))
  } finally {
    deploying.value = false
  }
}

async function handleStartAgent() {
  starting.value = true
  try {
    await api.startAgent(array.value.array_id)
    ElMessage.success('启动成功')
    await refresh()
  } catch (error) {
    ElMessage.error(errMsg(error, '启动失败'))
  } finally {
    starting.value = false
  }
}

async function handleRestartAgent() {
  restarting.value = true
  try {
    await api.restartAgent(array.value.array_id)
    ElMessage.success('重启成功')
    await refresh()
  } catch (error) {
    ElMessage.error(errMsg(error, '重启失败'))
  } finally {
    restarting.value = false
  }
}

async function handleStopAgent() {
  stopping.value = true
  try {
    await api.stopAgent(array.value.array_id)
    ElMessage.success('停止成功')
    await refresh()
  } catch (error) {
    ElMessage.error(errMsg(error, '停止失败'))
  } finally {
    stopping.value = false
  }
}
</script>

<style scoped>
.ops-collapse { margin-top: 4px; }

.ops-collapse :deep(.el-collapse-item__header) {
  font-weight: 600;
  font-size: 14px;
}

.agent-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.agent-buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.log-viewer-wrapper { height: 500px; }
</style>
