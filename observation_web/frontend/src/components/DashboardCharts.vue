<template>
  <el-col :span="16">
    <el-card class="content-card chart-card">
      <template #header>
        <span>24h 异常趋势</span>
      </template>
      <v-chart :option="trendChartOption" autoresize style="height: 260px" />
    </el-card>
  </el-col>
  <el-col :span="8">
    <el-card class="content-card chart-card">
      <template #header>
        <span>阵列健康分布</span>
      </template>
      <v-chart :option="healthPieOption" autoresize style="height: 260px" />
    </el-card>
  </el-col>
</template>

<script setup>
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent])

defineProps({
  trendChartOption: { type: Object, default: () => ({}) },
  healthPieOption: { type: Object, default: () => ({}) },
})
</script>

<style scoped>
.content-card {
  margin-bottom: 20px;
}

.chart-card :deep(.el-card__body) {
  padding: 12px;
}
</style>
