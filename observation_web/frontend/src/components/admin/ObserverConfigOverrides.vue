<template>
  <div class="observer-overrides">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="内置观察点配置：全局一份为默认值，可按小组（L1 标签）或按阵列新增覆盖层，小组各管各的。"
      style="margin-bottom: 16px"
    />

    <el-form inline>
      <el-form-item label="选择观察点">
        <el-select
          v-model="selectedObserver"
          placeholder="选择内置观察点"
          style="width: 240px"
          @change="loadOverrides"
        >
          <el-option v-for="obs in BUILTIN_OBSERVERS" :key="obs" :label="obs" :value="obs" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button :disabled="!selectedObserver" :loading="loading" @click="loadOverrides">刷新</el-button>
      </el-form-item>
    </el-form>

    <template v-if="selectedObserver">
      <!-- Global default (base config) -->
      <el-card shadow="never" class="override-card">
        <template #header>
          <span>全局默认</span>
        </template>
        <pre class="params-block">{{ formatParams(globalDefault) }}</pre>
      </el-card>

      <!-- Tag overrides -->
      <el-card shadow="never" class="override-card">
        <template #header>
          <div class="card-header">
            <span>按小组（标签）覆盖 ({{ grouped.tag.length }})</span>
          </div>
        </template>
        <el-empty v-if="grouped.tag.length === 0" description="暂无标签覆盖" :image-size="60" />
        <div v-for="ov in grouped.tag" :key="`tag-${ov.scope_id}`" class="override-row">
          <span class="scope-label">{{ tagLabel(ov.scope_id) }}</span>
          <el-tag :type="ov.enabled === false ? 'info' : 'success'" size="small" effect="plain">
            {{ ov.enabled === false ? '已停用' : '已启用' }}
          </el-tag>
          <span v-if="ov.updated_by" class="updated-by">by {{ ov.updated_by }}</span>
          <pre class="params-inline">{{ formatParams(ov.params) }}</pre>
          <el-button size="small" type="danger" text @click="removeOverride('tag', ov.scope_id)">删除</el-button>
        </div>
      </el-card>

      <!-- Array overrides -->
      <el-card shadow="never" class="override-card">
        <template #header>
          <div class="card-header">
            <span>按阵列覆盖 ({{ grouped.array.length }})</span>
          </div>
        </template>
        <el-empty v-if="grouped.array.length === 0" description="暂无阵列覆盖" :image-size="60" />
        <div v-for="ov in grouped.array" :key="`array-${ov.scope_id}`" class="override-row">
          <span class="scope-label">{{ arrayLabel(ov.scope_id) }}</span>
          <el-tag :type="ov.enabled === false ? 'info' : 'success'" size="small" effect="plain">
            {{ ov.enabled === false ? '已停用' : '已启用' }}
          </el-tag>
          <span v-if="ov.updated_by" class="updated-by">by {{ ov.updated_by }}</span>
          <pre class="params-inline">{{ formatParams(ov.params) }}</pre>
          <el-button size="small" type="danger" text @click="removeOverride('array', ov.scope_id)">删除</el-button>
        </div>
      </el-card>

      <!-- Add override form -->
      <el-card shadow="never" class="override-card">
        <template #header>
          <span>新增 / 更新覆盖</span>
        </template>
        <el-form label-width="90px">
          <el-form-item label="覆盖范围">
            <el-radio-group v-model="form.scope_type" @change="form.scope_id = null">
              <el-radio-button value="tag">按标签</el-radio-button>
              <el-radio-button value="array">按阵列</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="目标">
            <el-select
              v-if="form.scope_type === 'tag'"
              v-model="form.scope_id"
              placeholder="选择标签"
              style="width: 320px"
            >
              <el-option v-for="t in l1Tags" :key="t.id" :label="t.name" :value="t.id" />
            </el-select>
            <el-select
              v-else
              v-model="form.scope_id"
              filterable
              placeholder="选择阵列"
              style="width: 320px"
            >
              <el-option v-for="a in arrays" :key="a.array_id" :label="`${a.name} (${a.host})`" :value="a.array_id" />
            </el-select>
          </el-form-item>
          <el-form-item label="启用">
            <el-switch v-model="form.enabled" />
          </el-form-item>
          <el-form-item label="参数 (JSON)">
            <el-input
              v-model="form.paramsText"
              type="textarea"
              :rows="4"
              placeholder='例如 {"threshold": 90, "interval": 60}'
              style="width: 420px"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="saving" :disabled="!form.scope_id" @click="saveOverride">
              保存覆盖
            </el-button>
          </el-form-item>
        </el-form>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'
import { BUILTIN_OBSERVERS, groupOverridesByScope } from './observerOverrideHelpers'

const selectedObserver = ref('')
const overrides = ref([])
const globalDefault = ref(null)
const loading = ref(false)
const saving = ref(false)

const tags = ref([])
const arrays = ref([])

const l1Tags = computed(() => tags.value.filter(t => t.level === 1))
const grouped = computed(() => groupOverridesByScope(overrides.value))

const form = reactive({
  scope_type: 'tag',
  scope_id: null,
  enabled: true,
  paramsText: '',
})

function formatParams(params) {
  if (params == null) return '（无）'
  try {
    return typeof params === 'string' ? params : JSON.stringify(params, null, 2)
  } catch {
    return String(params)
  }
}

function tagLabel(id) {
  const t = tags.value.find(x => x.id === id)
  return t ? t.name : `标签 #${id}`
}

function arrayLabel(id) {
  const a = arrays.value.find(x => x.array_id === id)
  return a ? `${a.name} (${a.host})` : `阵列 ${id}`
}

async function loadReferenceData() {
  try {
    const [tagRes, arrRes] = await Promise.all([api.getTags(), api.getArrayStatuses()])
    tags.value = tagRes.data || []
    arrays.value = arrRes.data || []
  } catch {
    tags.value = []
    arrays.value = []
  }
}

async function loadOverrides() {
  if (!selectedObserver.value) return
  loading.value = true
  try {
    const res = await api.getObserverConfigOverrides(selectedObserver.value)
    overrides.value = res.data || []
    // Global default comes from the base observer config
    try {
      const cfgRes = await api.getObserverConfigs()
      const list = cfgRes.data || []
      const cfg = Array.isArray(list) ? list.find(c => c.name === selectedObserver.value) : list[selectedObserver.value]
      globalDefault.value = cfg?.params ?? cfg ?? null
    } catch {
      globalDefault.value = null
    }
  } catch (e) {
    ElMessage.error('加载覆盖失败: ' + (e.response?.data?.detail || e.message))
    overrides.value = []
  } finally {
    loading.value = false
  }
}

async function saveOverride() {
  let params
  try {
    params = form.paramsText.trim() ? JSON.parse(form.paramsText) : {}
  } catch {
    ElMessage.error('参数不是合法的 JSON')
    return
  }
  saving.value = true
  try {
    await api.upsertObserverConfigOverride(selectedObserver.value, {
      scope_type: form.scope_type,
      scope_id: form.scope_id,
      params,
      enabled: form.enabled,
    })
    ElMessage.success('覆盖已保存')
    form.scope_id = null
    form.paramsText = ''
    await loadOverrides()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function removeOverride(scopeType, scopeId) {
  try {
    await ElMessageBox.confirm('确定删除该覆盖？删除后将回退到上层默认值。', '确认删除', { type: 'warning' })
  } catch {
    return
  }
  try {
    await api.deleteObserverConfigOverride(selectedObserver.value, scopeType, scopeId)
    ElMessage.success('已删除')
    await loadOverrides()
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

loadReferenceData()
</script>

<style scoped>
.override-card {
  margin-top: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.override-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-wrap: wrap;
}
.override-row:last-child {
  border-bottom: none;
}
.scope-label {
  font-weight: 500;
  min-width: 160px;
}
.updated-by {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.params-block {
  margin: 0;
  padding: 8px;
  background: var(--el-fill-color-lighter);
  border-radius: 4px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
.params-inline {
  margin: 0;
  flex: 1;
  font-size: 12px;
  color: var(--el-text-color-regular);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
