<template>
  <div class="settings">
    <el-tabs v-model="activeTab">
      <!-- Array Management -->
      <el-tab-pane label="阵列管理" name="arrays">
        <el-card>
          <template #header>
            <span>阵列配置</span>
          </template>
          <p class="tab-desc">阵列管理功能请前往 <el-link type="primary" @click="$router.push('/arrays')">阵列管理</el-link> 页面</p>
        </el-card>
      </el-tab-pane>

      <!-- Observer Config -->
      <el-tab-pane label="观察点配置" name="observers">
        <el-card>
          <template #header>
            <span>观察点配置</span>
          </template>
          <el-table :data="observers" stripe>
            <el-table-column label="观察点" prop="name" />
            <el-table-column label="显示名称" prop="display" />
            <el-table-column label="描述" prop="description" />
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- Alert Rules -->
      <el-tab-pane label="告警规则" name="alerts">
        <el-card>
          <template #header>
            <span>告警规则配置</span>
          </template>
          <el-form label-width="120px">
            <el-form-item label="告警冷却时间">
              <el-input-number v-model="alertConfig.cooldown" :min="60" :max="3600" /> 秒
              <span class="form-help">相同告警在冷却时间内不重复上报</span>
            </el-form-item>
            <el-form-item label="默认告警级别">
              <el-select v-model="alertConfig.minLevel">
                <el-option label="信息 (INFO)" value="info" />
                <el-option label="警告 (WARNING)" value="warning" />
                <el-option label="错误 (ERROR)" value="error" />
              </el-select>
            </el-form-item>
            <el-form-item label="告警保留天数">
              <el-input-number v-model="alertConfig.retentionDays" :min="7" :max="365" /> 天
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveAlertConfig">保存配置</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- System -->
      <el-tab-pane label="系统设置" name="system">
        <el-card>
          <template #header>
            <span>系统信息</span>
          </template>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="系统版本">1.0.0</el-descriptions-item>
            <el-descriptions-item label="API 地址">{{ apiUrl }}</el-descriptions-item>
            <el-descriptions-item label="WebSocket">
              <el-tag :type="wsConnected ? 'success' : 'danger'">
                {{ wsConnected ? '已连接' : '未连接' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="刷新间隔">30 秒</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <el-card class="action-card">
          <template #header>
            <span>数据管理</span>
          </template>
          <el-space direction="vertical" alignment="start">
            <div class="action-item">
              <span>清理历史告警</span>
              <el-button type="warning" size="small" @click="cleanupAlerts">
                清理 30 天前的告警
              </el-button>
            </div>
          </el-space>
        </el-card>
      </el-tab-pane>

      <!-- About -->
      <el-tab-pane label="关于" name="about">
        <el-card>
          <template #header>
            <span>关于观察点监控平台</span>
          </template>
          <div class="about-content">
            <h3>观察点监控平台 v1.0.0</h3>
            <p>一个轻量级的存储阵列监控解决方案。</p>
            
            <h4>功能特性</h4>
            <ul>
              <li>多阵列集中管理</li>
              <li>实时告警推送</li>
              <li>多种观察点监测（误码、链路状态、卡修复等）</li>
              <li>灵活的自定义查询</li>
              <li>强大的正则匹配</li>
            </ul>
            
            <h4>技术栈</h4>
            <ul>
              <li>后端: FastAPI + SQLite + Paramiko</li>
              <li>前端: Vue 3 + Element Plus + ECharts</li>
              <li>通信: REST API + WebSocket</li>
            </ul>
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAlertStore } from '../stores/alerts'
import api from '../api'

const alertStore = useAlertStore()

const activeTab = ref('observers')
const apiUrl = computed(() => window.location.origin + '/api')
const wsConnected = computed(() => alertStore.wsConnected)

const observers = ref([
  { name: 'error_code', display: '误码监测', description: '监测端口和 PCIe 误码' },
  { name: 'link_status', display: '链路状态', description: '监测网络链路状态变化' },
  { name: 'card_recovery', display: '卡修复', description: '监测卡修复事件' },
  { name: 'alarm_type', display: 'AlarmType', description: '监测 AlarmType 告警' },
  { name: 'memory_leak', display: '内存泄漏', description: '检测内存持续增长' },
  { name: 'cpu_usage', display: 'CPU利用率', description: '监测 CPU 持续高负载' },
  { name: 'cmd_response', display: '命令响应', description: '监测命令响应时间' },
  { name: 'sig_monitor', display: 'sig信号', description: '监测异常信号' },
  { name: 'sensitive_info', display: '敏感信息', description: '检测日志中的敏感信息' },
])

const alertConfig = reactive({
  cooldown: 300,
  minLevel: 'info',
  retentionDays: 30,
})

function saveAlertConfig() {
  ElMessage.success('配置已保存')
}

async function cleanupAlerts() {
  await ElMessageBox.confirm(
    '确定要清理 30 天前的告警数据吗？此操作不可恢复。',
    '确认清理',
    { type: 'warning' }
  )
  
  try {
    const response = await api.http?.delete('/alerts/cleanup', { params: { days: 30 } })
    ElMessage.success(`已清理 ${response?.data?.deleted || 0} 条告警`)
  } catch (error) {
    ElMessage.error('清理失败')
  }
}
</script>

<style scoped>
.settings {
  padding: 20px;
}

.tab-desc {
  color: #909399;
}

.form-help {
  color: #909399;
  font-size: 12px;
  margin-left: 12px;
}

.action-card {
  margin-top: 20px;
}

.action-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 400px;
}

.about-content {
  line-height: 1.8;
}

.about-content h3 {
  margin-bottom: 16px;
}

.about-content h4 {
  margin: 16px 0 8px;
  color: #409eff;
}

.about-content ul {
  padding-left: 20px;
}

.about-content li {
  margin: 4px 0;
}
</style>
