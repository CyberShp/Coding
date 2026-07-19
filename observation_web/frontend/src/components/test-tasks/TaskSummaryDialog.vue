<template>
  <el-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" title="测试任务摘要" width="700px">
    <div v-if="summaryData" class="summary-content">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="任务名称">{{ summaryData.name }}</el-descriptions-item>
        <el-descriptions-item label="测试类型">{{ summaryData.task_type }}</el-descriptions-item>
        <el-descriptions-item label="持续时间">{{ formatDuration(summaryData.duration_seconds) }}</el-descriptions-item>
        <el-descriptions-item label="总告警数">{{ summaryData.alert_total }}</el-descriptions-item>
      </el-descriptions>

      <!-- Expected vs Unexpected breakdown -->
      <div class="expectation-section" v-if="summaryData.alert_total > 0">
        <h4>告警预期分析</h4>
        <el-row :gutter="16">
          <el-col :span="8">
            <div class="summary-stat expected">
              <div class="stat-val">{{ summaryData.expected_count || 0 }}</div>
              <div class="stat-lbl">预期内告警</div>
              <div class="stat-hint">可忽略</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="summary-stat unexpected">
              <div class="stat-val">{{ summaryData.unexpected_count || (summaryData.alert_total - (summaryData.expected_count || 0)) }}</div>
              <div class="stat-lbl">非预期告警</div>
              <div class="stat-hint">需关注</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="summary-stat unknown">
              <div class="stat-val">{{ summaryData.unknown_count || 0 }}</div>
              <div class="stat-lbl">未分类</div>
              <div class="stat-hint">无匹配规则</div>
            </div>
          </el-col>
        </el-row>
        <el-alert type="info" :closable="false" style="margin-top: 12px">
          <template #title>
            <span>💡 预期告警由"告警预期规则"自动判定，可在<el-link type="primary" @click="$emit('open-rules')">规则配置</el-link>中调整</span>
          </template>
        </el-alert>
      </div>

      <h4 style="margin: 16px 0 8px">按级别统计</h4>
      <el-row :gutter="12">
        <el-col v-for="(count, level) in summaryData.by_level" :key="level" :span="6">
          <div class="summary-stat">
            <div class="stat-val" :class="level">{{ count }}</div>
            <div class="stat-lbl">{{ { info: '信息', warning: '警告', error: '错误', critical: '严重' }[level] || level }}</div>
          </div>
        </el-col>
      </el-row>

      <h4 style="margin: 16px 0 8px">按观察点统计</h4>
      <el-table :data="observerStats" size="small">
        <el-table-column label="观察点" prop="name" />
        <el-table-column label="告警数" prop="count" width="100" />
      </el-table>

      <h4 v-if="summaryData.critical_events.length > 0" style="margin: 16px 0 8px; color: #f56c6c">
        关键事件 ({{ summaryData.critical_events.length }})
      </h4>
      <div v-for="(evt, idx) in summaryData.critical_events.slice(0, 20)" :key="idx" class="critical-item">
        <el-tag type="danger" size="small">{{ evt.level }}</el-tag>
        <span>{{ evt.observer }} — {{ evt.message }}</span>
        <span class="evt-time">{{ evt.timestamp }}</span>
      </div>
    </div>
    <el-empty v-else description="加载中..." />
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'
import { getObserverName } from '@/utils/alertTranslator'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  summaryData: { type: Object, default: null },
})
defineEmits(['update:modelValue', 'open-rules'])

const observerStats = computed(() => {
  if (!props.summaryData?.by_observer) return []
  return Object.entries(props.summaryData.by_observer).map(([k, v]) => ({
    name: getObserverName(k),
    count: v,
  })).sort((a, b) => b.count - a.count)
})

function formatDuration(sec) {
  if (!sec) return '--'
  if (sec < 60) return `${Math.round(sec)}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
}
</script>

<style scoped>
.summary-content { padding: 0 8px; }
.summary-stat { text-align: center; padding: 8px; background: var(--el-fill-color-light); border-radius: 6px; }
.stat-val { font-size: 24px; font-weight: bold; }
.stat-val.error, .stat-val.critical { color: #f56c6c; }
.stat-val.warning { color: #e6a23c; }
.stat-val.info { color: #909399; }
.stat-lbl { font-size: 12px; color: var(--el-text-color-secondary); }

.critical-item {
  display: flex; gap: 8px; align-items: center; padding: 6px 0;
  border-bottom: 1px solid var(--el-border-color-lighter); font-size: 13px;
}
.evt-time { margin-left: auto; font-size: 12px; color: var(--el-text-color-secondary); }

.expectation-section {
  margin: 16px 0;
  padding: 16px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
}
.expectation-section h4 { margin: 0 0 12px; font-size: 14px; }

.summary-stat.expected { background: #e8f5e9; }
.summary-stat.expected .stat-val { color: #4caf50; }
.summary-stat.unexpected { background: #ffebee; }
.summary-stat.unexpected .stat-val { color: #f44336; }
.summary-stat.unknown { background: #fff3e0; }
.summary-stat.unknown .stat-val { color: #ff9800; }
.stat-hint { font-size: 11px; color: var(--el-text-color-secondary); margin-top: 4px; }
</style>
