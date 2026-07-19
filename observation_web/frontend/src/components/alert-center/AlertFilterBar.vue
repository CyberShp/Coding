<template>
  <div class="card-header">
    <span>告警中心</span>
    <div class="filter-actions">
      <el-select
        :model-value="filters.level"
        @update:model-value="setFilter('level', $event)"
        placeholder="告警级别"
        clearable
        style="width: 120px"
      >
        <el-option label="信息" value="info" />
        <el-option label="警告" value="warning" />
        <el-option label="错误" value="error" />
        <el-option label="严重" value="critical" />
      </el-select>
      <el-select
        :model-value="filters.observer"
        @update:model-value="setFilter('observer', $event)"
        placeholder="观察点"
        clearable
        style="width: 140px"
      >
        <el-option v-for="(name, key) in OBSERVER_NAMES" :key="key" :label="name" :value="key" />
      </el-select>
      <el-select
        :model-value="filters.hours"
        @update:model-value="setFilter('hours', $event)"
        style="width: 120px"
      >
        <el-option label="最近 1 小时" :value="1" />
        <el-option label="最近 6 小时" :value="6" />
        <el-option label="最近 24 小时" :value="24" />
        <el-option label="最近 7 天" :value="168" />
      </el-select>
      <el-button type="primary" @click="$emit('search')">
        <el-icon><Search /></el-icon>
        查询
      </el-button>
      <el-button type="success" @click="$emit('export')" :loading="exporting">
        <el-icon><Download /></el-icon>
        导出
      </el-button>
      <el-switch
        :model-value="aggregateMode"
        @update:model-value="$emit('update:aggregateMode', $event)"
        active-text="聚合"
        inactive-text="平铺"
        @change="$emit('search')"
        style="margin-left: 8px"
      />
    </div>
  </div>
</template>

<script setup>
import { Search, Download } from '@element-plus/icons-vue'
import { OBSERVER_NAMES } from '@/utils/alertTranslator'

const props = defineProps({
  filters: { type: Object, required: true },
  exporting: { type: Boolean, default: false },
  aggregateMode: { type: Boolean, default: false },
})
const emit = defineEmits(['update:filters', 'update:aggregateMode', 'search', 'export'])

function setFilter(key, val) {
  emit('update:filters', { ...props.filters, [key]: val })
}
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.filter-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
