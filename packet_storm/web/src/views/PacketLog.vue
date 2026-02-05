<template>
  <div class="packet-log-page">
    <h2 class="page-title">Packet Log</h2>

    <el-card class="log-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>Sent Packets</span>
          <div>
            <el-button size="small" @click="exportCSV">Export CSV</el-button>
            <el-button size="small" @click="exportJSON">Export JSON</el-button>
            <el-button size="small" type="danger" @click="clearLog">Clear</el-button>
          </div>
        </div>
      </template>

      <div v-if="packets.length === 0" class="no-data">
        No packets captured yet. Start a session to see packet details.
      </div>

      <div v-else class="packet-list">
        <div
          v-for="(pkt, idx) in packets"
          :key="idx"
          class="packet-entry"
          :class="{ expanded: expandedIdx === idx }"
          @click="toggleExpand(idx)"
        >
          <div class="packet-header">
            <span class="packet-num">#{{ idx + 1 }}</span>
            <el-tag size="small" :type="pkt.anomaly ? 'warning' : ''">
              {{ pkt.anomaly || 'normal' }}
            </el-tag>
            <span class="packet-proto">{{ pkt.protocol || 'unknown' }}</span>
            <span class="packet-size">{{ pkt.size }} bytes</span>
            <span class="packet-time">{{ pkt.timestamp }}</span>
          </div>
          <div v-if="expandedIdx === idx" class="packet-hex">
            <pre>{{ pkt.hex }}</pre>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const packets = ref([])
const expandedIdx = ref(-1)

function toggleExpand(idx) {
  expandedIdx.value = expandedIdx.value === idx ? -1 : idx
}

async function exportCSV() {
  try {
    const res = await axios.post('/api/monitor/export/csv')
    ElMessage.success(`Exported to ${res.data.file}`)
  } catch (e) {
    ElMessage.error('Export failed')
  }
}

async function exportJSON() {
  try {
    const res = await axios.post('/api/monitor/export/json')
    ElMessage.success(`Exported to ${res.data.file}`)
  } catch (e) {
    ElMessage.error('Export failed')
  }
}

function clearLog() {
  packets.value = []
}
</script>

<style scoped>
.page-title { margin-bottom: 20px; color: #e0e0e0; }
.log-card { background: #16213e; border: 1px solid #2a2a3e; border-radius: 8px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.no-data { color: #666; text-align: center; padding: 40px; }
.packet-list { max-height: 70vh; overflow-y: auto; }
.packet-entry { border-bottom: 1px solid #2a2a3e; cursor: pointer; transition: background 0.2s; }
.packet-entry:hover { background: rgba(64, 158, 255, 0.05); }
.packet-header { display: flex; align-items: center; gap: 12px; padding: 10px 12px; font-size: 13px; }
.packet-num { color: #888; font-weight: 600; min-width: 40px; }
.packet-proto { color: #67C23A; }
.packet-size { color: #888; }
.packet-time { color: #555; margin-left: auto; font-size: 12px; }
.packet-hex { padding: 0 12px 12px; }
.packet-hex pre { background: #0f0f23; padding: 12px; border-radius: 4px; font-family: 'Fira Code', monospace; font-size: 11px; color: #67C23A; overflow-x: auto; white-space: pre-wrap; }
</style>
