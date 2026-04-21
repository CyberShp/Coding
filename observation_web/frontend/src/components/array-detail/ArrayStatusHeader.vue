<template>
  <!-- Zone 1: Status Strip + F203 Heartbeat + F204 Observer Map -->
  <div>
    <div class="status-strip">
      <span class="status-dot" :class="`dot-${getStateType(array?.state)}`"></span>
      <span class="strip-name">{{ array?.name }}</span>
      <span class="strip-separator">|</span>
      <span class="strip-ip">{{ array?.host }}:{{ array?.port }}</span>
      <span class="strip-separator">|</span>
      <span class="strip-mode">{{ enrollmentModeText }}</span>
      <div class="strip-tags">
        <el-tag
          v-for="w in watchers"
          :key="w.ip"
          :style="{ borderColor: w.color, color: w.color }"
          effect="plain"
          size="small"
          class="watcher-tag"
        >{{ w.nickname || w.ip }}</el-tag>
        <el-select
          v-model="array.tag_id"
          placeholder="标签"
          size="small"
          clearable
          style="width: 140px"
          @change="handleTagChange"
        >
          <el-option
            v-for="tag in tags"
            :key="tag.id"
            :label="tag.parent_name ? `${tag.parent_name} / ${tag.name}` : tag.name"
            :value="tag.id"
          />
        </el-select>
      </div>
      <!-- F203: Collection Heartbeat Indicator -->
      <div class="heartbeat-badge" :class="heartbeatState">
        <span class="heartbeat-dot"></span>
        <span class="heartbeat-text">{{ heartbeatLabel }}</span>
      </div>
    </div>

    <!-- F204: Observer Activity Map -->
    <div v-if="observerMapEntries.length > 0" class="observer-map">
      <el-tooltip
        v-for="obs in observerMapEntries"
        :key="obs.name"
        :content="obs.tooltip"
        placement="top"
      >
        <span class="obs-dot" :class="obs.dotClass">
          <span class="obs-label">{{ obs.shortName }}</span>
        </span>
      </el-tooltip>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, inject } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const { array, tags, watchers } = inject('arrayDetail')

// ───── Tag change ─────
async function handleTagChange(tagId) {
  if (!array.value?.array_id) return
  try {
    await api.updateArray(array.value.array_id, { tag_id: tagId || null })
    ElMessage.success('标签已更新')
  } catch (e) {
    const detail = e?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '更新失败')
  }
}

// ───── Zone 1: Status ─────
const enrollmentModeText = computed(() => {
  const mode = array.value?.enrollment_mode || array.value?.collect_mode
  const map = { ssh_only: 'SSH only', agent_preferred: 'Agent 优先', agent_only: 'Agent only' }
  return map[mode] || 'SSH only'
})

function getStateType(state) {
  const types = { connected: 'success', connecting: 'warning', disconnected: 'info', error: 'danger' }
  return types[state] || 'info'
}

// ───── F203: Collection Heartbeat ─────
const heartbeatAgeMs = ref(0)
let heartbeatTimer = null

function updateHeartbeatAge() {
  const ts = array.value?.last_refresh || array.value?.last_heartbeat_at
  if (!ts) { heartbeatAgeMs.value = Infinity; return }
  heartbeatAgeMs.value = Date.now() - new Date(ts).getTime()
}

const heartbeatState = computed(() => {
  const interval = (array.value?.collect_interval_s || 60) * 1000
  const age = heartbeatAgeMs.value
  if (age === Infinity) return 'hb-interrupted'
  if (age < interval * 2) return 'hb-active'
  if (age < interval * 5) return 'hb-delayed'
  return 'hb-interrupted'
})

const heartbeatLabel = computed(() => {
  const age = heartbeatAgeMs.value
  if (age === Infinity) return '未采集'
  if (age < 60000) return `${Math.round(age / 1000)}s`
  if (age < 3600000) return `${Math.round(age / 60000)}m`
  return `${Math.round(age / 3600000)}h`
})

// ───── F204: Observer Activity Map ─────
const OBSERVER_SHORT_NAMES = {
  alarm_type: 'Alarm', disk_smart: 'SMART', rebuild_status: 'Rebuild',
  bbu_status: 'BBU', fan_temp: 'Fan', pcie_error: 'PCIe',
  controller_status: 'Ctrl', enclosure_status: 'Encl', pool_status: 'Pool', card_info: 'Card',
}

const observerMapEntries = computed(() => {
  const obsStatus = array.value?.observer_status || {}
  return Object.entries(obsStatus).map(([name, info]) => {
    const lastTs = info.last_active_ts ? new Date(info.last_active_ts) : null
    const ageMs = lastTs ? Date.now() - lastTs.getTime() : Infinity
    const isAlerting = info.status === 'error' || info.status === 'critical'
    let dotClass = 'obs-gray'
    if (isAlerting) dotClass = 'obs-red'
    else if (ageMs < 3600000) dotClass = 'obs-green'
    const ageText = lastTs
      ? (ageMs < 60000 ? `${Math.round(ageMs/1000)}s ago`
        : ageMs < 3600000 ? `${Math.round(ageMs/60000)}m ago`
        : `${Math.round(ageMs/3600000)}h ago`)
      : '无数据'
    return {
      name,
      shortName: OBSERVER_SHORT_NAMES[name] || name.slice(0, 6),
      dotClass,
      tooltip: `${name}: ${info.status || 'unknown'} (${ageText})`,
    }
  })
})

onMounted(() => {
  updateHeartbeatAge()
  heartbeatTimer = setInterval(updateHeartbeatAge, 1000)
})

onUnmounted(() => {
  if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null }
})
</script>

<style scoped>
.status-strip {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 16px; background: #fafafa;
  border-bottom: 1px solid #ebeef5; border-radius: 6px;
  font-size: 13px; flex-wrap: wrap; min-height: 40px;
}
.strip-name { font-weight: 600; font-size: 14px; color: #303133; }
.strip-ip { color: #606266; font-family: 'SF Mono', 'Fira Code', monospace; }
.strip-mode { color: #909399; font-size: 12px; }
.strip-separator { color: #dcdfe6; font-size: 12px; }
.strip-tags { display: flex; align-items: center; gap: 6px; margin-left: auto; }
.watcher-tag { font-size: 11px; }

.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.dot-success { background: #67c23a; box-shadow: 0 0 6px rgba(103, 194, 58, 0.5); }
.dot-warning { background: #e6a23c; box-shadow: 0 0 6px rgba(230, 162, 60, 0.5); }
.dot-danger  { background: #f56c6c; box-shadow: 0 0 6px rgba(245, 108, 108, 0.5); }
.dot-info    { background: #909399; }

/* F203 */
.heartbeat-badge {
  display: flex; align-items: center; gap: 5px;
  padding: 2px 10px; border-radius: 12px;
  font-size: 11px; font-weight: 500; margin-left: 8px; white-space: nowrap;
}
.heartbeat-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
.hb-active { background: #f0fdf4; color: #16a34a; }
.hb-active .heartbeat-dot { background: #16a34a; animation: hb-pulse 2s infinite; }
.hb-delayed { background: #fffbeb; color: #d97706; }
.hb-delayed .heartbeat-dot { background: #d97706; }
.hb-interrupted { background: #fef2f2; color: #dc2626; }
.hb-interrupted .heartbeat-dot { background: #dc2626; }
@keyframes hb-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.7); }
}

/* F204 */
.observer-map {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 16px; flex-wrap: wrap; border-bottom: 1px solid #f0f0f0;
}
.obs-dot {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 8px; border-radius: 10px; font-size: 11px;
  cursor: default; transition: all 0.2s;
}
.obs-dot:hover { transform: scale(1.05); }
.obs-label { font-weight: 500; }
.obs-green { background: #f0fdf4; color: #16a34a; }
.obs-green::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: #16a34a; display: inline-block; }
.obs-gray { background: #f5f5f5; color: #8c8c8c; }
.obs-gray::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: #8c8c8c; display: inline-block; }
.obs-red { background: #fef2f2; color: #dc2626; }
.obs-red::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: #dc2626; display: inline-block; animation: obs-blink 1s infinite; }
@keyframes obs-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
</style>
