<template>
  <el-row :gutter="20" class="stats-row">
    <el-col :span="6">
      <div class="stat-item">
        <div class="stat-value">{{ stats?.total || 0 }}</div>
        <div class="stat-label">总告警数</div>
      </div>
    </el-col>
    <el-col :span="6">
      <div class="stat-item">
        <div class="stat-value error-text">{{ (stats?.by_level?.error || 0) + (stats?.by_level?.critical || 0) }}</div>
        <div class="stat-label">错误</div>
      </div>
    </el-col>
    <el-col :span="6">
      <div class="stat-item">
        <div class="stat-value warning-text">{{ stats?.by_level?.warning || 0 }}</div>
        <div class="stat-label">警告</div>
      </div>
    </el-col>
    <el-col :span="6">
      <div class="stat-item">
        <div class="stat-value info-text">{{ stats?.by_level?.info || 0 }}</div>
        <div class="stat-label">信息</div>
      </div>
    </el-col>
  </el-row>
</template>

<script setup>
defineProps({
  stats: { type: Object, default: null },
})
</script>

<style scoped>
.stats-row {
  margin-bottom: 20px;
  padding: 16px 0;
  border-bottom: 1px solid #ebeef5;
}

.stat-item {
  text-align: center;
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: #303133;
}

.stat-label {
  font-size: 14px;
  color: #909399;
}

.error-text {
  color: #f56c6c;
}

.warning-text {
  color: #e6a23c;
}

.info-text {
  color: #909399;
}
</style>
