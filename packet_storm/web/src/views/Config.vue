<template>
  <div class="config-page">
    <h2 class="page-title">Configuration</h2>

    <el-row :gutter="16">
      <!-- Config Editor -->
      <el-col :span="16">
        <el-card class="config-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>Configuration Editor</span>
              <div>
                <el-button type="primary" size="small" @click="saveConfig">Save</el-button>
                <el-button size="small" @click="resetConfig">Reset</el-button>
                <el-button size="small" @click="exportConfig">Export</el-button>
              </div>
            </div>
          </template>

          <el-form label-width="200px" size="default">
            <!-- Network Section -->
            <el-divider content-position="left">Network</el-divider>
            <el-form-item label="Interface">
              <el-input v-model="config.network.interface" placeholder="eth0" />
            </el-form-item>
            <el-form-item label="Source MAC">
              <el-input v-model="config.network.src_mac" placeholder="auto" />
            </el-form-item>
            <el-form-item label="Destination MAC">
              <el-input v-model="config.network.dst_mac" />
            </el-form-item>
            <el-form-item label="Source IP">
              <el-input v-model="config.network.src_ip" />
            </el-form-item>
            <el-form-item label="Destination IP">
              <el-input v-model="config.network.dst_ip" />
            </el-form-item>
            <el-form-item label="Use IPv6">
              <el-switch v-model="config.network.use_ipv6" />
            </el-form-item>

            <!-- Protocol Section -->
            <el-divider content-position="left">Protocol</el-divider>
            <el-form-item label="Protocol Type">
              <el-select v-model="config.protocol.type">
                <el-option label="iSCSI" value="iscsi" />
                <el-option label="NVMe-oF" value="nvmeof" />
                <el-option label="NAS" value="nas" />
              </el-select>
            </el-form-item>
            <el-form-item label="Target Port">
              <el-input-number v-model="protocolPort" :min="1" :max="65535" />
            </el-form-item>

            <!-- Transport Section -->
            <el-divider content-position="left">Transport</el-divider>
            <el-form-item label="Backend">
              <el-select v-model="config.transport.backend">
                <el-option label="Scapy" value="scapy" />
                <el-option label="Raw Socket" value="raw_socket" />
                <el-option label="DPDK" value="dpdk" />
              </el-select>
            </el-form-item>
            <el-form-item label="Rate Limit">
              <el-switch v-model="config.transport.rate_limit.enabled" />
            </el-form-item>
            <el-form-item v-if="config.transport.rate_limit.enabled" label="Rate Mode">
              <el-select v-model="config.transport.rate_limit.mode">
                <el-option label="Packets/s" value="pps" />
                <el-option label="Mbps" value="mbps" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="config.transport.rate_limit.enabled" label="Rate Value">
              <el-input-number v-model="config.transport.rate_limit.value" :min="1" />
            </el-form-item>

            <!-- Execution Section -->
            <el-divider content-position="left">Execution</el-divider>
            <el-form-item label="Repeat Count">
              <el-input-number v-model="config.execution.repeat" :min="0" />
            </el-form-item>
            <el-form-item label="Interval (ms)">
              <el-input-number v-model="config.execution.interval_ms" :min="0" />
            </el-form-item>
            <el-form-item label="Duration (seconds)">
              <el-input-number v-model="config.execution.duration_seconds" :min="0" />
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <!-- JSON Preview -->
      <el-col :span="8">
        <el-card class="json-card" shadow="never">
          <template #header>
            <span>JSON Preview</span>
          </template>
          <pre class="json-preview">{{ JSON.stringify(config, null, 2) }}</pre>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const config = ref({
  network: { interface: 'eth0', src_mac: 'auto', dst_mac: 'ff:ff:ff:ff:ff:ff', src_ip: '192.168.1.100', dst_ip: '192.168.1.200', use_ipv6: false },
  protocol: { type: 'iscsi', iscsi: { target_port: 3260 }, nvmeof: { target_port: 4420 }, nas: { nfs: { target_port: 2049 }, smb: { target_port: 445 } } },
  transport: { backend: 'scapy', rate_limit: { enabled: false, mode: 'pps', value: 100000 } },
  execution: { mode: 'single', repeat: 1, interval_ms: 100, duration_seconds: 0 },
  anomalies: [],
})

const protocolPort = computed({
  get() {
    const type = config.value.protocol.type
    if (type === 'iscsi') return config.value.protocol.iscsi?.target_port || 3260
    if (type === 'nvmeof') return config.value.protocol.nvmeof?.target_port || 4420
    return 2049
  },
  set(val) {
    const type = config.value.protocol.type
    if (type === 'iscsi') config.value.protocol.iscsi.target_port = val
    else if (type === 'nvmeof') config.value.protocol.nvmeof.target_port = val
  }
})

onMounted(async () => {
  try {
    const res = await axios.get('/api/config/')
    if (res.data) config.value = res.data
  } catch (e) {
    console.log('Could not load config from server, using defaults')
  }
})

async function saveConfig() {
  try {
    await axios.post('/api/config/import', { config: config.value })
    ElMessage.success('Configuration saved')
  } catch (e) {
    ElMessage.error('Failed to save: ' + (e.response?.data?.detail || e.message))
  }
}

function resetConfig() {
  location.reload()
}

async function exportConfig() {
  const blob = new Blob([JSON.stringify(config.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'packet_storm_config.json'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.page-title { margin-bottom: 20px; color: #e0e0e0; }
.config-card, .json-card { background: #16213e; border: 1px solid #2a2a3e; border-radius: 8px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.json-preview { background: #0f0f23; padding: 16px; border-radius: 4px; font-size: 12px; color: #67C23A; overflow: auto; max-height: 70vh; white-space: pre-wrap; word-break: break-all; }
</style>
