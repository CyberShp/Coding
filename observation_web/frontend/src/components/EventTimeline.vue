<template>
  <div class="event-timeline">
    <div class="timeline-header">
      <el-select v-model="timeRange" size="small" style="width: 130px" @change="fetchData">
        <el-option label="最近 1 小时" :value="1" />
        <el-option label="最近 6 小时" :value="6" />
        <el-option label="最近 24 小时" :value="24" />
        <el-option label="最近 3 天" :value="72" />
      </el-select>
      <el-select v-model="filterCategory" size="small" placeholder="全部分类" clearable style="width: 120px" @change="fetchData">
        <el-option label="端口级" value="port" />
        <el-option label="卡件级" value="card" />
        <el-option label="系统级" value="system" />
      </el-select>
      <el-button size="small" @click="fetchData" :loading="loading">刷新</el-button>
    </div>

    <div v-loading="loading" class="timeline-body">
      <!-- Chart container -->
      <div ref="chartContainer" class="chart-container" />

      <!-- Event detail tooltip -->
      <el-empty v-if="!loading && events.length === 0" description="暂无事件" :image-size="80" />
    </div>

    <!-- Event table below chart -->
    <div v-if="events.length > 0" class="event-table-section">
      <el-table :data="events" size="small" max-height="300" stripe>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ formatTime(row.timestamp) }}</template>
        </el-table-column>
        <el-table-column label="级别" width="70">
          <template #default="{ row }">
            <span :class="'level-dot level-' + row.level" />
          </template>
        </el-table-column>
        <el-table-column label="分类" width="80" prop="category_label" />
        <el-table-column label="观察点" width="100">
          <template #default="{ row }">{{ getObserverName(row.observer_name) }}</template>
        </el-table-column>
        <el-table-column label="消息" prop="message" min-width="250" show-overflow-tooltip />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'
import api from '@/api'
import { getObserverName } from '@/utils/alertTranslator'

const props = defineProps({
  arrayId: { type: String, required: true },
})

const timeRange = ref(24)
const filterCategory = ref('')
const loading = ref(false)
const events = ref([])
const taskWindows = ref([])
const chartContainer = ref(null)
let chartInstance = null

const LEVEL_COLORS = {
  critical: '#cc0000',
  error: '#f56c6c',
  warning: '#e6a23c',
  info: '#909399',
}

const CAT_Y = { port: 1, card: 2, system: 3 }
const CAT_LABELS = { 1: '端口级', 2: '卡件级', 3: '系统级' }

async function fetchData() {
  loading.value = true
  try {
    const params = { hours: timeRange.value }
    if (filterCategory.value) params.observer = filterCategory.value
    const res = await api.getTimeline(props.arrayId, params)
    events.value = res.data.events || []
    taskWindows.value = res.data.task_windows || []
    await nextTick()
    renderChart()
  } catch (e) {
    console.error('Timeline fetch error:', e)
  } finally {
    loading.value = false
  }
}

function renderChart() {
  if (!chartContainer.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartContainer.value)
  }

  const data = events.value.map(e => ({
    value: [new Date(e.timestamp).getTime(), CAT_Y[e.category] || 3],
    itemStyle: { color: LEVEL_COLORS[e.level] || '#909399' },
    _evt: e,
  }))

  // Task window markAreas
  const markAreaData = taskWindows.value.map(tw => [{
    name: tw.name,
    xAxis: new Date(tw.started_at).getTime(),
  }, {
    xAxis: tw.ended_at ? new Date(tw.ended_at).getTime() : new Date().getTime(),
  }])

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        const e = params.data?._evt
        if (!e) return ''
        return `<b>${getObserverName(e.observer_name)}</b><br/>
          ${formatTime(e.timestamp)}<br/>
          <span style="color:${LEVEL_COLORS[e.level]}">${e.level}</span>: ${e.message}`
      },
    },
    grid: { left: 80, right: 30, top: 20, bottom: 40 },
    xAxis: {
      type: 'time',
      axisLabel: { fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      min: 0.5,
      max: 3.5,
      interval: 1,
      axisLabel: {
        formatter: (v) => CAT_LABELS[v] || '',
        fontSize: 12,
      },
    },
    series: [{
      type: 'scatter',
      symbolSize: 10,
      data,
      markArea: markAreaData.length > 0 ? {
        silent: true,
        itemStyle: { color: 'rgba(64, 158, 255, 0.08)', borderColor: '#409eff', borderWidth: 1, borderType: 'dashed' },
        data: markAreaData,
      } : undefined,
    }],
    dataZoom: [{
      type: 'inside',
      xAxisIndex: 0,
    }],
  }

  chartInstance.setOption(option, true)
}

function formatTime(ts) {
  if (!ts) return '--'
  return new Date(ts).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function handleResize() {
  chartInstance?.resize()
}

onMounted(() => {
  fetchData()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
})

watch(() => props.arrayId, () => fetchData())
</script>

<style scoped>
.event-timeline { width: 100%; }
.timeline-header { display: flex; gap: 8px; margin-bottom: 12px; align-items: center; }
.chart-container { width: 100%; height: 200px; }
.event-table-section { margin-top: 12px; }

.level-dot {
  display: inline-block;
  width: 10px; height: 10px;
  border-radius: 50%;
}
.level-critical { background: #cc0000; }
.level-error { background: #f56c6c; }
.level-warning { background: #e6a23c; }
.level-info { background: #909399; }
</style>
