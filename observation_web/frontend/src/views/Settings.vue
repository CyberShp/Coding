<template>
  <div class="settings">
    <!-- Admin login entry -->
    <el-card class="admin-card" v-if="!authStore.isAdmin">
      <div class="admin-entry">
        <span>需要管理员权限操作（如 Issue 状态变更）时，请先登录</span>
        <el-button type="primary" @click="$router.push('/admin/login')">管理员登录</el-button>
      </div>
    </el-card>
    <el-card class="admin-card" v-else>
      <div class="admin-entry">
        <span>已登录管理员</span>
        <el-button type="default" @click="handleLogout">退出登录</el-button>
      </div>
    </el-card>

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

      <el-tab-pane label="个人偏好" name="preferences">
        <el-card>
          <template #header>
            <span>个人视图偏好</span>
          </template>
          <el-form label-width="140px">
            <el-form-item label="默认标签筛选">
              <el-select
                v-model="preferences.default_tag_id"
                placeholder="不筛选（显示全部）"
                clearable
                style="width: 280px"
              >
                <el-option v-for="tag in tags" :key="tag.id"
                  :label="tag.parent_name ? `${tag.parent_name} / ${tag.name}` : tag.name"
                  :value="tag.id" />
              </el-select>
              <div class="form-help">仪表盘与阵列管理将默认按此标签筛选阵列</div>
            </el-form-item>
            <el-divider />
            <el-form-item label="关注标签">
              <el-select v-model="preferences.watched_tag_ids" multiple collapse-tags collapse-tags-tooltip
                placeholder="选择要关注的标签" style="width: 380px">
                <el-option v-for="tag in tags" :key="tag.id"
                  :label="tag.parent_name ? `${tag.parent_name} / ${tag.name}` : tag.name"
                  :value="tag.id" />
              </el-select>
              <div class="form-help">个人视图模式下，只显示关注标签下的阵列和告警</div>
            </el-form-item>
            <el-form-item label="关注阵列">
              <el-select v-model="preferences.watched_array_ids" multiple collapse-tags collapse-tags-tooltip
                filterable placeholder="选择要关注的阵列" style="width: 380px">
                <el-option v-for="arr in allArrays" :key="arr.array_id"
                  :label="`${arr.name} (${arr.host})`"
                  :value="arr.array_id" />
              </el-select>
              <div class="form-help">个人视图模式下，只显示已关注阵列的告警</div>
            </el-form-item>
            <el-form-item label="关注观察点">
              <el-select v-model="preferences.watched_observers" multiple collapse-tags collapse-tags-tooltip
                placeholder="选择要关注的观察点" style="width: 380px">
                <el-option v-for="obs in observerOptions" :key="obs" :label="obs" :value="obs" />
              </el-select>
              <div class="form-help">个人视图模式下，只显示选中观察点的告警（留空则显示所有）</div>
            </el-form-item>
            <el-form-item label="静音观察点">
              <el-select v-model="preferences.muted_observers" multiple collapse-tags collapse-tags-tooltip
                placeholder="选择要静音的观察点" style="width: 380px">
                <el-option v-for="obs in observerOptions" :key="obs" :label="obs" :value="obs" />
              </el-select>
              <div class="form-help">这些观察点的告警将不会发出提示音</div>
            </el-form-item>
            <el-form-item label="告警提示音">
              <el-switch v-model="preferences.alert_sound" />
              <div class="form-help">关闭后所有告警都不会发出提示音</div>
            </el-form-item>
            <el-divider />
            <el-form-item label="仪表盘默认标签">
              <el-select
                v-model="preferences.dashboard_l1_tag_id"
                placeholder="不筛选（显示全部）"
                clearable
                style="width: 280px"
              >
                <el-option v-for="tag in l1Tags" :key="tag.id"
                  :label="tag.name"
                  :value="tag.id" />
              </el-select>
              <div class="form-help">仪表盘默认按此一级标签筛选阵列，不受全局/个人视图影响</div>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingPrefs" @click="savePreferences">保存偏好</el-button>
            </el-form-item>
          </el-form>
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

      <!-- AI Settings (admin only) -->
      <el-tab-pane v-if="authStore.isAdmin" label="AI 设置" name="ai">
        <el-card>
          <template #header>
            <div class="ai-header">
              <span>AI 智能解读配置</span>
              <el-tag :type="aiConfig.enabled ? 'success' : 'info'" size="small" effect="dark">
                {{ aiConfig.enabled ? '已启用' : '未启用' }}
              </el-tag>
            </div>
          </template>
          <el-form label-width="140px" :model="aiConfig">
            <el-form-item label="启用 AI">
              <el-switch v-model="aiConfig.enabled" />
              <span class="form-help">开启后，告警详情中可使用 AI 智能解读功能</span>
            </el-form-item>
            <el-form-item label="API 地址">
              <el-input
                v-model="aiConfig.api_url"
                placeholder="http://192.168.1.100:11434/v1/chat/completions"
                clearable
              >
                <template #append>
                  <el-button :loading="fetchingModels" @click="fetchModels">
                    获取模型
                  </el-button>
                </template>
              </el-input>
              <span class="form-help">兼容 OpenAI 接口格式的 API 地址</span>
            </el-form-item>
            <el-form-item label="API Key">
              <el-input
                v-model="aiConfig.api_key"
                placeholder="留空表示不需要认证"
                show-password
                clearable
              />
            </el-form-item>
            <el-form-item label="代理设置">
              <el-radio-group v-model="aiConfig.proxy_mode">
                <el-radio value="system">跟随系统代理</el-radio>
                <el-radio value="none">不使用代理（直连）</el-radio>
              </el-radio-group>
              <span class="form-help">设置 AI API 请求的代理方式</span>
            </el-form-item>
            <el-form-item label="模型">
              <el-select
                v-model="aiConfig.model"
                filterable
                allow-create
                placeholder="选择或输入模型名称"
                style="width: 100%"
                :loading="fetchingModels"
              >
                <el-option
                  v-for="m in availableModels"
                  :key="m.id"
                  :label="m.name"
                  :value="m.id"
                />
              </el-select>
              <span class="form-help">可输入 API 地址后点击「获取模型」自动加载可用模型</span>
            </el-form-item>
            <el-form-item label="超时时间">
              <el-input-number v-model="aiConfig.timeout" :min="5" :max="120" /> 秒
            </el-form-item>
            <el-form-item label="最大输出长度">
              <el-input-number v-model="aiConfig.max_tokens" :min="100" :max="4096" :step="100" /> tokens
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingAI" @click="saveAIConfig">保存配置</el-button>
              <el-button :loading="testingAI" @click="testAIConnection">测试连接</el-button>
            </el-form-item>
          </el-form>
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
import { useAuthStore } from '../stores/auth'
import { usePreferencesStore } from '../stores/preferences'
import api from '../api'

const alertStore = useAlertStore()
const authStore = useAuthStore()
const preferencesStore = usePreferencesStore()

// Personal preferences
const tags = ref([])
const allArrays = ref([])
const observerOptions = ref([
  'alarm_type', 'card_info', 'card_recovery', 'disk_error', 'eth_link',
  'fc_link', 'log_watcher', 'port_error', 'process_monitor',
])
const l1Tags = computed(() => tags.value.filter(t => t.level === 1))
const preferences = reactive({
  default_tag_id: null,
  watched_tag_ids: [],
  watched_array_ids: [],
  watched_observers: [],
  muted_observers: [],
  alert_sound: true,
  dashboard_l1_tag_id: null,
})
const savingPrefs = ref(false)

async function loadPreferences() {
  try {
    const res = await api.getPreferences()
    const d = res.data || {}
    preferences.default_tag_id = d.default_tag_id ?? null
    preferences.watched_tag_ids = d.watched_tag_ids || []
    preferences.watched_array_ids = d.watched_array_ids || []
    preferences.watched_observers = d.watched_observers || []
    preferences.muted_observers = d.muted_observers || []
    preferences.alert_sound = d.alert_sound !== false
    preferences.dashboard_l1_tag_id = d.dashboard_l1_tag_id ?? null
  } catch {
    preferences.default_tag_id = null
  }
}

async function loadAllArrays() {
  try {
    const res = await api.getArrayStatuses()
    allArrays.value = res.data || []
  } catch {
    allArrays.value = []
  }
}

async function loadTagsForPrefs() {
  try {
    const res = await api.getTags()
    tags.value = res.data || []
  } catch {
    tags.value = []
  }
}

async function savePreferences() {
  savingPrefs.value = true
  try {
    await preferencesStore.update({
      default_tag_id: preferences.default_tag_id,
      watched_tag_ids: preferences.watched_tag_ids,
      watched_array_ids: preferences.watched_array_ids,
      watched_observers: preferences.watched_observers,
      muted_observers: preferences.muted_observers,
      alert_sound: preferences.alert_sound,
      dashboard_l1_tag_id: preferences.dashboard_l1_tag_id,
    })
    ElMessage.success('偏好已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    savingPrefs.value = false
  }
}

function handleLogout() {
  authStore.logout()
  ElMessage.success('已退出登录')
}

const activeTab = ref('alerts')
const apiUrl = computed(() => window.location.origin + '/api')
const wsConnected = computed(() => alertStore.wsConnected)

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

// ---- AI Settings (admin only) ----
const aiConfig = reactive({
  enabled: false,
  api_url: '',
  api_key: '',
  proxy_mode: 'system',
  model: '',
  timeout: 15,
  max_tokens: 800,
})
const availableModels = ref([])
const fetchingModels = ref(false)
const savingAI = ref(false)
const testingAI = ref(false)

async function loadAIConfig() {
  if (!authStore.isAdmin) return
  try {
    const { data } = await api.getAIConfig()
    Object.assign(aiConfig, data)
  } catch {
    // Not admin or config not available — ignore
  }
}

async function fetchModels() {
  if (!aiConfig.api_url) {
    ElMessage.warning('请先填写 API 地址')
    return
  }
  fetchingModels.value = true
  try {
    // Save current url/key first so backend uses latest values
    await api.updateAIConfig({
      api_url: aiConfig.api_url,
      api_key: aiConfig.api_key,
      proxy_mode: aiConfig.proxy_mode,
    })
    const { data } = await api.getAIModels()
    availableModels.value = data || []
    if (data.length > 0) {
      ElMessage.success(`获取到 ${data.length} 个可用模型`)
    } else {
      ElMessage.info('API 返回了空的模型列表')
    }
  } catch (e) {
    const detail = e.response?.data?.detail || e.message
    ElMessage.error('获取模型失败: ' + detail)
    availableModels.value = []
  } finally {
    fetchingModels.value = false
  }
}

async function saveAIConfig() {
  savingAI.value = true
  try {
    const { data } = await api.updateAIConfig({
      enabled: aiConfig.enabled,
      api_url: aiConfig.api_url,
      api_key: aiConfig.api_key,
      proxy_mode: aiConfig.proxy_mode,
      model: aiConfig.model,
      timeout: aiConfig.timeout,
      max_tokens: aiConfig.max_tokens,
    })
    Object.assign(aiConfig, data)
    ElMessage.success('AI 配置已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    savingAI.value = false
  }
}

async function testAIConnection() {
  if (!aiConfig.api_url) {
    ElMessage.warning('请先填写 API 地址')
    return
  }
  testingAI.value = true
  try {
    // Save first, then try fetching models as a connectivity test
    await api.updateAIConfig({
      api_url: aiConfig.api_url,
      api_key: aiConfig.api_key,
      proxy_mode: aiConfig.proxy_mode,
    })
    const { data } = await api.getAIModels()
    if (data && data.length >= 0) {
      ElMessage.success(`连接成功！发现 ${data.length} 个可用模型`)
      availableModels.value = data
    }
  } catch (e) {
    const detail = e.response?.data?.detail || e.message
    ElMessage.error('连接测试失败: ' + detail)
  } finally {
    testingAI.value = false
  }
}

onMounted(() => {
  loadAIConfig()
  loadPreferences()
  loadTagsForPrefs()
  loadAllArrays()
})
</script>

<style scoped>
.settings {
  padding: 20px;
}

.admin-card {
  margin-bottom: 20px;
}

.admin-entry {
  display: flex;
  justify-content: space-between;
  align-items: center;
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

.ai-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
</style>
