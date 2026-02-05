<template>
  <div class="session-page">
    <h2 class="page-title">Session Control</h2>

    <!-- Control Panel -->
    <el-card class="control-card" shadow="never">
      <template #header>
        <span>Control</span>
      </template>
      <el-space :size="12">
        <el-button type="success" size="large" @click="startSession" :loading="loading">
          Start
        </el-button>
        <el-button type="danger" size="large" @click="stopSession">
          Stop
        </el-button>
        <el-button type="warning" size="large" @click="pauseSession">
          Pause
        </el-button>
        <el-button type="primary" size="large" @click="resumeSession">
          Resume
        </el-button>
        <el-button size="large" @click="stepSession">
          Step
        </el-button>
      </el-space>
    </el-card>

    <!-- Session Info -->
    <el-card class="info-card" shadow="never" style="margin-top: 16px;">
      <template #header>
        <span>Session Status</span>
      </template>

      <el-descriptions :column="2" border size="default">
        <el-descriptions-item label="Session ID">
          {{ sessionData?.session_id || 'None' }}
        </el-descriptions-item>
        <el-descriptions-item label="State">
          <el-tag :type="stateType">{{ sessionData?.state || 'N/A' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="Protocol">
          {{ sessionData?.protocol || 'N/A' }}
        </el-descriptions-item>
        <el-descriptions-item label="Transport">
          {{ status?.transport || 'N/A' }}
        </el-descriptions-item>
        <el-descriptions-item label="Packets Sent">
          {{ formatNumber(sessionData?.stats?.packets_sent) }}
        </el-descriptions-item>
        <el-descriptions-item label="Packets Failed">
          {{ formatNumber(sessionData?.stats?.packets_failed) }}
        </el-descriptions-item>
        <el-descriptions-item label="Send Rate">
          {{ formatNumber(sessionData?.stats?.send_rate_pps) }} pps
        </el-descriptions-item>
        <el-descriptions-item label="Throughput">
          {{ (sessionData?.stats?.send_rate_mbps || 0).toFixed(4) }} Mbps
        </el-descriptions-item>
        <el-descriptions-item label="Duration">
          {{ (sessionData?.stats?.duration_seconds || 0).toFixed(2) }}s
        </el-descriptions-item>
        <el-descriptions-item label="Success Rate">
          {{ ((sessionData?.stats?.success_rate || 0) * 100).toFixed(1) }}%
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const status = ref({})
const loading = ref(false)
let pollInterval = null

const sessionData = computed(() => status.value?.session)
const stateType = computed(() => {
  const state = sessionData.value?.state
  if (state === 'running') return 'success'
  if (state === 'paused') return 'warning'
  if (state === 'error') return 'danger'
  if (state === 'completed') return 'info'
  return ''
})

onMounted(() => {
  fetchStatus()
  pollInterval = setInterval(fetchStatus, 1000)
})

async function fetchStatus() {
  try {
    const res = await axios.get('/api/session/status')
    status.value = res.data
  } catch (e) { /* ignore */ }
}

async function startSession() {
  loading.value = true
  try {
    await axios.post('/api/session/start', {})
    ElMessage.success('Session started')
  } catch (e) {
    ElMessage.error('Start failed: ' + (e.response?.data?.detail || e.message))
  }
  loading.value = false
}

async function stopSession() {
  try {
    await axios.post('/api/session/stop')
    ElMessage.info('Session stopped')
  } catch (e) { ElMessage.error('Stop failed') }
}

async function pauseSession() {
  try {
    await axios.post('/api/session/pause')
    ElMessage.info('Session paused')
  } catch (e) { ElMessage.error('Pause failed') }
}

async function resumeSession() {
  try {
    await axios.post('/api/session/resume')
    ElMessage.info('Session resumed')
  } catch (e) { ElMessage.error('Resume failed') }
}

async function stepSession() {
  try {
    await axios.post('/api/session/step')
    ElMessage.info('Single packet sent')
  } catch (e) { ElMessage.error('Step failed') }
}

function formatNumber(n) { return (n || 0).toLocaleString() }
</script>

<style scoped>
.page-title { margin-bottom: 20px; color: #e0e0e0; }
.control-card, .info-card { background: #16213e; border: 1px solid #2a2a3e; border-radius: 8px; }
</style>
